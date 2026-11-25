#!/usr/bin/env python3
"""Start or check the private EV3 Kafka UI on a Kafka client EC2."""

import argparse
import base64
from pathlib import Path
import shlex
import sys
import time

from clp_inventory import SERVICES as EC2_SERVICES
from frontend_image import FAMILY as FRONTEND_SERVICE
from kafka_recovery import CLUSTER, PORT, REGION, SERVICE as BROKER_SERVICE, RecoveryError, load_lab_config, require
from kafka_ui_host import LABEL, MIN_AVAILABLE_MB
from webpay import RolloutError, aws, run_ssm


PROXY_DIR = "/opt/pedidos360-kafka-ui"
PROXY_FILES = ("Caddyfile.kafka-ui", "compose.kafka-ui-proxy.yml")
HOST_CAPACITY_COMMANDS = [
    "awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo",
    f"docker ps -a --quiet --filter label={shlex.quote(LABEL)} | wc -l",
]


def proxy_file_commands():
    commands = [f"install -d -m 0755 {PROXY_DIR}"]
    for name in PROXY_FILES:
        encoded = base64.b64encode(Path(__file__).with_name(name).read_bytes()).decode("ascii")
        commands.append(f"printf '%s' '{encoded}' | base64 --decode > {PROXY_DIR}/{name}")
    commands.append(f"printf '%s\\n' 'Configuración del proxy preparada en {PROXY_DIR}'")
    return commands


def probe_hosts(active, commands):
    if not active:
        return {}
    command = aws("ssm", "send-command", input_json={
        "DocumentName": "AWS-RunShellScript",
        "InstanceIds": sorted(active),
        "Comment": "Pedidos360 Kafka UI capacidad",
        "Parameters": {
            "commands": commands,
            "executionTimeout": ["15"],
        },
        "TimeoutSeconds": 30,
    })["Command"]["CommandId"]
    print(f"SSM capacidad: {command}", flush=True)
    deadline = time.monotonic() + 45
    terminal = {"Success", "Failed", "TimedOut", "Cancelled"}
    while True:
        result = aws("ssm", "list-command-invocations", "--command-id", command, "--details")
        rows = {row["InstanceId"]: row for row in result["CommandInvocations"]}
        if (active <= rows.keys() and all(rows[vm]["Status"] in terminal for vm in active)
                or time.monotonic() >= deadline):
            return {
                instance: row["CommandPlugins"][0].get("Output", "").split()
                for instance, row in rows.items() if row["Status"] == "Success" and row["CommandPlugins"]
            }
        time.sleep(2)


def find_host(clients, subnet, deploy):
    clients = {name: instance for name, instance in clients.items() if name != "Pago"}
    result = aws("ec2", "describe-instances", "--instance-ids", *clients.values())
    active = {vm["InstanceId"] for reservation in result["Reservations"] for vm in reservation["Instances"]
              if vm["State"]["Name"] == "running" and vm["SubnetId"] == subnet}
    require(active, "No hay EC2 candidatas activas en la subred del laboratorio")
    measurements = probe_hosts(active, HOST_CAPACITY_COMMANDS)
    installed = []
    available = []
    for name, instance in clients.items():
        output = measurements.get(instance, [])
        if len(output) != 2 or not all(part.isdecimal() for part in output):
            print(f"{name} · capacidad sin verificar")
            continue
        memory, containers = map(int, output)
        print(f"{name} · {memory} MiB libres" + (" · panel existente" if containers else ""))
        if containers:
            installed.append((name, instance))
        elif memory >= MIN_AVAILABLE_MB:
            available.append((memory, name, instance))
    require(len(installed) <= 1, "Hay más de un panel instalado. Revise el inventario antes de continuar")
    if installed:
        return installed[0]
    require(deploy, "Kafka UI todavía no está instalado en las EC2 verificadas")
    require(available, f"Ninguna EC2 candidata tiene los {MIN_AVAILABLE_MB} MiB necesarios para Kafka UI")
    _, name, instance = max(available)
    return name, instance


def inventory(clients, subnet, broker):
    names = {instance: name.capitalize() for name, (instance, *_rest) in EC2_SERVICES.items()}
    names.update({instance: name for name, instance in clients.items()})
    vpc = aws("ec2", "describe-subnets", "--subnet-ids", subnet)["Subnets"][0]["VpcId"]
    result = aws("ec2", "describe-instances", "--filters",
                 f"Name=vpc-id,Values={vpc}",
                 "Name=instance-state-name,Values=pending,running,stopping,stopped")
    instances = {vm["InstanceId"]: vm for group in result["Reservations"] for vm in group["Instances"]}
    for instance, vm in instances.items():
        tag = next((tag["Value"] for tag in vm.get("Tags", []) if tag["Key"] == "Name"), "")
        if "reporte" in tag.casefold() and instance not in names:
            names[instance] = "Reportes"
    if "Reportes" not in names.values():
        unmatched = instances.keys() - names.keys()
        if len(unmatched) == 1:
            # Confirm the service from the running image before labeling the host.
            names[unmatched.pop()] = "Por identificar"

    active = {instance for instance in names if instance in instances
              and instances[instance]["State"]["Name"] == "running"}
    tcp_test = (
        "import socket, sys; "
        "socket.create_connection((sys.argv[1], int(sys.argv[2])), 3).close()"
    )
    commands = [
        *HOST_CAPACITY_COMMANDS,
        f"if python3 -c {shlex.quote(tcp_test)} {shlex.quote(broker)} {PORT} 2>/dev/null; then echo 1; else echo 0; fi",
        "ss -ltnH | awk '$4 ~ /:(80|18443)$/ {count++} END {print count+0}'",
        "docker ps --format '{{.Image}}' | awk '/fazbears?-reportes([:@]|$)/ {count++} END {print count+0}'",
    ]
    measured = probe_hosts(active, commands)
    try:
        elastic = {address["PublicIp"] for address in aws("ec2", "describe-addresses")["Addresses"]}
    except RolloutError:
        elastic = None
        print("Elastic IP · AWS no permitió consultar las direcciones reservadas")

    reports_found = "Reportes" in names.values()
    for instance, name in sorted(names.items(), key=lambda item: item[1]):
        vm = instances.get(instance, {})
        state = vm.get("State", {}).get("Name", "sin localizar")
        public = vm.get("PublicIpAddress")
        ip_type = "sin IPv4 pública"
        if public:
            ip_type = public if elastic is None else f"{public} ({'Elastic IP' if public in elastic else 'dinámica'})"
        values = measured.get(instance, [])
        detail = ""
        if len(values) == 5 and all(part.isdecimal() for part in values):
            memory, panel, kafka, ports, reportes = map(int, values)
            if name == "Por identificar" and reportes:
                name = "Reportes"
                reports_found = True
            detail = (f" · {memory} MiB libres · broker TCP {'OK' if kafka else 'sin conexión'}"
                      f" · web {'80/18443 libres' if not ports else '80 o 18443 ocupado'}"
                      f"{' · Kafdrop instalado' if panel else ''}")
        elif state == "running":
            detail = " · medición SSM no disponible"
        print(f"{name} · EC2 {instance} · {state} · {vm.get('InstanceType', 'tipo sin verificar')} · {ip_type}{detail}")
    if not reports_found:
        print("Reportes · EC2 sin identificar en el inventario")

    services = aws("ecs", "describe-services", "--cluster", CLUSTER,
                   "--services", FRONTEND_SERVICE, BROKER_SERVICE)["services"]
    by_name = {service["serviceName"]: service for service in services if service["status"] != "INACTIVE"}
    for name, service_id in (("Frontend", FRONTEND_SERVICE), ("Kafka", BROKER_SERVICE)):
        service = by_name.get(service_id)
        if service:
            print(f"{name} · ECS · {service['runningCount']}/{service['desiredCount']} tareas activas")
        else:
            print(f"{name} · servicio ECS sin localizar")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--apply", action="store_true", help="levantar el panel y verificar los tópicos")
    modes.add_argument("--verify", action="store_true", help="consultar el panel instalado")
    modes.add_argument("--diagnose", action="store_true", help="inspeccionar el contenedor y las respuestas HTTP")
    modes.add_argument("--inventory", action="store_true", help="ver EC2, Elastic IP, capacidad, Kafka y ECS")
    parser.add_argument("--lab-config", type=Path, default=Path.home() / "kafka_recovery.py")
    args = parser.parse_args()
    try:
        account, subnet, broker, clients = load_lab_config(args.lab_config)
        require(aws("sts", "get-caller-identity")["Account"] == account,
                "Use la cuenta AWS del laboratorio EV3")
        if args.inventory:
            inventory(clients, subnet, broker)
            return 0
        name, instance = find_host(clients, subnet, args.apply)

        source = Path(__file__).with_name("kafka_ui_host.py").read_text(encoding="utf-8")
        mode = "apply" if args.apply else "diagnose" if args.diagnose else "verify"
        arguments = shlex.join([mode, f"{broker}:{PORT}"])
        commands = ["set -e", f"python3 - {arguments} <<'PEDIDOS360_KAFKA_UI'\n"
                             f"{source}\nPEDIDOS360_KAFKA_UI"]
        if args.apply:
            commands.extend(proxy_file_commands())
        print(f"Kafka UI · EC2 de {name} {instance} · {REGION}", flush=True)
        run_ssm({
            "DocumentName": "AWS-RunShellScript",
            "InstanceIds": [instance],
            "Comment": f"Pedidos360 Kafka UI {mode}",
            "Parameters": {
                "commands": commands,
                "executionTimeout": ["300"],
            },
        }, instance, timeout=320, failure="Kafka UI no quedó verificado. Revise el mensaje de SSM.")
    except (RolloutError, RecoveryError, OSError, ValueError, SyntaxError, KeyError, IndexError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
