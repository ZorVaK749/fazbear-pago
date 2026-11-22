"""Update the existing Webpay container and retain its database and environment."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from clp_backends_host import Backend, MODES
from webpay_host import CONTAINER, ENABLED_MODE, IMAGE, RETURN_URL, RolloutError, env_values, postgres_env, run, write_private

PACKAGE = IMAGE.split("@", 1)[0]
V5_IMAGE = PACKAGE + "@sha256:f1c7dc048ab725b16e585d49d0442d7850a2af4625c11e97740c949734ebf608"
V6_IMAGE = PACKAGE + "@sha256:55b7339291e1f8453d19ab75623978dcf42a342517a0236671564f20665cee0d"
RETURN_URL_EV3 = RETURN_URL.removesuffix("/checkout/webpay") + "/ev3/checkout/webpay"
BACKUP_TABLES = ("fixture_operation", "payment", "webpay_transaction", "idempotency_record", "flyway_schema_history")


class WebpayRelease(Backend):
    def __init__(self, address, image, migration=5, return_stage="keep"):
        super().__init__("pago", address, address, (8087, "/health", image))
        self.migration = migration
        self.state_dir = Path("/var/lib/pedidos360-webpay-release")
        self.journal = self.state_dir / "current.json"
        self.return_url = RETURN_URL_EV3 if return_stage == "ev3" else None

    def preflight(self):
        old, config = super().preflight()
        if (old["Name"] != "/" + CONTAINER or old["Config"]["Image"] not in {IMAGE, V5_IMAGE, V6_IMAGE, self.image}
                or self.mode() != ENABLED_MODE):
            raise RolloutError("El contenedor o la modalidad de Pago no coincide con el despliegue Webpay esperado.")
        if old["Config"]["Image"] == IMAGE:
            self.check_container(old)
        self.rollback_database_config(old)
        if self.return_url:
            config = self.candidate_config(old, {"WEBPAY_RETURN_URL": self.return_url},
                                           image=self.image, replace_keys={"WEBPAY_RETURN_URL"})
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
        previous = str(self.migration - 1)
        if (not isinstance(snapshot, dict) or set(snapshot) != set(BACKUP_TABLES)
                or not all(isinstance(rows, list) for rows in snapshot.values())
                or not any(str(row.get("version")) == previous and row.get("success")
                           for row in snapshot["flyway_schema_history"])):
            raise RolloutError(f"El respaldo de pagos no contiene las tablas y la migración V{previous} esperadas.")
        path = self.state_dir / f"pago-before-v{self.migration}-{uuid.uuid4().hex[:12]}.json"
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
        if self.return_url and env_values(current["Config"]["Env"]).get("WEBPAY_RETURN_URL") != self.return_url:
            raise RolloutError("El retorno Webpay del contenedor no corresponde al stage ev3.")
        env = postgres_env(current["Config"]["Env"])
        result = run(["psql", "-X", "-w", "-qAt", "-v", "ON_ERROR_STOP=1", "-c",
                      f"SELECT EXISTS (SELECT 1 FROM flyway_schema_history WHERE version='{self.migration}' AND success);"],
                     f"No se pudo comprobar Flyway V{self.migration} en Pago.", env=env, timeout=12)
        if result.strip() != b"t":
            raise RolloutError(f"Pago todavía no confirmó Flyway V{self.migration}.")
        print(f"Pago · Flyway V{self.migration} · Webpay de integración activo.")


def main(args):
    os.umask(0o077)
    try:
        mode, address, image, migration, *options = args
        return_stage = options[0] if options else "keep"
        if migration not in {"5", "6"} or return_stage not in {"keep", "ev3"} or len(options) > 1:
            raise RolloutError("Migración o stage de retorno de Pago no admitido.")
        host = WebpayRelease(address, image, int(migration), return_stage)
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
