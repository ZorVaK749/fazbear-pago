from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frontend_gateway as gateway


class FrontendGatewayTests(unittest.TestCase):
    target = "integrations/abc123"
    default_route = {"RouteKey": "$default", "AuthorizationType": "NONE", "Target": target, "RouteId": "legacy1"}
    default_stage = {"StageName": "$default", "AutoDeploy": False, "DeploymentId": "legacy-deployment",
                     "StageVariables": {"example": "synthetic"}}

    def test_prepare_adds_routes_and_named_stage_without_removing_current_gateway(self):
        default = {"RouteKey": "$default", "AuthorizationType": "NONE", "Target": self.target}
        with patch.object(gateway, "inventory", return_value=({"$default": default}, {"$default": {}}, self.target)), \
                patch.object(gateway, "aws") as aws, patch.object(gateway, "wait_for_stage") as verify, \
                redirect_stdout(io.StringIO()):
            gateway.execute("prepare")
        self.assertEqual([call.args[1] for call in aws.call_args_list],
                         ["create-route"] * len(gateway.ROUTES) + ["create-stage"])
        self.assertEqual(aws.call_args.args[-3:], ("--stage-name", "ev3", "--auto-deploy"))
        verify.assert_called_once()

    def test_conflicting_route_is_not_replaced(self):
        routes = {"GET /login": {"AuthorizationType": "JWT", "Target": self.target}}
        with self.assertRaisesRegex(gateway.RolloutError, "autorización diferente"):
            gateway.missing_routes(routes, self.target)

    def test_dry_run_never_creates_a_route_or_stage(self):
        with patch.object(gateway, "inventory", return_value=({}, {}, self.target)), \
                patch.object(gateway, "aws") as aws, redirect_stdout(io.StringIO()):
            gateway.execute("dry-run")
        aws.assert_not_called()

    def test_verify_checks_named_stage_paths_and_lazy_checkout_assets(self):
        routes = {key: {"AuthorizationType": "NONE", "Target": self.target} for key in gateway.ROUTES}
        stages = {"ev3": {"DeploymentId": "approvable"}}
        with patch.object(gateway, "inventory", return_value=(routes, stages, self.target)), \
                patch.object(gateway, "fetch", return_value="<app-root></app-root><script>'/ev3/'</script>") as fetch, \
                patch.object(gateway, "verify_checkout") as checkout, \
                patch.object(gateway, "verify_post_return") as return_post, redirect_stdout(io.StringIO()):
            gateway.execute("verify")
        self.assertIn("/ev3/checkout/webpay", [call.args[0] for call in fetch.call_args_list])
        checkout.assert_called_once_with("/ev3")
        return_post.assert_called_once_with("/ev3")

    def test_post_return_requires_an_internal_redirect_and_never_follows_it(self):
        for status, location in ((303, "webpay#TBK_TOKEN=synthetic-probe"), (405, ""),
                                 (303, "https://other.example/webpay")):
            with self.subTest(status=status, location=location), patch.object(gateway, "build_opener") as opener:
                opener.return_value.open.side_effect = HTTPError(
                    "https://example.test/ev3/checkout/webpay", status, "", {"Location": location}, io.BytesIO()
                )
                if location == "webpay#TBK_TOKEN=synthetic-probe":
                    gateway.verify_post_return("/ev3")
                else:
                    with self.assertRaisesRegex(gateway.RolloutError, f"HTTP {status}"):
                        gateway.verify_post_return("/ev3")
                request = opener.return_value.open.call_args.args[0]
                self.assertEqual(request.get_method(), "POST")
                self.assertEqual(request.data, b"TBK_TOKEN=synthetic-probe")
        self.assertIsNone(gateway.NoRedirect().redirect_request(None, None, 303, "", {}, "https://other.example"))

    def test_default_fallback_response_does_not_certify_the_named_stage(self):
        with patch.object(gateway, "inventory", return_value=({}, {"$default": {}}, self.target)), \
                patch.object(gateway, "fetch") as fetch:
            with self.assertRaisesRegex(gateway.RolloutError, "despliegue ev3"):
                gateway.execute("verify")
        fetch.assert_not_called()

    def test_retirement_rejects_unfinished_payments_without_deleting(self):
        stages = {"ev3": {"AutoDeploy": True}, "$default": self.default_stage}
        with TemporaryDirectory() as directory, patch.object(gateway, "verify_named_stage"), \
                patch.object(gateway, "inventory", return_value=({"$default": self.default_route}, stages, self.target)), \
                patch.object(gateway, "inspect_payments", return_value='{"total_sin_estado_final": 1}'), \
                patch.object(gateway, "aws") as aws:
            backup = Path(directory) / "backup.json"
            with self.assertRaisesRegex(gateway.RolloutError, "sin estado final"):
                gateway.retire_default(backup)
            self.assertFalse(backup.exists())
        aws.assert_not_called()

    def test_retirement_saves_the_route_and_stage_before_removing_only_default(self):
        stages = {"ev3": {"AutoDeploy": True}, "$default": self.default_stage}
        with TemporaryDirectory() as directory, patch.object(gateway, "verify_named_stage"), \
                patch.object(gateway, "inventory", return_value=({"$default": self.default_route}, stages, self.target)), \
                patch.object(gateway, "inspect_payments", return_value='{"total_sin_estado_final": 0}'), \
                patch.object(gateway, "aws") as aws, patch.object(gateway, "wait_for_stage") as verify, \
                redirect_stdout(io.StringIO()):
            backup_path = Path(directory) / "backup.json"

            def check_backup(*args):
                snapshot = json.loads(backup_path.read_text(encoding="utf-8"))
                self.assertEqual(snapshot["stage"], self.default_stage)
                self.assertEqual(snapshot["route"], self.default_route)

            aws.side_effect = check_backup
            gateway.execute("retire-default", backup_path)
        self.assertEqual([call.args for call in aws.call_args_list], [
            ("apigatewayv2", "delete-stage", "--api-id", gateway.API, "--stage-name", "$default"),
            ("apigatewayv2", "delete-route", "--api-id", gateway.API, "--route-id", "legacy1"),
        ])
        verify.assert_called_once_with(retired=True)

    def test_restores_default_from_the_snapshot_using_the_previous_deployment(self):
        with TemporaryDirectory() as directory, patch.object(gateway, "inventory", return_value=({}, {}, self.target)), \
                patch.object(gateway, "aws") as aws, patch.object(gateway, "wait_for_stage"), \
                redirect_stdout(io.StringIO()):
            backup_path = Path(directory) / "backup.json"
            backup_path.write_text(json.dumps({"account": gateway.ACCOUNT, "api": gateway.API, "target": self.target,
                                               "route": self.default_route, "stage": self.default_stage}), encoding="utf-8")
            gateway.execute("restore-default", backup_path)
        self.assertEqual([call.args[1] for call in aws.call_args_list], ["create-route", "create-stage"])
        self.assertEqual(aws.call_args.kwargs["input_json"], {"ApiId": gateway.API, **self.default_stage})

    def test_retirement_checks_that_root_and_unknown_named_routes_return_404(self):
        routes = {key: {"AuthorizationType": "NONE", "Target": self.target} for key in gateway.ROUTES}
        stages = {"ev3": {"DeploymentId": "active"}}
        with patch.object(gateway, "inventory", return_value=(routes, stages, self.target)), \
                patch.object(gateway, "fetch", return_value="<app-root></app-root><base href='/ev3/'>"), \
                patch.object(gateway, "verify_checkout"), patch.object(gateway, "verify_post_return"), \
                patch.object(gateway, "expect_not_found") as unavailable, redirect_stdout(io.StringIO()):
            gateway.verify_named_stage(retired=True)
        self.assertEqual([call.args[0] for call in unavailable.call_args_list], ["/", "/ev3/_verificacion/ruta-inexistente"])
