#!/usr/bin/env python3
"""Preparar el Gateway de Angular y retirar o restaurar su acceso $default."""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from frontend_image import ORIGIN, fetch, verify_checkout
from webpay import ACCOUNT, INSTANCE, RolloutError, aws
from webpay_payment_status import inspect as inspect_payments

API = "p5gsy16utd"
STAGE = "ev3"
DEFAULT = "$default"
BACKUP = Path.home() / "pedidos360-frontend-default.json"
CREATE_STAGE_KEYS = {
    "StageName", "AccessLogSettings", "AutoDeploy", "DefaultRouteSettings", "DeploymentId",
    "Description", "RouteSettings", "StageVariables", "Tags",
}
CREATE_ROUTE_KEYS = {"RouteKey", "Target", "AuthorizationType", "OperationName"}
ROUTES = (
    "GET /", "GET /login", "GET /catalogo", "GET /pedidos", "GET /perfil",
    "GET /reportes", "GET /checkout", "GET /checkout/webpay", "GET /actividad",
    "GET /{archivo}", "POST /checkout/webpay",
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify_post_return(prefix):
    request = Request(ORIGIN + prefix + "/checkout/webpay", data=b"TBK_TOKEN=synthetic-probe",
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=8):
            pass
    except HTTPError as error:
        with error:
            if error.code == 303 and error.headers.get("Location") == "webpay#TBK_TOKEN=synthetic-probe":
                return
            raise RolloutError(f"El retorno POST de Webpay en {prefix} respondió HTTP {error.code} sin la redirección esperada.") from None
    except (URLError, TimeoutError):
        raise RolloutError(f"No se pudo comprobar el retorno POST de Webpay en {prefix}.") from None
    raise RolloutError(f"El retorno POST de Webpay en {prefix} no devolvió HTTP 303.")


def inventory():
    if aws("sts", "get-caller-identity").get("Account") != ACCOUNT:
        raise RolloutError("La sesión debe corresponder a la cuenta de EV3.")
    api = aws("apigatewayv2", "get-api", "--api-id", API)
    if api.get("ProtocolType") != "HTTP" or api.get("Name") != "fazbear-frontend-http":
        raise RolloutError("El destino no coincide con el Gateway HTTP del frontend.")
    routes = {route["RouteKey"]: route for route in aws("apigatewayv2", "get-routes", "--api-id", API)["Items"]}
    stages = {stage["StageName"]: stage for stage in aws("apigatewayv2", "get-stages", "--api-id", API)["Items"]}
    source = routes.get("$default") or routes.get("GET /") or {}
    target = source.get("Target", "")
    if source.get("AuthorizationType") != "NONE" or not re.fullmatch(r"integrations/[a-z0-9]+", target):
        raise RolloutError("No se pudo verificar la integración pública actual de Angular.")
    integration = aws("apigatewayv2", "get-integration", "--api-id", API,
                      "--integration-id", target.split("/")[1])
    if integration.get("IntegrationType") != "HTTP_PROXY":
        raise RolloutError("La integración de Angular no es un proxy HTTP.")
    return routes, stages, target


def missing_routes(routes, target):
    missing = []
    for key in ROUTES:
        route = routes.get(key)
        if route is None:
            missing.append(key)
        elif route.get("Target") != target or route.get("AuthorizationType") != "NONE":
            raise RolloutError(f"{key} ya existe con una integración o autorización diferente.")
    return missing


def verify_named_stage(retired=False):
    routes, stages, target = inventory()
    if not stages.get(STAGE, {}).get("DeploymentId") or missing_routes(routes, target):
        raise RolloutError("El Gateway todavía no tiene un despliegue ev3 con las rutas explícitas.")
    if retired and (DEFAULT in routes or DEFAULT in stages):
        raise RolloutError("API Gateway todavía muestra la ruta o el stage $default.")
    prefix = "/" + STAGE
    for path in ("/", "/login", "/catalogo", "/perfil", "/checkout/webpay", "/actividad"):
        html = fetch(prefix + path)
        if "<app-root" not in html or "/ev3/" not in html:
            raise RolloutError(f"{prefix}{path} no sirve la imagen Angular preparada para el stage.")
    verify_checkout(prefix)
    verify_post_return(prefix)
    if retired:
        expect_not_found("/")
        expect_not_found(prefix + "/_verificacion/ruta-inexistente")
    print(f"Stage {STAGE} · páginas Angular, módulos de checkout y retorno POST de Webpay verificados por HTTPS.")


def expect_not_found(path):
    try:
        with build_opener(NoRedirect()).open(Request(ORIGIN + path, headers={"Cache-Control": "no-cache"}), timeout=8):
            pass
    except HTTPError as error:
        with error:
            if error.code == 404:
                return
    except (URLError, TimeoutError):
        pass
    raise RolloutError(f"La URL {path} aún no respondió HTTP 404.")


def wait_for_stage(timeout=75, *, retired=False, restored=False):
    deadline = time.monotonic() + timeout
    while True:
        try:
            verify_named_stage(retired)
            if restored and "<app-root" not in fetch("/"):
                raise RolloutError("La raíz del Gateway todavía no sirve Angular.")
            return
        except RolloutError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(5)


def read_backup(path, target):
    with path.open(encoding="utf-8") as stream:
        backup = json.load(stream)
    if not isinstance(backup, dict):
        raise RolloutError("El respaldo de $default tiene un formato inválido.")
    route = backup.get("route")
    stage = backup.get("stage")
    if (backup.get("account") != ACCOUNT or backup.get("api") != API or backup.get("target") != target
            or (route is not None and not isinstance(route, dict))
            or (stage is not None and not isinstance(stage, dict))
            or (route and (route.get("RouteKey") != DEFAULT or route.get("Target") != target
                           or route.get("AuthorizationType") != "NONE"))
            or (stage and stage.get("StageName") != DEFAULT)):
        raise RolloutError("El respaldo no corresponde a la configuración original de este frontend.")
    return backup


def retire_default(path):
    verify_named_stage()
    routes, stages, target = inventory()
    route, stage = routes.get(DEFAULT), stages.get(DEFAULT)
    if not route and not stage:
        wait_for_stage(retired=True)
        print("La ruta y el stage $default ya están retirados.")
        return
    if route and not stages[STAGE].get("AutoDeploy"):
        raise RolloutError("El stage ev3 requiere un despliegue manual tras el cambio de rutas.")
    pending = json.loads(inspect_payments(INSTANCE, "pendientes-webpay"))["total_sin_estado_final"]
    if type(pending) is not int or pending != 0:
        raise RolloutError("Quedan intentos Webpay sin estado final. Se detuvo el retiro.")

    if path.exists():
        backup = read_backup(path, target)
        if (route and route != backup.get("route")) or (stage and stage != backup.get("stage")):
            raise RolloutError("El respaldo existente difiere del Gateway. Use otro archivo si inicia un retiro nuevo.")
    else:
        backup = {"account": ACCOUNT, "api": API, "target": target, "route": route, "stage": stage}
        with open(path, "x", encoding="utf-8", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            json.dump(backup, stream, indent=2)
    print(f"Respaldo de $default: {path}", flush=True)

    if stage:
        aws("apigatewayv2", "delete-stage", "--api-id", API, "--stage-name", DEFAULT)
    if route:
        aws("apigatewayv2", "delete-route", "--api-id", API, "--route-id", route["RouteId"])
    wait_for_stage(retired=True)
    print("Ruta y stage $default retirados. El acceso público está en /ev3/.")


def restore_default(path):
    routes, stages, target = inventory()
    backup = read_backup(path, target)
    route, stage = backup.get("route"), backup.get("stage")
    if route and DEFAULT not in routes:
        payload = {key: value for key, value in route.items() if key in CREATE_ROUTE_KEYS}
        aws("apigatewayv2", "create-route", input_json={"ApiId": API, **payload})
    if stage and DEFAULT not in stages:
        payload = {key: value for key, value in stage.items() if key in CREATE_STAGE_KEYS}
        if payload.get("AutoDeploy"):
            payload.pop("DeploymentId", None)
        aws("apigatewayv2", "create-stage", input_json={"ApiId": API, **payload})
    wait_for_stage(restored=bool(route and stage))
    print("Configuración de $default restaurada.")


def execute(mode, backup=BACKUP):
    if mode == "verify":
        verify_named_stage()
        return
    if mode == "retire-default":
        retire_default(backup)
        return
    if mode == "restore-default":
        restore_default(backup)
        return
    routes, stages, target = inventory()
    missing = missing_routes(routes, target)
    print(f"Frontend {API} · stages: {', '.join(sorted(stages)) or 'ninguno'} · integración: {target}")
    print(f"Ruta $default: {'presente' if '$default' in routes else 'ausente'}")
    print(f"Rutas explícitas por crear: {', '.join(missing) or 'ninguna'}", flush=True)
    if mode == "dry-run":
        return
    if STAGE in stages and not stages[STAGE].get("AutoDeploy"):
        raise RolloutError("El stage ev3 existente usa despliegue manual. Revise su configuración antes del cambio.")
    for key in missing:
        aws("apigatewayv2", "create-route", "--api-id", API, "--route-key", key,
            "--target", target, "--authorization-type", "NONE")
    if STAGE not in stages:
        aws("apigatewayv2", "create-stage", "--api-id", API, "--stage-name", STAGE, "--auto-deploy")
    wait_for_stage()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for mode in ("dry-run", "prepare", "verify", "retire-default", "restore-default"):
        group.add_argument("--" + mode, dest="mode", action="store_const", const=mode)
    parser.add_argument("--backup", type=Path, default=BACKUP, help="Archivo de respaldo privado de $default")
    args = parser.parse_args()
    try:
        execute(args.mode, args.backup)
    except (RolloutError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}" if isinstance(error, RolloutError) else
              "ERROR: El Gateway devolvió una configuración inesperada.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
