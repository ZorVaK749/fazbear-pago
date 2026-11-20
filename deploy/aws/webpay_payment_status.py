#!/usr/bin/env python3
"""Diagnóstico de solo lectura para un intento de Webpay y su cotización."""

import argparse
import json
import sys
from uuid import UUID

from clp_inventory import SERVICES
from clp_productos import python_request
from webpay import ACCOUNT, INSTANCE, RolloutError, aws, run_ssm

MODULES = ("webpay_host", "clp_inventory_host", "webpay_payment_status_host")


def inspect(instance, mode, *ids):
    request = python_request(instance, f"Pedidos360 consulta Webpay {mode}", MODULES, (mode, *ids), 60)
    return run_ssm(request, instance, timeout=115, failure=f"Consulta incompleta en {mode}. Revise el Command ID.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payment-id", type=UUID, required=True)
    args = parser.parse_args()
    try:
        if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
            raise RolloutError("La sesión debe corresponder al laboratorio de EV3.")
        payment_id = str(args.payment_id)
        result = json.loads(inspect(INSTANCE, "pago", payment_id))
        inspect(SERVICES["orden"][0], "orden", str(UUID(result["operacion"])), payment_id)
    except (RolloutError, KeyError, ValueError) as error:
        print(f"ERROR: {error}" if isinstance(error, RolloutError) else "ERROR: respuesta de auditoría inválida.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
