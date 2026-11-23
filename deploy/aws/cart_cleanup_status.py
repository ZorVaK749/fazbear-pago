#!/usr/bin/env python3
"""Read the EV3 cart route and its access logs without modifying AWS."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import re
import sys

from webpay import ACCOUNT, REGION, RolloutError, aws
from webpay_cors import API_ID, STAGE

EXACT_ROUTE = "DELETE /api/carrito/{usuarioId}/items/comprados"
ITEM_ROUTE = re.compile(r"DELETE /api/carrito/\{[^}/]+\}/items/\{[^}/]+\}")
LOG_ARN_PREFIX = f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:"


def observed_responses(events, fields):
    for item in events:
        try:
            row = json.loads(item["message"])
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(row, dict):
            continue
        path = row.get(fields["$context.path"])
        if not isinstance(path, str) or not path.partition("?")[0].endswith("/items/comprados"):
            continue
        method = row.get(fields.get("$context.httpMethod", ""))
        if method not in {"DELETE", "OPTIONS"}:
            continue
        status = str(row.get(fields["$context.status"]))
        if not re.fullmatch(r"[1-5][0-9]{2}", status):
            continue
        when = datetime.fromtimestamp(item["timestamp"] / 1000, timezone.utc).isoformat(timespec="seconds")
        yield {"hora_utc": when, "metodo": method, "http": int(status)}


def inspect(at):
    if aws("sts", "get-caller-identity").get("Account") != ACCOUNT:
        raise RolloutError("Use la sesión de CloudShell del laboratorio EV3.")

    routes = aws("apigatewayv2", "get-routes", "--api-id", API_ID)["Items"]
    route = next((r for r in routes if r["RouteKey"] == EXACT_ROUTE), None)
    route = route or next((r for r in routes if ITEM_ROUTE.fullmatch(r["RouteKey"])), None)
    if route:
        print(f"Ruta de limpieza: {route['RouteKey']} · autorización {route['AuthorizationType']}")
        target = route.get("Target", "")
        if re.fullmatch(r"integrations/[a-z0-9]+", target):
            integration = aws("apigatewayv2", "get-integration", "--api-id", API_ID,
                              "--integration-id", target.split("/")[1])
            params = integration.get("RequestParameters") or {}
            if params.get("overwrite:path") not in (None, "$request.path"):
                print("La integración aplica una reescritura personalizada de la ruta.")
            if any(key in params for key in ("overwrite:querystring.revision", "remove:querystring.revision")):
                print("La integración modifica el parámetro revision.")
    else:
        print("No se encontró una ruta explícita de limpieza o eliminación por ítem.")

    stage = aws("apigatewayv2", "get-stage", "--api-id", API_ID, "--stage-name", STAGE)
    logs = stage.get("AccessLogSettings") or {}
    arn = logs.get("DestinationArn", "")
    if not arn.startswith(LOG_ARN_PREFIX):
        print("El stage ev3 no tiene un grupo local de registros de acceso configurado.")
        return
    try:
        fields = {value: key for key, value in json.loads(logs.get("Format", "")).items()
                  if isinstance(value, str)}
    except (AttributeError, TypeError, ValueError):
        fields = {}
    if not {"$context.path", "$context.httpMethod", "$context.status"}.issubset(fields):
        print("El registro configurado no identifica la ruta, el método y el estado HTTP de cada solicitud.")
        return

    group = arn.removeprefix(LOG_ARN_PREFIX).removesuffix(":*")
    start = int((at - timedelta(minutes=2)).timestamp() * 1000)
    end = int((at + timedelta(minutes=5)).timestamp() * 1000)
    output = aws("logs", "filter-log-events", "--log-group-name", group,
                 "--start-time", str(start), "--end-time", str(end), "--filter-pattern", '"comprados"')
    found = list(observed_responses(output["events"], fields))
    if found:
        for event in found:
            print(json.dumps(event, ensure_ascii=False))
    else:
        print("No se registró una solicitud de limpieza en ese horario.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", required=True, type=datetime.fromisoformat,
                        help="Hora de la compra en ISO 8601, con zona horaria")
    args = parser.parse_args()
    if args.at.utcoffset() is None:
        parser.error("--at requiere una zona horaria, por ejemplo -03:00.")
    try:
        inspect(args.at)
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
