"""SSM host-side read-only discovery. Print no environment values or Docker logs."""

import json
import os
from pathlib import PurePosixPath
import re
import subprocess
import sys


def docker(*args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("DOCKER_")}
    result = subprocess.run(["docker", "--host", "unix:///var/run/docker.sock", *args],
                            capture_output=True, timeout=15, check=True, env=env)
    return result.stdout


def target(package, port):
    ids = docker("ps", "-q").decode().split()
    if not ids:
        return None
    matches = []
    for container in json.loads(docker("inspect", "--type", "container", *ids)):
        image = container["Config"]["Image"]
        package_name = image.split("@", 1)[0].rsplit("/", 1)[-1].split(":", 1)[0]
        ports = container["NetworkSettings"]["Ports"] or {}
        bound = any(p["HostPort"] == str(port) for bindings in ports.values() if bindings for p in bindings)
        if package_name == package and bound:
            matches.append(container)
    return matches[0] if len(matches) == 1 else None


def datasource(container, service):
    config = container["Config"]
    env = dict(s.split("=", 1) for s in config["Env"] if "=" in s)
    external = any(env.get(key) for key in ("SPRING_APPLICATION_JSON", "SPRING_CONFIG_LOCATION",
                   "SPRING_CONFIG_ADDITIONAL_LOCATION", "SPRING_CONFIG_IMPORT"))
    command_line = " ".join((config.get("Entrypoint") or []) + (config.get("Cmd") or []))
    jvm_options = " ".join(env.get(key, "") for key in
                           ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"))
    if external or re.search(r"spring\.(?:datasource|config|profiles)", command_line + " " + jvm_options):
        return "requiere revisión por configuración externa", False
    url = env.get("SPRING_DATASOURCE_URL") or env.get(f"{service.upper()}_DB_URL", "")
    profiles = env.get("SPRING_PROFILES_ACTIVE", "").split(",")
    if not url and service in {"productos", "carrito", "pedidos"} and profiles == ["ev3-aws"]:
        url = f"jdbc:h2:file:/var/lib/fazbear/{service}/{service}db"
    if url.startswith("jdbc:h2:mem:"):
        return "H2 en memoria", False
    if url.startswith("jdbc:postgresql:"):
        return "PostgreSQL", True
    if url.startswith("jdbc:h2:file:"):
        path = PurePosixPath(url.removeprefix("jdbc:h2:file:").split(";", 1)[0])
        covered = path.is_absolute() and any(
            mount["RW"] and mount["Type"] in {"bind", "volume"}
            and PurePosixPath(mount["Destination"]) in path.parents
            for mount in container["Mounts"]
        )
        return "H2 en archivo con montaje" if covered else "H2 en archivo sin montaje", covered
    return "sin confirmar", False


def dashboard_settings(container):
    env = dict(item.split("=", 1) for item in container["Config"]["Env"] if "=" in item)
    flag = env.get("ANALYTICS_DASHBOARD_ENABLED", "").strip().lower()
    estado = {"true": "activado", "false": "desactivado", "": "sin configurar"}.get(flag, "valor no reconocido")
    url = "presente" if env.get("ANALYTICS_DASHBOARD_WSS_URL", "").strip() else "ausente"
    return f"Dashboard WebSocket · variable Docker: {estado} · URL WSS: {url}"


def main(service, package, port):
    container = target(package, int(port))
    if not container:
        print("No se identificó un único contenedor activo del paquete y puerto esperados.")
        return 1
    name = container["Name"].lstrip("/")
    image = container["Config"]["Image"]
    status = container["State"].get("Health", {}).get("Status", "sin healthcheck Docker")
    print(f"{service}: contenedor {name} · estado {status}")
    if re.fullmatch(r"ghcr\.io/zorvak749/[a-z0-9-]+(?:@sha256:[a-f0-9]{64}|:[A-Za-z0-9_.-]+)", image):
        print(f"Imagen actual: {image}")
    if service != "notificaciones":
        storage, persistent = datasource(container, service)
        print(f"Origen de datos: {storage}")
        if service == "productos" and not persistent:
            print("Se requiere una exportación verificable de la base antes de reemplazar Productos.")
    if service == "analytics":
        print(dashboard_settings(container))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(*sys.argv[1:]))
    except (OSError, ValueError, subprocess.SubprocessError, KeyError, TypeError):
        print("No se pudo comprobar el inventario Docker sin exponer la configuración.")
        sys.exit(1)
