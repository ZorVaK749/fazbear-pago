from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clp_backends as cli
import clp_backends_host as host


class ClpBackendsTest(unittest.TestCase):
    def test_explicit_image_is_bound_to_selected_service(self):
        image = "ghcr.io/zorvak749/fazbear-carrito@sha256:" + "f" * 64
        self.assertEqual(host.release_for("carrito", image), (8083, "/api/carrito/me", image))
        with patch.object(cli, "aws") as aws:
            with self.assertRaisesRegex(host.RolloutError, "--service"):
                cli.execute("apply", image=image)
            with self.assertRaisesRegex(host.RolloutError, "fazbear-orden"):
                cli.execute("apply", "orden", image)
        aws.assert_not_called()
        with patch.object(cli, "run_ssm"), patch.object(cli, "python_request") as request:
            cli.send("carrito", "verify", "172.31.7.210", "172.31.15.227", image)
        self.assertEqual(request.call_args.args[3], ("carrito", "verify", "172.31.7.210", "172.31.15.227", image))

    def test_all_preflight_checks_finish_before_any_cut(self):
        with patch.object(cli, "aws", return_value={"Account": cli.ACCOUNT}), \
                patch.object(cli, "private_ip", return_value="172.31.15.227"), \
                patch.object(cli, "resolve_target", return_value=("arn", "instance", 30)), \
                patch.object(cli, "target_state", return_value="healthy"), \
                patch.object(cli, "send") as send, patch.object(cli, "wait_for_target") as wait:
            cli.execute("apply")
        self.assertEqual([call.args[:2] for call in send.call_args_list],
                         [(name, mode) for mode in ("dry-run", "apply") for name in host.RELEASE])
        self.assertEqual([call.kwargs["port"] for call in wait.call_args_list], [8083, 8084, 8085])

    def test_unhealthy_last_backend_prevents_every_cut(self):
        with patch.object(cli, "aws", return_value={"Account": cli.ACCOUNT}), \
                patch.object(cli, "private_ip", return_value="172.31.15.227"), \
                patch.object(cli, "resolve_target", return_value=("arn", "instance", 30)), \
                patch.object(cli, "target_state", side_effect=["healthy", "healthy", "healthy", "unhealthy"]), \
                patch.object(cli, "send") as send:
            with self.assertRaisesRegex(host.RolloutError, "notificaciones"):
                cli.execute("apply")
        self.assertTrue(all(call.args[1] == "dry-run" for call in send.call_args_list))

    def cart_fixture(self):
        backend = host.Backend("carrito", "172.31.7.210", "172.31.15.227")
        current = {"Name": "/ms-carrito", "Id": "old", "State": {"Paused": False},
                   "Config": {"Entrypoint": ["java", "-jar", "app.jar"], "WorkingDir": "/app",
                              "Image": backend.registry + ":old", "Env": ["SPRING_PROFILES_ACTIVE=ev3-aws"]},
                   "HostConfig": {"NetworkMode": "bridge",
                                  "PortBindings": {"8083/tcp": [{"HostIp": backend.address, "HostPort": "8083"}]}},
                   "Mounts": [{"Type": "bind", "Destination": "/var/lib/fazbear/carrito", "RW": True}],
                   "NetworkSettings": {"Networks": {}}}
        return backend, current

    def test_preflight_changes_only_catalog_url_and_keeps_private_binding(self):
        backend, current = self.cart_fixture()
        with patch.object(backend, "current", return_value=current), patch.object(backend, "state", return_value={}), \
                patch.object(host, "http_status", return_value=401) as http:
            _, config = backend.preflight()
        self.assertEqual(config["HostConfig"]["PortBindings"], current["HostConfig"]["PortBindings"])
        self.assertIn("PRODUCTOS_URL=http://172.31.15.227:8081", config["Env"])
        self.assertEqual(config["Image"], backend.image)
        self.assertEqual([call.args for call in http.call_args_list],
                         [("172.31.15.227", 8081, "/api/productos"), ("172.31.7.210", 8083, "/api/carrito/me")])

    def test_in_memory_cart_is_not_replaced(self):
        backend, current = self.cart_fixture()
        current["Config"]["Env"].append("SPRING_DATASOURCE_URL=jdbc:h2:mem:carrito")
        with patch.object(backend, "current", return_value=current), patch.object(backend, "state", return_value={}), \
                patch.object(backend, "docker") as docker:
            with self.assertRaisesRegex(host.RolloutError, "H2 en memoria"):
                backend.apply()
        docker.assert_not_called()

    def test_verification_is_resumable_and_preserves_latest_candidate(self):
        backend = host.Backend("orden", "172.31.5.22", "172.31.15.227")
        state = {"phase": "activation_requested", "candidate": "new", "name": "ms-orden"}
        candidate = {"Id": "new", "Config": {"Image": backend.image}}
        with patch.multiple(backend, inspect=Mock(return_value=candidate), wait_http=Mock(), save=Mock(),
                            docker=Mock()):
            backend.verify(state)
            backend.wait_http.assert_called_once_with("ms-orden", "new")
            backend.save.assert_called_once_with(state, "active")
            with self.assertRaises(host.RolloutError):
                backend.recover(state)
            backend.docker.assert_not_called()
