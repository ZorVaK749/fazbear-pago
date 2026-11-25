"""Private, read-only Kafka UI for the EV3 Productos host."""

import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


NAME = "pedidos360-ev3-kafka-ui"
LABEL = "cl.pedidos360.service=kafka-ui-ev3"
IMAGE = "obsidiandynamics/kafdrop@sha256:22f63776b5ccea972050ea73adf242b3f5a4403a2537b4413c4cc646d3c788d5"
PORT = 18090
URL = f"http://127.0.0.1:{PORT}"
MEMORY_MB = 256
MIN_AVAILABLE_MB = MEMORY_MB + 64
TOPICS = ("producto.interaccion.v1", "carrito.actualizado.v1", "pago.aprobado.v1")


def settings(broker):
    return {
        "SERVER_ADDRESS": "127.0.0.1",
        "SERVER_PORT": str(PORT),
        "MANAGEMENT_SERVER_ADDRESS": "127.0.0.1",
        "MANAGEMENT_SERVER_PORT": str(PORT),
        "KAFKA_BROKERCONNECT": broker,
        "JVM_OPTS": "-Xms32m -Xmx80m -Xss384k -XX:+UseSerialGC -XX:ActiveProcessorCount=2",
        "CMD_ARGS": "--topic.createEnabled=false --topic.deleteEnabled=false "
                    "--message.sendEnabled=false --cors.enabled=false",
    }


def current_container(environment):
    result = subprocess.run(["docker", "container", "inspect", NAME],
                            capture_output=True, text=True, timeout=10)
    if result.returncode and f"No such container: {NAME}" in result.stderr:
        return None
    result.check_returncode()
    container = json.loads(result.stdout)[0]
    config = container["Config"]
    labels = config.get("Labels") or {}
    label, value = LABEL.split("=", 1)
    active_env = dict(item.split("=", 1) for item in config["Env"] if "=" in item)
    if (labels.get(label) != value or config["Image"] != IMAGE
            or container["HostConfig"]["NetworkMode"] != "host"
            or any(active_env.get(key) != value for key, value in environment.items())):
        raise RuntimeError("El nombre del panel ya está ocupado por otra configuración. Revísela antes de cambiarla.")
    return container["State"]["Running"]


def launch(broker, environment, existing):
    host, port = broker.rsplit(":", 1)
    with socket.create_connection((host, int(port)), timeout=5):
        pass
    memory = next(line for line in Path("/proc/meminfo").read_text().splitlines()
                  if line.startswith("MemAvailable:"))
    if int(memory.split()[1]) < MIN_AVAILABLE_MB * 1024:
        raise RuntimeError(f"La EC2 necesita al menos {MIN_AVAILABLE_MB} MiB disponibles para levantar el panel.")
    if existing is False:
        subprocess.run(["docker", "start", NAME], check=True, timeout=30)
        return
    args = ["docker", "run", "--detach", "--name", NAME, "--label", LABEL,
            "--network", "host", "--memory", f"{MEMORY_MB}m", "--cpus", "0.5",
            "--security-opt", "no-new-privileges",
            "--restart", "unless-stopped", "--log-opt", "max-size=5m", "--log-opt", "max-file=2"]
    for key, value in environment.items():
        args.extend(("--env", f"{key}={value}"))
    subprocess.run([*args, IMAGE], check=True, timeout=150)


def verify():
    opener = build_opener(ProxyHandler({}))
    request = Request(f"{URL}/topic", headers={"Accept": "application/json"})
    deadline = time.monotonic() + 95
    while time.monotonic() < deadline:
        try:
            with opener.open(request, timeout=5) as response:
                data = json.load(response)
            topics = {topic["name"] for topic in data}
            if topics:
                break
        except (URLError, OSError, KeyError, TypeError, ValueError):
            pass
        time.sleep(2)
    else:
        raise RuntimeError(f"El panel no pudo listar tópicos del broker. Revise docker logs --tail 80 {NAME}.")

    sockets = subprocess.check_output(["ss", "-ltnH", "sport", "=", f":{PORT}"], text=True, timeout=5)
    if {line.split()[3] for line in sockets.splitlines() if line.strip()} != {f"127.0.0.1:{PORT}"}:
        raise RuntimeError("La escucha del panel debe estar limitada a 127.0.0.1.")
    print(f"Kafka UI de solo lectura · {URL} · {len(topics)} tópicos listados")
    for topic in TOPICS:
        status = "visible" if topic in topics else "ausente en la consulta"
        print(f"{topic} · {status}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("apply", "verify"))
    parser.add_argument("broker")
    args = parser.parse_args()
    environment = settings(args.broker)
    try:
        existing = current_container(environment)
        if not existing:
            if args.mode == "verify":
                raise RuntimeError("Kafka UI está detenido o falta instalarlo. Use --apply en CloudShell.")
            launch(args.broker, environment, existing)
        verify()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
