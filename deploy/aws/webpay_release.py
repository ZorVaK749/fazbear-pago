#!/usr/bin/env python3
"""Verifica o actualiza Pago en la EC2 de Webpay conservando PostgreSQL."""

import argparse
from ipaddress import IPv4Address
import re
import sys

from clp_productos import python_request
from frontend_gateway import verify_named_stage
from webpay import ACCOUNT, INSTANCE, PORT, RolloutError, aws, private_ip, resolve_target, run_ssm, target_state, wait_for_target
from webpay_release_host import MODES, PACKAGE

MODULES = ("webpay_host", "clp_inventory_host", "clp_backends_host", "webpay_release_host")


def execute(mode, image, migration=5, return_stage="keep"):
    if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
        raise RolloutError(f"La sesión AWS debe corresponder a la cuenta {ACCOUNT}.")
    address = str(IPv4Address(private_ip(INSTANCE)))
    if return_stage == "ev3" and mode in {"dry-run", "apply", "verify"}:
        verify_named_stage()
    if mode != "status":
        arn, target, interval = resolve_target(None)
        initial = target_state(arn, target, True)
        print(f"Pago · Target Group {arn} · {initial}", flush=True)
        if mode in {"dry-run", "apply"} and initial != "healthy":
            raise RolloutError("Pago debe estar healthy antes del cambio.")
    arguments = (mode, address, image, str(migration))
    if return_stage != "keep":
        arguments += (return_stage,)
    request = python_request(INSTANCE, f"Pedidos360 Pago release {mode}", MODULES,
                             arguments, 360 if mode == "apply" else 160)
    run_ssm(request, INSTANCE, timeout=440 if mode == "apply" else 210,
            failure="Operación incompleta en Pago. Consulte --status con el mismo digest y el Command ID.")
    if mode in {"apply", "verify", "recover"}:
        wait_for_target(arn, target, interval, port=PORT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    flags = parser.add_mutually_exclusive_group(required=True)
    for mode in MODES:
        flags.add_argument(f"--{mode}", dest="mode", action="store_const", const=mode)
    parser.add_argument("--image", required=True)
    parser.add_argument("--migration", type=int, choices=(5, 6), default=5)
    parser.add_argument("--return-stage", choices=("ev3",))
    args = parser.parse_args()
    if not re.fullmatch(re.escape(PACKAGE) + r"@sha256:[a-f0-9]{64}", args.image):
        parser.error("--image requiere el digest GHCR del servicio Pago")
    try:
        execute(args.mode, args.image, args.migration, args.return_stage or "keep")
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
