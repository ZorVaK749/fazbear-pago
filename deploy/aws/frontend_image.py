#!/usr/bin/env python3
"""Roll out an approved Angular image to the existing EV3 Fargate service."""

import argparse
import re
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from webpay import ACCOUNT, RolloutError, aws

FAMILY = "pedidos360-ev3-frontend-fg"
PACKAGE = "ghcr.io/zorvak749/fazbears-frontend"
IMAGE_DIGEST = re.compile(re.escape(PACKAGE) + r"@sha256:[a-f0-9]{64}")
ORIGIN = "https://p5gsy16utd.execute-api.us-east-1.amazonaws.com"
REGISTER_KEYS = {
    "family", "taskRoleArn", "executionRoleArn", "networkMode", "containerDefinitions", "volumes",
    "placementConstraints", "requiresCompatibilities", "cpu", "memory", "pidMode", "ipcMode",
    "proxyConfiguration", "inferenceAccelerators", "ephemeralStorage", "runtimePlatform",
    "enableFaultInjection",
}


def find_service():
    matches = []
    for cluster in aws("ecs", "list-clusters")["clusterArns"]:
        arns = aws("ecs", "list-services", "--cluster", cluster)["serviceArns"]
        for page in range(0, len(arns), 10):
            services = aws("ecs", "describe-services", "--cluster", cluster, "--services", *arns[page:page + 10])
            if services.get("failures"):
                raise RolloutError("El inventario de servicios ECS está incompleto.")
            for service in services["services"]:
                family = service["taskDefinition"].rsplit("/", 1)[-1].split(":", 1)[0]
                if service["status"] == "ACTIVE" and family == FAMILY:
                    matches.append((cluster, service))
    if len(matches) != 1:
        raise RolloutError(f"Se requiere un único servicio ECS activo con la familia {FAMILY}.")
    return matches[0]


def registration(described, image):
    task = described["taskDefinition"]
    if task["family"] != FAMILY or "FARGATE" not in task["requiresCompatibilities"]:
        raise RolloutError("La revisión no corresponde al frontend Fargate de EV3.")
    config = {key: value for key, value in task.items() if key in REGISTER_KEYS}
    originals = task["containerDefinitions"]
    targets = [c for c in originals if c["image"] == PACKAGE or c["image"].startswith((PACKAGE + "@", PACKAGE + ":"))]
    if len(targets) != 1:
        raise RolloutError("La revisión debe contener un único contenedor de Angular del registro esperado.")
    target = targets[0]
    config["containerDefinitions"] = [dict(c, image=image) if c is target else c for c in originals]
    tags = [tag for tag in described.get("tags", []) if not tag["key"].startswith("aws:")]
    if tags:
        config["tags"] = tags
    return config, target["image"]


def wait_stable(cluster, service, arn):
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        result = aws("ecs", "describe-services", "--cluster", cluster, "--services", service)
        current = result["services"][0]
        deployments = current["deployments"]
        if current["taskDefinition"] != arn or any(
                d.get("rolloutState") == "FAILED" and d["taskDefinition"] == arn for d in deployments):
            raise RolloutError("ECS no mantuvo la revisión solicitada. Revise el estado del servicio.")
        if (len(deployments) == 1 and current["runningCount"] == current["desiredCount"] > 0
                and deployments[0].get("rolloutState", "COMPLETED") == "COMPLETED"):
            return
        time.sleep(10)
    raise RolloutError("ECS todavía no confirmó un frontend estable.")


def fetch(path):
    try:
        request = Request(ORIGIN + path, headers={"Cache-Control": "no-cache"})
        with urlopen(request, timeout=8) as response:
            return response.read(6 * 1024 * 1024).decode()
    except (URLError, TimeoutError, UnicodeError):
        raise RolloutError("El frontend público no respondió con su aplicación Angular.") from None


def verify_checkout():
    index = fetch("/checkout")
    main = re.search(r'src="(main-[A-Za-z0-9_-]+\.js)"', index)
    if not main:
        raise RolloutError("El frontend no entregó el archivo principal de Angular.")
    entry = fetch("/" + main.group(1))
    chunk = re.search(r"""import\(['"`]\./(chunk-[A-Za-z0-9_-]+\.js)['"`]\)\.then\([^)]*?\.CheckoutComponent\)""", entry)
    if not chunk or "btn-webpay" not in fetch("/" + chunk.group(1)):
        raise RolloutError("El frontend público todavía no sirve el checkout con el botón Webpay.")


def execute(mode, image):
    if aws("sts", "get-caller-identity").get("Account") != ACCOUNT:
        raise RolloutError(f"La sesión AWS debe corresponder a la cuenta {ACCOUNT}.")
    cluster, service = find_service()
    service_name = service["serviceArn"]
    current = service["taskDefinition"]
    task = aws("ecs", "describe-task-definition", "--task-definition", current, "--include", "TAGS")
    config, original = registration(task, image)
    print(f"Servicio: {service_name}\nRevisión actual: {current}\nImagen actual: {original}\nImagen solicitada: {image}", flush=True)
    if mode == "dry-run":
        return
    if mode == "verify" and original != image:
        raise RolloutError("La revisión activa de Fargate usa un digest distinto del solicitado.")
    if mode == "apply" and (service.get("deploymentController", {}).get("type", "ECS") != "ECS"
                            or len(service["deployments"]) != 1):
        raise RolloutError("El servicio tiene un despliegue en curso o usa un controlador distinto de ECS.")
    new = current
    if mode == "apply" and original != image:
        new = aws("ecs", "register-task-definition", input_json=config)["taskDefinition"]["taskDefinitionArn"]
        print(f"Revisión registrada: {new}", flush=True)
        aws("ecs", "update-service", "--cluster", cluster, "--service", service_name, "--task-definition", new)
    wait_stable(cluster, service_name, new)
    verify_checkout()
    print("Frontend Fargate estable. El checkout público sirve el botón Webpay.")


def main():
    parser = argparse.ArgumentParser(description="Actualizar la imagen del frontend Fargate EV3")
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("dry-run", "apply", "verify"):
        modes.add_argument("--" + mode, dest="mode", action="store_const", const=mode)
    parser.add_argument("--image")
    args = parser.parse_args()
    if (args.image is None and args.mode != "verify") or (
            args.image is not None and not IMAGE_DIGEST.fullmatch(args.image)):
        parser.error("--image requiere una referencia al paquete Angular por digest GHCR")
    try:
        if args.mode == "verify" and args.image is None:
            verify_checkout()
            print("El checkout público sirve el botón Webpay.")
        else:
            execute(args.mode, args.image)
    except (RolloutError, KeyError, IndexError, TypeError, ValueError) as error:
        message = str(error) if isinstance(error, RolloutError) else "ECS devolvió una respuesta inesperada."
        print(f"ERROR: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
