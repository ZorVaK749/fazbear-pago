import gzip
import json
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clp_productos
import clp_productos_host as host


class ClpProductosTest(unittest.TestCase):
    def test_h2_path_comes_from_exact_docker_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            mounted = Path(directory).resolve()
            source = mounted / "current.mv.db"
            source.touch()
            container = {
                "Config": {"Env": ["SPRING_PROFILES_ACTIVE=ev3-aws", "PRODUCTOS_DB_USER=source",
                                   "PRODUCTOS_DB_URL=jdbc:h2:file:/data/current;AUTO_SERVER=FALSE"]},
                "Mounts": [{"Source": str(mounted), "Destination": "/data", "Type": "bind", "RW": True}],
            }
            db = host.database(container)
            self.assertEqual(db.host_file, source)
            self.assertEqual(db.username, "source")
            container["Config"]["Env"].append("SPRING_CONFIG_IMPORT=extra.properties")
            with self.assertRaises(host.RolloutError):
                host.database(container)

    def test_stable_snapshot_preserves_bytes_and_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.write_bytes(b"stock")
            backup = Path(directory) / "copy"
            if sys.platform == "win32":
                self.skipTest("Directory fsync is exercised on Linux")
            self.assertEqual(host.copy_stable(source, backup), host.sha256(source))
            self.assertEqual(backup.read_bytes(), b"stock")
            with patch.object(host, "sha256", side_effect=["before", "after"]):
                with self.assertRaises(host.RolloutError):
                    host.copy_stable(source, backup.with_name("changed"))

    def test_catalog_preserves_zero_stock_and_requires_all_distinct_products(self):
        lines = [",".join(host.FIELDS)] + [f'{i},Pizza {i},"Descripción, {i}",12.99,PIZZA,,{i-1}'
                                          for i in range(1, 24)]
        self.assertEqual(host.catalog_rows("\n".join(lines))[0]["STOCK"], "0")
        with self.assertRaises(host.RolloutError):
            host.catalog_rows("\n".join(lines[:-1]))
        with self.assertRaises(host.RolloutError):
            host.catalog_rows("\n".join(lines[:-1] + [lines[-2]]))

    def test_in_memory_ssm_loader_registers_imports_and_keeps_arguments(self):
        source = [[name, (Path(host.__file__).parent / (name + ".py")).read_text(encoding="utf-8")]
                  for name in clp_productos.MODULES]
        source.append(["_dry_fixture", """
from clp_productos_host import NAME
def main(args):
    print(NAME, args[0])
    return 0
"""])
        result = subprocess.run([sys.executable, "-c", clp_productos.LOADER, "prepare"],
                                input=gzip.compress(json.dumps(source).encode()),
                                capture_output=True, check=True)
        self.assertEqual(result.stdout.decode().strip(), "ms-productos prepare")
        self.assertEqual(clp_productos.request("prepare")["InstanceIds"], ["i-0bc8e0a99f79ccac6"])
        request = clp_productos.request("verify", "172.31.15.227")
        self.assertIn(" verify 172.31.15.227", request["Parameters"]["commands"][-2])
        with self.assertRaises(ValueError):
            clp_productos.request("verify", "172.31.15.227 extra")

    def test_before_and_after_catalog_require_same_fields_except_planned_prices(self):
        lines = [",".join(host.FIELDS)] + [f"{i},Pizza {i},,12.99,PIZZA,,{i-1}" for i in range(1, 24)]
        old = host.catalog_rows("\n".join(lines))
        new = host.catalog_rows("\n".join(lines).replace("12.99", "12990.00"))
        plan = {row["NOMBRE"]: (Decimal("12.99"), Decimal("12990")) for row in old}
        host.verify_prices(old, new, plan)
        new[0]["STOCK"] = "2"
        with self.assertRaisesRegex(host.RolloutError, "stock"):
            host.verify_prices(old, new, plan)
        new[0]["STOCK"] = "0"
        new[0]["PRECIO"] = "129.90"
        with self.assertRaisesRegex(host.RolloutError, "plan CLP"):
            host.verify_prices(old, new, plan)

    def test_after_activation_recovery_cannot_start_original_container(self):
        rollout = host.ProductsHost()
        with patch.object(rollout, "docker") as docker:
            with self.assertRaisesRegex(host.RolloutError, "antes de activar"):
                rollout.recover({"phase": "activation_requested"})
        docker.assert_not_called()

    def test_failed_candidate_readiness_keeps_activation_journal_and_no_recovery(self):
        rollout = host.ProductsHost()
        current = {"Id": "old", "Config": {"Entrypoint": ["java", "-jar", "app.jar"], "WorkingDir": "/app"},
                   "HostConfig": {"NetworkMode": "bridge"}}
        stopped = {"State": {"Running": False, "ExitCode": 143}}
        candidate = {"Id": "new", "Config": {"Image": host.CLP_IMAGE}}
        db = host.Database(Path("/data/catalog.mv.db"), host.PurePosixPath("/data/catalog"), "", "sa", "")
        phases = []

        def save(state, phase):
            state["phase"] = phase
            phases.append(phase)

        with patch.multiple(rollout, source=Mock(return_value=current),
                            state=Mock(return_value={"phase": "prepared", "id": "backup",
                                                     "container": "old", "sha256": "verified"}),
                            docker=Mock(), inspect=Mock(side_effect=[stopped, candidate]),
                            candidate_config=Mock(), read_catalog=Mock(return_value=([], None)),
                            stage=Mock(), save=save, wait_http=Mock(side_effect=host.RolloutError("health timeout")),
                            recover=Mock()), \
                patch.object(rollout, "create", return_value="new"), \
                patch.object(host, "database", return_value=db), \
                patch.object(host, "sha256", return_value="verified"), \
                patch.object(host, "copy_stable", return_value="cold"), \
                patch.object(host, "clone_database", return_value=(Path("/clone"), host.PurePosixPath("/clone/db"))):
            with self.assertRaisesRegex(host.RolloutError, "health timeout"):
                rollout.apply()
            rollout.recover.assert_not_called()
        self.assertEqual(phases, ["stopping", "prepared_for_switch", "activation_requested"])

    def test_private_address_is_used_when_loopback_is_not_published(self):
        rollout = host.ProductsHost("172.31.15.227")
        container = {"Id": "new", "State": {"Running": True}}
        with patch.object(rollout, "inspect", return_value=container), \
                patch.object(rollout, "probe_http", side_effect=lambda ip: 401 if ip == rollout.address else None) as probe:
            self.assertEqual(rollout.wait_http("new"), ("172.31.15.227", 401))
        probe.assert_called_once_with("172.31.15.227")

    def test_verify_only_checks_activated_candidate_then_updates_journal(self):
        rollout = host.ProductsHost("172.31.15.227")
        state = {"phase": "activation_requested", "candidate": "new"}
        candidate = {"Id": "new", "Config": {"Image": host.CLP_IMAGE}}
        with patch.object(rollout, "inspect", return_value=candidate), \
                patch.object(rollout, "wait_http", return_value=("172.31.15.227", 401)), \
                patch.object(rollout, "save") as save, patch.object(rollout, "docker") as docker:
            rollout.verify(state)
        save.assert_called_once_with(state, "active")
        docker.assert_not_called()
