#!/usr/bin/env python3
"""Start or check the private EV3 Kafka UI on a Kafka client EC2."""

import argparse
from pathlib import Path
import shlex
import sys
import time

from kafka_recovery import PORT, REGION, RecoveryError, load_lab_config, require
from kafka_ui_host import LABEL, MIN_AVAILABLE_MB
from webpay import RolloutError, aws, run_ssm


def find_host(clients, subnet, deploy):
    clients = {name: instance for name, instance in clients.items() if name != "Pago"}
    result = aws("ec2", "describe-instances", "--instance-ids", *clients.values())
    active = {vm["InstanceId"] for reservation in result["Reservations"] for vm in reservation["Instances"]
              if vm["State"]["Name"] == "running" and vm["SubnetId"] == subnet}
    require(active, "No hay EC2 candidatas activas en la subred del laboratorio")
    command = aws("ssm", "send-command", input_json={
        "DocumentName": "AWS-RunShellScript",
        "InstanceIds": sorted(active),
        "Comment": "Pedidos360 Kafka UI capacidad",
        "Parameters": {
            "commands": [
                "awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo",
                f"docker ps -a --quiet --filter label={shlex.quote(LABEL)} | wc -l",
            ],
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
            break
        time.sleep(2)

    installed = []
    available = []
    for name, instance in clients.items():
        row = rows.get(instance, {})
        plugins = row.get("CommandPlugins", [])
        output = plugins[0].get("Output", "").split() if plugins else []
        if row.get("Status") != "Success" or len(output) != 2 or not all(part.isdecimal() for part in output):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--apply", action="store_true", help="levantar el panel y verificar los tópicos")
    modes.add_argument("--verify", action="store_true", help="consultar el panel instalado")
    parser.add_argument("--lab-config", type=Path, default=Path.home() / "kafka_recovery.py")
    args = parser.parse_args()
    try:
        account, subnet, broker, clients = load_lab_config(args.lab_config)
        require(aws("sts", "get-caller-identity")["Account"] == account,
                "Use la cuenta AWS del laboratorio EV3")
        name, instance = find_host(clients, subnet, args.apply)

        source = Path(__file__).with_name("kafka_ui_host.py").read_text(encoding="utf-8")
        mode = "apply" if args.apply else "verify"
        arguments = shlex.join([mode, f"{broker}:{PORT}"])
        print(f"Kafka UI · EC2 de {name} {instance} · {REGION}", flush=True)
        run_ssm({
            "DocumentName": "AWS-RunShellScript",
            "InstanceIds": [instance],
            "Comment": f"Pedidos360 Kafka UI {mode}",
            "Parameters": {
                "commands": [f"python3 - {arguments} <<'PEDIDOS360_KAFKA_UI'\n"
                             f"{source}\nPEDIDOS360_KAFKA_UI"],
                "executionTimeout": ["300"],
            },
        }, instance, timeout=320, failure="Kafka UI no quedó verificado. Revise el mensaje de SSM.")
    except (RolloutError, RecoveryError, OSError, ValueError, SyntaxError, KeyError, IndexError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
