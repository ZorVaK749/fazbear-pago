#!/usr/bin/env python3
"""Preparar y comprobar el stage ev3 del Gateway de Angular."""

import argparse
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from frontend_image import ORIGIN, fetch, verify_checkout
from webpay import ACCOUNT, RolloutError, aws

API = "p5gsy16utd"
STAGE = "ev3"
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


def verify_named_stage():
    routes, stages, target = inventory()
    if not stages.get(STAGE, {}).get("DeploymentId") or missing_routes(routes, target):
        raise RolloutError("El Gateway todavía no tiene un despliegue ev3 con las rutas explícitas.")
    prefix = "/" + STAGE
    for path in ("/", "/login", "/catalogo", "/perfil", "/checkout/webpay", "/actividad"):
        html = fetch(prefix + path)
        if "<app-root" not in html or "/ev3/" not in html:
            raise RolloutError(f"{prefix}{path} no sirve la imagen Angular preparada para el stage.")
    verify_checkout(prefix)
    verify_post_return(prefix)
    print(f"Stage {STAGE} · páginas Angular, módulos de checkout y retorno POST de Webpay verificados por HTTPS.")


def wait_for_stage(timeout=75):
    deadline = time.monotonic() + timeout
    while True:
        try:
            verify_named_stage()
            return
        except RolloutError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(5)


def execute(mode):
    if mode == "verify":
        verify_named_stage()
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
    for mode in ("dry-run", "prepare", "verify"):
        group.add_argument("--" + mode, dest="mode", action="store_const", const=mode)
    try:
        execute(parser.parse_args().mode)
    except (RolloutError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}" if isinstance(error, RolloutError) else
              "ERROR: El Gateway devolvió una configuración inesperada.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
