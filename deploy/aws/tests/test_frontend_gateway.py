from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frontend_gateway as gateway


class FrontendGatewayTests(unittest.TestCase):
    target = "integrations/abc123"

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
                patch.object(gateway, "verify_checkout") as checkout, redirect_stdout(io.StringIO()):
            gateway.execute("verify")
        self.assertIn("/ev3/checkout/webpay", [call.args[0] for call in fetch.call_args_list])
        checkout.assert_called_once_with("/ev3")

    def test_default_fallback_response_does_not_certify_the_named_stage(self):
        with patch.object(gateway, "inventory", return_value=({}, {"$default": {}}, self.target)), \
                patch.object(gateway, "fetch") as fetch:
            with self.assertRaisesRegex(gateway.RolloutError, "despliegue ev3"):
                gateway.execute("verify")
        fetch.assert_not_called()
