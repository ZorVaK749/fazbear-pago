#!/usr/bin/env python3
"""Discover the effective CLP rollout targets without changing the instances."""

import argparse
import base64
import gzip
from pathlib import Path
import shlex
import sys

from webpay import ACCOUNT, RolloutError, aws, run_ssm


SERVICES = {
    "productos": ("i-0bc8e0a99f79ccac6", "fazbears-productos", 8081),
    "carrito": ("i-0c29438f2236c5b39", "fazbear-carrito", 8083),
    "orden": ("i-0affb4cde24db3e39", "fazbear-orden", 8084),
    "notificaciones": ("i-0ab7a0bdce7b6cb9c", "fazbear-notificaciones", 8085),
    "analytics": ("i-049081f7c46b5aba3", "fazbear-analytics-recommendations", 8088),
}


def request(service):
    instance, package, port = SERVICES[service]
    source = Path(__file__).with_name("clp_inventory_host.py")
    script = base64.b64encode(gzip.compress(source.read_bytes(), mtime=0)).decode()
    args = shlex.join((service, package, str(port)))
    return {
        "DocumentName": "AWS-RunShellScript",
        "InstanceIds": [instance],
        "Comment": f"Pedidos360 CLP inventario {service}",
        "TimeoutSeconds": 90,
        "Parameters": {"commands": [f"printf %s '{script}' | base64 -d | gzip -dc | python3 - {args}"],
                       "executionTimeout": ["60"]},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=SERVICES, default="productos")
    args = parser.parse_args()
    try:
        if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
            raise RolloutError(f"La sesión AWS debe corresponder a la cuenta {ACCOUNT}.")
        run_ssm(request(args.service), SERVICES[args.service][0], timeout=160,
                failure="SSM no completó el inventario. Revise el Command ID.")
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
