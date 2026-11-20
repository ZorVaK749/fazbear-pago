"""Replace existing EC2 containers without replacing their data or network configuration."""

from ipaddress import IPv4Address
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler
import uuid

from clp_inventory_host import datasource, target
from webpay_host import Host, NoRedirect, RolloutError, env_values

RELEASE = {
    "carrito": (8083, "/api/carrito/me",
                "ghcr.io/zorvak749/fazbear-carrito@sha256:0972d9b0082649b842d46fadab78c960b61d3699d7009bb6ea9a927ae3b04270"),
    "orden": (8084, "/api/orden/health",
              "ghcr.io/zorvak749/fazbear-orden@sha256:29c351c0208ee67fff3c496b39305af67a22d6769fcb3574899a712918204f87"),
    "notificaciones": (8085, "/api/notificaciones/health",
                        "ghcr.io/zorvak749/fazbear-notificaciones@sha256:7338142218d895e20fd0710cea5e229e1de7b4ba5e03504032103a02cc7e72f8"),
}
MODES = ("dry-run", "status", "apply", "verify", "recover")
HEALTHY_HTTP = {200, 401, 403}
BEFORE_ACTIVATION = {"preparing", "prepared"}


def http_status(address, port, path):
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(f"http://{address}:{port}{path}", timeout=3) as response:
            return response.status
    except HTTPError as error:
        error.close()
        return error.code
    except OSError:
        return None


class Backend(Host):
    def __init__(self, name, address, catalog, release=None):
        self.name = name
        self.port, self.path, self.image = release if release is not None else RELEASE[name]
        self.registry = self.image.split("@", 1)[0]
        self.package = self.registry.rsplit("/", 1)[1]
        self.address = str(IPv4Address(address))
        self.catalog = str(IPv4Address(catalog))
        self.state_dir = Path(f"/var/lib/pedidos360-clp-{name}")
        self.journal = self.state_dir / "current.json"

    def current(self):
        current = target(self.package, self.port)
        if (not current or not current["Config"]["Image"].startswith((self.registry + ":", self.registry + "@"))
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]+", current["Name"].lstrip("/"))):
            raise RolloutError(f"Se requiere un único {self.name} activo del registro esperado en el puerto {self.port}.")
        return current

    def preflight(self):
        current = self.current()
        if self.state().get("phase") in BEFORE_ACTIVATION | {"activation_requested"}:
            raise RolloutError("Existe un corte pendiente. Consulte --status y use --verify o --recover según la fase.")
        config, host = current["Config"], current["HostConfig"]
        if (current["State"].get("Paused") or host.get("AutoRemove") or host["NetworkMode"] in {"host", "none"}
                or config["Entrypoint"] not in (["java", "-jar", "app.jar"], ["java", "-jar", "/app/app.jar"])
                or config["WorkingDir"] != "/app" or config.get("Cmd")):
            raise RolloutError("El contenedor usa un arranque o configuración Docker que requiere revisión.")
        overrides = {}
        if self.name in {"carrito", "orden"}:
            storage, persistent = datasource(current, self.name)
            if not persistent or (self.name == "orden" and storage != "PostgreSQL"):
                raise RolloutError(f"El origen de datos de {self.name} requiere revisión: {storage}.")
            print(f"{self.name} · datos {storage}")
        if self.name == "carrito":
            env = env_values(config["Env"])
            if env.get("SPRING_PROFILES_ACTIVE") != "ev3-aws":
                raise RolloutError("Carrito debe usar el perfil ev3-aws para leer precios del catálogo.")
            overrides["PRODUCTOS_URL"] = f"http://{self.catalog}:8081"
            code = http_status(self.catalog, 8081, "/api/productos")
            if code not in HEALTHY_HTTP:
                raise RolloutError("La EC2 de Carrito no pudo consultar el puerto privado de Productos.")
            print(f"Carrito consulta Productos · HTTP {code}")
        candidate = self.candidate_config(current, overrides, image=self.image, replace_keys=set())
        if http_status(self.address, self.port, self.path) not in HEALTHY_HTTP:
            raise RolloutError(f"{self.name} no responde en su IP privada y puerto publicado.")
        print(f"{self.name} · contenedor {current['Name'].lstrip('/')} · {current['Id'][:12]}")
        print(f"Imagen actual: {current['Config']['Image']}")
        print(f"Imagen CLP: {self.image}")
        return current, candidate

    def candidate_name(self, state):
        return f"{state['name']}-clp-{state['id']}"

    def apply(self):
        old, config = self.preflight()
        if old["Config"]["Image"] == self.image and env_values(old["Config"]["Env"]) == env_values(config["Env"]):
            print(f"{self.name} ya ejecuta la imagen CLP.")
            return
        self.docker("pull", self.image, failure="No se pudo descargar el digest CLP.")
        state = {"id": uuid.uuid4().hex[:12], "previous": old["Id"], "name": old["Name"].lstrip("/")}
        self.save(state, "preparing")
        try:
            state["candidate"] = self.create(self.candidate_name(state), config)
            created = self.inspect(state["candidate"])
            if (created["Config"]["Image"] != self.image
                    or env_values(created["Config"]["Env"]) != env_values(config["Env"])
                    or created["HostConfig"]["PortBindings"] != config["HostConfig"]["PortBindings"]):
                raise RolloutError("La configuración del candidato difiere de la aprobada.")
            self.save(state, "prepared")
            self.docker("stop", "-t", "35", state["previous"])
            stopped = self.inspect(state["previous"])["State"]
            if stopped["Running"] or stopped["ExitCode"] not in {0, 143}:
                raise RolloutError("El contenedor anterior no terminó con un cierre ordenado.")
            self.docker("rename", state["previous"], f"{state['name']}-before-clp-{state['id']}")
            self.docker("rename", state["candidate"], state["name"])
        except (RolloutError, OSError, ValueError, KeyError, TypeError) as error:
            self.recover(state)
            detail = f" Motivo: {error}" if isinstance(error, RolloutError) else ""
            raise RolloutError("Corte cancelado. Se recuperó el contenedor anterior." + detail) from None
        self.save(state, "activation_requested")
        self.docker("start", state["candidate"])
        self.verify(state)

    def wait_http(self, name, expected):
        deadline = time.monotonic() + 85
        while time.monotonic() < deadline:
            current = self.inspect(name)
            if current["Id"] != expected:
                raise RolloutError("El contenedor activo cambió durante la verificación.")
            state = current["State"]
            code = http_status(self.address, self.port, self.path) if state["Running"] and not state.get("Restarting") else None
            if code in HEALTHY_HTTP:
                print(f"{self.name} · HTTP {code} en {self.address}:{self.port}{self.path}")
                return
            if state["Status"] in {"exited", "dead"}:
                break
            time.sleep(3)
        raise RolloutError(f"{self.name} no quedó disponible. Consulte --status y conserve el diario.")

    def verify(self, state):
        if state.get("phase") in BEFORE_ACTIVATION:
            raise RolloutError("El corte se interrumpió antes de la activación. Consulte --status.")
        if state.get("phase") in {"activation_requested", "active"}:
            current = self.inspect(state["name"])
            if current["Id"] != state["candidate"] or current["Config"]["Image"] != self.image:
                raise RolloutError("El candidato del diario difiere del contenedor activo.")
            self.wait_http(state["name"], state["candidate"])
            self.save(state, "active")
            return
        current = self.current()
        if current["Config"]["Image"] != self.image:
            raise RolloutError(f"{self.name} todavía usa una imagen anterior.")
        self.wait_http(current["Name"].lstrip("/"), current["Id"])

    def recover(self, state):
        if state.get("phase") not in BEFORE_ACTIVATION:
            raise RolloutError("La recuperación automática está reservada para cortes previos a la activación.")
        old = self.inspect(state["previous"])
        existing = self.find(state["name"])
        if existing and existing["Id"] != old["Id"]:
            if existing["Id"] != state.get("candidate") or existing["State"]["Running"]:
                raise RolloutError("El nombre activo requiere una revisión antes de recuperar el original.")
            self.docker("rename", existing["Id"], self.candidate_name(state))
        if old["Name"] != "/" + state["name"]:
            self.docker("rename", old["Id"], state["name"])
        if not old["State"]["Running"]:
            self.docker("start", old["Id"])
        self.wait_http(state["name"], old["Id"])
        self.save(state, "recovered")

    def status(self):
        state = self.state()
        print(f"{self.name} CLP · fase {state.get('phase', 'none')}")
        if not state:
            current = self.current()
            print(f"Imagen actual: {current['Config']['Image']}")
            return
        for label, key in (("Anterior", "previous"), ("Candidato", "candidate")):
            if key not in state:
                continue
            current = self.inspect(state[key])
            runtime = current["State"]
            print(f"{label}: {current['Name'].lstrip('/')} · {runtime['Status']} · "
                  f"reinicios {current['RestartCount']} · salida {runtime['ExitCode']}")
        code = http_status(self.address, self.port, self.path)
        print(f"IP privada: {code if code is not None else 'sin respuesta HTTP'}")


def main(args):
    os.umask(0o077)
    name, mode, address, catalog = args
    try:
        host = Backend(name, address, catalog)
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
        print("ERROR: Inventario o respuesta inesperada. Consulte --status.", file=sys.stderr)
        return 1
    return 0
