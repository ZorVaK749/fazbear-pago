from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webpay_cors as cors


class CorsPolicyTests(unittest.TestCase):
    def test_merges_existing_policy_and_is_idempotent(self):
        current = {
            "AllowOrigins": ["https://otra.example"],
            "AllowMethods": ["PATCH"],
            "AllowHeaders": ["Authorization", "x-existing"],
            "ExposeHeaders": ["X-Request-Id"],
            "AllowCredentials": True,
            "MaxAge": 120,
        }
        result = cors.desired_policy(current)
        self.assertEqual(result["AllowOrigins"], ["https://otra.example", cors.ORIGIN])
        self.assertEqual(result["AllowHeaders"], ["Authorization", "x-existing", "content-type", "idempotency-key"])
        self.assertEqual(result["AllowMethods"], ["PATCH", "GET", "POST", "PUT", "DELETE", "OPTIONS"])
        self.assertEqual(result["ExposeHeaders"], ["X-Request-Id"])
        self.assertEqual(result["MaxAge"], 120)
        self.assertTrue(result["AllowCredentials"])
        self.assertEqual(cors.desired_policy(result), result)
        self.assertEqual(current["AllowMethods"], ["PATCH"])

    def test_204_without_cors_headers_is_a_failure(self):
        with patch.object(cors, "exchange", return_value=(204, {})):
            with self.assertRaisesRegex(cors.RolloutError, "HTTP 204"):
                cors.verify()

    def test_healthy_preflights_and_unauthenticated_get(self):
        def gateway(path, method, headers):
            if method == "GET":
                return 401, {}
            self.assertEqual(headers["Origin"], cors.ORIGIN)
            return 204, {
                "Access-Control-Allow-Origin": cors.ORIGIN,
                "Access-Control-Allow-Methods": headers["Access-Control-Request-Method"],
                "Access-Control-Allow-Headers": headers["Access-Control-Request-Headers"],
            }

        with patch.object(cors, "exchange", side_effect=gateway) as request:
            cors.verify()
            self.assertEqual(request.call_count, len(cors.PROBES) + 1)
            self.assertEqual({call.args[1] for call in request.call_args_list}, {"OPTIONS", "GET"})

    def test_apply_updates_only_cors_and_verifies_edge(self):
        live = {"ProtocolType": "HTTP", "CorsConfiguration": {"AllowOrigins": ["https://otra.example"]}}
        with patch.object(cors, "aws", side_effect=[{"Account": cors.ACCOUNT}, live, {"AutoDeploy": True}, {}]) as aws, \
             patch.object(cors, "wait_for_cors") as verify, redirect_stdout(io.StringIO()):
            cors.execute("apply")
        args = aws.call_args.args
        self.assertEqual(args[:-1], ("apigatewayv2", "update-api", "--api-id", cors.API_ID, "--cors-configuration"))
        self.assertEqual(json.loads(args[-1]), cors.desired_policy(live["CorsConfiguration"]))
        verify.assert_called_once()

    def test_apply_preserves_manual_stage_for_operator_review(self):
        with patch.object(cors, "aws", side_effect=[{"Account": cors.ACCOUNT}, {"ProtocolType": "HTTP"},
                                                  {"AutoDeploy": False}]) as aws, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(cors.RolloutError, "despliegue manual"):
                cors.execute("apply")
        self.assertEqual([call.args[1] for call in aws.call_args_list], ["get-caller-identity", "get-api", "get-stage"])

    def test_dry_run_never_updates_gateway(self):
        responses = [{"Account": cors.ACCOUNT}, {"ProtocolType": "HTTP"}, {"AutoDeploy": True}]
        with patch.object(cors, "aws", side_effect=responses) as aws, redirect_stdout(io.StringIO()):
            cors.execute("dry-run")
        self.assertEqual(aws.call_count, 3)


if __name__ == "__main__":
    unittest.main()
