"""Update the existing Webpay container and retain its database and environment."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from clp_backends_host import Backend, MODES
from webpay_host import CONTAINER, ENABLED_MODE, IMAGE, RolloutError, postgres_env, run, write_private

PACKAGE = IMAGE.split("@", 1)[0]
BACKUP_TABLES = ("fixture_operation", "payment", "webpay_transaction", "idempotency_record", "flyway_schema_history")


class WebpayRelease(Backend):
    def __init__(self, address, image):
        super().__init__("pago", address, address, (8087, "/health", image))
        self.state_dir = Path("/var/lib/pedidos360-webpay-release")
        self.journal = self.state_dir / "current.json"

    def preflight(self):
        old, config = super().preflight()
        if (old["Name"] != "/" + CONTAINER or old["Config"]["Image"] not in {IMAGE, self.image}
                or self.mode() != ENABLED_MODE):
            raise RolloutError("El contenedor o la modalidad de Pago no coincide con el despliegue Webpay esperado.")
        if old["Config"]["Image"] == IMAGE:
            self.check_container(old)
        self.rollback_database_config(old)
        return old, config

    def apply(self):
        current = self.current()
        if current["Config"]["Image"] != self.image:
            self.preflight()
            self.backup_database(self.rollback_database_config(current))
        super().apply()

    def backup_database(self, env):
        # One SELECT gives a consistent snapshot across the related tables in PostgreSQL.
        fields = ", ".join(f"'{table}', (SELECT COALESCE(json_agg(t), '[]'::json) FROM {table} t)"
                           for table in BACKUP_TABLES)
        data = run(["psql", "-X", "-w", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", f"SELECT json_build_object({fields});"],
                   "No se pudo respaldar el registro de pagos con psql.", env=env, timeout=25)
        snapshot = json.loads(data)
        if (not isinstance(snapshot, dict) or set(snapshot) != set(BACKUP_TABLES)
                or not all(isinstance(rows, list) for rows in snapshot.values())
                or not any(str(row.get("version")) == "4" and row.get("success")
                           for row in snapshot["flyway_schema_history"])):
            raise RolloutError("El respaldo de pagos no contiene las tablas y la migración V4 esperadas.")
        path = self.state_dir / f"pago-before-v5-{uuid.uuid4().hex[:12]}.json"
        write_private(path, data)
        digest = hashlib.sha256(data).hexdigest()
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RolloutError("El archivo de respaldo no coincide con el SHA256 comprobado.")
        print(f"Respaldo PostgreSQL privado de pagos: {path.name} · SHA256 {digest}", flush=True)

    def wait_http(self, name, expected):
        super().wait_http(name, expected)
        if self.mode() != ENABLED_MODE:
            raise RolloutError("Pago responde con una modalidad distinta de SIMULATION_AND_WEBPAY_INTEGRATION.")
        current = self.inspect(expected)
        if current["Config"]["Image"] != self.image:
            return
        env = postgres_env(current["Config"]["Env"])
        result = run(["psql", "-X", "-w", "-qAt", "-v", "ON_ERROR_STOP=1", "-c",
                      "SELECT EXISTS (SELECT 1 FROM flyway_schema_history WHERE version='5' AND success);"],
                     "No se pudo comprobar Flyway V5 en Pago.", env=env, timeout=12)
        if result.strip() != b"t":
            raise RolloutError("Pago todavía no confirmó Flyway V5.")
        print("Pago · Flyway V5 · Webpay de integración activo.")


def main(args):
    os.umask(0o077)
    mode, address, image = args
    try:
        host = WebpayRelease(address, image)
        if mode == "status":
            host.status()
        elif mode == "dry-run":
            host.preflight()
        elif mode in {"apply", "verify", "recover"}:
            with host.locked():
                if mode == "apply":
                    host.apply()
                else:
                    getattr(host, mode)(host.state())
        else:
            raise RolloutError("Modo no admitido.")
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("ERROR: No se pudo comprobar el inventario de Pago sin exponer su configuración.", file=sys.stderr)
        return 1
    return 0
