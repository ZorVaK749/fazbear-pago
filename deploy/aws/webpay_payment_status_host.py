"""Read sandbox Webpay and simulated antifraud evidence without modifying it."""

from decimal import Decimal
import json
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID

from clp_inventory_host import target
from webpay_host import CONTAINER, IMAGE, Host, NoRedirect, RolloutError, env_values, postgres_env, run

PROVIDER_URL = "https://webpay3gint.transbank.cl/rswebpaytransaction/api/webpay/v1.2/transactions/"
PROVIDER_STATES = {"INITIALIZED", "AUTHORIZED", "REVERSED", "FAILED", "NULLIFIED", "PARTIALLY_NULLIFIED", "CAPTURED"}


def read_row(lines, sql, *, prefix="PAGO"):
    environment = postgres_env(lines, prefix=prefix)
    value = run(["psql", "-X", "-w", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", sql],
                f"No se pudo consultar PostgreSQL de {prefix} en modo de solo lectura.", env=environment, timeout=12)
    return json.loads(value) if value.strip() else None


def read_provider(row, configuration):
    token = row["token"]
    commerce = configuration.get("WEBPAY_COMMERCE_CODE", "")
    key = configuration.get("WEBPAY_API_KEY", "")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9]{20,128}", token):
        return {"consulta": "sin referencia Transbank válida"}
    if not re.fullmatch(r"[0-9]{12}", commerce) or not key:
        return {"consulta": "credenciales de integración ausentes"}
    request = Request(PROVIDER_URL + token, headers={"Tbk-Api-Key-Id": commerce, "Tbk-Api-Key-Secret": key})
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=6) as response:
            result = json.loads(response.read(8192), parse_float=Decimal)
        if not isinstance(result, dict):
            return {"consulta": "respuesta inesperada"}
        amount = result.get("amount")
        state = result.get("status")
        code = result.get("response_code")
        matched = (type(amount) in (int, Decimal) and Decimal(str(row["importe"])) == amount
                   and row["orden"] == result.get("buy_order") and row["sesion"] == result.get("session_id"))
        return {"consulta": "HTTP 200", "estado": state if isinstance(state, str) and state in PROVIDER_STATES else "desconocido",
                "codigo": code if type(code) is int else None, "referencias_validas": matched}
    except HTTPError as error:
        with error:
            return {"consulta": f"HTTP {error.code}"}
    except (URLError, OSError, ValueError):
        return {"consulta": "Transbank no disponible"}


def payment_env():
    pago = Host().inspect(CONTAINER)
    if not pago["State"]["Running"] or not pago["Config"]["Image"].startswith(IMAGE.split("@", 1)[0] + "@sha256:"):
        raise RolloutError("Se requiere el contenedor oficial de Pago en ejecución.")
    return pago["Config"]["Env"]


def inspect_payment(payment_id):
    lines = payment_env()
    row = read_row(lines, f"""
        SELECT json_build_object('operacion', p.operation_id, 'estado', p.status, 'importe', p.amount,
            'retorno_registrado', w.browser_return_received, 'token', w.provider_token,
            'orden', w.buy_order, 'sesion', w.session_id)
        FROM payment p JOIN webpay_transaction w ON w.payment_id=p.id
        WHERE p.id='{payment_id}'::uuid AND NOT p.simulation;
        """)
    if row is None:
        raise RolloutError("No se encontró ese intento de Webpay en Pago.")
    summary = {key: row[key] for key in ("operacion", "estado", "importe", "retorno_registrado")}
    summary["transbank"] = read_provider(row, env_values(lines))
    print(json.dumps(summary), flush=True)


def inspect_antifraud(payment_id):
    result = read_row(payment_env(), f"""
        BEGIN READ ONLY;
        WITH referencia AS (
            SELECT id, tenant_id, owner_id, instrument_id, created_at
            FROM payment WHERE id='{payment_id}'::uuid AND simulation
        ), intentos AS (
            SELECT to_char(a.attempted_at AT TIME ZONE 'America/Santiago',
                           'YYYY-MM-DD HH24:MI:SS.MS') AS hora_santiago,
                   round(extract(epoch FROM a.attempted_at - r.created_at)::numeric, 3) AS segundos_desde_referencia,
                   p.status AS estado, p.id=r.id AS referencia, d.attempts_in_window AS intentos_en_ventana,
                   d.blocked AS bloqueado, f.attempt_id IS NOT NULL AS alerta_registrada
            FROM referencia r
            JOIN payment p USING (tenant_id, owner_id, instrument_id)
            JOIN payment_attempt a ON a.payment_id=p.id
            JOIN antifraud_decision d ON d.attempt_id=a.id
            LEFT JOIN fraud_alert f ON f.attempt_id=a.id
            WHERE p.simulation AND a.attempted_at BETWEEN r.created_at - interval '1 minute'
                                                     AND r.created_at + interval '1 minute'
            ORDER BY (p.id=r.id) DESC, a.attempted_at DESC LIMIT 16
        )
        SELECT json_build_object('intentos', json_agg(intentos ORDER BY segundos_desde_referencia))
        FROM intentos HAVING count(*) > 0;
        ROLLBACK;
        """)
    if result is None:
        raise RolloutError("No se encontró evidencia antifraude para ese pago simulado.")
    print(json.dumps(result), flush=True)


def inspect_order(operation_id, payment_id):
    orden = target("fazbear-orden", 8084)
    if not orden or not orden["Config"]["Image"].startswith("ghcr.io/zorvak749/fazbear-orden@sha256:"):
        raise RolloutError("Se requiere el contenedor oficial de Orden en ejecución.")
    result = read_row(orden["Config"]["Env"], f"""
        SELECT json_build_object('pedido', pedido_id, 'pago_asociado', pago_id='{payment_id}'::uuid)
        FROM checkout_quote WHERE id='{operation_id}'::uuid;
        """, prefix="ORDEN")
    print(json.dumps({"orden": result or "cotización no encontrada"}), flush=True)


def main(args):
    try:
        mode, *ids = args
        if mode == "pago" and len(ids) == 1:
            inspect_payment(UUID(ids[0]))
        elif mode == "antifraude" and len(ids) == 1:
            inspect_antifraud(UUID(ids[0]))
        elif mode == "orden" and len(ids) == 2:
            inspect_order(UUID(ids[0]), UUID(ids[1]))
        else:
            raise RolloutError("Modo de diagnóstico no admitido.")
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
        print("ERROR: respuesta inválida al consultar el intento.", file=sys.stderr)
        return 1
    return 0
