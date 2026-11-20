from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fidelizacion
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
            fidelizacion.create_ec2({}, {}, {"InstanceId": "i-existing"})
        aws.assert_not_called()

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
