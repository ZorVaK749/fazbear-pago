#!/usr/bin/env python3
"""Prepare and verify the mounted H2 catalog on the existing Productos EC2."""

import argparse
import base64
import gzip
from ipaddress import IPv4Address
import json
from pathlib import Path
import shlex
import sys

from clp_inventory import SERVICES
from webpay import ACCOUNT, RolloutError, aws, private_ip, resolve_target, run_ssm, target_state, wait_for_target

INSTANCE = SERVICES["productos"][0]
PORT = SERVICES["productos"][2]
MODULES = ("webpay_host", "clp_inventory_host", "clp_productos_host")
MODES = ("prepare", "status", "apply", "verify", "recover")
LOADER = """
import gzip, json, sys, types
for name, source in json.loads(gzip.decompress(sys.stdin.buffer.read())):
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, name + ".py", "exec"), module.__dict__)
sys.exit(module.main(sys.argv[1:]))
""".strip()


def request(mode, address="127.0.0.1"):
    if mode not in MODES:
        raise ValueError("Modo de Productos no admitido")
    source = Path(__file__).parent
    address = str(IPv4Address(address))
    scripts = [(name, (source / (name + ".py")).read_text(encoding="utf-8")) for name in MODULES]
    bundle = base64.b64encode(gzip.compress(json.dumps(scripts).encode(), mtime=0)).decode()
    commands = ["exec bash -s <<'PEDIDOS360_CLP'", "set -euo pipefail", "umask 077", "{"]
    commands.extend(f"printf %s '{bundle[i:i + 2000]}'" for i in range(0, len(bundle), 2000))
    commands += [f"}} | base64 -d | python3 -c {shlex.quote(LOADER)} {mode} {address}", "PEDIDOS360_CLP"]
    return {
        "DocumentName": "AWS-RunShellScript",
        "InstanceIds": [INSTANCE],
        "Comment": f"Pedidos360 Productos CLP {mode}",
        "TimeoutSeconds": 90,
        "Parameters": {"commands": commands, "executionTimeout": ["540" if mode == "apply" else "180"]},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in MODES:
        modes.add_argument(f"--{mode}", dest="mode", action="store_const", const=mode)
    args = parser.parse_args()
    try:
        if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
            raise RolloutError(f"La sesión AWS debe corresponder a la cuenta {ACCOUNT}.")
        if args.mode in {"apply", "verify"}:
            arn, target_id, interval = resolve_target(None, instance=INSTANCE, port=PORT)
            if args.mode == "apply" and target_state(arn, target_id, True, port=PORT) != "healthy":
                raise RolloutError("El Target Group de Productos debe estar healthy antes del cambio.")
            print(f"Target Group de Productos: {arn}", flush=True)
        address = private_ip(INSTANCE) if args.mode != "prepare" else "127.0.0.1"
        run_ssm(request(args.mode, address), INSTANCE, timeout=600 if args.mode == "apply" else 240,
                failure="SSM no completó la operación de Productos. Revise --status y el Command ID.")
        if args.mode in {"apply", "verify"}:
            wait_for_target(arn, target_id, interval, port=PORT)
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
