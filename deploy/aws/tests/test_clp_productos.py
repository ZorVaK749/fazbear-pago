import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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
