#!/usr/bin/env python3
"""Prepara una EC2 de Fidelización en el VPC de Pedidos360 EV3."""

import argparse
from fnmatch import fnmatchcase
import getpass
import json
import re
import sys
import warnings

from clp_productos import python_request
from fidelizacion_host import PARAMETER, PORT, validate_config
from webpay import ACCOUNT, INSTANCE as PAGO, RolloutError, aws, private_ip, run_ssm, wait_for_target

NAME = "fazbear-fidelizacion"
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


def inventory():
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
    records = instances(**{"vpc-id": pago["VpcId"], "tag:Name": NAME,
                           "instance-state-name": "pending,running,stopping,stopped"})
    if len(records) > 1:
        raise RolloutError("Hay más de una EC2 activa o detenida con el nombre de Fidelización.")
    print(f"VPC {pago['VpcId']} · subnet {pago['SubnetId']} · ALB {alb['LoadBalancerName']}", flush=True)
    if records:
        print(f"Fidelización EC2: {records[0]['InstanceId']} · {records[0]['State']['Name']}", flush=True)
    else:
        print("Fidelización: aún sin EC2 dedicada.", flush=True)
    return pago, listener_arn, alb, records[0] if records else None


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


def create_ec2(pago, alb, existing):
    if existing:
        print("Se conserva la instancia dedicada ya registrada.", flush=True)
        return
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
    tags = [{"Key": "Name", "Value": NAME}, {"Key": "Project", "Value": "Pedidos360-EV3"}]
    response = aws("ec2", "run-instances", input_json={
        "MinCount": 1, "MaxCount": 1, "ImageId": image["ImageId"], "InstanceType": "t3.micro",
        "IamInstanceProfile": {"Arn": profile},
        "ClientToken": "pedidos360-ev3-fidelizacion-v1",
        "NetworkInterfaces": [{"DeviceIndex": 0, "SubnetId": pago["SubnetId"],
                               "Groups": sorted(set(original_groups + [group])), "AssociatePublicIpAddress": public}],
        "MetadataOptions": {"HttpTokens": "required"},
        "CreditSpecification": {"CpuCredits": "standard"},
        "BlockDeviceMappings": [{"DeviceName": image["RootDeviceName"],
                                 "Ebs": {"Encrypted": True, "DeleteOnTermination": True}}],
        "TagSpecifications": [{"ResourceType": resource, "Tags": tags} for resource in ("instance", "volume")],
    })
    print(f"EC2 dedicada solicitada: {response['Instances'][0]['InstanceId']}", flush=True)


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
    if not node or node["State"]["Name"] != "running":
        raise RolloutError("La EC2 dedicada debe estar en ejecución.")
    instance = node["InstanceId"]
    deploy = mode == "deploy"
    request = python_request(instance, f"Pedidos360 Fidelizacion {mode}",
                             ("webpay_host", "fidelizacion_host"),
                             (mode, node["PrivateIpAddress"], private_ip(PAGO)), 480 if deploy else 160)
    run_ssm(request, instance, timeout=540 if deploy else 210,
            failure="SSM no completó Fidelización. Revise el Command ID.")


def prepare_database(node):
    if not node:
        raise RolloutError("Se requiere una EC2 dedicada registrada antes de preparar PostgreSQL.")
    request = python_request(PAGO, "Pedidos360 preparar PostgreSQL de Fidelizacion",
                             ("webpay_host", "fidelizacion_host", "fidelizacion_db"), (), 160)
    run_ssm(request, PAGO, timeout=210,
            failure="La preparación de PostgreSQL quedó pendiente. Revise la salida de SSM.")


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
    for mode in ("plan", "create-ec2", "prepare-db", "set-config", "deploy", "verify"):
        flags.add_argument("--" + mode, dest="mode", action="store_const", const=mode)
    args = parser.parse_args()
    try:
        if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
            raise RolloutError(f"La sesión debe corresponder al laboratorio {ACCOUNT}.")
        if args.mode == "set-config":
            configure()
            return 0
        pago, listener, alb, node = inventory()
        if args.mode == "create-ec2":
            create_ec2(pago, alb, node)
        elif args.mode == "prepare-db":
            prepare_database(node)
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
