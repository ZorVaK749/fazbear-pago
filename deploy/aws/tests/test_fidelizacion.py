from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

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
        terminated = {"State": {"Name": "terminated"},
                      "StateReason": {"Message": "Client.UserInitiatedShutdown: User initiated shutdown"}}
        with patch.object(fidelizacion, "instances", side_effect=[[pending], [terminated]]), \
                patch.object(fidelizacion.time, "sleep") as sleep:
            with self.assertRaisesRegex(host.RolloutError, "terminated · Client.UserInitiatedShutdown"):
                fidelizacion.wait_for_ec2("i-new")
        sleep.assert_called_once_with(5)

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
                patch.object(db, "psql", side_effect=["f|-|t", "", "1", "", "1"]) as psql, \
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
                patch.object(db, "psql", return_value="f|-|f") as psql:
            with self.assertRaisesRegex(host.RolloutError, "administrador de RDS"):
                db.bootstrap(connection, {})
        put.assert_not_called()
        self.assertEqual(psql.call_count, 1)

    def test_existing_unmanaged_database_preserves_its_credentials(self):
        connection = {"PGHOST": "db.example.test", "PGPORT": "5432", "PGSSLMODE": "require"}
        with patch.object(db, "stored_config", return_value=None), patch.object(db, "put_config") as put, \
                patch.object(db, "psql", return_value="t|fidelizacion|f") as psql:
            with self.assertRaisesRegex(host.RolloutError, "--set-config"):
                db.bootstrap(connection, {})
        put.assert_not_called()
        self.assertEqual(psql.call_count, 1)

    @unittest.skipUnless(os.environ.get("FIDELIZACION_TEST_POSTGRES"), "Requiere PostgreSQL desechable de CI")
    def test_postgres_creates_and_reuses_the_real_role_and_database(self):
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

        with patch.object(db, "stored_config", side_effect=lambda: saved), \
                patch.object(db, "put_config", side_effect=keep_config) as put, \
                patch.object(db, "psql", side_effect=ci_psql):
            db.bootstrap(connection, values)
            db.bootstrap(connection, values)
        put.assert_called_once()
        app = dict(connection, PGUSER="fidelizacion", PGDATABASE="fidelizacion",
                   PGPASSWORD=saved["FIDELIZACION_DB_PASSWORD"])
        self.assertEqual(ci_psql(app, "SELECT current_user;", "No se pudo comprobar el rol de prueba."), "fidelizacion")
