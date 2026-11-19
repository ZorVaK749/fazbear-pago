#!/usr/bin/env python3
"""Plan, apply and verify the browser CORS policy for the EV3 HTTP API."""

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from webpay import ACCOUNT, REGION, RolloutError, aws
from webpay_host import NoRedirect

API_ID = "uuzifgcyd2"
STAGE = "ev3"
ORIGIN = "https://p5gsy16utd.execute-api.us-east-1.amazonaws.com"
BASE = f"https://{API_ID}.execute-api.{REGION}.amazonaws.com/{STAGE}/api"
AUTH = ("authorization",)
JSON_AUTH = (*AUTH, "content-type")
IDEMPOTENT = (*JSON_AUTH, "idempotency-key")
PROBES = (
    ("/pagos/webpay/capacidad", "GET", AUTH),
    ("/pagos/webpay", "POST", IDEMPOTENT),
    ("/pagos/webpay/retorno", "POST", JSON_AUTH),
    ("/orden/cotizaciones", "POST", IDEMPOTENT),
    ("/orden/confirmar-pago", "POST", IDEMPOTENT),
)


def desired_policy(current):
    desired = dict(current)
    required = {"AllowOrigins": [ORIGIN], "AllowMethods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                "AllowHeaders": list(IDEMPOTENT)}
    for setting, required_items in required.items():
        items = list(desired.get(setting, []))
        existing = {item.casefold() if setting == "AllowHeaders" else item for item in items}
        items.extend(item for item in required_items if item not in existing)
        desired[setting] = items
    return desired


def exchange(path, method, headers):
    try:
        request = Request(BASE + path, method=method, headers=headers)
        with build_opener(NoRedirect()).open(request, timeout=8) as response:
            return response.status, response.headers
    except HTTPError as error:
        with error:
            return error.code, error.headers
    except (URLError, TimeoutError):
        raise RolloutError("No se pudo consultar el Gateway público de EV3.") from None


def header_set(headers, key):
    return {value.strip().lower() for value in headers.get(key, "").split(",")}


def verify():
    for path, method, requested in PROBES:
        status, headers = exchange(path, "OPTIONS", {
            "Origin": ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": ",".join(requested),
        })
        allowed_origin = headers.get("Access-Control-Allow-Origin")
        credentials = headers.get("Access-Control-Allow-Credentials", "").lower() == "true"
        methods = header_set(headers, "Access-Control-Allow-Methods")
        allowed_headers = header_set(headers, "Access-Control-Allow-Headers")
        if (not 200 <= status < 300 or (allowed_origin != ORIGIN and (allowed_origin != "*" or credentials))
                or not {method.lower(), "*"}.intersection(methods)
                or not set(requested).issubset(allowed_headers)):
            raise RolloutError(f"CORS pendiente en {method} {path}. El OPTIONS respondió HTTP {status}.")
    status, _ = exchange("/pagos/webpay/capacidad", "GET", {"Origin": ORIGIN})
    if status != 401:
        raise RolloutError(f"La ruta de capacidad debería devolver 401 sin JWT. Recibió HTTP {status}.")


def wait_for_cors():
    deadline = time.monotonic() + 85
    while True:
        try:
            verify()
            return
        except RolloutError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(5)


def execute(mode):
    if mode == "verify":
        verify()
        print("CORS válido en las cinco rutas y capacidad protegida con JWT.")
        return
    if aws("sts", "get-caller-identity").get("Account") != ACCOUNT:
        raise RolloutError(f"La sesión AWS debe corresponder a la cuenta {ACCOUNT}.")
    api = aws("apigatewayv2", "get-api", "--api-id", API_ID)
    stage = aws("apigatewayv2", "get-stage", "--api-id", API_ID, "--stage-name", STAGE)
    if api["ProtocolType"] != "HTTP":
        raise RolloutError("El API configurado debe ser un HTTP API.")
    current = api.get("CorsConfiguration") or {}
    target = desired_policy(current)
    print(f"HTTP API {API_ID} · stage {STAGE} · AutoDeploy={stage.get('AutoDeploy', False)}")
    print("Política CORS propuesta:")
    print(json.dumps(target, indent=2))
    if mode == "dry-run":
        return
    if current != target:
        if not stage.get("AutoDeploy"):
            raise RolloutError("El stage usa despliegue manual. Revise los cambios pendientes antes de publicar.")
        aws("apigatewayv2", "update-api", "--api-id", API_ID, "--cors-configuration", json.dumps(target))
    wait_for_cors()
    print("CORS válido en las cinco rutas y capacidad protegida con JWT.")


def main():
    parser = argparse.ArgumentParser(description="CORS de checkout Webpay en API Gateway EV3")
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("dry-run", "apply", "verify"):
        modes.add_argument("--" + mode, dest="mode", action="store_const", const=mode)
    try:
        execute(parser.parse_args().mode)
    except (RolloutError, KeyError, TypeError, ValueError) as error:
        message = str(error) if isinstance(error, RolloutError) else "AWS devolvió una configuración inesperada."
        print(f"ERROR: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
