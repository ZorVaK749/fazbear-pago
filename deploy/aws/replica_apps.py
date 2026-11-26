#!/usr/bin/env python3
"""Install the EV3 applications and private data containers in the backup stack."""

import argparse
import base64
import gzip
from getpass import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener


REGISTRY = "ghcr.io/zorvak749/"
IMAGES = {
    "Productos": ("fazbears-productos", "b6738b92eb0372d30782154e2c709b3f162c2afe87d03a46be84a42ef1ddee37"),
    "Pedidos": ("fazbears-pedidos", "e425eb1c1bda1f078e478a146eb94eb2aa478227bac888e280240201e9f00281"),
    "Carrito": ("fazbear-carrito", "149b0394ccb03a7db9565bd760ef8406041ae398dd2cb30feb57b0bf1322cc66"),
    "Orden": ("fazbear-orden", "29c351c0208ee67fff3c496b39305af67a22d6769fcb3574899a712918204f87"),
    "Notificaciones": ("fazbear-notificaciones", "7338142218d895e20fd0710cea5e229e1de7b4ba5e03504032103a02cc7e72f8"),
    "Reportes": ("fazbear-reportes", "a874105db34f64563604049acdb772937016807d22164198c1477238fa234865"),
    "Pago": ("fazbear-pago", "2a4c4fca0fe4b6895e0308609fea76c545879fb271e030d83ad4e6a74136dd19"),
    "Analytics": ("fazbear-analytics-recommendations", "3d6a8cd2454a1a6af597b28f845bf87d089e0ec87430839c463422354529d87e"),
    "Fidelizacion": ("fazbear-fidelizacion", "627283e9b8b68869ecd9ec8498bdf9423e9ef68e13f9f7c052eff486bd33b2c0"),
}
DATABASES = ("productos", "orden", "pago", "analytics", "fidelizacion")
RABBIT_CLIENTS = ("Productos", "Orden", "Notificaciones", "Reportes")
VOLUMES = ("Carrito", "Pedidos", "Notificaciones", "Reportes")
CONTAINER_LABEL = "cl.pedidos360.replica"
CONFIG_LABEL = "cl.pedidos360.replica.config"
ROOT = Path("/etc/pedidos360-replica")
WEBPAY_TEST_COMMERCE = "597055555532"
WEBPAY_MODE = "SIMULATION_AND_WEBPAY_INTEGRATION"


def image_for(service):
    package, digest = IMAGES[service]
    return f"{REGISTRY}{package}@sha256:{digest}"


def application_configs(outputs, services, kafka_clients, region, parameter):
    urls = {name: f"http://{outputs[name + 'Ip']}:{spec[0]}" for name, spec in services.items()}
    extra = {
        "Productos": {"SPRING_PROFILES_ACTIVE": "ev3-local", "EV3_LOCAL_SEED": "true",
                      "EV3_LOCAL_CATALOG_SNAPSHOT": "true", "EV3_KAFKA_ENABLED": "true"},
        "Carrito": {"SPRING_PROFILES_ACTIVE": "ev3-aws", "PRODUCTOS_URL": urls["Productos"],
                    "EV3_KAFKA_ENABLED": "true"},
        "Pedidos": {"SPRING_PROFILES_ACTIVE": "ev3-aws"},
        "Orden": {"SPRING_PROFILES_ACTIVE": "ev3-aws", "PRODUCTOS_URL": urls["Productos"],
                  "PAGO_URL": urls["Pago"], "PEDIDOS_URL": urls["Pedidos"], "CARRITO_URL": urls["Carrito"]},
        "Pago": {"SPRING_PROFILES_ACTIVE": "ev3-aws", "ORDEN_URL": urls["Orden"],
                 "WEBPAY_RETURN_URL": outputs["WebpayReturn"]},
        "Fidelizacion": {"SPRING_PROFILES_ACTIVE": "ev3-aws", "PAGO_URL": urls["Pago"]},
    }
    configs = {}
    for name, (port, _, health, codes) in services.items():
        env = {"SPRING_H2_CONSOLE_ENABLED": "false",
               "JAVA_TOOL_OPTIONS": "-XX:+UseSerialGC -XX:ActiveProcessorCount=2 -Xms48m -Xmx270m",
               **extra.get(name, {})}
        db = name.lower()
        if db in DATABASES:
            env[f"{name.upper()}_DB_URL"] = f"jdbc:postgresql://{outputs['PagoIp']}:5432/{db}"
            env[f"{name.upper()}_DB_USER"] = db
        if name in kafka_clients:
            env["KAFKA_BOOTSTRAP_SERVERS"] = outputs["KafkaBootstrap"]
        if name in RABBIT_CLIENTS:
            env.update(RABBITMQ_HOST=outputs["NotificacionesIp"], RABBITMQ_PORT="5672", RABBITMQ_USER="pedidos360",
                       RABBITMQ_VHOST="/", SPRING_RABBITMQ_SSL_ENABLED="false")
        if name in ("Notificaciones", "Reportes"):
            env.update(SPRING_DATASOURCE_URL=f"jdbc:h2:file:/var/lib/fazbear/{db}/{db}db",
                       SPRING_JPA_HIBERNATE_DDL_AUTO="update")
        configs[name] = {"name": name, "host": outputs[f"{name}Ip"], "port": port,
                         "container_port": 8080 if name in ("Pago", "Orden", "Analytics", "Fidelizacion") else port,
                         "health": health, "allowed": [int(code) for code in codes.split(",")],
                         "image": image_for(name), "env": env, "region": region, "parameter": parameter}
    return configs


def checked(command, phase, *, data=None):
    result = subprocess.run(command, input=data, capture_output=True, text=True, timeout=270)
    if result.returncode:
        raise RuntimeError(f"{phase} falló (código {result.returncode}).")
    return result.stdout


def wait_until(probe, description, seconds=125):
    expiration = time.monotonic() + seconds
    while not probe():
        if time.monotonic() >= expiration:
            raise RuntimeError(f"Sin respuesta de {description} en {seconds} s.")
        time.sleep(3)


def start_container(name, image, env, options, *, image_ready=False):
    fingerprint = hashlib.sha256(json.dumps((image, env, options), sort_keys=True).encode()).hexdigest()
    current = subprocess.run(["docker", "inspect", "--type", "container", name], capture_output=True, text=True)
    if current.returncode == 0:
        instance = json.loads(current.stdout)[0]
        labels = instance["Config"].get("Labels") or {}
        if labels.get(CONTAINER_LABEL) != name or labels.get(CONFIG_LABEL) != fingerprint:
            raise RuntimeError(f"{name} ya existe con una configuración distinta.")
        if not instance["State"]["Running"]:
            checked(["docker", "start", name], f"Arranque de {name}")
        return
    if "No such" not in current.stderr:
        raise RuntimeError(f"Docker aún no responde en la EC2 de {name}.")
    if not image_ready:
        checked(["docker", "pull", image], f"Descarga de {image}")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=ROOT) as env_file:
        for key, value in env.items():
            if "\n" in value or "\r" in value:
                raise RuntimeError(f"El valor de {key} debe ocupar una sola línea.")
            env_file.write(f"{key}={value}\n")
        env_file.flush()
        checked(["docker", "run", "-d", "--name", name, "--restart", "unless-stopped", "--env-file", env_file.name,
                 "--log-opt", "max-size=8m", "--log-opt", "max-file=2", "--label", f"{CONTAINER_LABEL}={name}",
                 "--label", f"{CONFIG_LABEL}={fingerprint}", *options, image], f"Creación de {name}")


def ready_command(*args):
    return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12).returncode == 0


def postgres(host, credentials):
    name = "ev3-replica-postgres"
    env = {"POSTGRES_USER": "ev3admin", "POSTGRES_PASSWORD": credentials["pg_admin"], "POSTGRES_DB": "postgres"}
    start_container(name, "postgres:17.7-alpine", env,
                    ["--memory", "512m", "-p", f"{host}:5432:5432",
                     "-v", f"{name}:/var/lib/postgresql/data"])
    wait_until(lambda: ready_command("docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "ev3admin"),
               "PostgreSQL")
    sql = ["SELECT 1;"]
    for db in DATABASES:
        password = credentials[db]
        if len(password) != 48 or any(char not in "0123456789abcdef" for char in password):
            raise RuntimeError(f"La credencial generada para {db} tiene formato incorrecto.")
        sql.extend([f"SELECT 'CREATE ROLE {db} LOGIN PASSWORD ''{password}''' "
                    f"WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{db}')\n\\gexec",
                    f"SELECT 'CREATE DATABASE {db} OWNER {db}' "
                    f"WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{db}')\n\\gexec"])
    checked(["docker", "exec", "-i", name, "psql", "-U", "ev3admin", "-d", "postgres", "-v", "ON_ERROR_STOP=1"],
            "Creación de bases de la réplica", data="\n".join(sql) + "\n")
    print("PostgreSQL listo y bases verificadas.", flush=True)


def rabbit(host, credentials):
    name = "ev3-replica-rabbitmq"
    env = {"RABBITMQ_DEFAULT_USER": "pedidos360", "RABBITMQ_DEFAULT_PASS": credentials["rabbit"],
           "RABBITMQ_DEFAULT_VHOST": "/"}
    start_container(name, "rabbitmq:4.1-alpine", env,
                    ["--memory", "512m", "-p", f"{host}:5672:5672", "-v", f"{name}:/var/lib/rabbitmq",
                     "--hostname", name])
    wait_until(lambda: ready_command("docker", "exec", name, "rabbitmq-diagnostics", "-q", "check_port_connectivity"), "RabbitMQ")
    print("RabbitMQ listo.", flush=True)


def cors_proxy(host, backend_dns, frontend_origin):
    if not re.fullmatch(r"[A-Za-z0-9-]+\.(?:us-east-1\.elb|elb\.us-east-1)\.amazonaws\.com", backend_dns):
        raise RuntimeError("El DNS del balanceador de la réplica no tiene el formato esperado.")
    nginx = ROOT / "cors-proxy.conf"
    nginx.write_text(f"""
server {{
    listen 8080;
    access_log off;
    resolver 127.0.0.11 ipv6=off valid=30s;
    location = /health {{ return 200 'UP'; }}
    location /api/ {{
        if ($request_method = OPTIONS) {{ return 204; }}
        proxy_set_header Origin "";
        proxy_set_header Authorization $http_authorization;
        proxy_set_header X-Service-Key "";
        set $backend http://{backend_dns};
        proxy_pass $backend$request_uri;
    }}
    location / {{ return 404; }}
}}
""", encoding="utf-8")
    network = "ev3-replica-cors"
    if not ready_command("docker", "network", "inspect", network):
        checked(["docker", "network", "create", network], "Red Docker del proxy CORS")
    start_container("ev3-replica-cors-proxy", "nginx:1.28-alpine", {"REPLICA_BACKEND_DNS": backend_dns},
                    ["--network", network, "--memory", "96m", "-p", f"{host}:18080:8080",
                     "-v", f"{nginx}:/etc/nginx/conf.d/default.conf:ro"])
    wait_until(lambda: ready_command("curl", "-fsS", "--max-time", "5", f"http://{host}:18080/health"), "proxy CORS")
    options = ["curl", "-sS", "--max-time", "10", "-o", "/dev/null", "-w", "%{http_code}"]
    code = checked([*options, "-H", f"Origin: {frontend_origin}",
                    f"http://{host}:18080/api/productos"], "Prueba de conexión del proxy a Productos").strip()
    if code not in ("200", "401"):
        raise RuntimeError(f"El proxy devolvió HTTP {code} al consultar el catálogo en el ALB.")
    print(f"Proxy CORS privado listo. Productos responde HTTP {code} sin token en el tramo privado.", flush=True)


def app(config, credentials):
    name = config["name"]
    db = name.lower()
    env = dict(config["env"])
    if db in DATABASES:
        env[f"{name.upper()}_DB_PASSWORD"] = credentials[db]
    if name in ("Orden", "Pedidos", "Pago", "Fidelizacion"):
        env["INTERNAL_SERVICE_KEY"] = credentials["internal"]
    if name in RABBIT_CLIENTS:
        env["RABBITMQ_PASS"] = credentials["rabbit"]
    mount = []
    if name in VOLUMES:
        directory = ROOT / "data" / db
        directory.mkdir(parents=True, exist_ok=True)
        os.chown(directory, 10001, 10001)
        mount = ["-v", f"{directory}:/var/lib/fazbear/{db}"]
    container_name = f"ev3-replica-{db}"
    start_container(container_name, config["image"], env,
                    ["--memory", "600m", "-p", f"{config['host']}:{config['port']}:{config['container_port']}", *mount])
    url = f"http://{config['host']}:{config['port']}{config['health']}"
    opener = build_opener(ProxyHandler({}))

    last_code = None

    def healthy():
        nonlocal last_code
        try:
            with opener.open(url, timeout=4) as response:
                last_code = response.status
        except HTTPError as error:
            last_code = error.code
        except (URLError, TimeoutError):
            last_code = None
        return last_code in config["allowed"]

    try:
        wait_until(healthy, name)
    except RuntimeError as error:
        raise RuntimeError(f"{error} Ultimo HTTP: {last_code}. Revisar sudo docker logs --tail 50 {container_name} en su EC2.") from error
    print(f"{name} · HTTP {last_code} en el puerto {config['port']}.", flush=True)


def webpay_release(config):
    name = "ev3-replica-pago"
    backup = f"{name}-prewebpay-{time.time_ns()}"
    current = json.loads(checked(["docker", "inspect", "--type", "container", name], "Inventario de Pago"))[0]
    if (not current["State"]["Running"] or (current["Config"].get("Labels") or {}).get(CONTAINER_LABEL) != name
            or current.get("Mounts")):
        raise RuntimeError("Pago debe estar en ejecución, administrado por la réplica y sin montajes propios.")
    credential = checked(["aws", "ssm", "get-parameter", "--region", config["region"], "--name", config["parameter"],
                          "--with-decryption", "--query", "Parameter.Value", "--output", "text"],
                         "Lectura de la llave Webpay de integración").strip()
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", credential):
        raise RuntimeError("La llave de integración guardada no tiene el formato esperado.")
    original = dict(entry.split("=", 1) for entry in current["Config"]["Env"])
    desired = {**original, "WEBPAY_ENABLED": "true", "WEBPAY_COMMERCE_CODE": WEBPAY_TEST_COMMERCE,
               "WEBPAY_API_KEY": credential, "WEBPAY_RETURN_URL": config["return_url"]}
    host = config["host"]
    opener = build_opener(ProxyHandler({}))

    def webpay_ready():
        try:
            with opener.open(f"http://{host}:8087/health", timeout=4) as response:
                return json.load(response).get("mode") == WEBPAY_MODE
        except (URLError, TimeoutError, ValueError):
            return False

    def verify_release():
        wait_until(webpay_ready, "Webpay Plus de integración")
        postgres = ["docker", "exec", "ev3-replica-postgres", "psql", "-U", "ev3admin", "-d", "pago",
                    "-X", "-qAt", "-v", "ON_ERROR_STOP=1"]
        migration = checked([*postgres, "-c",
                             "SELECT EXISTS(SELECT 1 FROM flyway_schema_history WHERE version='7' AND success)"],
                            "Verificación de Flyway V7").strip()
        if migration != "t":
            raise RuntimeError("Pago aún no tiene aplicada la migración V7.")
        print("Pago · Webpay Plus de integración activo · antifraude V7 aplicado.", flush=True)

    if current["Config"]["Image"] == config["image"] and original == desired:
        verify_release()
        return

    checked(["docker", "pull", config["image"]], "Descarga de la imagen de Pago")
    snapshot = ROOT / f"{backup}.dump"
    with snapshot.open("xb") as output:
        result = subprocess.run(["docker", "exec", "ev3-replica-postgres", "pg_dump",
                                 "-U", "ev3admin", "-Fc", "pago"], stdout=output,
                                stderr=subprocess.DEVNULL, timeout=120)
    if result.returncode or snapshot.stat().st_size == 0:
        raise RuntimeError("No se pudo respaldar PostgreSQL de Pago.")
    print(f"Respaldo privado de Pago: {snapshot.name}", flush=True)
    checked(["docker", "rename", name, backup], "Renombrar Pago anterior")
    try:
        checked(["docker", "stop", backup], "Detener Pago anterior")
        start_container(name, config["image"], desired,
                        ["--memory", "600m", "-p", f"{host}:8087:8080"], image_ready=True)
        verify_release()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
        if ready_command("docker", "inspect", "--type", "container", name):
            checked(["docker", "rm", "-f", name], "Retirar candidato de Pago")
        checked(["docker", "rename", backup, name], "Restaurar el nombre de Pago")
        checked(["docker", "start", name], "Volver a iniciar Pago anterior")
        raise RuntimeError("La nueva revisión no pasó la verificación. Se volvió a iniciar el Pago anterior.") from None


def host_operation(config):
    import fcntl

    ROOT.mkdir(mode=0o700, exist_ok=True)
    with (ROOT / "deploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        wait_until(lambda: ready_command("systemctl", "is-active", "--quiet", "docker"), "Docker")
        operation = config.get("operation", "app")
        if operation == "cors_proxy":
            cors_proxy(config["host"], config["backend_dns"], config["frontend_origin"])
            return
        if operation == "webpay_release":
            webpay_release(config)
            return
        output = checked(["aws", "ssm", "get-parameter", "--region", config["region"], "--name", config["parameter"],
                          "--with-decryption", "--query", "Parameter.Value", "--output", "text"],
                         "Lectura de configuración cifrada por LabInstanceProfile")
        credentials = json.loads(output)
        if operation == "app":
            app(config, credentials)
        elif operation == "postgres":
            postgres(config["host"], credentials)
        elif operation == "rabbit":
            rabbit(config["host"], credentials)
        else:
            raise RuntimeError("Operación SSM desconocida.")


def prepare_credentials(aws, parameter):
    try:
        aws("ssm", "get-parameter", "--name", parameter, "--query", "Parameter.Name")
        return
    except RuntimeError as error:
        if "ParameterNotFound" not in str(error):
            raise
    credentials = {name: secrets.token_hex(24) for name in (*DATABASES, "pg_admin", "rabbit", "internal")}
    with tempfile.TemporaryDirectory(prefix="pedidos360-config-") as directory:
        path = Path(directory) / "ssm.json"
        path.write_text(json.dumps({"Name": parameter, "Type": "SecureString", "Value": json.dumps(credentials)}),
                        encoding="utf-8")
        try:
            aws("ssm", "put-parameter", "--cli-input-json", path.resolve().as_uri())
        except RuntimeError as error:
            if "ParameterAlreadyExists" not in str(error):
                raise


def prepare_webpay_key(aws, parameter):
    try:
        aws("ssm", "get-parameter", "--name", parameter, "--query", "Parameter.Name")
        return
    except RuntimeError as error:
        if "ParameterNotFound" not in str(error):
            raise
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise RuntimeError("Abre una sesión interactiva de CloudShell para ingresar la llave de integración.")
    key = getpass("Llave pública del ambiente de integración Webpay Plus (entrada oculta): ").strip()
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", key):
        raise RuntimeError("La llave de integración debe tener 64 caracteres hexadecimales.")
    with tempfile.TemporaryDirectory(prefix="pedidos360-webpay-") as directory:
        path = Path(directory) / "ssm.json"
        path.write_text(json.dumps({"Name": parameter, "Type": "SecureString", "Value": key}), encoding="utf-8")
        aws("ssm", "put-parameter", "--cli-input-json", path.resolve().as_uri())


def deploy_many(aws, operations, payload):
    pending = {}
    for name, instance, config in operations:
        encoded = base64.b64encode(json.dumps(config).encode()).decode()
        command = f"printf %s {payload} | base64 --decode | gzip -d | python3 - --host {encoded}"
        response = aws("ssm", "send-command", "--document-name", "AWS-RunShellScript", "--instance-ids", instance,
                       "--comment", f"Pedidos360 EV3 respaldo {name}", "--timeout-seconds", "120",
                       "--parameters", json.dumps({"commands": [command], "executionTimeout": ["540"]}))
        command_id = response["Command"]["CommandId"]
        pending[command_id] = (name, instance)
        print(f"{name} · SSM {command_id}", flush=True)
    failed = []

    def poll():
        for command_id, (name, instance) in list(pending.items()):
            try:
                result = aws("ssm", "get-command-invocation", "--command-id", command_id, "--instance-id", instance)
            except RuntimeError as error:
                if "InvocationDoesNotExist" in str(error):
                    continue
                raise
            status = result["Status"]
            if status in ("Pending", "InProgress", "Delayed", "Cancelling"):
                continue
            pending.pop(command_id)
            if status != "Success":
                failed.append(name)
            detail = result.get("StandardOutputContent" if status == "Success" else "StandardErrorContent", "").strip()
            print(f"{name} · {status} · {detail}", flush=True)
        return not pending

    wait_until(poll, "todos los comandos SSM", seconds=650)
    if failed:
        raise RuntimeError("Servicios pendientes: " + ", ".join(failed))


def verify_targets(aws, stack_name, hosts):
    resources = aws("cloudformation", "list-stack-resources", "--stack-name", stack_name)["StackResourceSummaries"]
    arns = {item["LogicalResourceId"]: item["PhysicalResourceId"] for item in resources
            if item["ResourceType"] == "AWS::ElasticLoadBalancingV2::TargetGroup"}
    pending = dict(hosts)

    def poll():
        for name, instance in list(pending.items()):
            health = aws("elbv2", "describe-target-health", "--target-group-arn", arns[f"{name}Target"])
            if any(item["Target"]["Id"] == instance and item["TargetHealth"]["State"] == "healthy"
                   for item in health["TargetHealthDescriptions"]):
                print(f"{name} · Target Group healthy", flush=True)
                pending.pop(name)
        return not pending

    try:
        wait_until(poll, "los Target Groups de la API", seconds=180)
    except RuntimeError as error:
        raise RuntimeError(f"{error} Pendientes: {', '.join(pending)}") from error


def launch(account, *, proxy_only=False, webpay_image=None):
    from replica_infra import KAFKA_CLIENTS, REGION, SERVICES, STACK, aws

    if aws("sts", "get-caller-identity")["Account"] != account:
        raise RuntimeError("CloudShell está en una cuenta distinta a la solicitada.")
    stack = aws("cloudformation", "describe-stacks", "--stack-name", STACK)["Stacks"][0]
    params = {item["ParameterKey"]: item.get("ParameterValue") for item in stack["Parameters"]}
    if stack["StackStatus"] not in ("CREATE_COMPLETE", "UPDATE_COMPLETE") or params.get("DataContainers") != "true":
        raise RuntimeError("Primero aplicar replica_infra.py --data-containers y esperar que CloudFormation termine.")
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
    hosts = {name: outputs[f"{name}Instance"] for name in SERVICES}
    required_hosts = {hosts["Pago"]} if webpay_image else {hosts["Analytics"]} if proxy_only else set(hosts.values())

    def online():
        nodes = aws("ssm", "describe-instance-information")["InstanceInformationList"]
        return required_hosts <= {node["InstanceId"] for node in nodes if node["PingStatus"] == "Online"}

    wait_until(online, "las EC2 seleccionadas en Systems Manager")
    payload = base64.b64encode(gzip.compress(Path(__file__).read_bytes())).decode()
    if webpay_image:
        parameter = f"/{STACK}/webpay-integration"
        prepare_webpay_key(aws, parameter)
        config = {"operation": "webpay_release", "image": webpay_image, "host": outputs["PagoIp"],
                  "region": REGION, "parameter": parameter, "return_url": outputs["WebpayReturn"]}
        deploy_many(aws, [("Webpay", hosts["Pago"], config)], payload)
        verify_targets(aws, STACK, {"Pago": hosts["Pago"]})
        return
    if not proxy_only:
        parameter = f"/{STACK}/runtime"
        prepare_credentials(aws, parameter)
        configs = application_configs(outputs, SERVICES, KAFKA_CLIENTS, REGION, parameter)
        deploy_many(aws, [("PostgreSQL", hosts["Pago"], {**configs["Pago"], "operation": "postgres"}),
                          ("RabbitMQ", hosts["Notificaciones"], {**configs["Notificaciones"], "operation": "rabbit"})], payload)
        deploy_many(aws, [(name, hosts[name], configs[name]) for name in SERVICES], payload)
        verify_targets(aws, STACK, hosts)
    proxy_config = {"operation": "cors_proxy", "host": outputs["AnalyticsIp"], "backend_dns": outputs["BackendAlbDns"],
                    "frontend_origin": outputs["Frontend"].removesuffix("/ev3/")}
    deploy_many(aws, [("Proxy CORS", hosts["Analytics"], proxy_config)], payload)
    verify_targets(aws, STACK, {"CorsProxy": hosts["Analytics"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", help="Expected 12-digit AWS account ID")
    parser.add_argument("--apply", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--proxy-only", action="store_true", help="install and check only the private CORS proxy")
    mode.add_argument("--webpay-image", help="roll out only the published Pago V7 image and enable integration Webpay")
    parser.add_argument("--host", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.host and (not args.apply or not args.account or len(args.account) != 12 or not args.account.isdecimal()):
        parser.error("usar --account con el ID de cuenta de 12 dígitos y --apply")
    if args.webpay_image and not re.fullmatch(REGISTRY + r"fazbear-pago@sha256:[a-f0-9]{64}", args.webpay_image):
        parser.error("--webpay-image requiere el digest GHCR de Pago")
    try:
        if args.host:
            os.umask(0o077)
            host_operation(json.loads(base64.b64decode(args.host)))
        else:
            launch(args.account, proxy_only=args.proxy_only, webpay_image=args.webpay_image)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
