#!/usr/bin/env python3
"""Start or check the private EV3 Kafka UI on the Productos EC2."""

import argparse
from pathlib import Path
import shlex
import sys

from kafka_recovery import PORT, REGION, RecoveryError, load_lab_config, require
from webpay import RolloutError, aws, run_ssm


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
        instance = clients["Productos"]
        result = aws("ec2", "describe-instances", "--instance-ids", instance)
        target = result["Reservations"][0]["Instances"][0]
        require(target["State"]["Name"] == "running" and target["SubnetId"] == subnet,
                "La EC2 de Productos debe estar activa en la subred del laboratorio")

        source = Path(__file__).with_name("kafka_ui_host.py").read_text(encoding="utf-8")
        mode = "apply" if args.apply else "verify"
        arguments = shlex.join([mode, f"{broker}:{PORT}"])
        print(f"Kafka UI · EC2 de Productos {instance} · {REGION}", flush=True)
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
