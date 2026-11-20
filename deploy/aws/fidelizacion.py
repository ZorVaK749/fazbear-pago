#!/usr/bin/env python3
"""Prepara una EC2 de Fidelización en el VPC de Pedidos360 EV3."""

import argparse
from fnmatch import fnmatchcase
import getpass
import json
import re
import sys
import time
import warnings

from clp_productos import python_request
from fidelizacion_host import PARAMETER, PORT, validate_config
from frontend_image import FAMILY as FRONTEND_SERVICE, verify_checkout
from webpay import ACCOUNT, INSTANCE as PAGO, RolloutError, aws, private_ip, run_ssm, wait_for_target

NAME = "fazbear-fidelizacion"
PROJECT = "Pedidos360-EV3"
LAUNCH_TOKEN = "pedidos360-ev3-fidelizacion-v1"
LEGACY_FRONTEND = "i-0644c1d2ca954f9aa"
LEGACY_NAME = "ec2-frontend"
LEGACY_TG = "fazbear-tg-frontend"
SERVICE_TAG = "Pedidos360EV3Service"
GROUP = "fazbear-fidelizacion-alb"
TG = "fazbear-tg-fidelizacion"
API = "uuzifgcyd2"
PATH = "/api/fidelizacion/*"
ROUTES = {
    "GET /api/fidelizacion/me/saldo",
    "GET /api/fidelizacion/me/movimientos",
    "GET /api/fidelizacion/recompensas",
    "POST /api/fidelizacion/me/canjes",
}


def instances(**filters):
    arguments = [f"Name={key},Values={value}" for key, value in filters.items()]
    result = aws("ec2", "describe-instances", "--filters", *arguments)
    return [i for reservation in result["Reservations"] for i in reservation["Instances"]]


def one(values, message):
    if len(values) != 1:
        raise RolloutError(message)
    return values[0]


def instance_tags(record):
    return {entry["Key"]: entry["Value"] for entry in record.get("Tags", [])}


def reused_frontend(record, tags):
    return record["InstanceId"] == LEGACY_FRONTEND and tags.get(SERVICE_TAG) == NAME


def select_instance(pago, instance_id=None):
    if instance_id:
        record = one(instances(**{"instance-id": instance_id}),
                     f"AWS no muestra un registro único para {instance_id}.")
        require_running(record)
        tags = instance_tags(record)
        token = record.get("ClientToken", "")
        launch_matches = re.fullmatch(rf"{re.escape(LAUNCH_TOKEN)}(?:-i-[0-9a-f]{{17}})?", token) is not None
        dedicated = (tags.get("Name") == NAME and tags.get("Project") == PROJECT) or (
            launch_matches and tags.get("Name", NAME) == NAME and tags.get("Project", PROJECT) == PROJECT)
        if (record["InstanceId"] != instance_id or instance_id == PAGO or record.get("VpcId") != pago["VpcId"]
                or not (dedicated or reused_frontend(record, tags))):
            raise RolloutError(f"AWS no identifica {instance_id} como EC2 de Fidelización en el VPC de Pago.")
        return record
    records = []
    for record in instances(**{"vpc-id": pago["VpcId"], "instance-state-name": "pending,running,stopping,stopped"}):
        tags = instance_tags(record)
        if tags.get("Name") == NAME or reused_frontend(record, tags):
            records.append(record)
    if len(records) > 1:
        raise RolloutError("Hay más de una EC2 activa o detenida con el nombre de Fidelización.")
    return records[0] if records else None


def inventory(instance_id=None):
    pago = one(instances(**{"instance-id": PAGO}), "No se encontró la EC2 de Pago.")
    routes = aws("apigatewayv2", "get-routes", "--api-id", API)["Items"]
    selected = {r["RouteKey"]: r for r in routes if r["RouteKey"] in ROUTES}
    if set(selected) != ROUTES or any(r["AuthorizationType"] != "JWT" or
                                      "access_as_user" not in r.get("AuthorizationScopes", [])
                                      for r in selected.values()):
        raise RolloutError("Revise las cuatro rutas JWT de Fidelización y el scope access_as_user.")
    integrations = {r["Target"] for r in selected.values()}
    integration_id = one(list(integrations), "Las rutas de Fidelización tienen destinos distintos.").removeprefix("integrations/")
    integration = aws("apigatewayv2", "get-integration", "--api-id", API, "--integration-id", integration_id)
    listener_arn = integration.get("IntegrationUri", "")
    if integration.get("ConnectionType") != "VPC_LINK" or not listener_arn.startswith(
            f"arn:aws:elasticloadbalancing:us-east-1:{ACCOUNT}:listener/app/"):
        raise RolloutError("Fidelización debe apuntar al listener del balanceador interno por VPC Link.")
    link = aws("apigatewayv2", "get-vpc-link", "--vpc-link-id", integration["ConnectionId"])
    if link["VpcLinkStatus"] != "AVAILABLE":
        raise RolloutError("El VPC Link debe estar AVAILABLE.")
    listener = one(aws("elbv2", "describe-listeners", "--listener-arns", listener_arn)["Listeners"],
                   "No se encontró el listener compartido de EV3.")
    alb = one(aws("elbv2", "describe-load-balancers", "--load-balancer-arns", listener["LoadBalancerArn"])["LoadBalancers"],
              "No se encontró el balanceador compartido de EV3.")
    if alb["Scheme"] != "internal" or alb["VpcId"] != pago["VpcId"] or not alb.get("SecurityGroups"):
        raise RolloutError("Pago y el ALB interno deben pertenecer al mismo VPC.")
    node = select_instance(pago, instance_id)
    print(f"VPC {pago['VpcId']} · subnet {pago['SubnetId']} · ALB {alb['LoadBalancerName']}", flush=True)
    if node:
        print(f"Fidelización EC2: {node['InstanceId']} · {node['State']['Name']}", flush=True)
    else:
        print("Fidelización: aún sin EC2 dedicada.", flush=True)
    return pago, listener_arn, alb, node


def open_to_alb(pago, alb):
    groups = aws("ec2", "describe-security-groups", "--filters",
                 f"Name=vpc-id,Values={pago['VpcId']}", f"Name=group-name,Values={GROUP}")["SecurityGroups"]
    if groups:
        group = one(groups, "Grupo de seguridad de Fidelización ambiguo.")
        group_id = group["GroupId"]
        authorized = {pair["GroupId"] for rule in group.get("IpPermissions", [])
                      if rule["IpProtocol"] == "tcp" and rule.get("FromPort") == PORT and rule.get("ToPort") == PORT
                      for pair in rule.get("UserIdGroupPairs", [])}
    else:
        group_id = aws("ec2", "create-security-group", "--group-name", GROUP, "--vpc-id", pago["VpcId"],
                       "--description", "ALB interno a Fidelizacion EV3 por el puerto 8089")["GroupId"]
        authorized = set()
    missing = set(alb["SecurityGroups"]) - authorized
    if missing:
        aws("ec2", "authorize-security-group-ingress", input_json={"GroupId": group_id, "IpPermissions": [{
            "IpProtocol": "tcp", "FromPort": PORT, "ToPort": PORT,
            "UserIdGroupPairs": [{"GroupId": gid} for gid in sorted(missing)],
        }]})
    return group_id


def create_ec2(pago, alb, existing, *, client_token=LAUNCH_TOKEN):
    if existing:
        print("Se conserva la instancia dedicada ya registrada.", flush=True)
        return existing["InstanceId"]
    profile = pago.get("IamInstanceProfile", {}).get("Arn")
    original_groups = [g["GroupId"] for g in pago.get("SecurityGroups", [])]
    if not profile or not original_groups:
        raise RolloutError("La EC2 de referencia debe tener perfil SSM y red de microservicios.")
    images = aws("ec2", "describe-images", "--image-ids", pago["ImageId"], "--owners", "amazon")["Images"]
    image = one(images, "La AMI de Pago no es una imagen Amazon reutilizable. Identifique una AMI AL2023 oficial.")
    if not image.get("Name", "").startswith("al2023-ami-") or image["Architecture"] != "x86_64":
        raise RolloutError("Se requiere una AMI Amazon Linux 2023 x86_64 compatible con GHCR.")
    public = bool(pago.get("PublicIpAddress"))
    if public:
        groups = aws("ec2", "describe-security-groups", "--group-ids", *original_groups)["SecurityGroups"]
        restricted = [g["GroupId"] for g in groups if not any(
            r.get("CidrIp") == "0.0.0.0/0" or r.get("CidrIpv6") == "::/0"
            for p in g.get("IpPermissions", []) for r in (*p.get("IpRanges", []), *p.get("Ipv6Ranges", []))
        )]
        if set(restricted) != set(original_groups):
            print("La EC2 reutilizará solo los grupos de Pago sin entrada abierta a internet.", flush=True)
        original_groups = restricted
    group = open_to_alb(pago, alb)
    tags = [{"Key": "Name", "Value": NAME}, {"Key": "Project", "Value": PROJECT}]
    response = aws("ec2", "run-instances", input_json={
        "MinCount": 1, "MaxCount": 1, "ImageId": image["ImageId"], "InstanceType": "t3.micro",
        "IamInstanceProfile": {"Arn": profile},
        "ClientToken": client_token,
        "NetworkInterfaces": [{"DeviceIndex": 0, "SubnetId": pago["SubnetId"],
                               "Groups": sorted(set(original_groups + [group])), "AssociatePublicIpAddress": public}],
        "MetadataOptions": {"HttpTokens": "required"},
        "CreditSpecification": {"CpuCredits": "standard"},
        "BlockDeviceMappings": [{"DeviceName": image["RootDeviceName"],
                                 "Ebs": {"Encrypted": True, "DeleteOnTermination": True}}],
        "TagSpecifications": [{"ResourceType": resource, "Tags": tags} for resource in ("instance", "volume")],
    })
    instance_id = response["Instances"][0]["InstanceId"]
    print(f"EC2 dedicada solicitada: {instance_id}", flush=True)
    return instance_id


def retry_ec2(pago, alb, existing, previous_id):
    if not re.fullmatch(r"i-[0-9a-f]{17}", previous_id):
        raise RolloutError("Ingrese el ID de la EC2 terminada de Fidelización.")
    if existing:
        return create_ec2(pago, alb, existing)
    records = instances(**{"instance-id": previous_id})
    if records:
        previous = one(records, "AWS devolvió más de un registro para la EC2 anterior.")
        tags = {entry["Key"]: entry["Value"] for entry in previous.get("Tags", [])}
        vpc = previous.get("VpcId")
        if (previous["State"]["Name"] != "terminated" or (vpc and vpc != pago["VpcId"])
                or tags.get("Name", NAME) != NAME or tags.get("Project", PROJECT) != PROJECT):
            raise RolloutError("El ID debe pertenecer a una EC2 terminada de Fidelización en este VPC.")
        reason = previous.get("StateReason", {}).get("Code", "terminated")
        print(f"Fidelización anterior {previous_id} · {reason}", flush=True)
    else:
        print(f"AWS ya no lista {previous_id}. Se usa el ID indicado para identificar este reintento.", flush=True)
    return create_ec2(pago, alb, None, client_token=f"{LAUNCH_TOKEN}-{previous_id}")


def require_running(node):
    if not node:
        raise RolloutError("Se requiere una EC2 dedicada de Fidelización. Si ya la creó, indique --instance-id.")
    instance_id = node["InstanceId"]
    state = node["State"]["Name"]
    if state != "running":
        reason = node.get("StateReason", {}).get("Message") or node.get("StateTransitionReason")
        raise RolloutError(f"EC2 {instance_id} · {state}" + (f" · {reason}" if reason else ""))
    return instance_id


def wait_for_ec2(instance_id):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        records = instances(**{"instance-id": instance_id})
        if records:
            record = one(records, "AWS devolvió un estado ambiguo para la EC2 de Fidelización.")
            if record["State"]["Name"] != "pending":
                require_running(record)
                print(f"EC2 de Fidelización en ejecución: {instance_id}", flush=True)
                return
        time.sleep(5)
    raise RolloutError(f"EC2 {instance_id} aún no está en ejecución. Consulte el estado con --plan.")


def configure():
    if not sys.stdin.isatty():
        raise RolloutError("Use una sesión interactiva para ingresar los parámetros privados.")
    prompts = (
        ("FIDELIZACION_DB_URL", "URL JDBC de la base dedicada"),
        ("FIDELIZACION_DB_USER", "Usuario de PostgreSQL"),
        ("FIDELIZACION_DB_PASSWORD", "Contraseña de PostgreSQL"),
        ("KAFKA_BOOTSTRAP_SERVERS", "Bootstrap servers de Kafka"),
        ("INTERNAL_SERVICE_KEY", "Clave interna compartida con Pago"),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        data = {key: getpass.getpass(f"{label} (oculto): ") for key, label in prompts}
    validate_config(data)
    result = aws("ssm", "put-parameter", input_json={"Name": PARAMETER, "Value": json.dumps(data),
                 "Type": "SecureString", "Overwrite": False})
    print("Parámetro privado existente conservado." if result.get("AlreadyExists")
          else "Configuración privada guardada en Parameter Store.")


def run_service(node, mode):
    instance = require_running(node)
    deploy = mode == "deploy"
    request = python_request(instance, f"Pedidos360 Fidelizacion {mode}",
                             ("webpay_host", "fidelizacion_host"),
                             (mode, node["PrivateIpAddress"], private_ip(PAGO)), 480 if deploy else 160)
    run_ssm(request, instance, timeout=540 if deploy else 210,
            failure="SSM no completó Fidelización. Revise el Command ID.")


def prepare_database(node):
    require_running(node)
    request = python_request(PAGO, "Pedidos360 preparar PostgreSQL de Fidelizacion",
                             ("webpay_host", "fidelizacion_host", "fidelizacion_db"), (), 160)
    run_ssm(request, PAGO, timeout=210,
            failure="La preparación de PostgreSQL quedó pendiente. Revise la salida de SSM.")


def check_frontend_traffic(node):
    services = aws("ecs", "describe-services", "--cluster", "pedidos360-ev3-infra", "--services", FRONTEND_SERVICE)
    frontend = one(services["services"], "No se encontró el frontend de EV3 en ECS.")
    providers = {entry["capacityProvider"] for entry in frontend.get("capacityProviderStrategy", [])}
    fargate = frontend.get("launchType") == "FARGATE" or (providers and providers <= {"FARGATE", "FARGATE_SPOT"})
    if (frontend["status"] != "ACTIVE" or not fargate
            or frontend["runningCount"] != frontend["desiredCount"] or not frontend["runningCount"]):
        raise RolloutError("El frontend principal debe estar activo en Fargate.")
    verify_checkout()
    target_ids = {LEGACY_FRONTEND, node["PrivateIpAddress"]}
    for group in aws("elbv2", "describe-target-groups")["TargetGroups"]:
        name = group["TargetGroupName"]
        if not group["LoadBalancerArns"] or name == TG:
            continue
        if name == LEGACY_TG:
            raise RolloutError(f"El Target Group {LEGACY_TG} sigue asociado a un balanceador.")
        health = aws("elbv2", "describe-target-health", "--target-group-arn", group["TargetGroupArn"])
        if any(target["Target"]["Id"] in target_ids for target in health["TargetHealthDescriptions"]):
            raise RolloutError(f"La EC2 anterior sigue registrada en el grupo activo {name}.")
    print("Frontend Fargate verificado. La EC2 anterior está fuera de los grupos con balanceador.", flush=True)


def check_existing_ingress(groups):
    response = aws("ec2", "describe-security-groups", "--group-ids", *sorted(groups))
    for group in response["SecurityGroups"]:
        for rule in group["IpPermissions"]:
            protocol = rule["IpProtocol"]
            if protocol == "-1" or (protocol in {"tcp", "6"} and rule["FromPort"] <= PORT <= rule["ToPort"]):
                if (any(entry["CidrIp"] == "0.0.0.0/0" for entry in rule.get("IpRanges", []))
                        or any(entry["CidrIpv6"] == "::/0" for entry in rule.get("Ipv6Ranges", []))):
                    raise RolloutError(f"El grupo {group['GroupId']} permite acceso público al puerto {PORT}.")


def reuse_frontend(pago, listener, alb, existing):
    if existing and existing["InstanceId"] != LEGACY_FRONTEND:
        raise RolloutError("Ya existe otra EC2 de Fidelización. Use --verify o --deploy.")
    node = one(instances(**{"instance-id": LEGACY_FRONTEND}), "No se encontró la EC2 del frontend anterior.")
    require_running(node)
    tags = instance_tags(node)
    profile = (pago.get("IamInstanceProfile") or {}).get("Arn")
    if (node["InstanceId"] != LEGACY_FRONTEND or node.get("VpcId") != pago["VpcId"]
            or node.get("Architecture") != "x86_64" or tags.get("Name") != LEGACY_NAME
            or tags.get(SERVICE_TAG, NAME) != NAME or not profile
            or (node.get("IamInstanceProfile") or {}).get("Arn") != profile):
        raise RolloutError("La EC2 anterior difiere del inventario esperado de EV3.")
    managed = aws("ssm", "describe-instance-information", "--filters", f"Key=InstanceIds,Values={LEGACY_FRONTEND}")
    info = one(managed["InstanceInformationList"], "SSM todavía no muestra la EC2 del frontend anterior.")
    if info["PingStatus"] != "Online" or info["PlatformName"] != "Amazon Linux":
        raise RolloutError("La EC2 anterior debe estar Online en SSM y usar Amazon Linux.")
    check_frontend_traffic(node)
    groups = {group["GroupId"] for group in node["SecurityGroups"]}
    check_existing_ingress(groups)
    prepare_database(node)
    group = open_to_alb(pago, alb)
    if group not in groups:
        aws("ec2", "modify-instance-attribute", "--instance-id", LEGACY_FRONTEND, "--groups", *sorted(groups | {group}))
    if not reused_frontend(node, tags):
        aws("ec2", "create-tags", "--resources", LEGACY_FRONTEND, "--tags", f"Key={SERVICE_TAG},Value={NAME}")
    run_service(node, "deploy")
    attach(node, pago, listener)


def attach(node, pago, listener, verify_only=False):
    groups = [g for g in aws("elbv2", "describe-target-groups")["TargetGroups"] if g["TargetGroupName"] == TG]
    if groups:
        group = one(groups, "Target Group de Fidelización ambiguo.")
    elif verify_only:
        raise RolloutError("Todavía falta el Target Group de Fidelización.")
    else:
        group = aws("elbv2", "create-target-group", input_json={
            "Name": TG, "Protocol": "HTTP", "Port": PORT, "TargetType": "instance", "VpcId": pago["VpcId"],
            "HealthCheckPath": "/health", "Matcher": {"HttpCode": "200"},
        })["TargetGroups"][0]
    if (group["Protocol"] != "HTTP" or group["Port"] != PORT or group["VpcId"] != pago["VpcId"]
            or group["TargetType"] != "instance"
            or group["HealthCheckPath"] != "/health" or group.get("Matcher", {}).get("HttpCode") != "200"):
        raise RolloutError("El Target Group existente difiere del plan de Fidelización.")
    arn = group["TargetGroupArn"]
    rules = aws("elbv2", "describe-rules", "--listener-arn", listener)["Rules"]
    priority = rule_priority(rules, arn)
    target = node["InstanceId"]
    registered = aws("elbv2", "describe-target-health", "--target-group-arn", arn)["TargetHealthDescriptions"]
    if any((t["Target"].get("Id"), t["Target"].get("Port")) != (target, PORT) for t in registered):
        raise RolloutError("El Target Group de Fidelización contiene otro destino.")
    if verify_only and (not registered or priority is not None):
        raise RolloutError("Falta registrar la EC2 o enlazar el Target Group al listener.")
    if not registered:
        aws("elbv2", "register-targets", "--target-group-arn", arn, "--targets", f"Id={target},Port={PORT}")
    if priority is not None:
        aws("elbv2", "create-rule", input_json={
            "ListenerArn": listener, "Priority": priority,
            "Conditions": [{"Field": "path-pattern", "PathPatternConfig": {"Values": [PATH]}}],
            "Actions": [{"Type": "forward", "TargetGroupArn": arn}],
        })
    wait_for_target(arn, target, group["HealthCheckIntervalSeconds"], port=PORT)


def rule_priority(rules, arn):
    available = 1
    present = False
    first_overlap = 50001
    for rule in sorted((r for r in rules if not r["IsDefault"]), key=lambda r: int(r["Priority"])):
        priority = int(rule["Priority"])
        conditions = rule["Conditions"]
        paths = [v for condition in conditions if condition["Field"] == "path-pattern"
                 for v in condition.get("PathPatternConfig", {}).get("Values", condition.get("Values", []))]
        if len(conditions) == 1 and paths == [PATH]:
            actions = rule["Actions"]
            if len(actions) != 1 or actions[0].get("TargetGroupArn") != arn or first_overlap < priority:
                raise RolloutError("La regla de Fidelización existente tiene otro destino o precedencia ambigua.")
            present = True
        elif not paths or any(fnmatchcase(route.split(" ", 1)[1], p) for p in paths for route in ROUTES):
            first_overlap = min(first_overlap, priority)
        if priority == available:
            available += 1
    if present:
        return None
    if available >= first_overlap:
        raise RolloutError("No hay una prioridad libre antes de una regla que podría interceptar Fidelización.")
    return available


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    flags = parser.add_mutually_exclusive_group(required=True)
    for mode in ("plan", "create-ec2", "prepare-db", "set-config", "deploy", "verify", "reuse-frontend"):
        flags.add_argument("--" + mode, dest="mode", action="store_const", const=mode)
    flags.add_argument("--retry-ec2", metavar="INSTANCE_ID", help="Reintenta después de una EC2 terminada y espera su arranque.")
    parser.add_argument("--instance-id", metavar="INSTANCE_ID", help="Selecciona la EC2 ya creada por ID en lugar de buscarla por etiqueta.")
    args = parser.parse_args()
    if args.instance_id and (args.mode not in {"prepare-db", "deploy", "verify"}
                             or not re.fullmatch(r"i-[0-9a-f]{17}", args.instance_id)):
        parser.error("--instance-id requiere un ID de EC2 válido y --prepare-db, --deploy o --verify.")
    try:
        if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
            raise RolloutError(f"La sesión debe corresponder al laboratorio {ACCOUNT}.")
        if args.mode == "set-config":
            configure()
            return 0
        pago, listener, alb, node = inventory(args.instance_id)
        if args.mode == "create-ec2":
            create_ec2(pago, alb, node)
        elif args.retry_ec2:
            wait_for_ec2(retry_ec2(pago, alb, node, args.retry_ec2))
        elif args.mode == "prepare-db":
            prepare_database(node)
        elif args.mode == "reuse-frontend":
            reuse_frontend(pago, listener, alb, node)
        elif args.mode in {"deploy", "verify"}:
            run_service(node, args.mode)
            attach(node, pago, listener, verify_only=args.mode == "verify")
    except (KeyError, IndexError, TypeError, ValueError, OSError, EOFError, getpass.GetPassWarning, RolloutError) as error:
        print(f"ERROR: {error}" if isinstance(error, RolloutError) else
              "ERROR: Inventario o entrada privada incompletos. Revise --plan.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
