import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webpay_payment_status_host as host


class WebpayPaymentStatusTests(unittest.TestCase):
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
