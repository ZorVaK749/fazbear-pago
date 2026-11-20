from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webpay_release as cli
import webpay_release_host as host

IMAGE = host.PACKAGE + "@sha256:" + "a" * 64


class WebpayReleaseTest(unittest.TestCase):
    def test_apply_uses_the_live_payment_instance_and_checks_target_health(self):
        with patch.object(cli, "aws", return_value={"Account": cli.ACCOUNT}), \
                patch.object(cli, "private_ip", return_value="172.31.11.205"), \
                patch.object(cli, "resolve_target", return_value=("group", cli.INSTANCE, 30)), \
                patch.object(cli, "target_state", return_value="healthy"), \
                patch.object(cli, "run_ssm") as remote, patch.object(cli, "wait_for_target") as health, \
                redirect_stdout(io.StringIO()):
            cli.execute("apply", IMAGE)
        request = remote.call_args.args[0]
        self.assertEqual(request["InstanceIds"], [cli.INSTANCE])
        self.assertIn(IMAGE, request["Parameters"]["commands"][-2])
        health.assert_called_once_with("group", cli.INSTANCE, 30, port=8087)

    def test_backup_persists_snapshot_without_printing_provider_data(self):
        release = host.WebpayRelease("172.31.11.205", IMAGE)
        snapshot = {table: [] for table in host.BACKUP_TABLES}
        snapshot["flyway_schema_history"] = [{"version": "4", "success": True}]
        snapshot["webpay_transaction"] = [{"provider_token": "private-token-for-test"}]
        raw = json.dumps(snapshot).encode()
        output = io.StringIO()
        with patch.object(host, "run", return_value=raw) as command, \
                patch.object(host, "write_private") as write, patch.object(Path, "read_bytes", return_value=raw), \
                redirect_stdout(output):
            release.backup_database({"PGPASSWORD": "password-for-test"})
        self.assertIn("SELECT json_build_object", command.call_args.args[0][-1])
        self.assertEqual(write.call_args.args[1], raw)
        self.assertIn("SHA256", output.getvalue())
        self.assertNotIn("private-token-for-test", output.getvalue())
        self.assertNotIn("password-for-test", output.getvalue())
