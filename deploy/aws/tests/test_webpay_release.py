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
    def test_ev3_return_requires_working_frontend_before_requesting_ssm(self):
        with patch.object(cli, "aws", return_value={"Account": cli.ACCOUNT}), \
                patch.object(cli, "private_ip", return_value="172.31.11.205"), \
                patch.object(cli, "verify_named_stage", side_effect=cli.RolloutError("Frontend pendiente")), \
                patch.object(cli, "run_ssm") as remote:
            with self.assertRaisesRegex(cli.RolloutError, "Frontend pendiente"):
                cli.execute("apply", IMAGE, 6, "ev3")
        remote.assert_not_called()

    def test_ev3_return_candidate_overrides_only_the_return_url_from_v6(self):
        release = host.WebpayRelease("172.31.11.205", IMAGE, 6, "ev3")
        old = {"Name": "/" + host.CONTAINER, "Config": {"Image": host.V6_IMAGE}}
        with patch.object(host.Backend, "preflight", return_value=(old, {})), \
                patch.object(release, "mode", return_value=host.ENABLED_MODE), \
                patch.object(release, "rollback_database_config"), \
                patch.object(release, "candidate_config", return_value={"new": True}) as candidate:
            self.assertEqual(release.preflight(), (old, {"new": True}))
        candidate.assert_called_once_with(old, {"WEBPAY_RETURN_URL": host.RETURN_URL_EV3},
                                          image=IMAGE, replace_keys={"WEBPAY_RETURN_URL"})

    def test_apply_uses_the_live_payment_instance_and_checks_target_health(self):
        with patch.object(cli, "aws", return_value={"Account": cli.ACCOUNT}), \
                patch.object(cli, "private_ip", return_value="172.31.11.205"), \
                patch.object(cli, "resolve_target", return_value=("group", cli.INSTANCE, 30)), \
                patch.object(cli, "target_state", return_value="healthy"), \
                patch.object(cli, "run_ssm") as remote, patch.object(cli, "wait_for_target") as health, \
                redirect_stdout(io.StringIO()):
            cli.execute("apply", IMAGE, 6)
        request = remote.call_args.args[0]
        self.assertEqual(request["InstanceIds"], [cli.INSTANCE])
        self.assertIn(IMAGE, request["Parameters"]["commands"][-2])
        self.assertTrue(request["Parameters"]["commands"][-2].endswith(" 6"))
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
