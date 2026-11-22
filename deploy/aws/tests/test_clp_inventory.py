import base64
import gzip
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clp_inventory
import clp_inventory_host as host


class ClpInventoryTest(unittest.TestCase):
    def container(self, variables=(), mounts=()):
        return {"Config": {"Env": list(variables)}, "Mounts": list(mounts)}

    def test_reports_persistence_only_when_path_is_covered_by_writable_mount(self):
        mount = {"Destination": "/var/lib/fazbear/productos", "Type": "bind", "RW": True}
        data = self.container(["SPRING_PROFILES_ACTIVE=ev3-aws"], [mount])
        self.assertEqual(host.datasource(data, "productos"), ("H2 en archivo con montaje", True))
        mount["RW"] = False
        self.assertEqual(host.datasource(data, "productos"), ("H2 en archivo sin montaje", False))

    def test_env_override_takes_precedence_and_does_not_expose_url(self):
        data = self.container(["SPRING_PROFILES_ACTIVE=ev3-aws", "SPRING_DATASOURCE_URL=jdbc:h2:mem:test",
                               "PRODUCTOS_DB_URL=jdbc:postgresql://private/db"])
        self.assertEqual(host.datasource(data, "productos"), ("H2 en memoria", False))
        data["Config"]["Env"].append("SPRING_CONFIG_LOCATION=/etc/private.properties")
        self.assertEqual(host.datasource(data, "productos"), ("requiere revisión por configuración externa", False))

    def test_ssm_request_only_targets_the_approved_instance(self):
        request = clp_inventory.request("productos")
        self.assertEqual(request["InstanceIds"], ["i-0bc8e0a99f79ccac6"])
        wrapper = request["Parameters"]["commands"][0]
        script = re.search(r"'([A-Za-z0-9+/=]+)'", wrapper)[1]
        self.assertEqual(gzip.decompress(base64.b64decode(script)), Path(host.__file__).read_bytes())
        self.assertTrue(wrapper.endswith("python3 - productos fazbears-productos 8081"))

    def test_dashboard_status_checks_analytics_without_printing_urls(self):
        request = clp_inventory.request("analytics")
        self.assertEqual(request["InstanceIds"], ["i-049081f7c46b5aba3"])
        self.assertTrue(request["Parameters"]["commands"][0].endswith("python3 - analytics fazbear-analytics-recommendations 8088"))
        self.assertIn("sin configurar · URL WSS: ausente", host.dashboard_settings(self.container()))
        enabled = self.container(["ANALYTICS_DASHBOARD_ENABLED=true",
                                  "ANALYTICS_DASHBOARD_WSS_URL=wss://private.example/ws/analytics"])
        self.assertEqual(host.dashboard_settings(enabled),
                         "Dashboard WebSocket · variable Docker: activado · URL WSS: presente")
