#!/usr/bin/env python3
"""Collect Kafka and RabbitMQ evidence from the Pedidos360 backup laboratory."""

import argparse
import base64
from pathlib import Path
import re
import shlex
import sys

from kafka_ui_host import TOPICS, URL
from replica_infra import STACK, aws
from webpay import RolloutError, run_ssm


SOURCE = Path(__file__).resolve().parent
DESTINATION = "/opt/pedidos360-kafka-ui"
PANEL_FILES = ("kafka_ui_host.py", "kafka_ui_proxy.sh", "Caddyfile.kafka-ui")

KAFKA_PROBE = f"""
import json
from urllib.request import ProxyHandler, Request, build_opener

opener = build_opener(ProxyHandler({{}}))
for topic in {TOPICS!r}:
    try:
        request = Request(f'{URL}/topic/{{topic}}', headers={{'Accept': 'application/json'}})
        with opener.open(request, timeout=6) as response:
            data = json.load(response)
        count = data['totalSize']
        if isinstance(count, int) and count >= 0:
            print(f'{{topic}} · mensajes publicados acumulados: {{count}}')
        else:
            print(f'{{topic}} · contador no disponible')
    except (KeyError, OSError, TypeError, ValueError):
        print(f'{{topic}} · sin contador verificable')
"""

RABBIT_PROBE = """
import json
import subprocess

broker = 'ev3-replica-rabbitmq'
notifier = 'ev3-replica-notificaciones'
exchange = subprocess.check_output(['docker', 'exec', broker, 'rabbitmqctl', '-q',
                                     'list_exchanges', 'name', 'type'], text=True, timeout=25)
for row in exchange.splitlines():
    if row.split()[:1] in (['pedidos.exchange'], ['pedidos.dlx']):
        print(row)
print('Cola | pendientes | sin confirmar | consumidores')
queues = subprocess.check_output(['docker', 'exec', broker, 'rabbitmqctl', '-q', 'list_queues',
                                   'name', 'messages_ready', 'messages_unacknowledged', 'consumers'],
                                  text=True, timeout=25)
for row in queues.splitlines():
    if row.startswith('pedido.creado.'):
        print(row)
env = json.loads(subprocess.check_output(['docker', 'inspect', '--format', '{{json .Config.Env}}', notifier],
                                         text=True, timeout=10))
settings = dict(entry.split('=', 1) for entry in env if '=' in entry)
configured = (settings.get('MAIL_USERNAME') not in (None, '', 'correo@gmail.com')
              and settings.get('MAIL_PASSWORD') not in (None, '', 'app-password-aqui'))
print('SMTP configurado: ' + ('si' if configured else 'no'))
logs = subprocess.run(['docker', 'logs', '--tail', '250', notifier], capture_output=True, text=True, timeout=15, check=True)
recent = logs.stdout + logs.stderr
print('Notificaciones · eventos RabbitMQ en log reciente: ' + str(recent.count('Mensaje recibido de RabbitMQ:')))
print('Notificaciones · errores de envio en log reciente: ' + str(recent.count('Error al enviar correo')))
print('Notificaciones · confirmaciones aceptadas por SMTP en log reciente: '
      + str(recent.count('Correo de confirmación enviado a')))
"""


def python_probe(code):
    return f"python3 -c {shlex.quote(code)}"


def kafka_commands(broker, install):
    if not re.fullmatch(r"[A-Za-z0-9.-]+:9092", broker):
        raise RuntimeError("KafkaBootstrap de la réplica tiene un formato inesperado.")
    commands = ["set -eu"]
    if install:
        commands.append(f"install -d -m 0755 {DESTINATION}")
        for filename in PANEL_FILES:
            encoded = base64.b64encode((SOURCE / filename).read_bytes()).decode("ascii")
            commands.append(f"printf '%s' '{encoded}' | base64 --decode > {DESTINATION}/{filename}")
    mode = "apply" if install else "verify"
    return [*commands, f"python3 {DESTINATION}/kafka_ui_host.py {mode} {shlex.quote(broker)}", python_probe(KAFKA_PROBE)]


def inspect_host(instance, commands, label):
    request = {"DocumentName": "AWS-RunShellScript", "InstanceIds": [instance], "Comment": f"EV3 respaldo {label}",
               "Parameters": {"commands": commands, "executionTimeout": ["300"]}, "TimeoutSeconds": 120}
    return run_ssm(request, instance, failure=f"SSM no completó la comprobación de {label}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True, help="Expected account ID of the backup laboratory")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--install-kafka-ui", action="store_true", help="install the private Kafdrop dashboard and take baseline metrics")
    modes.add_argument("--check", action="store_true", help="read Kafka and RabbitMQ metrics again")
    args = parser.parse_args()
    try:
        if aws("sts", "get-caller-identity")["Account"] != args.account:
            raise RuntimeError("La sesión no corresponde a la cuenta del respaldo.")
        stack = aws("cloudformation", "describe-stacks", "--stack-name", STACK)["Stacks"][0]
        outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
        print("RabbitMQ y Notificaciones", flush=True)
        inspect_host(outputs["NotificacionesInstance"], [python_probe(RABBIT_PROBE)], "RabbitMQ")
        print("Kafka y Kafdrop", flush=True)
        inspect_host(outputs["AnalyticsInstance"], kafka_commands(outputs["KafkaBootstrap"], args.install_kafka_ui), "Kafka UI")
    except (OSError, KeyError, ValueError, RuntimeError, RolloutError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
