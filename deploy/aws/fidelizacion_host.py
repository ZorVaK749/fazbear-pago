"""SSM host bootstrap for a dedicated EV3 Fidelización instance."""

from ipaddress import IPv4Address
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import build_opener, ProxyHandler

from webpay_host import Host, NoRedirect, RolloutError, run, write_private

PARAMETER = "/pedidos360/ev3/fidelizacion/config"
ENV_FILE = Path("/etc/pedidos360/ev3/fidelizacion.env")
IMAGE = "ghcr.io/zorvak749/fazbear-fidelizacion@sha256:627283e9b8b68869ecd9ec8498bdf9423e9ef68e13f9f7c052eff486bd33b2c0"
CONTAINER = "ev3-fidelizacion"
PORT = 8089
KEYS = {"FIDELIZACION_DB_URL", "FIDELIZACION_DB_USER", "FIDELIZACION_DB_PASSWORD",
        "KAFKA_BOOTSTRAP_SERVERS", "INTERNAL_SERVICE_KEY"}


def validate_config(config):
    if not isinstance(config, dict) or set(config) != KEYS or any(
            not isinstance(value, str) or not value or any(c in value for c in "\r\n\0")
            for value in config.values()):
        raise RolloutError("La configuración privada está incompleta o tiene valores no admitidos.")
    jdbc = config["FIDELIZACION_DB_URL"]
    if not jdbc.startswith("jdbc:postgresql://") or not re.fullmatch(
            r"[A-Za-z0-9_.-]{1,63}", config["FIDELIZACION_DB_USER"]):
        raise RolloutError("Fidelización requiere PostgreSQL con un usuario dedicado.")
    uri = urlsplit(jdbc.removeprefix("jdbc:"))
    options = parse_qs(uri.query, strict_parsing=True)
    if (not uri.hostname or uri.username or uri.password or uri.fragment
            or uri.path not in {"/fidelizacion", "/fidelizacion_ev3"}
            or options.get("sslmode") not in (["require"], ["verify-ca"], ["verify-full"])):
        raise RolloutError("Use la base dedicada fidelizacion o fidelizacion_ev3 y active TLS en su URL JDBC.")
    for endpoint in config["KAFKA_BOOTSTRAP_SERVERS"].split(","):
        if not re.fullmatch(r"[A-Za-z0-9.-]+:[0-9]{1,5}", endpoint) or not (
                1 <= int(endpoint.rsplit(":", 1)[1]) <= 65535):
            raise RolloutError("Ingrese bootstrap servers de Kafka como host:puerto separados por comas.")
        host = endpoint.rsplit(":", 1)[0].lower()
        if host == "localhost" or host.startswith("127."):
            raise RolloutError("Fidelización necesita un broker alcanzable desde su propia EC2.")
    if len(config["INTERNAL_SERVICE_KEY"]) < 32:
        raise RolloutError("Se requiere la clave interna compartida con Pago de al menos 32 caracteres.")
    return uri.hostname, uri.port or 5432


def role_environment():
    role = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
    role.update(AWS_CONFIG_FILE="/dev/null", AWS_SHARED_CREDENTIALS_FILE="/dev/null")
    return role


def read_config():
    response = run(["aws", "ssm", "get-parameter", "--region", "us-east-1", "--name", PARAMETER,
                    "--with-decryption", "--no-cli-pager", "--output", "json"],
                   "La EC2 no pudo leer el SecureString de Fidelización con su perfil.", env=role_environment())
    private = json.loads(response)["Parameter"]
    if private["Name"] != PARAMETER or private["Type"] != "SecureString":
        raise RolloutError("La configuración de Fidelización debe estar en el SecureString esperado.")
    return json.loads(private["Value"])


def read_health(address, port):
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(f"http://{address}:{port}/health", timeout=3) as response:
            return json.loads(response.read(4096))
    except (OSError, ValueError):
        return {}


def check_dependencies(config, pago):
    database, db_port = validate_config(config)
    endpoints = [("PostgreSQL", database, db_port)]
    endpoints.extend(("Kafka", entry.rsplit(":", 1)[0], int(entry.rsplit(":", 1)[1]))
                     for entry in config["KAFKA_BOOTSTRAP_SERVERS"].split(","))
    failures = []
    for label, address, port in endpoints:
        dependency = f"{label} TCP/{port}"
        try:
            with socket.create_connection((address, port), timeout=5):
                print(f"{dependency} · conectado.", flush=True)
        except OSError as error:
            failures.append(f"{dependency} ({type(error).__name__})")
    if read_health(pago, 8087).get("status") != "UP":
        failures.append("Pago HTTP/8087 /health")
    else:
        print("Pago HTTP/8087 /health · UP.", flush=True)
    if failures:
        raise RolloutError("Dependencias inaccesibles desde Fidelización: " + ", ".join(failures) + ".")


class FidelizacionHost(Host):
    def __init__(self, address, pago):
        super().__init__(ENV_FILE)
        self.state_dir = Path("/var/lib/pedidos360-fidelizacion")
        self.address = str(IPv4Address(address))
        self.pago = str(IPv4Address(pago))

    def verify(self):
        deployed = self.inspect(CONTAINER)
        if deployed["Config"]["Image"] != IMAGE or not deployed["State"]["Running"]:
            raise RolloutError("El contenedor de Fidelización no ejecuta el digest esperado.")
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            data = read_health(self.address, PORT)
            if data.get("status") == "UP" and data.get("service") == "ms-fidelizacion":
                print("Fidelización · HTTP 200 /health · digest verificado.", flush=True)
                return
            time.sleep(3)
        raise RolloutError("Fidelización no está lista. Revise PostgreSQL, Flyway y los logs en la EC2.")

    def deploy(self):
        packages = [package for binary, package in (("docker", "docker"), ("aws", "awscli2"))
                    if shutil.which(binary) is None]
        if packages:
            run(["dnf", "install", "-y", *packages], "No se pudo preparar Docker o AWS CLI en la EC2.",
                timeout=145)
        run(["systemctl", "enable", "--now", "docker"], "No se pudo iniciar Docker en la EC2.")
        if self.find(CONTAINER):
            self.verify()
            return
        config = read_config()
        check_dependencies(config, self.pago)
        variables = dict(config, PAGO_URL=f"http://{self.pago}:8087",
                         JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=65 -XX:+ExitOnOutOfMemoryError")
        self.docker("pull", IMAGE, failure="No se pudo descargar el digest de Fidelización en la EC2.")
        self.env_file.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        write_private(self.env_file, "".join(f"{key}={value}\n" for key, value in variables.items()).encode())
        self.docker("run", "-d", "--name", CONTAINER, "--restart", "unless-stopped",
                    "--memory", "640m", "--user", "10001:10001",
                    "-p", f"{self.address}:{PORT}:8080", "--env-file", str(self.env_file), IMAGE)
        self.verify()


def main(args):
    os.umask(0o077)
    try:
        mode, address, pago = args
        host = FidelizacionHost(address, pago)
        if mode == "verify":
            host.verify()
        elif mode == "deploy":
            with host.locked():
                host.deploy()
        else:
            raise RolloutError("Modo de Fidelización no admitido.")
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        print("ERROR: No se pudo comprobar Fidelización. Revise el inventario sin publicar sus credenciales.",
              file=sys.stderr)
        return 1
    return 0
