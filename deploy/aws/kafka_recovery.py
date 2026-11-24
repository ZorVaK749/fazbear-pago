#!/usr/bin/env python3
"""Restore the EV3 lab broker behind its existing private bootstrap address."""

import argparse
import ast
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ACCOUNT: str
SUBNET: str
ADDRESS: str
CLIENTS: dict[str, str]
REGION = "us-east-1"
CLUSTER = "pedidos360-ev3-infra"
ORIGINAL_TASK = "pedidos360-ev3-kafka:2"
SERVICE = "pedidos360-ev3-kafka-recovery"
PORT = 9092
LOAD_BALANCER = "pedidos360-ev3-kafka-nlb"
TARGET_GROUP = "pedidos360-ev3-kafka-tcp"
CLIENT_NAMES = {"Productos", "Carrito", "Pago", "Analytics", "Fidelización"}
OWNER = "pedidos360-ev3-kafka-recovery"
TAG = {"Key": "ManagedBy", "Value": OWNER}


class RecoveryError(Exception):
    pass


def aws(service, operation, *arguments, payload=None, absent=()):
    command = ["aws", service, operation, "--region", REGION, "--output", "json"]
    command.extend(arguments)
    # The AWS CLI can read the JSON twice. Use a seekable file without a disk copy.
    source = (nullcontext() if payload is None
              else os.fdopen(os.memfd_create("pedidos360-kafka"), "w+b"))
    with source as data:
        options = {}
        if data is not None:
            data.write(json.dumps(payload).encode("utf-8"))
            data.flush()
            data.seek(0)
            fd = data.fileno()
            command.extend(("--cli-input-json", f"file:///proc/self/fd/{fd}"))
            options["pass_fds"] = (fd,)
        result = subprocess.run(
            command, capture_output=True, text=True, env={**os.environ, "AWS_PAGER": ""}, **options,
        )
    if result.returncode:
        match = re.search(r"An error occurred \(([^)]+)\)", result.stderr)
        code = match.group(1) if match else f"exit {result.returncode}"
        if code in absent:
            return {}
        detail = result.stderr.strip().splitlines()
        raise RecoveryError(f"{service} {operation}: {detail[0] if detail else code}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def require(condition, message):
    if not condition:
        raise RecoveryError(message)


def load_lab_config(path):
    # Reuse the identifiers from the private CloudShell copy without executing it.
    keys = {"ACCOUNT", "SUBNET", "ADDRESS", "CLIENTS"}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if isinstance(target, ast.Name) and target.id in keys:
                require(target.id not in values, f"Configuración duplicada: {target.id}")
                values[target.id] = ast.literal_eval(statement.value)
    require(set(values) == keys, f"Faltan identificadores de EV3 en {path}")
    account, subnet, address, clients = (values[key] for key in ("ACCOUNT", "SUBNET", "ADDRESS", "CLIENTS"))
    require(isinstance(account, str) and re.fullmatch(r"\d{12}", account), "Cuenta AWS inválida")
    require(isinstance(subnet, str) and re.fullmatch(r"subnet-[0-9a-f]{17}", subnet), "Subred AWS inválida")
    require(isinstance(address, str) and ipaddress.IPv4Address(address).is_private,
            "El broker debe usar una IPv4 privada")
    require(isinstance(clients, dict) and clients.keys() == CLIENT_NAMES
            and all(isinstance(value, str) and re.fullmatch(r"i-[0-9a-f]{17}", value)
                    for value in clients.values()) and len(set(clients.values())) == len(CLIENT_NAMES),
            "Se necesitan las cinco EC2 de EV3")
    return account, subnet, address, clients


def owned(tags):
    return any(tag.get("Key", tag.get("key")) == TAG["Key"]
               and tag.get("Value", tag.get("value")) == OWNER for tag in tags)


def get_load_balancer():
    result = aws("elbv2", "describe-load-balancers", "--names", LOAD_BALANCER,
                 absent=("LoadBalancerNotFound",))
    return next(iter(result.get("LoadBalancers", [])), None)


def get_service():
    result = aws("ecs", "describe-services", "--cluster", CLUSTER,
                 "--services", SERVICE, "--include", "TAGS")
    unexpected = [failure for failure in result.get("failures", [])
                  if failure.get("reason") != "MISSING"]
    require(not unexpected, "ECS no pudo inspeccionar el servicio de recuperación")
    active = [service for service in result["services"] if service["status"] != "INACTIVE"]
    return next(iter(active), None)


def elb_owned(arn):
    result = aws("elbv2", "describe-tags", "--resource-arns", arn)
    return owned(result["TagDescriptions"][0]["Tags"])


def preflight():
    require(aws("sts", "get-caller-identity")["Account"] == ACCOUNT,
            "La sesión tiene que corresponder a la cuenta de Pedidos360 EV3")
    subnet = aws("ec2", "describe-subnets", "--subnet-ids", SUBNET)["Subnets"][0]
    vpc = subnet["VpcId"]
    require(ipaddress.ip_address(ADDRESS) in ipaddress.ip_network(subnet["CidrBlock"]),
            "La IP original está fuera de la subred que usaba el broker")

    result = aws("ec2", "describe-instances", "--instance-ids", *CLIENTS.values())
    instances = {instance["InstanceId"]: instance for reservation in result["Reservations"]
                 for instance in reservation["Instances"]}
    client_ips = set()
    for name, instance_id in CLIENTS.items():
        instance = instances.get(instance_id, {})
        require(instance.get("VpcId") == vpc and instance.get("State", {}).get("Name") == "running"
                and instance.get("PrivateIpAddress"), f"{name} debe estar activo en la VPC de EV3")
        client_ips.add(instance["PrivateIpAddress"])

    load_balancer = get_load_balancer()
    interfaces = aws("ec2", "describe-network-interfaces", "--filters",
                     f"Name=vpc-id,Values={vpc}",
                     f"Name=addresses.private-ip-address,Values={ADDRESS}")["NetworkInterfaces"]
    if load_balancer:
        arn = load_balancer["LoadBalancerArn"]
        mappings = {(zone["SubnetId"], item.get("PrivateIPv4Address"))
                    for zone in load_balancer["AvailabilityZones"]
                    for item in zone.get("LoadBalancerAddresses", [])}
        require(elb_owned(arn) and load_balancer["VpcId"] == vpc
                and load_balancer["Scheme"] == "internal" and load_balancer["Type"] == "network"
                and mappings == {(SUBNET, ADDRESS)}, "El NLB existente no coincide con la recuperación")
    else:
        require(not interfaces, f"La IP {ADDRESS} ya pertenece a otro recurso")

    service = get_service()
    if service:
        require(owned(service.get("tags", [])), "Ya existe un servicio con el nombre de recuperación")
    old_tasks = aws("ecs", "list-tasks", "--cluster", CLUSTER, "--family", ORIGINAL_TASK.split(":")[0],
                    "--desired-status", "RUNNING")["taskArns"]
    require(not old_tasks, "Hay una tarea de la familia original en ejecución. Revísela antes de avanzar")
    original = aws("ecs", "describe-task-definition", "--task-definition", ORIGINAL_TASK)["taskDefinition"]
    require(original["networkMode"] == "awsvpc" and "FARGATE" in original["requiresCompatibilities"]
            and not original.get("volumes") and len(original["containerDefinitions"]) == 1,
            "La definición original cambió y requiere revisión antes de copiarla")
    broker = original["containerDefinitions"][0]
    require(broker["name"] == "kafka" and broker["image"] == "apache/kafka:3.9.1"
            and not broker.get("mountPoints") and not broker.get("secrets"),
            "La imagen o configuración del broker original cambió")
    print(f"Cuenta y subred verificadas. Broker privado {ADDRESS}:{PORT}, {len(client_ips)} clientes EC2.", flush=True)
    return vpc, client_ips, load_balancer, service, original


def security_group(vpc, suffix, rule):
    name = f"{SERVICE}-{suffix}"
    description = f"Pedidos360 EV3 recovery Kafka {suffix}"
    groups = aws("ec2", "describe-security-groups", "--filters",
                 f"Name=vpc-id,Values={vpc}", f"Name=group-name,Values={name}")["SecurityGroups"]
    if groups:
        group = groups[0]
        require(owned(group.get("Tags", [])) or group.get("Description") == description,
                f"El grupo {name} pertenece a otro despliegue")
        group_id = group["GroupId"]
        current = group["IpPermissions"]
    else:
        group_id = aws("ec2", "create-security-group", "--group-name", name,
                       "--description", description, "--vpc-id", vpc)["GroupId"]
        current = []
    if current:
        for permission in current:
            require((permission["IpProtocol"], permission.get("FromPort"), permission.get("ToPort"))
                    == ("tcp", PORT, PORT) and not permission.get("Ipv6Ranges")
                    and not permission.get("PrefixListIds"), f"Ingreso no esperado en {name}")
        for key, field in (("IpRanges", "CidrIp"), ("UserIdGroupPairs", "GroupId")):
            expected = {entry[field] for entry in rule.get(key, [])}
            existing = {entry[field] for permission in current for entry in permission.get(key, [])}
            require(existing == expected, f"Los orígenes permitidos cambiaron en {name}")
    else:
        aws("ec2", "authorize-security-group-ingress", payload={
            "GroupId": group_id,
            "IpPermissions": [{"IpProtocol": "tcp", "FromPort": PORT, "ToPort": PORT, **rule}],
        })
    return group_id


def target(vpc, *, create=True):
    found = aws("elbv2", "describe-target-groups", "--names", TARGET_GROUP,
                absent=("TargetGroupNotFound",)).get("TargetGroups", [])
    if found:
        group = found[0]
        arn = group["TargetGroupArn"]
        require(elb_owned(arn) and group["VpcId"] == vpc and group["Protocol"] == "TCP"
                and group["Port"] == PORT and group["TargetType"] == "ip",
                "El Target Group existente no coincide con la recuperación")
        return arn
    require(create, "Todavía no existe el Target Group de Kafka")
    return aws("elbv2", "create-target-group", payload={
        "Name": TARGET_GROUP, "VpcId": vpc, "Port": PORT, "Protocol": "TCP", "TargetType": "ip",
        "HealthCheckProtocol": "TCP", "HealthCheckIntervalSeconds": 10, "Tags": [TAG],
    })["TargetGroups"][0]["TargetGroupArn"]


def connect_load_balancer(group_id, load_balancer, target_arn):
    if load_balancer is None:
        load_balancer = aws("elbv2", "create-load-balancer", payload={
            "Name": LOAD_BALANCER, "Type": "network", "Scheme": "internal", "IpAddressType": "ipv4",
            "SecurityGroups": [group_id], "Tags": [TAG],
            "SubnetMappings": [{"SubnetId": SUBNET, "PrivateIPv4Address": ADDRESS}],
        })["LoadBalancers"][0]
    require(load_balancer.get("SecurityGroups") == [group_id], "El NLB usa un grupo de seguridad distinto")
    arn = load_balancer["LoadBalancerArn"]
    listeners = aws("elbv2", "describe-listeners", "--load-balancer-arn", arn)["Listeners"]
    if not listeners:
        aws("elbv2", "create-listener", payload={
            "LoadBalancerArn": arn, "Protocol": "TCP", "Port": PORT,
            "DefaultActions": [{"Type": "forward", "TargetGroupArn": target_arn}],
        })
    else:
        require(len(listeners) == 1 and listeners[0]["Port"] == PORT
                and listeners[0]["Protocol"] == "TCP"
                and listeners[0]["DefaultActions"][0].get("TargetGroupArn") == target_arn,
                "El listener existente no coincide con la recuperación")


def task_configuration(original):
    copy_fields = ("taskRoleArn", "executionRoleArn", "networkMode", "volumes",
                   "requiresCompatibilities", "cpu", "memory", "runtimePlatform", "ephemeralStorage")
    task = {key: original[key] for key in copy_fields if key in original}
    broker = dict(original["containerDefinitions"][0])
    for field in ("entryPoint", "command", "healthCheck"):
        broker.pop(field, None)
    broker["environment"] = [{"name": key, "value": value} for key, value in {
        **{item["name"]: item["value"] for item in broker.get("environment", [])},
        "KAFKA_ADVERTISED_LISTENERS": f"PLAINTEXT://{ADDRESS}:{PORT}",
        "KAFKA_INTER_BROKER_LISTENER_NAME": "PLAINTEXT",
        "KAFKA_AUTO_CREATE_TOPICS_ENABLE": "true",
        "KAFKA_DEFAULT_REPLICATION_FACTOR": "1",
        "KAFKA_MIN_INSYNC_REPLICAS": "1",
        "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1",
        "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR": "1",
        "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR": "1",
    }.items()]
    return {**task, "family": SERVICE, "containerDefinitions": [broker],
            "tags": [{"key": TAG["Key"], "value": OWNER}]}


def broker_env(definition):
    return {item["name"]: item["value"] for item in definition["containerDefinitions"][0]["environment"]}


def deploy(vpc, client_ips, load_balancer, service, original):
    nlb_sg = security_group(vpc, "nlb", {"IpRanges": [{"CidrIp": ip + "/32"} for ip in sorted(client_ips)]})
    broker_sg = security_group(vpc, "broker", {"UserIdGroupPairs": [{"GroupId": nlb_sg}]})
    target_arn = target(vpc)
    connect_load_balancer(nlb_sg, load_balancer, target_arn)
    attachment = {"targetGroupArn": target_arn, "containerName": "kafka", "containerPort": PORT}
    network = {"subnets": [SUBNET], "securityGroups": [broker_sg], "assignPublicIp": "ENABLED"}
    if service is None:
        desired = task_configuration(original)
        definitions = aws("ecs", "list-task-definitions", "--family-prefix", SERVICE,
                          "--sort", "DESC")["taskDefinitionArns"]
        if definitions:
            definition = aws("ecs", "describe-task-definition", "--task-definition", definitions[0],
                             "--include", "TAGS")
            active = definition["taskDefinition"]
            require(owned(definition.get("tags", [])) and active["family"] == SERVICE
                    and broker_env(active) == broker_env(desired),
                    "La definición de recuperación existente requiere revisión")
        else:
            definition = aws("ecs", "register-task-definition", payload=desired)
        task_arn = definition["taskDefinition"]["taskDefinitionArn"]
        aws("ecs", "create-service", payload={
            "cluster": CLUSTER, "serviceName": SERVICE, "taskDefinition": task_arn,
            "desiredCount": 1, "launchType": "FARGATE", "loadBalancers": [attachment],
            "networkConfiguration": {"awsvpcConfiguration": network}, "healthCheckGracePeriodSeconds": 90,
            "deploymentConfiguration": {"minimumHealthyPercent": 0, "maximumPercent": 100},
            "tags": [{"key": TAG["Key"], "value": OWNER}],
        })
    else:
        require(service["loadBalancers"] == [attachment] and service["desiredCount"] == 1
                and service["networkConfiguration"]["awsvpcConfiguration"] == network,
                "La configuración del servicio existente requiere revisión")
    return target_arn


def metadata_probe(refresh_neighbor=False):
    return f"""python3 - <<'PY'
import errno
import json
import socket
import struct
import subprocess

address, port = {ADDRESS!r}, {PORT}
refresh = {refresh_neighbor!r}

def ip_json(*arguments):
    result = subprocess.run(['ip', '-j', '-4', *arguments], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)

route = ip_json('route', 'get', address)[0]
interface = route['dev']
print('Ruta desde', route.get('prefsrc', route.get('src', '?')), 'dev', interface,
      'via', route.get('gateway', 'directa'), flush=True)

def neighbor():
    entries = ip_json('neigh', 'show', 'to', address, 'dev', interface)
    return entries[0] if entries else {{}}

def connect():
    try:
        return socket.create_connection((address, port), timeout=7)
    except OSError as error:
        entry = neighbor()
        states = entry.get('state', [])
        print('Primer intento:', type(error).__name__, 'vecino:', states, entry.get('lladdr', '-'), flush=True)
        retryable = isinstance(error, TimeoutError) or error.errno == errno.EHOSTUNREACH
        if not refresh or not retryable or route.get('gateway') or not entry or {{'PERMANENT', 'NOARP'}} & set(states):
            raise
        subprocess.run(['ip', '-4', 'neigh', 'del', address, 'dev', interface],
                       capture_output=True, text=True, check=True)
        print('Vecino del broker renovado. Reintentando TCP.', flush=True)
        try:
            return socket.create_connection((address, port), timeout=7)
        except OSError:
            entry = neighbor()
            print('Vecino después del reintento:', entry.get('state', []), entry.get('lladdr', '-'), flush=True)
            raise

def receive(connection, length):
    content = bytearray()
    while len(content) < length:
        chunk = connection.recv(length - len(content))
        if not chunk:
            raise OSError('Kafka cerró la conexión')
        content.extend(chunk)
    return content

with connect() as connection:
    request = struct.pack('>hhih', 3, 0, 1, 3) + b'ev3' + struct.pack('>i', 0)
    connection.sendall(struct.pack('>i', len(request)) + request)
    length = struct.unpack('>i', receive(connection, 4))[0]
    if not 8 <= length <= 1048576:
        raise ValueError('Respuesta Kafka inesperada')
    data = receive(connection, length)
    correlation, count = struct.unpack_from('>ii', data)
    if correlation != 1 or count != 1:
        raise ValueError('Se esperaba exactamente un broker de laboratorio')
    _, size = struct.unpack_from('>ih', data, 8)
    advertised_host = data[14:14 + size].decode()
    advertised_port = struct.unpack_from('>i', data, 14 + size)[0]
    if (advertised_host, advertised_port) != (address, port):
        raise ValueError('Kafka anuncia una dirección distinta del bootstrap')
    print('Kafka Metadata OK', advertised_host, advertised_port)
PY"""


def print_balance_metrics(load_balancer):
    dimension = load_balancer["LoadBalancerArn"].split("loadbalancer/", 1)[1]
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=15)
    for metric in ("SecurityGroupBlockedFlowCount_Inbound", "SecurityGroupBlockedFlowCount_Outbound"):
        try:
            stats = aws("cloudwatch", "get-metric-statistics", "--namespace", "AWS/NetworkELB",
                        "--metric-name", metric, "--dimensions", f"Name=LoadBalancer,Value={dimension}",
                        "--start-time", start.isoformat(), "--end-time", end.isoformat(),
                        "--period", "60", "--statistics", "Sum")["Datapoints"]
            value = int(sum(point["Sum"] for point in stats)) if stats else "sin datos"
            print(f"NLB {metric} (15 min): {value}")
        except RecoveryError as error:
            print(f"No se pudo consultar la métrica del NLB: {error}")
            break


def verify(target_arn, *, refresh_neighbor=False, load_balancer=None):
    print("Esperando al broker y a su Target Group", flush=True)
    deadline = time.monotonic() + 480
    while time.monotonic() < deadline:
        status = aws("elbv2", "describe-target-health", "--target-group-arn", target_arn)
        if any(row["TargetHealth"]["State"] == "healthy" for row in status["TargetHealthDescriptions"]):
            break
        time.sleep(10)
    else:
        service = get_service() or {}
        message = next(iter(service.get("events", [])), {}).get("message", "sin eventos de ECS")
        raise RecoveryError(f"Kafka no quedó healthy. Último evento: {message}")
    command = aws("ssm", "send-command", payload={
        "InstanceIds": list(CLIENTS.values()), "DocumentName": "AWS-RunShellScript",
        "Comment": "Pedidos360 EV3 Kafka metadata",
        "Parameters": {"commands": [metadata_probe(refresh_neighbor)], "executionTimeout": ["30"]},
    })["Command"]["CommandId"]
    print(f"SSM Metadata: {command}", flush=True)
    deadline = time.monotonic() + 75
    results = {}
    while time.monotonic() < deadline:
        rows = aws("ssm", "list-command-invocations", "--command-id", command,
                   "--details")["CommandInvocations"]
        results = {row["InstanceId"]: row for row in rows}
        if len(results) == len(CLIENTS) and all(row["Status"] not in {"Pending", "InProgress", "Delayed"}
                                                for row in results.values()):
            break
        time.sleep(3)
    failed = []
    for name, instance in CLIENTS.items():
        row = results.get(instance, {})
        passed = row.get("Status") == "Success" and any(
            f"Kafka Metadata OK {ADDRESS} {PORT}" in plugin.get("Output", "")
            for plugin in row.get("CommandPlugins", []))
        print(f"{name}: {'Kafka Metadata OK' if passed else row.get('Status', 'sin respuesta SSM')}")
        if refresh_neighbor or not passed:
            for plugin in row.get("CommandPlugins", []):
                output = plugin.get("Output", "")
                if output.strip():
                    print(output.strip())
        if not passed:
            failed.append(name)
    if failed and load_balancer is not None:
        print_balance_metrics(load_balancer)
    require(not failed, "Queda pendiente verificar Kafka desde " + ", ".join(failed))


def main():
    global ACCOUNT, SUBNET, ADDRESS, CLIENTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-config", type=Path, default=Path.home() / "kafka_recovery.py",
                        help="archivo privado de CloudShell con los identificadores de la cuenta")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="crea y verifica Kafka privado en la cuenta EV3")
    mode.add_argument("--verify", action="store_true", help="prueba el Kafka existente sin recrearlo")
    parser.add_argument("--refresh-neighbor", action="store_true",
                        help="con --verify renueva solo el vecino del broker si falla la conexión TCP")
    args = parser.parse_args()
    if args.refresh_neighbor and not args.verify:
        parser.error("--refresh-neighbor requiere --verify")
    try:
        ACCOUNT, SUBNET, ADDRESS, CLIENTS = load_lab_config(args.lab_config)
        state = preflight()
        if args.apply:
            verify(deploy(*state))
        elif args.verify:
            vpc, _, load_balancer, service, _ = state
            require(load_balancer and service, "Se necesitan el NLB y el servicio de recuperación existentes")
            verify(target(vpc, create=False), refresh_neighbor=args.refresh_neighbor, load_balancer=load_balancer)
        else:
            print("Inspección correcta. --apply crea un NLB interno, dos grupos privados y un servicio Fargate.")
    except (RecoveryError, OSError, KeyError, ValueError, SyntaxError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
