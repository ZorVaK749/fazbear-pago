#!/usr/bin/env python3
"""Actualiza servicios ya instalados en EC2 por digest."""

import argparse
from ipaddress import IPv4Address
import sys

from clp_inventory import SERVICES
from clp_productos import python_request
from clp_backends_host import MODES, RELEASE, release_for
from webpay import ACCOUNT, RolloutError, aws, private_ip, resolve_target, run_ssm, target_state, wait_for_target

MODULES = ("webpay_host", "clp_inventory_host", "clp_backends_host")


def send(name, mode, address, catalog, image=None):
    instance = SERVICES[name][0]
    arguments = (name, mode, str(IPv4Address(address)), str(IPv4Address(catalog)))
    if image:
        arguments += (image,)
    request = python_request(instance, f"Pedidos360 CLP {name} {mode}", MODULES, arguments, 200)
    run_ssm(request, instance, timeout=270,
            failure=f"Operación incompleta en {name}. Consulte --status --service {name} y el Command ID.")


def execute(mode, selected=None, image=None):
    if selected == "pedidos" and mode in {"dry-run", "apply", "verify"} and image is None:
        raise RolloutError("Pedidos requiere --image con el digest publicado.")
    if image is not None:
        if selected is None:
            raise RolloutError("--image requiere --service.")
        release_for(selected, image)
    if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
        raise RolloutError(f"La sesión AWS debe corresponder a la cuenta {ACCOUNT}.")
    product_instance, _, product_port = SERVICES["productos"]
    catalog = private_ip(product_instance)
    names = (selected,) if selected else tuple(name for name in RELEASE if name != "pedidos")
    targets = []
    if mode in {"dry-run", "apply"}:
        arn, target, _ = resolve_target(None, instance=product_instance, port=product_port)
        if target_state(arn, target, True, port=product_port) != "healthy":
            raise RolloutError("Productos debe estar healthy antes de actualizar los demás servicios.")
    for name in names:
        instance, _, port = SERVICES[name]
        address = private_ip(instance)
        if mode == "status":
            send(name, mode, address, catalog, image)
            continue
        arn, target, interval = resolve_target(None, instance=instance, port=port)
        initial = target_state(arn, target, True, port=port)
        print(f"{name} · Target Group {arn} · {initial}", flush=True)
        if mode in {"dry-run", "apply"}:
            if initial != "healthy":
                raise RolloutError(f"El Target Group de {name} debe estar healthy antes del corte.")
            send(name, "dry-run", address, catalog, image)
        targets.append((name, address, arn, target, interval, port))
    if mode in {"apply", "verify", "recover"}:
        for name, address, arn, target, interval, port in targets:
            send(name, mode, address, catalog, image)
            wait_for_target(arn, target, interval, port=port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    flags = parser.add_mutually_exclusive_group(required=True)
    for mode in MODES:
        flags.add_argument(f"--{mode}", dest="mode", action="store_const", const=mode)
    parser.add_argument("--service", choices=RELEASE)
    parser.add_argument("--image", help="Referencia GHCR por digest para el servicio indicado")
    args = parser.parse_args()
    if args.mode == "recover" and not args.service:
        parser.error("--recover requiere --service")
    try:
        execute(args.mode, args.service, args.image)
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
