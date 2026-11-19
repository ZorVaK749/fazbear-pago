from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frontend_image as frontend

OLD = frontend.PACKAGE + "@sha256:" + "a" * 64
NEW = frontend.PACKAGE + "@sha256:" + "b" * 64
TASK = {
    "taskDefinition": {
        "family": frontend.FAMILY,
        "taskDefinitionArn": frontend.FAMILY + ":2",
        "revision": 2,
        "status": "ACTIVE",
        "executionRoleArn": "execution-role",
        "requiresCompatibilities": ["FARGATE"],
        "runtimePlatform": {"cpuArchitecture": "X86_64"},
        "containerDefinitions": [
            {"name": "angular", "image": OLD, "portMappings": [{"containerPort": 80}],
             "environment": [{"name": "ENV", "value": "existing"}]},
            {"name": "sidecar", "image": "registry.example/sidecar:1"},
        ],
    },
    "tags": [{"key": "product", "value": "ev3"}, {"key": "aws:ecs:serviceName", "value": "existing"}],
}
SERVICE = {"serviceArn": "frontend-existing", "status": "ACTIVE", "taskDefinition": frontend.FAMILY + ":2",
           "deployments": [{}]}


class FrontendRolloutTests(unittest.TestCase):
    def test_copies_only_registration_fields_and_replaces_only_angular_image(self):
        config, original = frontend.registration(TASK, NEW)
        self.assertEqual(original, OLD)
        self.assertEqual(config["containerDefinitions"][0], dict(TASK["taskDefinition"]["containerDefinitions"][0], image=NEW))
        self.assertEqual(config["containerDefinitions"][1], TASK["taskDefinition"]["containerDefinitions"][1])
        self.assertEqual(config["executionRoleArn"], "execution-role")
        self.assertEqual(config["tags"], [{"key": "product", "value": "ev3"}])
        self.assertNotIn("taskDefinitionArn", config)
        self.assertNotIn("revision", config)

    def test_finds_service_by_task_family(self):
        with patch.object(frontend, "aws", side_effect=[
            {"clusterArns": ["cluster"]},
            {"serviceArns": ["frontend-existing", "unrelated"]},
            {"services": [SERVICE, dict(SERVICE, taskDefinition="someone-else:1")]},
        ]):
            self.assertEqual(frontend.find_service(), ("cluster", SERVICE))

    def test_dry_run_never_registers_or_updates(self):
        with patch.object(frontend, "aws", side_effect=[{"Account": frontend.ACCOUNT}, TASK]) as aws, \
             patch.object(frontend, "find_service", return_value=("cluster", SERVICE)), redirect_stdout(io.StringIO()):
            frontend.execute("dry-run", NEW)
        self.assertEqual([call.args[1] for call in aws.call_args_list], ["get-caller-identity", "describe-task-definition"])

    def test_apply_updates_existing_service_with_the_new_revision(self):
        new_revision = frontend.FAMILY + ":3"
        with patch.object(frontend, "aws", side_effect=[
            {"Account": frontend.ACCOUNT}, TASK, {"taskDefinition": {"taskDefinitionArn": new_revision}}, {},
        ]) as aws, patch.object(frontend, "find_service", return_value=("cluster", SERVICE)), \
             patch.object(frontend, "wait_stable") as stable, patch.object(frontend, "verify_checkout") as verify, \
             redirect_stdout(io.StringIO()):
            frontend.execute("apply", NEW)
        self.assertEqual(aws.call_args_list[-2].kwargs["input_json"]["containerDefinitions"][0]["image"], NEW)
        self.assertEqual(aws.call_args.args,
                         ("ecs", "update-service", "--cluster", "cluster", "--service", "frontend-existing",
                          "--task-definition", new_revision))
        stable.assert_called_once_with("cluster", "frontend-existing", new_revision)
        verify.assert_called_once()

    def test_verifies_the_button_in_the_lazy_module_actually_delivered(self):
        with patch.object(frontend, "fetch", side_effect=[
            '<script src="main-RPXEOIZS.js" type="module"></script>',
            'path:`checkout`,loadComponent:()=>import(`./chunk-DMbAa7AA.js`).then(t=>t.CheckoutComponent)',
            'const selector="btn-webpay";',
        ]) as fetch:
            frontend.verify_checkout()
        self.assertEqual([call.args[0] for call in fetch.call_args_list],
                         ["/checkout", "/main-RPXEOIZS.js", "/chunk-DMbAa7AA.js"])

    def test_verify_waits_for_existing_revision_without_registering_or_updating(self):
        deploying = dict(SERVICE, deployments=[{}, {}])
        with patch.object(frontend, "aws", side_effect=[{"Account": frontend.ACCOUNT}, TASK]) as aws, \
             patch.object(frontend, "find_service", return_value=("cluster", deploying)), \
             patch.object(frontend, "wait_stable") as stable, patch.object(frontend, "verify_checkout") as checkout, \
             redirect_stdout(io.StringIO()):
            frontend.execute("verify", OLD)
        self.assertEqual([call.args[1] for call in aws.call_args_list], ["get-caller-identity", "describe-task-definition"])
        stable.assert_called_once_with("cluster", "frontend-existing", frontend.FAMILY + ":2")
        checkout.assert_called_once()

    def test_verify_rejects_a_different_digest_in_the_current_revision(self):
        with patch.object(frontend, "aws", side_effect=[{"Account": frontend.ACCOUNT}, TASK]), \
             patch.object(frontend, "find_service", return_value=("cluster", SERVICE)), \
             patch.object(frontend, "wait_stable") as stable, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(frontend.RolloutError, "digest distinto"):
                frontend.execute("verify", NEW)
        stable.assert_not_called()


if __name__ == "__main__":
    unittest.main()
