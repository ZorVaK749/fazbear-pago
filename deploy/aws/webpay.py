#!/usr/bin/env python3
"""Send the reviewed rollout to the Pago EC2 and verify its load-balancer target."""

import argparse
import base64
from contextlib import contextmanager
import getpass
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import warnings

from webpay_host import MODES, PARAMETERS, RolloutError, validate_credentials

REGION = "us-east-1"
ACCOUNT = "767398096661"
INSTANCE = "i-0241836a7e45a2e3f"
PORT = 8087
HOST_SCRIPT = Path(__file__).with_name("webpay_host.py")
TARGET_ARN = re.compile(r"arn:aws:elasticloadbalancing:us-east-1:[0-9]{12}:targetgroup/[A-Za-z0-9-]+/[a-f0-9]+")


@contextmanager
def cli_arguments(args, input_json):
    if input_json is None:
        yield args, ()
        return
    # AWS CLI can read the parameter source more than once. An anonymous
    # seekable Linux file allows that without writing credentials to disk.
    with os.fdopen(os.memfd_create("pedidos360-webpay"), "w+b") as data:
        data.write(json.dumps(input_json).encode())
        data.flush()
        data.seek(0)
        fd = data.fileno()
        yield (*args, "--cli-input-json", f"file:///proc/self/fd/{fd}"), (fd,)


def aws(*args, input_json=None):
    failure = f"Falló AWS CLI para {args[0]} {args[1]}. Revise región, credenciales e IAM."
    try:
        with cli_arguments(args, input_json) as (arguments, fds):
            response = subprocess.run(
                ["aws", "--region", REGION, "--no-cli-pager", "--output", "json", *arguments],
                capture_output=True, check=True, timeout=30, pass_fds=fds,
            )
        return json.loads(response.stdout)
    except subprocess.CalledProcessError as error:
        if args[:2] == ("ssm", "put-parameter"):
            stderr = error.stderr or b""
            if b"(ParameterAlreadyExists)" in stderr:
                return {"AlreadyExists": True}
            if b"AccessDenied" in stderr or b"is not authorized" in stderr:
                failure = "AWS denegó la creación del parámetro. Revise ssm:PutParameter y los permisos KMS."
        raise RolloutError(failure) from None
    except (OSError, ValueError, subprocess.SubprocessError):
        raise RolloutError(failure) from None


def create_parameters():
    if not hasattr(os, "memfd_create") or not sys.stdin.isatty():
        raise RolloutError("Use una sesión interactiva de CloudShell para ingresar las credenciales con eco desactivado.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            code = getpass.getpass("Código de comercio Webpay Plus de integración (oculto): ").strip()
            key = getpass.getpass("API key Webpay Plus de integración (oculta): ").strip()
    except (EOFError, getpass.GetPassWarning):
        raise RolloutError("No se pudo leer desde una terminal con eco desactivado.") from None
    code, key = validate_credentials(code, key)
    for name, value in zip(PARAMETERS.values(), (code, key)):
        response = aws("ssm", "put-parameter", input_json={
            "Name": name, "Value": value, "Type": "SecureString", "Tier": "Standard", "Overwrite": False,
        })
        result = "ya existía y se conservó" if response.get("AlreadyExists") else "creado"
        print(f"{name}: {result}")


def private_ip():
    reservations = aws("ec2", "describe-instances", "--instance-ids", INSTANCE)["Reservations"]
    instance = reservations[0]["Instances"][0]
    if instance["InstanceId"] != INSTANCE or instance["State"]["Name"] != "running":
        raise RolloutError("La EC2 de Pago debe estar en ejecución.")
    return instance["PrivateIpAddress"]


def registered(group):
    return aws("elbv2", "describe-target-health", "--target-group-arn", group)["TargetHealthDescriptions"]


def match(target, target_id):
    return target["Target"]["Id"] == target_id and target["Target"]["Port"] == PORT


def resolve_target(explicit):
    ip = private_ip()
    extra = ("--target-group-arns", explicit) if explicit else ()
    groups = aws("elbv2", "describe-target-groups", *extra)["TargetGroups"]
    candidates = []
    for group in groups:
        id_for_type = {"instance": INSTANCE, "ip": ip}.get(group["TargetType"])
        port_matches = group["Port"] == PORT or group.get("HealthCheckPort") == str(PORT)
        if id_for_type and (explicit or port_matches):
            arn = group["TargetGroupArn"]
            targets = registered(arn)
            if any(match(target, id_for_type) for target in targets):
                candidates.append((arn, id_for_type, int(group["HealthCheckIntervalSeconds"])))
    if len(candidates) != 1:
        raise RolloutError("El Target Group de Pago es ambiguo o no se encontró. Indique --target-group-arn.")
    return candidates[0]


def target_state(arn, target_id, sole=False):
    targets = registered(arn)
    matches = [target for target in targets if match(target, target_id)]
    if len(matches) != 1 or (sole and len(targets) != 1):
        raise RolloutError("Se requiere un único destino de Pago registrado en el Target Group seleccionado.")
    return matches[0]["TargetHealth"]["State"]


def wait_for_target(arn, target_id, interval, sole=True):
    # The first healthy response can still be cached from the previous container.
    deadline = time.monotonic() + max(120, 3 * interval + 25)
    first_healthy = None
    while time.monotonic() < deadline:
        current = time.monotonic()
        if target_state(arn, target_id, sole) == "healthy":
            if first_healthy is None:
                first_healthy = current
            elif current - first_healthy >= interval:
                print(f"Target Group healthy en dos observaciones separadas por al menos {interval} s.")
                return
        else:
            first_healthy = None
        time.sleep(5)
    raise RolloutError("Target Group sin salud estable. Se conservó el contenedor activo. Use --status.")


def ssm_request(mode, source, check_credentials=False):
    # Only reviewed code and allowlisted switches travel in Run Command parameters.
    script = base64.b64encode(gzip.compress(HOST_SCRIPT.read_bytes(), mtime=0)).decode()
    commands = ["exec bash -s <<'PEDIDOS360_WEBPAY'", "set -euo pipefail", "{"]
    commands.extend(f"printf %s '{script[i:i + 2000]}'" for i in range(0, len(script), 2000))
    check = " --check-credentials" if check_credentials else ""
    commands.extend([f"}} | base64 -d | gzip -dc | python3 - {mode} {source}{check}", "PEDIDOS360_WEBPAY"])
    return {
        "DocumentName": "AWS-RunShellScript",
        "InstanceIds": [INSTANCE],
        "Comment": f"Pedidos360 Webpay {mode}",
        "TimeoutSeconds": 120,
        "Parameters": {"commands": commands, "executionTimeout": ["420"]},
    }


def run_host(mode, source, check_credentials=False):
    run_ssm(ssm_request(mode, source, check_credentials), INSTANCE)


def run_ssm(request, instance, timeout=480,
            failure="SSM no completó la operación. Revise el diario con --status."):
    command = aws("ssm", "send-command", "--cli-input-json", json.dumps(request))["Command"]["CommandId"]
    print(f"SSM Command ID: {command}", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # List handles the short period before the invocation appears without parsing CLI stderr.
        results = aws("ssm", "list-command-invocations", "--command-id", command, "--instance-id", instance)
        invocations = results["CommandInvocations"]
        if invocations and invocations[0]["Status"] not in {"Pending", "InProgress", "Delayed", "Cancelling"}:
            result = aws("ssm", "get-command-invocation", "--command-id", command, "--instance-id", instance)
            for field in ("StandardOutputContent", "StandardErrorContent"):
                output = result.get(field, "").strip()
                if output:
                    print(output, file=sys.stderr if field == "StandardErrorContent" else sys.stdout)
            if result["Status"] != "Success":
                raise RolloutError(failure)
            return
        time.sleep(5)
    raise RolloutError("SSM sigue sin confirmar el resultado. Revise el Command ID antes de reintentar.")


def execute(mode, source, requested_target, check_credentials=False):
    if aws("sts", "get-caller-identity").get("Account") != ACCOUNT:
        raise RolloutError(f"La sesión AWS debe corresponder a la cuenta {ACCOUNT}.")
    if mode == "create-parameters":
        create_parameters()
        return
    if requested_target and requested_target.split(":")[4] != ACCOUNT:
        raise RolloutError("El Target Group indicado pertenece a otra cuenta AWS.")
    mutating = mode in {"apply", "rollback", "recover"}
    try:
        arn, target_id, interval = resolve_target(requested_target)
        initial = target_state(arn, target_id, sole=mutating or mode in {"dry-run", "prepare-rollback"})
    except RolloutError:
        if mode == "status":
            run_host(mode, source, check_credentials)
        raise
    print(f"Target Group: {arn}\nDestino {target_id}:{PORT} · estado inicial {initial}", flush=True)
    if mode in {"apply", "dry-run", "prepare-rollback"} and initial != "healthy":
        raise RolloutError("El Target Group de Pago debe estar healthy antes de preparar o activar Webpay.")
    run_host(mode, source, check_credentials)
    if mutating:
        wait_for_target(arn, target_id, interval)


def main():
    parser = argparse.ArgumentParser(description="Inspección y activación Webpay en la EC2 Pago EV3")
    methods = parser.add_mutually_exclusive_group(required=True)
    for mode in MODES:
        methods.add_argument(f"--{mode}", dest="mode", action="store_const", const=mode)
    methods.add_argument("--create-parameters", dest="mode", action="store_const", const="create-parameters",
                         help="Crea los dos SecureString desde una terminal interactiva en CloudShell.")
    parser.add_argument("--source", choices=("ssm", "host-file"), default="ssm")
    parser.add_argument("--check-credentials", action="store_true",
                        help="Con --dry-run, comprueba lectura y formato de credenciales sin exponer valores.")
    parser.add_argument("--target-group-arn")
    args = parser.parse_args()
    if args.target_group_arn and not TARGET_ARN.fullmatch(args.target_group_arn):
        parser.error("ARN de Target Group inválido para us-east-1")
    if args.check_credentials and args.mode != "dry-run":
        parser.error("--check-credentials requiere --dry-run")
    try:
        execute(args.mode, args.source, args.target_group_arn, args.check_credentials)
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (KeyError, IndexError, OSError, ValueError, TypeError):
        print("ERROR: inventario o respuesta inesperados. Revise el Command ID si se emitió uno.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrumpido. Si se emitió un Command ID, verifique su estado antes de reintentar.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
