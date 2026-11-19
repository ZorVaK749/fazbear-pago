#!/usr/bin/env python3
"""Prepare and verify the mounted H2 catalog on the existing Productos EC2."""

import argparse
import base64
import gzip
import json
from pathlib import Path
import shlex
import sys

from clp_inventory import SERVICES
from webpay import ACCOUNT, RolloutError, aws, run_ssm

INSTANCE = SERVICES["productos"][0]
MODULES = ("webpay_host", "clp_inventory_host", "clp_productos_host")
LOADER = """
import gzip, json, sys, types
for name, source in json.loads(gzip.decompress(sys.stdin.buffer.read())):
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, name + ".py", "exec"), module.__dict__)
sys.exit(module.main(sys.argv[1:]))
""".strip()


def request(mode):
    if mode not in {"prepare", "status"}:
        raise ValueError("Modo de Productos no admitido")
    source = Path(__file__).parent
    scripts = [(name, (source / (name + ".py")).read_text(encoding="utf-8")) for name in MODULES]
    bundle = base64.b64encode(gzip.compress(json.dumps(scripts).encode(), mtime=0)).decode()
    commands = ["exec bash -s <<'PEDIDOS360_CLP'", "set -euo pipefail", "umask 077", "{"]
    commands.extend(f"printf %s '{bundle[i:i + 2000]}'" for i in range(0, len(bundle), 2000))
    commands += [f"}} | base64 -d | python3 -c {shlex.quote(LOADER)} {mode}", "PEDIDOS360_CLP"]
    return {
        "DocumentName": "AWS-RunShellScript",
        "InstanceIds": [INSTANCE],
        "Comment": f"Pedidos360 Productos CLP {mode}",
        "TimeoutSeconds": 90,
        "Parameters": {"commands": commands, "executionTimeout": ["180"]},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", dest="mode", action="store_const", const="prepare")
    modes.add_argument("--status", dest="mode", action="store_const", const="status")
    args = parser.parse_args()
    try:
        if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
            raise RolloutError(f"La sesión AWS debe corresponder a la cuenta {ACCOUNT}.")
        run_ssm(request(args.mode), INSTANCE, timeout=240,
                failure="SSM no completó la preparación de Productos. Revise --status y el Command ID.")
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
