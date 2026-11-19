"""Host-side Webpay rollout. Executed as root by SSM on the Pago EC2 only."""

import argparse
from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

CONTAINER = "ev3-pago"
IMAGE = "ghcr.io/zorvak749/fazbear-pago@sha256:2e93d9d7b905480c1704bbc31644ba3e2e67410fd1fe0da6ca8c54ac49c61c12"
ENV_FILE = Path("/etc/pedidos360/ev3/pago.env")
RETURN_URL = "https://p5gsy16utd.execute-api.us-east-1.amazonaws.com/checkout/webpay"
ENABLED_MODE = "SIMULATION_AND_WEBPAY_INTEGRATION"
DISABLED_MODE = "SIMULATION_ONLY"
PARAMETERS = {
    "WEBPAY_COMMERCE_CODE": "/pedidos360/ev3/webpay/commerce-code",
    "WEBPAY_API_KEY": "/pedidos360/ev3/webpay/api-key",
}
WEBPAY_KEYS = {"WEBPAY_ENABLED", "WEBPAY_RETURN_URL", *PARAMETERS}
WEBPAY_BYTES = {key.encode() for key in WEBPAY_KEYS}
MODES = ("status", "dry-run", "apply", "rollback", "recover")


class RolloutError(Exception):
    """Only fixed, operator-safe messages may be raised with this type."""


def run(args, failure, *, env=None, timeout=45):
    try:
        result = subprocess.run(args, env=env, capture_output=True, timeout=timeout, check=True)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise RolloutError(failure) from None


def private_file(path, *, strict=True):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if path.is_symlink():
        raise RolloutError("Se rechazó un archivo de configuración enlazado.")
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_nlink != 1
                or meta.st_mode & (0o077 if strict else 0o022)):
            raise RolloutError("Permisos o propietario inesperados en un archivo de configuración.")
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise RolloutError("Archivo de configuración demasiado grande.")
    return data


def write_private(path, content):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            temporary.replace(path)
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)


def env_values(lines):
    return dict(line.split("=", 1) for line in lines if "=" in line)


def replace_webpay_lines(content, overrides):
    kept = []
    for line in content.splitlines(keepends=True):
        key = line.split(b"=", 1)[0].strip()
        if key not in WEBPAY_BYTES:
            kept.append(line)
    result = b"".join(kept)
    if result and not result.endswith(b"\n"):
        result += b"\n"
    return result + "".join(f"{key}={value}\n" for key, value in overrides.items()).encode()


def system_release():
    try:
        fields = env_values(Path("/etc/os-release").read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeError):
        return "desconocido"
    values = [fields.get(key, "").strip('"') for key in ("ID", "VERSION_ID")]
    return " ".join(value for value in values if re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", value)) or "desconocido"


def webpay_overrides(source):
    if source == "ssm":
        role_env = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
        role_env.update(AWS_CONFIG_FILE="/dev/null", AWS_SHARED_CREDENTIALS_FILE="/dev/null")
        response = json.loads(run([
            "aws", "ssm", "get-parameters", "--region", "us-east-1", "--with-decryption",
            "--no-cli-pager", "--output", "json", "--names", *PARAMETERS.values(),
        ], "EC2 no pudo leer los dos SecureString con su rol.", env=role_env))
        names = {p["Name"]: p["Value"] for p in response["Parameters"] if p["Type"] == "SecureString"}
        values = {key: names.get(name, "") for key, name in PARAMETERS.items()}
    else:
        data = private_file(ENV_FILE.with_name("webpay.credentials")).decode()
        values = env_values(line for line in data.splitlines() if not line.startswith("#"))
    code = values.get("WEBPAY_COMMERCE_CODE", "")
    key = values.get("WEBPAY_API_KEY", "")
    if not re.fullmatch(r"[0-9]{12}", code) or not re.fullmatch(r"[0-9A-Fa-f]{64}", key):
        raise RolloutError("Credenciales de integración ausentes o con formato inválido.")
    return {"WEBPAY_ENABLED": "true", "WEBPAY_COMMERCE_CODE": code,
            "WEBPAY_API_KEY": key, "WEBPAY_RETURN_URL": RETURN_URL}


class EngineConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Host:
    def __init__(self, env_file=ENV_FILE):
        self.env_file = env_file
        self.state_dir = env_file.parent / ".webpay-rollout"
        self.journal = self.state_dir / "current.json"

    def inspect(self, reference):
        return json.loads(self.docker("inspect", "--type", "container", reference,
                                     failure="El contenedor requerido no está disponible."))[0]

    def find(self, reference):
        names = self.docker("ps", "-a", "--no-trunc", "--format", "{{.ID}} {{.Names}}",
                            failure="No se pudo consultar el inventario Docker.").decode().splitlines()
        for line in names:
            cid, name = line.split(maxsplit=1)
            if reference in (cid, name):
                return self.inspect(cid)
        return None

    def docker(self, *args, failure="Falló una operación Docker. Consulte --status y el diario del despliegue."):
        env = {key: value for key, value in os.environ.items() if not key.startswith("DOCKER_")}
        return run(["docker", "--host", "unix:///var/run/docker.sock", *args], failure, env=env)

    def check_container(self, current):
        image_id = self.docker("image", "inspect", "--format", "{{.Id}}", IMAGE,
                               failure="La imagen fijada por digest debe existir en la EC2.").decode().strip()
        config, host = current["Config"], current["HostConfig"]
        ports = host["PortBindings"].get("8080/tcp", [])
        if (current["Image"] != image_id or config["User"] != "10001:10001"
                or host["Memory"] != 640 * 1024**2 or host["RestartPolicy"]["Name"] != "unless-stopped"
                or not any(binding["HostPort"] == "8087" for binding in ports)
                or host.get("AutoRemove")):
            raise RolloutError("La imagen, puerto, usuario, memoria o política Docker no coincide con el inventario.")

    def candidate_config(self, current, overrides):
        config = dict(current["Config"], Image=IMAGE)
        config["Env"] = [line for line in config["Env"] if line.split("=", 1)[0] not in WEBPAY_KEYS]
        config["Env"].extend(f"{key}={value}" for key, value in overrides.items())
        host = current["HostConfig"]
        if host["NetworkMode"].startswith("container:") or host.get("VolumesFrom"):
            raise RolloutError("La configuración comparte el espacio de red o volúmenes con otro contenedor.")
        explicit = {mount["Target"] for mount in host.get("Mounts") or []}
        explicit.update(binding.split(":")[1] for binding in host.get("Binds") or [] if ":" in binding)
        if any(mount["Type"] == "volume" and mount["Destination"] not in explicit for mount in current["Mounts"]):
            raise RolloutError("Hay un volumen anónimo. Revise sus montajes antes de replicar el contenedor.")
        networks = {}
        for name, endpoint in current["NetworkSettings"]["Networks"].items():
            if name in {"bridge", "host", "none"}:
                continue
            if endpoint.get("IPAMConfig"):
                raise RolloutError("La red usa una IP estática. El corte requiere revisar esa reserva.")
            networks[name] = {key: endpoint[key] for key in ("Aliases", "Links", "DriverOpts", "GwPriority") if endpoint.get(key)}
        config["HostConfig"] = host
        if networks:
            config["NetworkingConfig"] = {"EndpointsConfig": networks}
        return config

    def create(self, name, config):
        conn = EngineConnection("localhost", timeout=30)
        try:
            conn.request("POST", "/containers/create?" + urllib.parse.urlencode({"name": name}),
                         body=json.dumps(config).encode(), headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            if response.status != 201:
                raise RolloutError("Docker rechazó la creación del candidato.")
            return json.loads(response.read())["Id"]
        finally:
            conn.close()

    def state(self):
        if not self.state_dir.exists() and not self.state_dir.is_symlink():
            return {}
        self.check_state_dir()
        if not self.journal.exists() and not self.journal.is_symlink():
            return {}
        return json.loads(private_file(self.journal))

    def check_state_dir(self):
        meta = self.state_dir.lstat()
        if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_mode & 0o077:
            raise RolloutError("El directorio del diario debe pertenecer a root y ser privado.")

    @contextmanager
    def locked(self):
        import fcntl
        self.state_dir.mkdir(mode=0o700, exist_ok=True)
        self.check_state_dir()
        fd = os.open(self.state_dir / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RolloutError("Ya se está ejecutando otro cambio Webpay en esta EC2.") from None
            yield

    def save(self, state, phase):
        state["phase"] = phase
        write_private(self.journal, json.dumps(state).encode())

    def backup(self, state):
        return self.state_dir / (state["id"] + ".env.before")

    def mode(self):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open("http://127.0.0.1:8087/health", timeout=3) as response:
                body = json.loads(response.read(4096))
                if response.status == 200 and body.get("status") == "UP" and body.get("mode") in {ENABLED_MODE, DISABLED_MODE}:
                    return body["mode"]
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None

    def wait_health(self, expected):
        deadline = time.monotonic() + 85
        while time.monotonic() < deadline:
            if self.mode() == expected:
                print(f"HTTP 200 /health · {expected}")
                return
            time.sleep(3)
        raise RolloutError("El health local no alcanzó HTTP 200 en la modalidad esperada.")

    def status(self, source, dry_run, check_credentials=False):
        phase = self.state().get("phase", "none")
        print(f"Diario Webpay · fase {phase}")
        current = self.find(CONTAINER)
        if current is None:
            if dry_run:
                raise RolloutError("El contenedor activo no está disponible. Revise el diario y --recover.")
            print("El nombre activo no está asignado a ningún contenedor.")
            return
        self.check_container(current)
        private_file(self.env_file, strict=False)
        self.candidate_config(current, {})
        mode = self.mode()
        print(f"EC2 Pago · contenedor {current['Id'][:12]}")
        print(f"Health local: {mode or 'sin HTTP 200 esperado'}")
        print(f"Sistema EC2: {system_release()}")
        print(f"psql para rollback: {'disponible' if shutil.which('psql') else 'ausente'}")
        if dry_run:
            print(f"Plan: respaldo privado, candidato con digest actual, corte y verificación · origen {source}")
            if source == "ssm" and not shutil.which("aws"):
                raise RolloutError("La EC2 requiere AWS CLI para leer SecureString con su rol.")
            if source == "host-file":
                path = self.env_file.with_name("webpay.credentials")
                private_file(path)
            if not mode or not current["State"]["Running"]:
                raise RolloutError("El contenedor actual debe estar sano antes del corte.")
            if check_credentials:
                webpay_overrides(source)
                print("Credenciales Webpay: lectura y formato verificados.")

    def apply(self, source):
        old = self.inspect(CONTAINER)
        self.check_container(old)
        phase = self.state().get("phase", "none")
        health = self.mode()
        if health == ENABLED_MODE and phase in {"none", "active"}:
            print("Webpay ya está activo. Se verificará el Target Group.")
            return
        if phase not in {"none", "rolled_back"} or health != DISABLED_MODE or not old["State"]["Running"]:
            raise RolloutError("Revise --status y use --recover si el corte anterior quedó incompleto.")
        original = private_file(self.env_file, strict=False)
        overrides = webpay_overrides(source)
        config = self.candidate_config(old, overrides)
        transaction = uuid.uuid4().hex[:12]
        state = {"id": transaction, "previous": old["Id"], "candidate": None}
        write_private(self.backup(state), original)
        self.save(state, "preparing")
        try:
            state["candidate"] = self.create(self.candidate_name(state), config)
            new = self.inspect(state["candidate"])
            self.check_container(new)
            if env_values(new["Config"]["Env"]) != env_values(config["Env"]):
                raise RolloutError("El entorno del candidato difiere de la configuración aprobada.")
            self.save(state, "prepared")
            self.docker("stop", "-t", "20", state["previous"])
            self.docker("rename", state["previous"], self.previous_name(state))
            self.docker("rename", state["candidate"], CONTAINER)
            write_private(self.env_file, replace_webpay_lines(original, overrides))
        except Exception:
            self.restore_previous(state)
            raise RolloutError("Corte cancelado antes de iniciar Webpay. Se restauró Pago anterior.") from None

        # Persist before sending start. A timeout can still mean Docker started it.
        self.save(state, "start_requested")
        self.start_candidate(state)

    def candidate_name(self, state):
        return CONTAINER + "-webpay-" + state["id"]

    def previous_name(self, state):
        return CONTAINER + "-previous-" + state["id"]

    def start_candidate(self, state, restart_unhealthy=False):
        cid = state["candidate"]
        current = self.inspect(cid)
        self.check_container(current)
        if current["Name"] != "/" + CONTAINER:
            raise RolloutError("La identidad del candidato activo difiere del diario. Revisión manual requerida.")
        if not current["State"]["Running"]:
            self.docker("start", cid)
        elif restart_unhealthy and self.mode() != ENABLED_MODE:
            self.docker("restart", "-t", "20", cid)
        self.wait_health(ENABLED_MODE)
        self.save(state, "active")

    def restore_previous(self, state):
        previous = self.inspect(state["previous"])
        candidate = self.find(state["candidate"] or self.candidate_name(state))
        if candidate and candidate["State"]["Running"]:
            raise RolloutError("El candidato sigue activo. No se iniciará Pago anterior.")
        active_name = self.find(CONTAINER)
        if active_name and active_name["Id"] != previous["Id"]:
            if active_name["Id"] != state["candidate"]:
                raise RolloutError("El nombre activo pertenece a un contenedor ajeno al diario.")
            self.docker("rename", active_name["Id"], self.candidate_name(state))
        if previous["Name"] != "/" + CONTAINER:
            self.docker("rename", previous["Id"], CONTAINER)
        write_private(self.env_file, private_file(self.backup(state)))
        if not previous["State"]["Running"]:
            self.docker("start", previous["Id"])
        self.wait_health(DISABLED_MODE)
        self.save(state, "rolled_back")

    def recover(self):
        state = self.state()
        if state.get("phase") in {"preparing", "prepared", "rollback_empty"}:
            self.restore_previous(state)
        elif state.get("phase") in {"start_requested", "active", "rollback_guard"}:
            self.start_candidate(state, restart_unhealthy=True)
        else:
            raise RolloutError("No hay un corte recuperable en el diario.")

    def rollback(self):
        state = self.state()
        phase = state.get("phase")
        if phase in {"preparing", "prepared", "rollback_empty"}:
            self.restore_previous(state)
            return
        if phase not in {"start_requested", "active", "rollback_guard"}:
            raise RolloutError("No hay un despliegue Webpay administrado para revertir.")
        candidate = self.inspect(state["candidate"])
        if candidate["Name"] != "/" + CONTAINER:
            raise RolloutError("El nombre activo difiere del diario.")
        if (candidate["Config"]["Entrypoint"] != ["java", "-jar", "app.jar"] or candidate["Config"]["Cmd"]
                or candidate["Mounts"]):
            raise RolloutError("El arranque o los montajes del contenedor requieren verificar el datasource manualmente.")
        db = postgres_env(candidate["Config"]["Env"])
        if not shutil.which("psql"):
            raise RolloutError("Se requiere psql en EC2 para comprobar el estado de Webpay antes de revertir.")
        self.save(state, "rollback_guard")
        try:
            if candidate["State"]["Running"]:
                self.docker("stop", "-t", "20", candidate["Id"])
            if self.inspect(candidate["Id"])["State"]["Running"]:
                raise RolloutError("No se pudo detener el candidato para comprobar PostgreSQL.")
            if self.database_used(db):
                raise RolloutError("PostgreSQL contiene transacciones Webpay. Conserve el candidato y concilie los pagos.")
        except Exception as error:
            self.start_candidate(state)
            if isinstance(error, RolloutError):
                raise
            raise RolloutError("No se pudo confirmar la ausencia de transacciones. Webpay sigue habilitado.") from None
        self.save(state, "rollback_empty")
        self.restore_previous(state)

    def database_used(self, env):
        result = run(["psql", "-X", "-w", "-qAt", "-v", "ON_ERROR_STOP=1", "-c",
                      "SELECT EXISTS (SELECT 1 FROM webpay_transaction) OR "
                      "EXISTS (SELECT 1 FROM payment WHERE NOT simulation);"],
                     "No se pudo confirmar el estado de Webpay en PostgreSQL.", env=env, timeout=12).strip()
        if result not in {b"t", b"f"}:
            raise RolloutError("Respuesta de PostgreSQL inconclusa.")
        return result == b"t"


def postgres_env(lines):
    values = env_values(lines)
    supported = {"SPRING_DATASOURCE_URL", "SPRING_DATASOURCE_USERNAME", "SPRING_DATASOURCE_PASSWORD"}
    # Do not guess a database if other mechanisms can override the datasource.
    if values.get("SPRING_PROFILES_ACTIVE") != "ev3-aws" or any(
            value and key not in supported and key.startswith(("SPRING_APPLICATION_JSON", "SPRING_CONFIG_",
                "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS", "SPRING_DATASOURCE_"))
            for key, value in values.items()):
        raise RolloutError("La configuración PostgreSQL requiere verificación manual.")
    jdbc = values.get("SPRING_DATASOURCE_URL", values.get("PAGO_DB_URL", ""))
    if not jdbc.startswith("jdbc:postgresql://"):
        raise RolloutError("Se requiere una URL PostgreSQL inequívoca para el rollback.")
    uri = urllib.parse.urlsplit(jdbc[5:])
    db = uri.path[1:]
    options = urllib.parse.parse_qs(uri.query, keep_blank_values=True, strict_parsing=True)
    sslmode = options.get("sslmode", ["require"])
    if (not uri.hostname or not re.fullmatch(r"[A-Za-z0-9.-]+", uri.hostname)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", db) or uri.username or uri.password or uri.fragment
            or set(options) - {"sslmode"} or sslmode not in (["require"], ["verify-ca"], ["verify-full"])):
        raise RolloutError("La URL PostgreSQL incluye opciones que requieren verificación manual.")
    user = values.get("SPRING_DATASOURCE_USERNAME", values.get("PAGO_DB_USER"))
    password = values.get("SPRING_DATASOURCE_PASSWORD", values.get("PAGO_DB_PASSWORD"))
    if not user or not password:
        raise RolloutError("Falta configuración PostgreSQL para el rollback.")
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update(PGHOST=uri.hostname, PGPORT=str(uri.port or 5432), PGDATABASE=db, PGUSER=user,
               PGPASSWORD=password, PGSSLMODE=sslmode[0], PGCONNECT_TIMEOUT="5",
               PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=5000")
    return env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=MODES)
    parser.add_argument("source", choices=("ssm", "host-file"))
    parser.add_argument("--check-credentials", action="store_true")
    args = parser.parse_args()
    if args.check_credentials and args.mode != "dry-run":
        parser.error("--check-credentials requiere dry-run")
    try:
        if os.geteuid() != 0:
            raise RolloutError("La ejecución remota requiere root.")
        host = Host()
        if args.mode in {"status", "dry-run"}:
            host.status(args.source, args.mode == "dry-run", args.check_credentials)
        else:
            with host.locked():
                if args.mode == "apply":
                    host.apply(args.source)
                else:
                    getattr(host, args.mode)()
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("ERROR: ejecución interrumpida. Use --status y --recover para revisar el diario.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
