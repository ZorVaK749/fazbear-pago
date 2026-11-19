import base64
from contextlib import redirect_stdout
import copy
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webpay
import webpay_host as host

ORIGINAL = b"# config\r\nPAGO_DB_PASSWORD=pago=secret\r\nFEATURE=value"
KEY = "a" * 64
OVERRIDES = {"WEBPAY_ENABLED": "true", "WEBPAY_COMMERCE_CODE": "000000000000",
             "WEBPAY_API_KEY": KEY, "WEBPAY_RETURN_URL": host.RETURN_URL}


class FakeHost(host.Host):
    def __init__(self, env_file):
        super().__init__(env_file)
        self.containers = {"old": {
            "Id": "old", "Name": "/ev3-pago", "Image": "sha256:existing",
            "State": {"Running": True}, "Mounts": [], "NetworkSettings": {"Networks": {"bridge": {}}},
            "Config": {"Image": host.IMAGE, "User": "10001:10001", "Entrypoint": ["java", "-jar", "app.jar"],
                       "Cmd": None, "Env": ["SPRING_PROFILES_ACTIVE=ev3-aws",
                           "PAGO_DB_URL=jdbc:postgresql://db.example.test:5432/payment?sslmode=require",
                           "PAGO_DB_USER=app", "PAGO_DB_PASSWORD=pago=secret", "FEATURE=value",
                           "WEBPAY_ENABLED=false"]},
            "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "", "HostPort": "8087"}]},
                           "Memory": 640 * 1024**2, "RestartPolicy": {"Name": "unless-stopped"}, "NetworkMode": "default"},
        }}
        self.calls = []
        self.fail_once = None
        self.transaction_count = 0

    def inspect(self, reference):
        container = self.find(reference)
        if container is None:
            raise host.RolloutError("Contenedor de prueba ausente.")
        return container

    def find(self, reference):
        found = next((c for c in self.containers.values() if reference in (c["Id"], c["Name"][1:])), None)
        return copy.deepcopy(found)

    def docker(self, *args, **kwargs):
        self.calls.append(args)
        if args[:2] == ("image", "inspect"):
            return b"sha256:existing\n"
        if self.fail_once and args[0] == self.fail_once:
            self.fail_once = None
            raise host.RolloutError("Fallo Docker de prueba.")
        if args[0] == "rename":
            self.containers[args[1]]["Name"] = "/" + args[2]
        elif args[0] in ("start", "restart", "stop"):
            self.containers[args[-1]]["State"]["Running"] = args[0] != "stop"

    def create(self, name, config):
        container = copy.deepcopy(self.containers["old"])
        container.update(Id="new", Name="/" + name, State={"Running": False})
        container["Config"] = {k: v for k, v in config.items() if k not in {"HostConfig", "NetworkingConfig"}}
        container["HostConfig"] = config["HostConfig"]
        self.containers["new"] = container
        return "new"

    def mode(self):
        container = self.find(host.CONTAINER)
        if container and container["State"]["Running"]:
            return host.ENABLED_MODE if "WEBPAY_ENABLED=true" in container["Config"]["Env"] else host.DISABLED_MODE
        return None

    def wait_health(self, expected):
        if self.mode() != expected:
            raise host.RolloutError("Health de prueba inesperado.")

    def database_used(self, env):
        assert not self.containers["new"]["State"]["Running"]
        assert env["PGDATABASE"] == "payment"
        if self.transaction_count is None:
            raise host.RolloutError("BD inconclusa.")
        return self.transaction_count > 0


class RolloutTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name) / "pago.env"
        path.write_bytes(ORIGINAL)
        self.client = FakeHost(path)
        self.client.state_dir.mkdir(mode=0o700)
        self.start_patch(patch.object(host, "webpay_overrides", return_value=OVERRIDES))
        self.start_patch(patch.object(host.shutil, "which", return_value="/usr/bin/psql"))
        self.output = io.StringIO()
        self.start_patch(redirect_stdout(self.output))
        if os.name == "nt":
            # Exercise the same state machine on Windows; Linux CI also exercises
            # POSIX owner checks and atomic writes with directory fsync.
            self.start_patch(patch.object(host, "private_file", side_effect=lambda p, **kw: p.read_bytes()))
            self.start_patch(patch.object(host, "write_private", side_effect=lambda p, data: p.write_bytes(data)))
            self.start_patch(patch.object(self.client, "check_state_dir"))

    def start_patch(self, context):
        self.addCleanup(context.__exit__, None, None, None)
        return context.__enter__()

    def test_dry_run_never_changes_runtime_or_reads_secret_values(self):
        self.client.status("ssm", True)
        self.assertEqual(self.client.env_file.read_bytes(), ORIGINAL)
        self.assertFalse(self.client.journal.exists())
        host.webpay_overrides.assert_not_called()

    def test_credential_check_validates_without_printing_or_persisting_credentials(self):
        self.client.status("ssm", True, check_credentials=True)
        host.webpay_overrides.assert_called_once_with("ssm")
        self.assertIn("lectura y formato verificados", self.output.getvalue())
        self.assertNotIn(KEY, self.output.getvalue())
        self.assertEqual(self.client.env_file.read_bytes(), ORIGINAL)
        self.assertFalse(self.client.journal.exists())

    def test_apply_preserves_container_environment_and_original_file(self):
        self.client.apply("ssm")
        candidate = self.client.inspect(host.CONTAINER)
        original = self.client.inspect("old")
        self.assertEqual(candidate["HostConfig"], original["HostConfig"])
        self.assertEqual(candidate["Config"]["User"], original["Config"]["User"])
        self.assertEqual(candidate["Config"]["Image"], host.IMAGE)
        candidate_vars = host.env_values(candidate["Config"]["Env"])
        self.assertEqual(candidate_vars["PAGO_DB_PASSWORD"], "pago=secret")
        self.assertEqual(candidate_vars["FEATURE"], "value")
        self.assertEqual(candidate_vars["WEBPAY_RETURN_URL"], host.RETURN_URL)
        self.assertFalse(original["State"]["Running"])
        self.assertEqual(self.client.backup(self.client.state()).read_bytes(), ORIGINAL)
        self.assertTrue(self.client.env_file.read_bytes().startswith(ORIGINAL + b"\n"))
        self.assertNotIn(KEY, self.output.getvalue())
        self.assertNotIn("pago=secret", self.output.getvalue())
        self.client.apply("ssm")
        host.webpay_overrides.assert_called_once()

    def test_failure_before_start_restores_previous_configuration(self):
        self.client.fail_once = "rename"
        with self.assertRaisesRegex(host.RolloutError, "antes de iniciar Webpay"):
            self.client.apply("ssm")
        self.assertEqual(self.client.inspect(host.CONTAINER)["Id"], "old")
        self.assertEqual(self.client.state()["phase"], "rolled_back")
        self.assertEqual(self.client.env_file.read_bytes(), ORIGINAL)
        self.assertNotIn(("start", "new"), self.client.calls)

    def test_uncertain_start_is_recovered_with_same_candidate(self):
        self.client.fail_once = "start"
        with self.assertRaises(host.RolloutError):
            self.client.apply("ssm")
        self.assertEqual(self.client.state()["phase"], "start_requested")
        self.assertFalse(self.client.inspect("old")["State"]["Running"])
        self.client.recover()
        self.assertEqual(self.client.inspect(host.CONTAINER)["Id"], "new")
        self.assertEqual(self.client.state()["phase"], "active")

    def test_rollback_proves_database_empty_and_restores_previous_container(self):
        self.client.apply("ssm")
        self.client.rollback()
        self.assertEqual(self.client.inspect(host.CONTAINER)["Id"], "old")
        self.assertEqual(self.client.env_file.read_bytes(), ORIGINAL)
        self.assertFalse(self.client.inspect("new")["State"]["Running"])

    def test_rollback_keeps_webpay_active_with_existing_or_uncertain_data(self):
        self.client.apply("ssm")
        for outcome in (1, None):
            with self.subTest(outcome=outcome):
                self.client.transaction_count = outcome
                with self.assertRaises(host.RolloutError):
                    self.client.rollback()
                self.assertEqual(self.client.state()["phase"], "active")
                self.assertEqual(self.client.mode(), host.ENABLED_MODE)
                self.assertNotIn(("start", "old"), self.client.calls)

    def test_rollback_refuses_to_stop_container_without_psql(self):
        self.client.apply("ssm")
        with patch.object(host.shutil, "which", return_value=None), self.assertRaisesRegex(host.RolloutError, "psql"):
            self.client.rollback()
        self.assertNotIn(("stop", "-t", "20", "new"), self.client.calls)

    def test_prepare_rollback_installs_only_the_client_on_al2023_then_reads_rds(self):
        with patch.object(host.shutil, "which", side_effect=[None, "/usr/bin/psql"]), \
             patch.object(host, "system_release", return_value="amzn 2023"), \
             patch.object(host, "run") as run, \
             patch.object(self.client, "database_used", return_value=False) as check:
            self.client.prepare_rollback()
            self.assertEqual(run.call_args.args[0], ["dnf", "install", "-y", "postgresql15"])
            self.assertEqual(check.call_args.args[0]["PGDATABASE"], "payment")
            self.assertFalse(any(call[0] in {"stop", "start", "restart"} for call in self.client.calls))
            self.assertFalse(self.client.journal.exists())

    def test_prepare_rollback_refuses_to_install_on_a_different_distribution(self):
        with patch.object(host.shutil, "which", return_value=None), \
             patch.object(host, "system_release", return_value="ubuntu 24.04"), \
             patch.object(host, "run") as run:
            with self.assertRaisesRegex(host.RolloutError, "Amazon Linux 2023"):
                self.client.prepare_rollback()
            run.assert_not_called()

    def test_rollback_never_guesses_an_overridden_datasource(self):
        self.client.apply("ssm")
        self.client.containers["new"]["Config"]["Env"].append("SPRING_DATASOURCE_JNDI_NAME=db/other")
        with self.assertRaisesRegex(host.RolloutError, "SPRING_DATASOURCE_JNDI_NAME"):
            self.client.rollback()
        self.assertNotIn(("stop", "-t", "20", "new"), self.client.calls)

    def test_prepare_rollback_accepts_memory_and_pool_limits_proven_not_to_change_the_datasource(self):
        self.client.containers["old"]["Config"]["Env"].extend([
            "JAVA_TOOL_OPTIONS=-Xms128m -Xmx320m -XX:MaxRAMPercentage=65.0 -XX:+UseSerialGC",
            "SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE=6",
            "SPRING_DATASOURCE_DRIVER_CLASS_NAME=org.postgresql.Driver",
        ])
        with patch.object(self.client, "database_used", return_value=False) as check:
            self.client.prepare_rollback()
        self.assertEqual(check.call_args.args[0]["PGDATABASE"], "payment")

    def test_datasource_override_in_jvm_is_rejected_without_printing_value(self):
        private_value = "jdbc:postgresql://private.example.test/other"
        self.client.containers["old"]["Config"]["Env"].append(
            "JAVA_TOOL_OPTIONS=-Xmx320m -Dspring.datasource.url=" + private_value)
        with self.assertRaisesRegex(host.RolloutError, "JAVA_TOOL_OPTIONS") as blocked:
            self.client.prepare_rollback()
        self.assertNotIn(private_value, str(blocked.exception))


class AwsDispatchTests(unittest.TestCase):
    def setUp(self):
        account = patch.object(webpay, "aws", return_value={"Account": webpay.ACCOUNT})
        account.start()
        self.addCleanup(account.stop)

    def test_wrong_account_stops_before_elb_or_ssm(self):
        with patch.object(webpay, "aws", return_value={"Account": "000000000000"}) as aws, \
             patch.object(webpay, "resolve_target") as resolve, patch.object(webpay, "run_host") as remote:
            with self.assertRaisesRegex(host.RolloutError, webpay.ACCOUNT):
                webpay.execute("apply", "ssm", None)
            aws.assert_called_once_with("sts", "get-caller-identity")
            resolve.assert_not_called()
            remote.assert_not_called()

    def test_rejects_target_group_owned_by_another_account(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/pago/0123456789abcdef"
        with patch.object(webpay, "resolve_target") as resolve:
            with self.assertRaisesRegex(host.RolloutError, "otra cuenta"):
                webpay.execute("dry-run", "ssm", arn)
            resolve.assert_not_called()

    def test_provisioning_checks_aws_account_without_sending_a_remote_command(self):
        with patch.object(webpay, "create_parameters") as create, patch.object(webpay, "run_host") as remote:
            webpay.execute("create-parameters", "ssm", None)
            webpay.aws.assert_called_once_with("sts", "get-caller-identity")
            create.assert_called_once()
            remote.assert_not_called()

    def test_payload_contains_reviewed_source_and_switches_only(self):
        request = webpay.ssm_request("apply", "ssm")
        self.assertEqual(request["InstanceIds"], [webpay.INSTANCE])
        commands = request["Parameters"]["commands"]
        chunks = "".join(re.findall(r"printf %s '([A-Za-z0-9+/=]+)'", "\n".join(commands)))
        self.assertEqual(gzip.decompress(base64.b64decode(chunks)), webpay.HOST_SCRIPT.read_bytes())
        self.assertTrue(commands[-2].endswith("python3 - apply ssm"))
        self.assertEqual(commands[-1], "PEDIDOS360_WEBPAY")
        self.assertNotIn(KEY, repr(request))
        self.assertLess(max(map(len, commands)), 4096)

    def test_credential_check_passes_only_the_read_only_switch_to_ssm(self):
        request = webpay.ssm_request("dry-run", "ssm", check_credentials=True)
        self.assertTrue(request["Parameters"]["commands"][-2].endswith("python3 - dry-run ssm --check-credentials"))
        self.assertNotIn(KEY, repr(request))

    @unittest.skipUnless(os.name == "posix", "Requiere el shell POSIX de SSM")
    def test_payload_runs_through_a_posix_shell_and_passes_only_two_switches(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "host.py"
            path.write_text("import sys\nprint(*sys.argv[1:])\n", encoding="utf-8")
            with patch.object(webpay, "HOST_SCRIPT", path):
                commands = webpay.ssm_request("status", "host-file")["Parameters"]["commands"]
            result = subprocess.run(["/bin/sh", "-c", "\n".join(commands)], check=True, capture_output=True)
            self.assertEqual(result.stdout, b"status host-file\n")

    def test_unhealthy_initial_target_stops_apply_before_ssm(self):
        with patch.object(webpay, "resolve_target", return_value=("arn", "target", 30)), \
             patch.object(webpay, "target_state", return_value="unhealthy"), \
             patch.object(webpay, "run_host") as remote:
            with self.assertRaisesRegex(host.RolloutError, "preparar o activar"):
                webpay.execute("apply", "ssm", None)
            remote.assert_not_called()

    def test_target_must_stay_healthy_for_at_least_one_health_interval(self):
        with patch.object(webpay, "target_state", side_effect=["healthy", "unhealthy", "healthy", "healthy"]), \
             patch.object(webpay.time, "monotonic", side_effect=[0, 0, 0, 5, 5, 10, 10, 15, 15]), \
             patch.object(webpay.time, "sleep") as sleep:
            webpay.wait_for_target("arn", "target", 5)
            self.assertEqual(sleep.call_count, 3)

    def test_unhealthy_target_after_cutover_never_dispatches_a_rollback(self):
        with patch.object(webpay, "resolve_target", return_value=("arn", "target", 30)), \
             patch.object(webpay, "target_state", return_value="healthy"), \
             patch.object(webpay, "wait_for_target", side_effect=host.RolloutError("unhealthy")), \
             patch.object(webpay, "run_host") as remote:
            with self.assertRaises(host.RolloutError):
                webpay.execute("apply", "ssm", None)
            remote.assert_called_once_with("apply", "ssm", False)

    def test_status_reads_host_diary_even_when_target_cannot_be_found(self):
        with patch.object(webpay, "resolve_target", side_effect=host.RolloutError("absent")), \
             patch.object(webpay, "run_host") as remote:
            with self.assertRaises(host.RolloutError):
                webpay.execute("status", "ssm", None)
            remote.assert_called_once_with("status", "ssm", False)

    def test_ip_target_resolution_uses_registration_and_port(self):
        target = {"Target": {"Id": "172.31.11.205", "Port": 8087}}
        group = {"TargetType": "ip", "TargetGroupArn": "arn", "Port": 80,
                 "HealthCheckPort": "8087", "HealthCheckIntervalSeconds": 15}
        with patch.object(webpay, "private_ip", return_value="172.31.11.205"), \
             patch.object(webpay, "aws", return_value={"TargetGroups": [group]}), \
             patch.object(webpay, "registered", return_value=[target]):
            self.assertEqual(webpay.resolve_target(None), ("arn", "172.31.11.205", 15))

    def test_securestring_reader_rejects_plain_string_even_with_valid_key(self):
        records = {"Parameters": [
            {"Name": host.PARAMETERS["WEBPAY_API_KEY"], "Type": "String", "Value": KEY},
            {"Name": host.PARAMETERS["WEBPAY_COMMERCE_CODE"], "Type": "SecureString", "Value": "000000000000"},
        ]}
        with patch.object(host, "run", return_value=json.dumps(records).encode()) as aws_cli:
            with self.assertRaisesRegex(host.RolloutError, "tipo SecureString"):
                host.webpay_overrides("ssm")
            self.assertNotIn(KEY, repr(aws_cli.call_args.args))

    def test_missing_credentials_reports_only_predefined_names(self):
        with patch.object(host, "run", return_value=b'{"Parameters": []}'):
            with self.assertRaisesRegex(host.RolloutError, host.PARAMETERS["WEBPAY_API_KEY"]):
                host.webpay_overrides("ssm")


class CredentialProvisionTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux" and shutil.which("aws"), "Requiere AWS CLI en Linux")
    def test_aws_cli_accepts_securestring_json_from_anonymous_memory_without_an_api_call(self):
        payload = {"Name": host.PARAMETERS["WEBPAY_API_KEY"], "Value": KEY,
                   "Type": "SecureString", "Tier": "Standard", "Overwrite": False}
        env = {"AWS_EC2_METADATA_DISABLED": "true", "AWS_CONFIG_FILE": "/dev/null",
               "AWS_SHARED_CREDENTIALS_FILE": "/dev/null", "AWS_ACCESS_KEY_ID": "fixture",
               "AWS_SECRET_ACCESS_KEY": "fixture"}
        with patch.dict(os.environ, env):
            result = webpay.aws("ssm", "put-parameter", "--endpoint-url", "http://127.0.0.1:1",
                                "--generate-cli-skeleton", "output", input_json=payload)
        self.assertIn("Version", result)

    def test_creates_only_fixed_securestrings_and_never_prints_secret_values(self):
        output = io.StringIO()
        code = "001234567890"
        with patch.object(webpay.os, "memfd_create", create=True), \
             patch.object(webpay.sys.stdin, "isatty", return_value=True), \
             patch.object(webpay.getpass, "getpass", side_effect=[code, KEY]), \
             patch.object(webpay, "aws", side_effect=[{"Version": 1}, {"AlreadyExists": True}]) as aws, \
             redirect_stdout(output):
            webpay.create_parameters()
        self.assertEqual(aws.call_count, 2)
        payloads = [call.kwargs["input_json"] for call in aws.call_args_list]
        self.assertEqual([item["Name"] for item in payloads], list(host.PARAMETERS.values()))
        self.assertEqual([item["Value"] for item in payloads], [code, KEY])
        for call, item in zip(aws.call_args_list, payloads):
            self.assertEqual(call.args, ("ssm", "put-parameter"))
            self.assertEqual(item["Type"], "SecureString")
            self.assertEqual(item["Tier"], "Standard")
            self.assertFalse(item["Overwrite"])
        self.assertIn("ya existía y se conservó", output.getvalue())
        self.assertNotIn(code, output.getvalue())
        self.assertNotIn(KEY, output.getvalue())

    @unittest.skipUnless(hasattr(os, "memfd_create"), "Requiere descriptor anónimo Linux")
    def test_cli_subprocess_receives_secrets_via_inherited_descriptor_not_process_arguments(self):
        def inspect_input(args, pass_fds, **kwargs):
            self.assertNotIn(KEY, repr(args))
            self.assertEqual(len(pass_fds), 1)
            self.assertEqual(json.loads(os.pread(pass_fds[0], 4096, 0)), {"Value": KEY})
            self.assertEqual(args[-1], f"file:///proc/self/fd/{pass_fds[0]}")
            return subprocess.CompletedProcess(args, 0, b'{"Version":1}')

        with patch.object(webpay.subprocess, "run", side_effect=inspect_input):
            webpay.aws("ssm", "put-parameter", input_json={"Value": KEY})

    def test_permission_error_is_sanitized_even_if_stderr_contains_credentials(self):
        denied = subprocess.CalledProcessError(1, "aws", stderr=f"AccessDenied {KEY}".encode())
        with patch.object(webpay.subprocess, "run", side_effect=denied):
            with self.assertRaisesRegex(host.RolloutError, "ssm:PutParameter") as blocked:
                webpay.aws("ssm", "put-parameter")
        self.assertNotIn(KEY, str(blocked.exception))


if __name__ == "__main__":
    unittest.main()
