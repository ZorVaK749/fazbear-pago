"""Private, read-only Kafka UI for an EV3 Kafka client host."""

import argparse
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
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
        "MANAGEMENT_SERVER_PORT": "-1",
        "KAFKA_BROKERCONNECT": broker,
        "JVM_OPTS": "-Xms32m -Xmx80m -Xss384k -XX:+UseSerialGC -XX:ActiveProcessorCount=2",
        "CMD_ARGS": "--topic.createEnabled=false --topic.deleteEnabled=false "
                    "--message.sendEnabled=false --cors.enabled=false",
    }


def current_container(environment, *, replace_legacy=False):
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
    same_container = (labels.get(label) == value and config["Image"] == IMAGE
                      and container["HostConfig"]["NetworkMode"] == "host")
    if same_container and all(active_env.get(key) == value for key, value in environment.items()):
        return container["State"]["Running"]
    legacy_env = {**environment, "MANAGEMENT_SERVER_PORT": str(PORT),
                  "MANAGEMENT_SERVER_ADDRESS": "127.0.0.1"}
    if not (replace_legacy and same_container
            and all(active_env.get(key) == value for key, value in legacy_env.items())):
        raise RuntimeError("El nombre del panel ya está ocupado por otra configuración. Revísela antes de cambiarla.")

    # The previous settings caused a startup loop. Retain the old container for inspection.
    subprocess.run(["docker", "stop", "--time", "10", NAME], check=True, timeout=25)
    backup = f"{NAME}-antes-{container['Id'][:12]}"
    subprocess.run(["docker", "rename", NAME, backup], check=True, timeout=15)
    print(f"Kafdrop anterior detenido y conservado como {backup}")
    return None


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
    last_result = "sin respuesta HTTP"
    while time.monotonic() < deadline:
        try:
            with opener.open(request, timeout=5) as response:
                data = json.load(response)
            topics = {topic["name"] for topic in data}
            if topics:
                break
            last_result = "HTTP 200 con una lista vacía de tópicos"
        except HTTPError as error:
            last_result = f"HTTP {error.code} en /topic"
        except (OSError, KeyError, TypeError, ValueError) as error:
            last_result = f"{type(getattr(error, 'reason', error)).__name__} en /topic"
        time.sleep(2)
    else:
        raise RuntimeError(f"El panel no pudo listar tópicos del broker ({last_result}). Ejecute --diagnose.")

    sockets = subprocess.check_output(["ss", "-ltnH", "sport", "=", f":{PORT}"], text=True, timeout=5)
    if {line.split()[3] for line in sockets.splitlines() if line.strip()} != {f"127.0.0.1:{PORT}"}:
        raise RuntimeError("La escucha del panel debe estar limitada a 127.0.0.1.")
    print(f"Kafka UI de solo lectura · {URL} · {len(topics)} tópicos listados")
    for topic in TOPICS:
        status = "visible" if topic in topics else "ausente en la consulta"
        print(f"{topic} · {status}")


def diagnose(broker):
    state = subprocess.check_output([
        "docker", "container", "inspect", "--format",
        "{{.State.Status}} · OOM={{.State.OOMKilled}} · código={{.State.ExitCode}} · reinicios={{.RestartCount}}",
        NAME,
    ], text=True, timeout=10)
    print(f"Contenedor · {state.strip()}")
    host, port = broker.rsplit(":", 1)
    try:
        with socket.create_connection((host, int(port)), timeout=4):
            print("Broker · conexión TCP disponible")
    except OSError as error:
        print(f"Broker · {type(error).__name__}")
    sockets = subprocess.check_output(["ss", "-ltnH"], text=True, timeout=5)
    for line in sockets.splitlines():
        address = line.split()[3]
        if address.rpartition(":")[2] in {"9000", str(PORT)}:
            print(f"Escucha · {address}")

    opener = build_opener(ProxyHandler({}))
    for path, accept in (("/", "text/html"), ("/topic", "application/json")):
        try:
            request = Request(URL + path, headers={"Accept": accept})
            with opener.open(request, timeout=12) as response:
                print(f"{path} · HTTP {response.status} · {response.headers.get_content_type()}")
                if path == "/topic":
                    data = json.load(response)
                    print(f"Tópicos · tipo {type(data).__name__} · {len(data)} elementos")
        except HTTPError as error:
            print(f"{path} · HTTP {error.code}")
        except (URLError, OSError, ValueError, TypeError) as error:
            print(f"{path} · {type(getattr(error, 'reason', error)).__name__}")

    logs = subprocess.run(["docker", "logs", "--tail", "120", NAME],
                          capture_output=True, text=True, timeout=10, check=True)
    indicators = r"OutOfMemoryError|BindException|TimeoutException|UnknownHostException|ConnectException|BeanCreationException|UnsupportedClassVersionError|Failed to start|APPLICATION FAILED TO START|Started Kafdrop|Tomcat started"
    errors = sorted(set(re.findall(indicators, logs.stdout + logs.stderr)))
    if errors:
        print("Indicadores en el log · " + ", ".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("apply", "verify", "diagnose"))
    parser.add_argument("broker")
    args = parser.parse_args()
    environment = settings(args.broker)
    try:
        if args.mode == "diagnose":
            diagnose(args.broker)
            return 0
        existing = current_container(environment, replace_legacy=args.mode == "apply")
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
