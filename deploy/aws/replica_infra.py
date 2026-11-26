#!/usr/bin/env python3
"""Provision the AWS foundation for a second Pedidos360 EV3 laboratory."""

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REGION = "us-east-1"
STACK = "pedidos360-ev3-respaldo"
TENANT = "ee0d2c5b-e60b-4c57-9b30-8a38a520c430"
AUDIENCE = "304fa289-2b72-447b-9c48-f00998f7c22f"
ORIGINAL_API = "uuzifgcyd2.execute-api.us-east-1.amazonaws.com"
SERVICES = {
    "Productos": (8081, "/api/productos", "/api/productos", "200,401"),
    "Pedidos": (8082, "/api/pedidos", "/api/pedidos", "200,401,403"),
    "Carrito": (8083, "/api/carrito", "/api/carrito/me", "200,401"),
    "Orden": (8084, "/api/orden", "/api/orden/health", "200,401"),
    "Notificaciones": (8085, "/api/notificaciones", "/api/notificaciones/health", "200,401"),
    "Reportes": (8086, "/api/reportes", "/api/reportes/health", "200"),
    "Pago": (8087, "/api/pagos", "/health", "200"),
    "Analytics": (8088, "/api/analytics", "/health", "200"),
    "Fidelizacion": (8089, "/api/fidelizacion", "/health", "200"),
}
KAFKA_CLIENTS = ("Productos", "Carrito", "Pago", "Analytics", "Fidelizacion")

BACKEND_METHODS = {
    # Productos
    "/api/productos": "GET POST",
    "/api/productos/{id}": "GET PUT DELETE",
    "/api/productos/categoria/{categoria}": "GET",
    "/api/productos/{id}/interacciones": "POST",
    # Carrito
    "/api/carrito/me": "GET",
    "/api/carrito/{usuarioId}": "GET DELETE",
    "/api/carrito/{usuarioId}/items": "POST",
    "/api/carrito/{usuarioId}/items/{itemId}": "DELETE",
    "/api/carrito/{usuarioId}/items/comprados": "DELETE",
    # Pedidos
    "/api/pedidos": "GET POST",
    "/api/pedidos/{id}": "GET DELETE",
    "/api/pedidos/usuario/{usuarioId}": "GET",
    "/api/pedidos/{id}/estado": "PUT",
    # Orden and checkout
    "/api/orden/health": "GET",
    "/api/orden/confirmar": "POST",
    "/api/orden/cotizaciones": "POST",
    "/api/orden/cotizaciones/{id}": "GET",
    "/api/orden/confirmar-pago": "POST",
    # Notificaciones and Reportes
    "/api/notificaciones/health": "GET",
    "/api/notificaciones/prueba-correo": "POST",
    "/api/reportes/resumen": "GET",
    "/api/reportes/ingresos": "GET",
    "/api/reportes/health": "GET",
    # Pago and Webpay
    "/api/pagos": "POST",
    "/api/pagos/{id}": "GET",
    "/api/pagos/me": "GET",
    "/api/pagos/{id}/anulacion": "POST",
    "/api/pagos/{id}/intentos": "GET",
    "/api/pagos/me/alertas": "GET",
    "/api/pagos/webpay": "POST",
    "/api/pagos/webpay/capacidad": "GET",
    "/api/pagos/webpay/retorno": "POST",
    "/api/pagos/webpay/{id}/estado": "POST",
    # Analytics and recommendations
    "/api/recomendaciones/me": "GET",
    "/api/analytics/me/resumen": "GET",
    "/api/analytics/me/dashboard-ticket": "POST",
    # Fidelizacion
    "/api/fidelizacion/me/saldo": "GET",
    "/api/fidelizacion/me/movimientos": "GET",
    "/api/fidelizacion/recompensas": "GET",
    "/api/fidelizacion/me/canjes": "POST",
}
BACKEND_ROUTES = tuple(f"{method} {path}" for path, methods in BACKEND_METHODS.items() for method in methods.split())


def ref(name):
    return {"Ref": name}


def attr(name, attribute):
    return {"Fn::GetAtt": [name, attribute]}


def sub(value, bindings=None):
    return {"Fn::Sub": value if bindings is None else [value, bindings]}


def resource(kind, condition=None, depends_on=None, **properties):
    definition = {"Type": kind, "Properties": properties}
    if condition:
        definition["Condition"] = condition
    if depends_on:
        definition["DependsOn"] = depends_on
    return definition


def endpoint(api):
    return attr(api, "ApiEndpoint")


def template():
    parameters = {
        "Ami": {"Type": "AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>",
                "Default": "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"},
        "InstanceProfile": {"Type": "String", "Default": "LabInstanceProfile"},
        "FrontendImage": {"Type": "String", "Default": "",
                          "AllowedPattern": r"^$|^ghcr\.io/zorvak749/fazbears-frontend@sha256:[a-f0-9]{64}$"},
        "DemoCidr": {"Type": "String", "Default": "", "AllowedPattern": r"^$|^[0-9.]+/32$"},
        "PublicAcme": {"Type": "String", "Default": "false", "AllowedValues": ["true", "false"]},
        "DataContainers": {"Type": "String", "Default": "false", "AllowedValues": ["true", "false"]},
        "CorsProxy": {"Type": "String", "Default": "false", "AllowedValues": ["true", "false"]},
    }
    outputs = {
        "Frontend": {"Value": sub("${Endpoint}/ev3/", {"Endpoint": endpoint("FrontendApi")})},
        "Backend": {"Value": sub("${Endpoint}/ev3/api", {"Endpoint": endpoint("BackendApi")})},
        "BackendApiId": {"Value": ref("BackendApi")},
        "WebpayReturn": {"Value": sub("${Endpoint}/ev3/checkout/webpay", {"Endpoint": endpoint("FrontendApi")})},
        "KafkaBootstrap": {"Value": sub("${KafkaNlb.DNSName}:9092")},
        "BackendAlbDns": {"Value": attr("Alb", "DNSName")},
        "AnalyticsElasticIp": {"Condition": "Demo", "Value": ref("AnalyticsEip")},
    }
    resources = {}

    def add(name, kind, **properties):
        resources[name] = resource(kind, **properties)

    def sg(name):
        add(name, "AWS::EC2::SecurityGroup", GroupDescription=f"EV3 replica {name}", VpcId=ref("Vpc"))

    def allow(name, group, port, *, source=None, cidr=None, condition=None):
        origin = {"SourceSecurityGroupId": ref(source)} if source else {"CidrIp": cidr}
        add(name, "AWS::EC2::SecurityGroupIngress", condition=condition, GroupId=ref(group),
            IpProtocol="tcp", FromPort=port, ToPort=port, **origin)

    add("Vpc", "AWS::EC2::VPC", CidrBlock="10.84.0.0/16", EnableDnsSupport=True, EnableDnsHostnames=True)
    add("Igw", "AWS::EC2::InternetGateway")
    add("IgwAttachment", "AWS::EC2::VPCGatewayAttachment", VpcId=ref("Vpc"), InternetGatewayId=ref("Igw"))
    add("Routes", "AWS::EC2::RouteTable", VpcId=ref("Vpc"))
    add("Outbound", "AWS::EC2::Route", depends_on="IgwAttachment", RouteTableId=ref("Routes"),
        DestinationCidrBlock="0.0.0.0/0", GatewayId=ref("Igw"))
    for index, name in enumerate(("SubnetA", "SubnetB")):
        add(name, "AWS::EC2::Subnet", VpcId=ref("Vpc"), CidrBlock=f"10.84.{index + 1}.0/24",
            AvailabilityZone={"Fn::Select": [index, {"Fn::GetAZs": ""}]})
        add(f"{name}Routes", "AWS::EC2::SubnetRouteTableAssociation",
            SubnetId=ref(name), RouteTableId=ref("Routes"))
    network_ready = ["Outbound", "SubnetARoutes", "SubnetBRoutes"]

    for group in ("LinkSg", "AlbSg", "FrontendSg", "KafkaNlbSg", "KafkaSg"):
        sg(group)
    allow("AlbFromLinkBackend", "AlbSg", 80, source="LinkSg")
    allow("AlbFromLinkFrontend", "AlbSg", 8080, source="LinkSg")
    allow("FrontendFromAlb", "FrontendSg", 80, source="AlbSg")
    allow("KafkaFromNlb", "KafkaSg", 9092, source="KafkaNlbSg")
    add("Alb", "AWS::ElasticLoadBalancingV2::LoadBalancer", Type="application", Scheme="internal",
        Subnets=[ref("SubnetA"), ref("SubnetB")], SecurityGroups=[ref("AlbSg")])
    add("BackendListener", "AWS::ElasticLoadBalancingV2::Listener", LoadBalancerArn=ref("Alb"), Protocol="HTTP",
        Port=80, DefaultActions=[{"Type": "fixed-response", "FixedResponseConfig": {"StatusCode": "404"}}])
    add("FrontendTarget", "AWS::ElasticLoadBalancingV2::TargetGroup", TargetType="ip", VpcId=ref("Vpc"),
        Protocol="HTTP", Port=80, HealthCheckPath="/")
    add("FrontendListener", "AWS::ElasticLoadBalancingV2::Listener", LoadBalancerArn=ref("Alb"), Protocol="HTTP",
        Port=8080, DefaultActions=[{"Type": "forward", "TargetGroupArn": ref("FrontendTarget")}])

    for index, (name, (port, prefix, health, codes)) in enumerate(SERVICES.items(), 1):
        group = f"{name}Sg"
        sg(group)
        allow(f"{name}FromAlb", group, port, source="AlbSg")
        size = "t3.small" if name == "Analytics" else "t3.micro"
        if name in ("Pago", "Notificaciones"):
            size = {"Fn::If": ["WithData", "t3.small", size]}
        add(name, "AWS::EC2::Instance", depends_on=network_ready, ImageId=ref("Ami"), InstanceType=size,
            IamInstanceProfile=ref("InstanceProfile"), MetadataOptions={"HttpTokens": "required"},
            NetworkInterfaces=[{"DeviceIndex": "0", "AssociatePublicIpAddress": True,
                                "SubnetId": ref("SubnetA"), "GroupSet": [ref(group)]}],
            UserData={"Fn::Base64": "#!/bin/bash\nset -eu\ndnf install -y docker\nsystemctl enable --now docker\n"},
            Tags=[{"Key": "Name", "Value": f"ev3-replica-{name.lower()}"}, {"Key": "Service", "Value": name}])
        target = f"{name}Target"
        add(target, "AWS::ElasticLoadBalancingV2::TargetGroup", VpcId=ref("Vpc"), TargetType="instance",
            Protocol="HTTP", Port=port, Targets=[{"Id": ref(name), "Port": port}],
            HealthCheckPath=health, Matcher={"HttpCode": codes})
        paths = [prefix, f"{prefix}/*"]
        if name == "Analytics":
            paths.extend(["/api/recomendaciones", "/api/recomendaciones/*"])
        add(f"{name}Route", "AWS::ElasticLoadBalancingV2::ListenerRule", ListenerArn=ref("BackendListener"),
            Priority=index, Conditions=[{"Field": "path-pattern", "Values": paths}],
            Actions=[{"Type": "forward", "TargetGroupArn": ref(target)}])
        outputs[f"{name}Instance"] = {"Value": ref(name)}
        outputs[f"{name}Ip"] = {"Value": attr(name, "PrivateIp")}

    for source, destination in (("Carrito", "Productos"), ("Orden", "Productos"), ("Orden", "Carrito"),
                                ("Orden", "Pago"), ("Orden", "Pedidos"), ("Pago", "Orden"),
                                ("Fidelizacion", "Pago")):
        allow(f"{destination}From{source}", f"{destination}Sg", SERVICES[destination][0], source=f"{source}Sg")
    for name in KAFKA_CLIENTS:
        allow(f"KafkaNlbFrom{name}", "KafkaNlbSg", 9092, source=f"{name}Sg")
    for name in ("Productos", "Pago", "Orden", "Analytics", "Fidelizacion"):
        allow(f"PostgresFrom{name}", "PagoSg", 5432, source=f"{name}Sg", condition="WithData")
    for name in ("Productos", "Orden", "Notificaciones", "Reportes"):
        allow(f"RabbitFrom{name}", "NotificacionesSg", 5672, source=f"{name}Sg", condition="WithData")
    allow("AlbProxyFromLink", "AlbSg", 8081, source="LinkSg", condition="WithData")
    allow("AnalyticsProxyFromAlb", "AnalyticsSg", 18080, source="AlbSg", condition="WithData")
    allow("AlbFromAnalyticsProxy", "AlbSg", 80, source="AnalyticsSg", condition="WithData")
    add("CorsProxyTarget", "AWS::ElasticLoadBalancingV2::TargetGroup", condition="WithData", VpcId=ref("Vpc"),
        TargetType="instance", Protocol="HTTP", Port=18080, Targets=[{"Id": ref("Analytics"), "Port": 18080}],
        HealthCheckPath="/health")
    add("CorsProxyListener", "AWS::ElasticLoadBalancingV2::Listener", condition="WithData", LoadBalancerArn=ref("Alb"),
        Protocol="HTTP", Port=8081, DefaultActions=[{"Type": "forward", "TargetGroupArn": ref("CorsProxyTarget")}])
    add("AnalyticsEip", "AWS::EC2::EIP", condition="Demo", depends_on="IgwAttachment",
        Domain="vpc", InstanceId=ref("Analytics"))
    allow("DemoHttps", "AnalyticsSg", 18443, cidr=ref("DemoCidr"), condition="Demo")
    allow("AcmeHttp", "AnalyticsSg", 80, cidr="0.0.0.0/0", condition="Acme")

    add("VpcLink", "AWS::ApiGatewayV2::VpcLink", Name=sub("${AWS::StackName}"),
        SubnetIds=[ref("SubnetA"), ref("SubnetB")], SecurityGroupIds=[ref("LinkSg")])
    for prefix in ("Frontend", "Backend"):
        api = f"{prefix}Api"
        cors = {"CorsConfiguration": {
            "AllowOrigins": [endpoint("FrontendApi")],
            "AllowHeaders": ["authorization", "content-type", "idempotency-key", "x-idempotency-key"],
            "AllowMethods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        }} if prefix == "Backend" else {}
        add(api, "AWS::ApiGatewayV2::Api", Name=sub(f"${{AWS::StackName}}-{prefix.lower()}"),
            ProtocolType="HTTP", **cors)
        integration = f"{prefix}Integration"
        listener = ref(f"{prefix}Listener")
        if prefix == "Backend":
            listener = {"Fn::If": ["UseCorsProxy", ref("CorsProxyListener"), listener]}
        add(integration, "AWS::ApiGatewayV2::Integration", ApiId=ref(api), ConnectionType="VPC_LINK",
            ConnectionId=ref("VpcLink"), IntegrationType="HTTP_PROXY", IntegrationMethod="ANY",
            IntegrationUri=listener, PayloadFormatVersion="1.0",
            RequestParameters={"overwrite:path": "$request.path"})
        integration_target = sub(f"integrations/${{{integration}}}")
        if prefix == "Backend":
            add("Entra", "AWS::ApiGatewayV2::Authorizer", Name="Microsoft-Entra", ApiId=ref(api),
                AuthorizerType="JWT", IdentitySource=["$request.header.Authorization"],
                JwtConfiguration={"Issuer": f"https://login.microsoftonline.com/{TENANT}/v2.0",
                                  "Audience": [AUDIENCE, f"api://{AUDIENCE}"]})
            for key in BACKEND_ROUTES:
                logical_id = "Route" + hashlib.sha256(key.encode()).hexdigest()[:16]
                authorization = {"AuthorizationType": "JWT", "AuthorizerId": ref("Entra"),
                                 "AuthorizationScopes": ["access_as_user"]}
                add(logical_id, "AWS::ApiGatewayV2::Route", ApiId=ref(api), RouteKey=key,
                    Target=integration_target, **authorization)
            stage_dependencies = [integration, "Entra"]
        else:
            for suffix, key in (("Root", "GET /"), ("Proxy", "ANY /{proxy+}")):
                add(f"Frontend{suffix}", "AWS::ApiGatewayV2::Route", ApiId=ref(api), RouteKey=key,
                    Target=integration_target, AuthorizationType="NONE")
            stage_dependencies = ["FrontendRoot", "FrontendProxy"]
        add(f"{prefix}Stage", "AWS::ApiGatewayV2::Stage", depends_on=stage_dependencies,
            ApiId=ref(api), StageName="ev3", AutoDeploy=True)

    add("Cluster", "AWS::ECS::Cluster", ClusterName=sub("${AWS::StackName}"))
    add("KafkaNlb", "AWS::ElasticLoadBalancingV2::LoadBalancer", Type="network", Scheme="internal",
        Subnets=[ref("SubnetA")], SecurityGroups=[ref("KafkaNlbSg")])
    add("KafkaTarget", "AWS::ElasticLoadBalancingV2::TargetGroup", VpcId=ref("Vpc"), TargetType="ip",
        Protocol="TCP", Port=9092)
    add("KafkaListener", "AWS::ElasticLoadBalancingV2::Listener", LoadBalancerArn=ref("KafkaNlb"),
        Protocol="TCP", Port=9092, DefaultActions=[{"Type": "forward", "TargetGroupArn": ref("KafkaTarget")}])
    kafka_env = {
        "KAFKA_NODE_ID": "1", "KAFKA_PROCESS_ROLES": "broker,controller",
        "KAFKA_LISTENERS": "PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093",
        "KAFKA_ADVERTISED_LISTENERS": sub("PLAINTEXT://${KafkaNlb.DNSName}:9092"),
        "KAFKA_CONTROLLER_QUORUM_VOTERS": "1@127.0.0.1:9093", "KAFKA_CONTROLLER_LISTENER_NAMES": "CONTROLLER",
        "KAFKA_INTER_BROKER_LISTENER_NAME": "PLAINTEXT",
        "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP": "PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT",
        "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1", "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR": "1",
        "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR": "1", "KAFKA_HEAP_OPTS": "-Xms512m -Xmx1024m",
    }
    frontend_command = f"""found=0
for bundle in /usr/share/nginx/html/*.js; do
  if grep -Fq '{ORIGINAL_API}' "$bundle"; then
    sed -i "s/uuzifgcyd2\\.execute-api\\.us-east-1\\.amazonaws\\.com/$BACKEND_HOST/g" "$bundle"
    found=1
  fi
done
test "$found" -eq 1
exec /docker-entrypoint.sh nginx -g 'daemon off;'
"""
    for name, image, port, cpu, memory, env, extra, condition in (
        ("Kafka", "apache/kafka:3.9.1", 9092, "1024", "3072", kafka_env, {}, None),
        ("Frontend", ref("FrontendImage"), 80, "256", "512",
         {"BACKEND_HOST": {"Fn::Select": [2, {"Fn::Split": ["/", endpoint("BackendApi")]}]}},
         {"EntryPoint": ["/bin/sh", "-ec"], "Command": [frontend_command]}, "WithFrontend"),
    ):
        add(f"{name}Task", "AWS::ECS::TaskDefinition", condition=condition, RequiresCompatibilities=["FARGATE"],
            NetworkMode="awsvpc", Cpu=cpu, Memory=memory,
            ContainerDefinitions=[{"Name": name.lower(), "Image": image, "Essential": True,
                                   "PortMappings": [{"ContainerPort": port}],
                                   "Environment": [{"Name": key, "Value": value} for key, value in env.items()], **extra}])
        add(f"{name}Service", "AWS::ECS::Service", condition=condition,
            depends_on=[f"{name}Listener", *network_ready], ServiceName=name.lower(), Cluster=ref("Cluster"),
            LaunchType="FARGATE", DesiredCount=1, TaskDefinition=ref(f"{name}Task"),
            DeploymentConfiguration={"MinimumHealthyPercent": 0 if name == "Kafka" else 100,
                                     "MaximumPercent": 100 if name == "Kafka" else 200,
                                     "DeploymentCircuitBreaker": {"Enable": True, "Rollback": True}},
            HealthCheckGracePeriodSeconds=60,
            LoadBalancers=[{"ContainerName": name.lower(), "ContainerPort": port,
                            "TargetGroupArn": ref(f"{name}Target")}],
            NetworkConfiguration={"AwsvpcConfiguration": {"AssignPublicIp": "ENABLED", "Subnets": [ref("SubnetA")],
                                                          "SecurityGroups": [ref(f"{name}Sg")]}})

    return {"AWSTemplateFormatVersion": "2010-09-09", "Description": "Pedidos360 EV3 replica foundation",
            "Parameters": parameters, "Resources": resources, "Outputs": outputs,
            "Conditions": {"Demo": {"Fn::Not": [{"Fn::Equals": [ref("DemoCidr"), ""]}]},
                           "Acme": {"Fn::And": [{"Condition": "Demo"}, {"Fn::Equals": [ref("PublicAcme"), "true"]}]},
                           "WithData": {"Fn::Equals": [ref("DataContainers"), "true"]},
                           "UseCorsProxy": {"Fn::And": [{"Condition": "WithData"},
                                                       {"Fn::Equals": [ref("CorsProxy"), "true"]}]},
                           "WithFrontend": {"Fn::Not": [{"Fn::Equals": [ref("FrontendImage"), ""]}]}}}


def aws(*arguments, capture=True):
    result = subprocess.run(["aws", *arguments, "--region", REGION, "--no-cli-pager", "--output", "json"],
                            text=True, capture_output=capture, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() if capture else "CloudFormation no completó el despliegue.")
    return json.loads(result.stdout) if capture else None


def deploy_stack(path, flags, parameters):
    try:
        aws("cloudformation", "deploy", "--stack-name", STACK, "--template-file", str(path),
            "--no-fail-on-empty-changeset", *flags, "--parameter-overrides", *parameters, capture=False)
    except RuntimeError:
        try:
            events = aws("cloudformation", "describe-stack-events", "--stack-name", STACK)["StackEvents"]
        except (OSError, RuntimeError, ValueError):
            events = []
        failures = {}
        for event in events:
            reason = event.get("ResourceStatusReason", "")
            if event["ResourceStatus"].endswith("_FAILED") and reason and "cancelled" not in reason.lower():
                failures.setdefault(event["LogicalResourceId"], reason)
        for resource_name, reason in failures.items():
            print(f"{resource_name}: {reason}", file=sys.stderr)
        raise


def verify_backend_routes(api_id):
    authorizers = aws("apigatewayv2", "get-authorizers", "--api-id", api_id)["Items"]
    entra = next((item for item in authorizers if item["Name"] == "Microsoft-Entra"), None)
    if not entra or entra["AuthorizerType"] != "JWT" or entra["JwtConfiguration"]["Issuer"] != (
        f"https://login.microsoftonline.com/{TENANT}/v2.0"
    ) or set(entra["JwtConfiguration"]["Audience"]) != {AUDIENCE, f"api://{AUDIENCE}"}:
        raise RuntimeError("El autorizador desplegado no coincide con Microsoft Entra.")
    routes = {item["RouteKey"]: item for item in aws("apigatewayv2", "get-routes", "--api-id", api_id)["Items"]}
    expected = set(BACKEND_ROUTES)
    missing = sorted(expected - routes.keys())
    extra = sorted(routes.keys() - expected)
    if missing or extra:
        raise RuntimeError(f"Rutas backend faltantes: {missing} · adicionales: {extra}")
    for key in BACKEND_ROUTES:
        route = routes[key]
        if (route["AuthorizationType"] != "JWT" or route.get("AuthorizerId") != entra["AuthorizerId"]
                or route.get("AuthorizationScopes") != ["access_as_user"]):
            raise RuntimeError(f"Autorización inesperada en {key}.")
    print(f"Backend {api_id} · {len(BACKEND_ROUTES)} rutas explícitas con JWT y access_as_user verificadas.")


def deploy(args):
    identity = aws("sts", "get-caller-identity")
    if identity["Account"] != args.account:
        raise RuntimeError("La sesión AWS no corresponde a la cuenta de destino indicada.")
    if not args.plan:
        existing = aws("ec2", "describe-instances", "--filters",
                       "Name=instance-state-name,Values=running,pending,stopping,stopped")
        other = [vm["InstanceId"] for reservation in existing["Reservations"] for vm in reservation["Instances"]
                 if {tag["Key"]: tag["Value"] for tag in vm.get("Tags", [])}
                 .get("aws:cloudformation:stack-name") != STACK]
        if other:
            raise RuntimeError("Hay EC2 fuera del stack en esta región y el despliegue crearía nueve nuevas: "
                               + ", ".join(other))
    with tempfile.TemporaryDirectory(prefix="pedidos360-replica-") as directory:
        path = Path(directory) / "replica.json"
        path.write_text(json.dumps(template(), separators=(",", ":")), encoding="utf-8")
        aws("cloudformation", "validate-template", "--template-body", path.resolve().as_uri())
        flags = ["--no-execute-changeset"] if args.plan else []
        parameters = [f"InstanceProfile={args.profile}"]
        if args.demo_cidr:
            parameters.append(f"DemoCidr={args.demo_cidr}")
        if args.public_acme is not None:
            parameters.append(f"PublicAcme={str(args.public_acme).lower()}")
        if args.frontend_image:
            parameters.append(f"FrontendImage={args.frontend_image}")
        if args.data_containers:
            parameters.append("DataContainers=true")
        if args.cors_proxy:
            parameters.append("CorsProxy=true")
        deploy_stack(path, flags, parameters)
    if not args.plan:
        stack = aws("cloudformation", "describe-stacks", "--stack-name", STACK)["Stacks"][0]
        for item in stack.get("Outputs", []):
            print(f"{item['OutputKey']} = {item['OutputValue']}")
        api_id = next(item["OutputValue"] for item in stack["Outputs"] if item["OutputKey"] == "BackendApiId")
        verify_backend_routes(api_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--render", action="store_true", help="print the CloudFormation template offline")
    mode.add_argument("--plan", action="store_true", help="create a change set without running it")
    mode.add_argument("--apply", action="store_true", help="deploy the foundation in the destination lab")
    parser.add_argument("--account", help="12-digit AWS account ID of the destination lab")
    parser.add_argument("--profile", default="LabInstanceProfile", help="existing EC2 instance profile name")
    parser.add_argument("--frontend-image", default="", help="published frontend GHCR digest")
    parser.add_argument("--demo-cidr", default="", help="public IPv4 /32 for access to Kafdrop via HTTPS")
    parser.add_argument("--public-acme", action=argparse.BooleanOptionalAction,
                        help="open or close HTTP-01 certificate validation on Analytics")
    parser.add_argument("--data-containers", action="store_true", help="prepare private PostgreSQL and RabbitMQ hosts")
    parser.add_argument("--cors-proxy", action="store_true", help="route the backend through the private CORS proxy")
    args = parser.parse_args()
    if args.render:
        print(json.dumps(template(), indent=2))
        return 0
    if not args.account or not re.fullmatch(r"[0-9]{12}", args.account):
        parser.error("--account debe ser el ID de 12 dígitos de la cuenta de destino")
    if args.frontend_image and not re.fullmatch(r"ghcr\.io/zorvak749/fazbears-frontend@sha256:[0-9a-f]{64}", args.frontend_image):
        parser.error("--frontend-image debe ser el digest de GHCR del frontend")
    try:
        if args.demo_cidr:
            demo = ipaddress.IPv4Network(args.demo_cidr)
            if demo.prefixlen != 32 or not demo.network_address.is_global:
                raise ValueError("--demo-cidr debe ser una IPv4 pública /32")
        elif args.public_acme:
            raise ValueError("--public-acme requiere --demo-cidr")
        deploy(args)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
