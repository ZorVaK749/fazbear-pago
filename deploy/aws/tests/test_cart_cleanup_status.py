from contextlib import redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cart_cleanup_status as diagnostic


class CartCleanupDiagnosticTests(unittest.TestCase):
    at = datetime.fromisoformat("2026-11-22T21:50:00-03:00")
    route = {"RouteKey": "DELETE /api/carrito/{owner}/items/{id}", "AuthorizationType": "JWT",
             "Target": "integrations/cart123"}

    def test_inspect_reports_no_logs_without_inventing_a_request_result(self):
        responses = [{"Account": diagnostic.ACCOUNT}, {"Items": [self.route]}, {}, {}]
        with patch.object(diagnostic, "aws", side_effect=responses) as aws, redirect_stdout(io.StringIO()) as output:
            diagnostic.inspect(self.at)
        self.assertIn(self.route["RouteKey"], output.getvalue())
        self.assertIn("no tiene un grupo", output.getvalue())
        self.assertEqual([call.args[1] for call in aws.call_args_list],
                         ["get-caller-identity", "get-routes", "get-integration", "get-stage"])

    def test_inspect_filters_the_window_and_prints_no_paths_or_parameters(self):
        access_log = {"DestinationArn": diagnostic.LOG_ARN_PREFIX + "cart-access:*",
                      "Format": json.dumps({"url": "$context.path", "method": "$context.httpMethod",
                                            "code": "$context.status"})}
        events = {"events": [
            {"message": json.dumps({"url": "/ev3/api/carrito/private-owner/items/comprados?revision=private-value",
                                    "method": "DELETE", "code": "409"}),
             "timestamp": int(self.at.timestamp() * 1000)},
            {"message": "unstructured private-value"},
        ]}
        responses = [{"Account": diagnostic.ACCOUNT}, {"Items": [self.route]}, {},
                     {"AccessLogSettings": access_log}, events]
        with patch.object(diagnostic, "aws", side_effect=responses) as aws, redirect_stdout(io.StringIO()) as output:
            diagnostic.inspect(self.at)
        self.assertIn('"hora_utc": "2026-11-23T00:50:00+00:00"', output.getvalue())
        self.assertIn('"http": 409', output.getvalue())
        self.assertNotIn("private-", output.getvalue())
        self.assertEqual(aws.call_args.args, ("logs", "filter-log-events", "--log-group-name", "cart-access",
                         "--start-time", str(int(self.at.timestamp() * 1000) - 120_000), "--end-time",
                         str(int(self.at.timestamp() * 1000) + 300_000), "--filter-pattern", '"comprados"'))
