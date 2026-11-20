from contextlib import redirect_stdout
import gzip
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fidelizacion
import fidelizacion_db as db
import fidelizacion_host as host


class FidelizacionTest(unittest.TestCase):
    def rule(self, priority, path, destination="target"):
        return {"IsDefault": False, "Priority": str(priority),
                "Conditions": [{"Field": "path-pattern", "PathPatternConfig": {"Values": [path]}}],
                "Actions": [{"Type": "forward", "TargetGroupArn": destination}]}

    def test_new_rule_has_precedence_without_modifying_other_priorities(self):
        rules = [self.rule(1, "/api/productos/*"), self.rule(5, "/api/*")]
        self.assertEqual(fidelizacion.rule_priority(rules, "target"), 2)
        rules.append(self.rule(2, fidelizacion.PATH))
        self.assertIsNone(fidelizacion.rule_priority(rules, "target"))
        with self.assertRaises(host.RolloutError):
            fidelizacion.rule_priority(rules, "some-other-target")

    def test_catch_all_at_first_priority_requires_review(self):
        with self.assertRaisesRegex(host.RolloutError, "prioridad libre"):
            fidelizacion.rule_priority([self.rule(1, "/api/*")], "target")

    def test_creates_one_micro_in_existing_network_without_a_world_open_group(self):
        pago = {"ImageId": "ami-test", "SubnetId": "subnet-test", "VpcId": "vpc-test",
                "IamInstanceProfile": {"Arn": "profile-test"},
                "SecurityGroups": [{"GroupId": "sg-safe"}, {"GroupId": "sg-public"}],
                "PublicIpAddress": "203.0.113.10"}
        image = {"Images": [{"ImageId": "ami-test", "RootDeviceName": "/dev/xvda",
                             "Name": "al2023-ami-test", "Architecture": "x86_64"}]}
        groups = {"SecurityGroups": [
            {"GroupId": "sg-safe", "IpPermissions": []},
            {"GroupId": "sg-public", "IpPermissions": [{"IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]},
        ]}
        with patch.object(fidelizacion, "aws", side_effect=[image, groups, {"Instances": [{"InstanceId": "i-new"}]}]) as aws, \
             patch.object(fidelizacion, "open_to_alb", return_value="sg-alb-ingress"), redirect_stdout(io.StringIO()):
            fidelizacion.create_ec2(pago, {"SecurityGroups": ["sg-alb"]}, None)
        launch = aws.call_args.kwargs["input_json"]
        self.assertEqual(launch["MinCount"], launch["MaxCount"])
        self.assertEqual(launch["MaxCount"], 1)
        self.assertEqual(launch["InstanceType"], "t3.micro")
        self.assertEqual(launch["NetworkInterfaces"][0]["Groups"], ["sg-alb-ingress", "sg-safe"])
        self.assertTrue(launch["BlockDeviceMappings"][0]["Ebs"]["Encrypted"])
        self.assertEqual(launch["MetadataOptions"]["HttpTokens"], "required")

    def test_reuses_a_dedicated_instance_without_allocating_another(self):
        with patch.object(fidelizacion, "aws") as aws, redirect_stdout(io.StringIO()):
            self.assertEqual(fidelizacion.create_ec2({}, {}, {"InstanceId": "i-existing"}), "i-existing")
        aws.assert_not_called()

    def test_retry_uses_a_stable_new_token_for_the_confirmed_terminated_instance(self):
        instance_id = "i-0123456789abcdef0"
        pago = {"VpcId": "vpc-test"}
        previous = {"VpcId": "vpc-test", "State": {"Name": "terminated"},
                    "Tags": [{"Key": "Name", "Value": fidelizacion.NAME},
                             {"Key": "Project", "Value": fidelizacion.PROJECT}]}
        with patch.object(fidelizacion, "instances", return_value=[previous]), \
                patch.object(fidelizacion, "create_ec2", return_value="i-new") as create, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(fidelizacion.retry_ec2(pago, {}, None, instance_id), "i-new")
            previous["VpcId"] = "vpc-other"
            with self.assertRaisesRegex(host.RolloutError, "EC2 terminada de Fidelización"):
                fidelizacion.retry_ec2(pago, {}, None, instance_id)
        create.assert_called_once_with(pago, {}, None, client_token=f"{fidelizacion.LAUNCH_TOKEN}-{instance_id}")

    def test_retry_accepts_a_terminated_record_without_network_or_tags_and_an_expired_record(self):
        instance_id = "i-0123456789abcdef0"
        pago = {"VpcId": "vpc-test"}
        for records in ([{"State": {"Name": "terminated"}}], []):
            with self.subTest(records=records), patch.object(fidelizacion, "instances", return_value=records), \
                    patch.object(fidelizacion, "create_ec2", return_value="i-new") as create, \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(fidelizacion.retry_ec2(pago, {}, None, instance_id), "i-new")
                create.assert_called_once_with(pago, {}, None, client_token=f"{fidelizacion.LAUNCH_TOKEN}-{instance_id}")

    def test_retry_rejects_a_previous_instance_that_is_still_running(self):
        previous = {"State": {"Name": "running"}}
        with patch.object(fidelizacion, "instances", return_value=[previous]), \
                patch.object(fidelizacion, "create_ec2") as create:
            with self.assertRaisesRegex(host.RolloutError, "EC2 terminada de Fidelización"):
                fidelizacion.retry_ec2({}, {}, None, "i-0123456789abcdef0")
        create.assert_not_called()

    def test_retry_reuses_the_active_instance_even_if_the_old_record_has_expired(self):
        with patch.object(fidelizacion, "aws") as aws, redirect_stdout(io.StringIO()):
            target = fidelizacion.retry_ec2({}, {}, {"InstanceId": "i-existing"}, "i-0123456789abcdef0")
        self.assertEqual(target, "i-existing")
        aws.assert_not_called()

    def test_wait_reports_ec2_reason_on_terminal_transition(self):
        pending = {"State": {"Name": "pending"}}
        terminated = {"InstanceId": "i-new", "State": {"Name": "terminated"},
                      "StateReason": {"Message": "Client.UserInitiatedShutdown: User initiated shutdown"}}
        with patch.object(fidelizacion, "instances", side_effect=[[pending], [terminated]]), \
                patch.object(fidelizacion.time, "sleep") as sleep:
            with self.assertRaisesRegex(host.RolloutError, "terminated · Client.UserInitiatedShutdown"):
                fidelizacion.wait_for_ec2("i-new")
        sleep.assert_called_once_with(5)

    def test_selects_running_fidelizacion_by_id_when_tags_are_not_visible(self):
        instance_id = "i-0123456789abcdef0"
        pago = {"VpcId": "vpc-test"}
        record = {"InstanceId": instance_id, "VpcId": "vpc-test", "State": {"Name": "running"},
                  "ClientToken": f"{fidelizacion.LAUNCH_TOKEN}-i-0123456789abcdef1"}
        with patch.object(fidelizacion, "instances", return_value=[record]) as instances:
            self.assertIs(fidelizacion.select_instance(pago, instance_id), record)
            instances.assert_called_once_with(**{"instance-id": instance_id})
            record["VpcId"] = "vpc-other"
            with self.assertRaisesRegex(host.RolloutError, "VPC de Pago"):
                fidelizacion.select_instance(pago, instance_id)
            record["VpcId"] = pago["VpcId"]
            record["ClientToken"] = "other-service"
            with self.assertRaisesRegex(host.RolloutError, "EC2 de Fidelización"):
                fidelizacion.select_instance(pago, instance_id)

    def test_prepare_database_checks_instance_state_before_sending_ssm(self):
        record = {"InstanceId": "i-new", "State": {"Name": "terminated"},
                  "StateReason": {"Message": "Client.UserInitiatedShutdown"}}
        with patch.object(fidelizacion, "run_ssm") as run:
            with self.assertRaisesRegex(host.RolloutError, "i-new · terminated · Client.UserInitiatedShutdown"):
                fidelizacion.prepare_database(record)
        run.assert_not_called()

    def test_reuse_refuses_to_change_an_ec2_with_a_frontend_target_group_attached(self):
        node = {"PrivateIpAddress": "192.0.2.10"}
        services = {"services": [{"status": "ACTIVE", "launchType": "FARGATE", "runningCount": 1, "desiredCount": 1}]}
        group = {"TargetGroupName": fidelizacion.LEGACY_TG, "LoadBalancerArns": ["active-alb"]}
        with patch.object(fidelizacion, "aws", side_effect=[services, {"TargetGroups": [group]}]) as aws, \
                patch.object(fidelizacion, "verify_checkout"):
            with self.assertRaisesRegex(host.RolloutError, "sigue asociado"):
                fidelizacion.check_frontend_traffic(node)
        self.assertEqual([call.args[:2] for call in aws.call_args_list],
                         [("ecs", "describe-services"), ("elbv2", "describe-target-groups")])

    def test_reuse_checks_database_before_adding_network_and_service_tag_to_known_host(self):
        instance_id = fidelizacion.LEGACY_FRONTEND
        profile = {"Arn": "example-profile"}
        pago = {"VpcId": "vpc-test", "IamInstanceProfile": profile}
        candidate = dict(pago, InstanceId=instance_id, State={"Name": "running"}, Architecture="x86_64",
                         Tags=[{"Key": "Name", "Value": fidelizacion.LEGACY_NAME}],
                         SecurityGroups=[{"GroupId": "sg-original"}])
        online = {"InstanceInformationList": [{"PingStatus": "Online", "PlatformName": "Amazon Linux"}]}
        with patch.object(fidelizacion, "instances", return_value=[candidate]), \
                patch.object(fidelizacion, "aws", side_effect=[online, {}, {}]) as aws, \
                patch.object(fidelizacion, "check_frontend_traffic"), patch.object(fidelizacion, "check_existing_ingress"), \
                patch.object(fidelizacion, "prepare_database", side_effect=host.RolloutError("DB pendiente")) as prepare, \
                patch.object(fidelizacion, "open_to_alb", return_value="sg-new") as group, \
                patch.object(fidelizacion, "run_service") as run, patch.object(fidelizacion, "attach") as attach:
            with self.assertRaisesRegex(host.RolloutError, "DB pendiente"):
                fidelizacion.reuse_frontend(pago, "listener", {}, None)
            group.assert_not_called()
            run.assert_not_called()
            attach.assert_not_called()
            self.assertEqual(aws.call_count, 1)
            aws.side_effect = iter([online, {}, {}])
            prepare.side_effect = None
            fidelizacion.reuse_frontend(pago, "listener", {}, None)
        self.assertEqual(aws.call_args_list[-2].args, ("ec2", "modify-instance-attribute", "--instance-id",
                         instance_id, "--groups", "sg-new", "sg-original"))
        self.assertEqual(aws.call_args_list[-1].args, ("ec2", "create-tags", "--resources", instance_id,
                         "--tags", f"Key={fidelizacion.SERVICE_TAG},Value={fidelizacion.NAME}"))
        run.assert_called_once_with(candidate, "deploy")
        attach.assert_called_once_with(candidate, pago, "listener")

    def test_reuse_enrolls_only_the_reviewed_frontend_instance(self):
        pago = {"VpcId": "vpc-test"}
        candidate = dict(pago, InstanceId=fidelizacion.LEGACY_FRONTEND, State={"Name": "running"},
                         Tags=[{"Key": "Name", "Value": fidelizacion.LEGACY_NAME},
                               {"Key": fidelizacion.SERVICE_TAG, "Value": fidelizacion.NAME}])
        other = dict(candidate, InstanceId="i-0123456789abcdef0")
        with patch.object(fidelizacion, "instances", side_effect=[[candidate, other], [candidate], [other]]):
            self.assertIs(fidelizacion.select_instance(pago), candidate)
            self.assertIs(fidelizacion.select_instance(pago, candidate["InstanceId"]), candidate)
            with self.assertRaisesRegex(host.RolloutError, "EC2 de Fidelización"):
                fidelizacion.select_instance(pago, other["InstanceId"])

    def test_rds_ingress_uses_only_the_dedicated_source_and_actual_database_port(self):
        node = {"InstanceId": "i-loyalty", "State": {"Name": "running"}, "SecurityGroups": [{"GroupId": "sg-app"}]}
        pago = {"VpcId": "vpc-test", "SecurityGroups": [{"GroupId": "sg-pago"}]}
        sources = {"SecurityGroups": [{"GroupId": "sg-app", "GroupName": fidelizacion.GROUP, "VpcId": "vpc-test"}]}
        interfaces = {"NetworkInterfaces": [{"Attachment": {"InstanceId": node["InstanceId"]}}]}
        database = {"DBInstanceIdentifier": "test-rds", "Engine": "postgres", "Endpoint": {"Port": 5432},
                    "DBSubnetGroup": {"VpcId": "vpc-test"},
                    "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-db", "Status": "active"}]}
        db_group = {"GroupId": "sg-db", "IpPermissions": []}
        with patch.object(fidelizacion, "database_command", return_value='{"identifier":"test-rds","port":5432}'), \
                patch.object(fidelizacion, "aws", side_effect=[sources, interfaces, {"DBInstances": [database]},
                                                               {"SecurityGroups": [db_group]}, {}]) as aws, \
                redirect_stdout(io.StringIO()):
            fidelizacion.allow_rds(node, pago)
        self.assertEqual(aws.call_args.args, ("ec2", "authorize-security-group-ingress"))
        rule = aws.call_args.kwargs["input_json"]
        self.assertEqual(rule["GroupId"], "sg-db")
        self.assertEqual(rule["IpPermissions"], [{"IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432,
                         "UserIdGroupPairs": [{"GroupId": "sg-app", "Description": "EV3 Fidelizacion a PostgreSQL"}]}])
        db_group["IpPermissions"] = rule["IpPermissions"]
        with patch.object(fidelizacion, "database_command", return_value='{"identifier":"test-rds","port":5432}'), \
                patch.object(fidelizacion, "aws", side_effect=[sources, interfaces, {"DBInstances": [database]},
                                                               {"SecurityGroups": [db_group]}]) as aws, \
                redirect_stdout(io.StringIO()):
            fidelizacion.allow_rds(node, pago)
        self.assertEqual(aws.call_count, 4)
        interfaces["NetworkInterfaces"].append({"Attachment": {"InstanceId": "i-other"}})
        with patch.object(fidelizacion, "database_command") as inspect, \
                patch.object(fidelizacion, "aws", side_effect=[sources, interfaces]) as aws:
            with self.assertRaisesRegex(host.RolloutError, "no es exclusivo"):
                fidelizacion.allow_rds(node, pago)
        inspect.assert_not_called()
        self.assertEqual(aws.call_count, 2)

    def test_reports_all_unreachable_dependencies_without_dumping_endpoint_details(self):
        config = {"FIDELIZACION_DB_URL": "jdbc:postgresql://db.example.test/fidelizacion?sslmode=require",
                  "FIDELIZACION_DB_USER": "fidelizacion", "FIDELIZACION_DB_PASSWORD": "test-only",
                  "KAFKA_BOOTSTRAP_SERVERS": "broker.example.test:9092", "INTERNAL_SERVICE_KEY": "a" * 32}
        with patch.object(host.socket, "create_connection", side_effect=[TimeoutError(), ConnectionRefusedError()]), \
                patch.object(host, "read_health", return_value={}):
            with self.assertRaisesRegex(host.RolloutError, "PostgreSQL TCP/5432.*Kafka TCP/9092.*Pago HTTP/8087") as error:
                host.check_dependencies(config, "192.0.2.5")
        self.assertNotIn("example.test", str(error.exception))

    def test_dedicated_tls_database_and_kafka_endpoints(self):
        config = {"FIDELIZACION_DB_URL": "jdbc:postgresql://db.example.test:5432/fidelizacion?sslmode=require",
                  "FIDELIZACION_DB_USER": "fidelizacion", "FIDELIZACION_DB_PASSWORD": "test-only",
                  "KAFKA_BOOTSTRAP_SERVERS": "broker1.example.test:9092,broker2.example.test:9092",
                  "INTERNAL_SERVICE_KEY": "a" * 32}
        self.assertEqual(host.validate_config(config), ("db.example.test", 5432))
        for jdbc in ("jdbc:postgresql://db.example.test/pago?sslmode=require",
                     "jdbc:postgresql://db.example.test/fidelizacion?sslmode=disable"):
            with self.assertRaises(host.RolloutError):
                host.validate_config(dict(config, FIDELIZACION_DB_URL=jdbc))

    def test_verify_does_not_create_a_target_group(self):
        with patch.object(fidelizacion, "aws", return_value={"TargetGroups": []}) as aws:
            with self.assertRaises(host.RolloutError):
                fidelizacion.attach({}, {}, "listener", verify_only=True)
        aws.assert_called_once_with("elbv2", "describe-target-groups")

    def test_database_bootstrap_creates_a_separate_db_and_keeps_password_out_of_sql(self):
        connection = {"PGHOST": "db.example.test", "PGPORT": "5432", "PGSSLMODE": "require"}
        values = {"INTERNAL_SERVICE_KEY": "a" * 32, "KAFKA_BOOTSTRAP_SERVERS": "kafka.example.test:9092"}
        password = "synthetic-private-fixture"
        with patch.object(db, "stored_config", return_value=None), \
                patch.object(db, "put_config") as put, \
                patch.object(db.secrets, "token_urlsafe", return_value=password), \
                patch.object(db, "psql", side_effect=["f|-|t|t", "", "1", "", "1"]) as psql, \
                redirect_stdout(io.StringIO()) as output:
            db.bootstrap(connection, values)
        config = put.call_args.args[0]
        self.assertEqual(config["FIDELIZACION_DB_PASSWORD"], password)
        self.assertTrue(config["FIDELIZACION_DB_URL"].endswith("/fidelizacion?sslmode=require"))
        queries = [call.args[1] for call in psql.call_args_list]
        self.assertIn("CREATE ROLE fidelizacion LOGIN PASSWORD 'SCRAM-SHA-256$", queries[1])
        self.assertIn("CREATE DATABASE fidelizacion OWNER fidelizacion;", queries[3])
        self.assertNotIn(password, "".join(queries) + output.getvalue())

    def test_lack_of_db_authority_changes_neither_rds_nor_ssm(self):
        connection = {"PGHOST": "db.example.test", "PGPORT": "5432", "PGSSLMODE": "require"}
        with patch.object(db, "stored_config", return_value=None), patch.object(db, "put_config") as put, \
                patch.object(db, "psql", return_value="f|-|f|f") as psql:
            with self.assertRaisesRegex(host.RolloutError, "administrador de RDS"):
                db.bootstrap(connection, {})
        put.assert_not_called()
        self.assertEqual(psql.call_count, 1)

    def test_existing_unmanaged_database_preserves_its_credentials(self):
        connection = {"PGHOST": "db.example.test", "PGPORT": "5432", "PGSSLMODE": "require"}
        with patch.object(db, "stored_config", return_value=None), patch.object(db, "put_config") as put, \
                patch.object(db, "psql", return_value="t|fidelizacion|f|f") as psql:
            with self.assertRaisesRegex(host.RolloutError, "--set-config"):
                db.bootstrap(connection, {})
        put.assert_not_called()
        self.assertEqual(psql.call_count, 1)

    def test_existing_populated_database_needs_its_current_configuration(self):
        connection = {"PGHOST": "db.example.test", "PGPORT": "5432", "PGSSLMODE": "require", "PGUSER": "pago"}
        with patch.object(db, "stored_config", return_value=None), patch.object(db, "put_config") as put, \
                patch.object(db, "psql", side_effect=["f|pago|t|t", '{"objetos": 2, "fidelizacion": 1}']) as psql:
            with self.assertRaisesRegex(host.RolloutError, "permisos vigentes"):
                db.bootstrap(connection, {})
        put.assert_not_called()
        self.assertEqual(psql.call_count, 2)
        self.assertTrue(all(call.args[1].strip().startswith("SELECT") for call in psql.call_args_list))

    def test_existing_database_with_supplied_credentials_does_not_change_its_owner(self):
        connection = {"PGHOST": "db.example.test", "PGPORT": "5432", "PGSSLMODE": "require", "PGUSER": "pago"}
        config = {"FIDELIZACION_DB_URL": "jdbc:postgresql://db.example.test/fidelizacion?sslmode=require",
                  "FIDELIZACION_DB_USER": "loyalty", "FIDELIZACION_DB_PASSWORD": "synthetic-private-fixture",
                  "INTERNAL_SERVICE_KEY": "a" * 32, "KAFKA_BOOTSTRAP_SERVERS": "kafka.example.test:9092"}
        with patch.object(db, "stored_config", return_value=config), patch.object(db, "put_config") as put, \
                patch.object(db, "psql", side_effect=["f|other_owner|f|f", "t"]) as psql, redirect_stdout(io.StringIO()):
            db.bootstrap(connection, config)
        self.assertEqual(psql.call_args.args[0]["PGUSER"], "loyalty")
        self.assertTrue(all(call.args[1].strip().startswith("SELECT") for call in psql.call_args_list))
        put.assert_not_called()

    def test_rds_admin_reads_only_the_managed_secret_for_the_pago_endpoint(self):
        connection = {"PGHOST": "db.example.test", "PGPORT": "5432", "PGUSER": "pago"}
        instance = {"Engine": "postgres", "Endpoint": {"Address": connection["PGHOST"], "Port": 5432},
                    "MasterUsername": "admin", "MasterUserSecret": {"SecretArn": "approved-rds-secret"}}
        credential = {"username": "admin", "password": "private-test-value"}
        with patch.object(db, "aws_json", side_effect=[{"DBInstances": [instance]},
                                                      {"SecretString": json.dumps(credential)}]) as aws, \
                redirect_stdout(io.StringIO()) as output:
            admin = db.managed_admin(connection)
        self.assertEqual(admin["PGPASSWORD"], credential["password"])
        self.assertEqual(aws.call_args.args[0], ["secretsmanager", "get-secret-value", "--secret-id", "approved-rds-secret"])
        self.assertEqual(output.getvalue(), "")
        instance.pop("MasterUserSecret")
        with patch.object(db, "aws_json", return_value={"DBInstances": [instance]}) as aws:
            with self.assertRaisesRegex(host.RolloutError, "--stage-db-admin"):
                db.managed_admin(connection)
        self.assertEqual(aws.call_count, 1)

    def test_stages_a_bundle_for_an_interactive_prompt(self):
        source = gzip.compress(json.dumps([("fidelizacion_db", "def main(args):\n    return 0\n")]).encode())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "admin.pyz"
            subprocess.run([sys.executable, "-c", fidelizacion.ADMIN_LOADER, str(path)],
                           input=source, capture_output=True, check=True)
            with zipfile.ZipFile(path) as archive:
                script = archive.read("__main__.py").decode()
                compile(script, "__main__.py", "exec")
                self.assertIn("interactive-admin", script)
            subprocess.run([sys.executable, str(path)], capture_output=True, check=True)

    @unittest.skipUnless(os.environ.get("FIDELIZACION_TEST_POSTGRES"), "Requiere PostgreSQL desechable de CI")
    def test_postgres_bootstraps_the_existing_empty_database_without_changing_its_owner(self):
        password = os.environ["FIDELIZACION_TEST_POSTGRES"]
        connection = dict(os.environ, PGHOST="127.0.0.1", PGPORT="5432", PGUSER="postgres",
                          PGPASSWORD=password, PGSSLMODE="require")
        values = {"INTERNAL_SERVICE_KEY": "a" * 32, "KAFKA_BOOTSTRAP_SERVERS": "kafka.example.test:9092"}
        saved = None
        real_psql = db.psql

        def keep_config(config):
            nonlocal saved
            saved = config

        def ci_psql(environment, sql, failure, **kwargs):
            # The disposable PostgreSQL service has no TLS certificate.
            return real_psql(dict(environment, PGSSLMODE="disable"), sql, failure, **kwargs)

        ci_psql(dict(connection, PGDATABASE="postgres"), "CREATE DATABASE fidelizacion;", "Faltó la base de prueba.")
        ci_psql(dict(connection, PGDATABASE="postgres"),
                "CREATE ROLE pago_fixture LOGIN PASSWORD 'test-pago-fixture-only';", "Faltó el rol de prueba de Pago.")
        pago = dict(connection, PGUSER="pago_fixture", PGPASSWORD="test-pago-fixture-only")
        with patch.object(db, "stored_config", side_effect=lambda: saved), \
                patch.object(db, "put_config", side_effect=keep_config) as put, \
                patch.object(db, "psql", side_effect=ci_psql):
            with self.assertRaisesRegex(host.RolloutError, "--prepare-db-admin"):
                db.bootstrap(pago, values)
            db.bootstrap(connection, values)
            db.bootstrap(pago, values)
        put.assert_called_once()
        app = dict(connection, PGUSER="fidelizacion", PGDATABASE="fidelizacion",
                   PGPASSWORD=saved["FIDELIZACION_DB_PASSWORD"])
        self.assertEqual(ci_psql(app, "SELECT current_user;", "No se pudo comprobar el rol de prueba."), "fidelizacion")
        self.assertEqual(ci_psql(app, "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database();",
                                "No se pudo comprobar el propietario."), "postgres")
