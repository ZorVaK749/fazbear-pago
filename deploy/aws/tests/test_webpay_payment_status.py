import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webpay_payment_status_host as host
import webpay_payment_status as cli


class WebpayPaymentStatusTests(unittest.TestCase):
    def test_antifraud_reads_attempts_and_alerts_for_the_reference_account(self):
        payment = UUID("9105d229-9ef2-4adc-a85b-0ab3dd71e17a")
        result = {"intentos": [{"estado": "BLOCKED", "intentos_en_ventana": 4, "alerta_registrada": True}]}
        with patch.object(host, "payment_env", return_value=["PRIVATE=fake"]), \
                patch.object(host, "read_row", return_value=result) as read, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(host.main(["antifraude", str(payment)]), 0)
        env, sql = read.call_args.args
        self.assertEqual(env, ["PRIVATE=fake"])
        self.assertIn("BEGIN READ ONLY;", sql)
        self.assertIn("JOIN payment p USING (tenant_id, owner_id, instrument_id)", sql)
        self.assertIn("LEFT JOIN fraud_alert f ON f.attempt_id=a.id", sql)
        self.assertIn(f"WHERE id='{payment}'::uuid AND simulation", sql)
        self.assertEqual(json.loads(out.getvalue()), result)

    def test_antifraud_command_only_queries_the_pago_instance(self):
        payment = "9105d229-9ef2-4adc-a85b-0ab3dd71e17a"
        with patch.object(sys, "argv", ["status", "--antifraude", "--payment-id", payment]), \
                patch.object(cli, "aws", return_value={"Account": cli.ACCOUNT}), \
                patch.object(cli, "inspect") as inspect:
            self.assertEqual(cli.main(), 0)
        inspect.assert_called_once_with(cli.INSTANCE, "antifraude", payment)

    def test_provider_get_reports_only_reconciliation_fields(self):
        row = {"token": "syntheticreference000001", "importe": 25980, "orden": "related-order", "sesion": "related-session"}
        settings = {"WEBPAY_COMMERCE_CODE": "000000000001", "WEBPAY_API_KEY": "private-fixture"}
        response = {"amount": 25980, "status": "AUTHORIZED", "response_code": 0,
                    "buy_order": row["orden"], "session_id": row["sesion"], "authorization_code": "private-fixture"}
        with patch.object(host, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(response).encode())
            summary = host.read_provider(row, settings)
        self.assertEqual(summary, {"consulta": "HTTP 200", "estado": "AUTHORIZED", "codigo": 0, "referencias_validas": True})
        self.assertEqual(opener.return_value.open.call_args.args[0].get_method(), "GET")

    def test_provider_error_never_reports_its_url_or_body(self):
        row = {"token": "syntheticreference000001"}
        settings = {"WEBPAY_COMMERCE_CODE": "000000000001", "WEBPAY_API_KEY": "private-fixture"}
        error = HTTPError(host.PROVIDER_URL + row["token"], 404, "rejected", {}, io.BytesIO(b"private-fixture"))
        with patch.object(host, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            self.assertEqual(host.read_provider(row, settings), {"consulta": "HTTP 404"})
