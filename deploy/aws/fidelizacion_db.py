"""Prepare the dedicated PostgreSQL database through the existing Pago EC2."""

import base64
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import warnings
from urllib.parse import parse_qs, urlsplit

from fidelizacion_host import PARAMETER, role_environment, validate_config
from webpay_host import CONTAINER, IMAGE, Host, RolloutError, env_values, postgres_env

DATABASE = "fidelizacion"
PACKAGE = IMAGE.split("@", 1)[0]
SCHEMA_SUMMARY = """
    SELECT json_build_object(
        'objetos', (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                     WHERE n.nspname <> 'information_schema' AND n.nspname !~ '^pg_')
                 + (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                     WHERE n.nspname <> 'information_schema' AND n.nspname !~ '^pg_')
                 + (SELECT count(*) FROM pg_namespace WHERE nspname NOT IN ('public', 'information_schema') AND nspname !~ '^pg_'),
        'fidelizacion', (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                          WHERE n.nspname='public' AND c.relkind IN ('r', 'p') AND
                                c.relname IN ('wallet', 'payment_award', 'redemption', 'entitlement',
                                              'ledger', 'inbox', 'quarantine', 'flyway_schema_history')));
"""


def psql(environment, sql, failure, *, allow_failure=False):
    result = subprocess.run(["psql", "-X", "-w", "-qAt", "-v", "ON_ERROR_STOP=1"],
                            env=environment, input=sql.encode(), capture_output=True, timeout=20)
    if result.returncode:
        if allow_failure:
            return None
        raise RolloutError(failure)
    return result.stdout.strip().decode()


def stored_config():
    attempt = subprocess.run(["aws", "ssm", "get-parameter", "--region", "us-east-1", "--no-cli-pager",
                              "--output", "json", "--name", PARAMETER, "--with-decryption"],
                             env=role_environment(), capture_output=True, timeout=30)
    if attempt.returncode:
        if b"(ParameterNotFound)" in attempt.stderr:
            return None
        raise RolloutError("El perfil de Pago no pudo consultar el SecureString de Fidelización.")
    parameter = json.loads(attempt.stdout)["Parameter"]
    if parameter["Name"] != PARAMETER or parameter["Type"] != "SecureString":
        raise RolloutError("El parámetro de Fidelización debe ser SecureString.")
    return json.loads(parameter["Value"])


def put_config(config):
    # The value stays in an anonymous FD, never in command arguments or SSM output.
    payload = json.dumps({"Name": PARAMETER, "Value": json.dumps(config), "Type": "SecureString", "Overwrite": False})
    with os.fdopen(os.memfd_create("pedidos360-fidelizacion"), "w+b") as data:
        data.write(payload.encode())
        data.flush()
        data.seek(0)
        fd = data.fileno()
        result = subprocess.run(
            ["aws", "ssm", "put-parameter", "--region", "us-east-1", "--no-cli-pager",
             "--cli-input-json", f"file:///proc/self/fd/{fd}"],
            env=role_environment(), pass_fds=(fd,), capture_output=True, timeout=30,
        )
    if result.returncode:
        raise RolloutError("El perfil de Pago no pudo guardar el SecureString. Revise ssm:PutParameter.")


def scram(password):
    # PostgreSQL accepts a SCRAM verifier, so the cleartext isn't sent in a DDL statement.
    # Generated credentials use ASCII and do not need SASLprep normalization.
    iterations = 4096
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("ascii"), salt, iterations)
    client = hmac.digest(salted, b"Client Key", "sha256")
    stored = hashlib.sha256(client).digest()
    server = hmac.digest(salted, b"Server Key", "sha256")
    salt64, stored64, server64 = (base64.b64encode(value).decode() for value in (salt, stored, server))
    return f"SCRAM-SHA-256${iterations}:{salt64}${stored64}:{server64}"


def schema_summary(connection, database):
    result = psql(dict(connection, PGDATABASE=database), SCHEMA_SUMMARY,
                  "No se pudo consultar el esquema de Fidelización.")
    return json.loads(result)


def inspect_database(connection):
    admin = dict(connection, PGDATABASE="postgres")
    summary = json.loads(psql(admin, """
        SELECT json_build_object(
            'puede_crear_roles', (SELECT rolcreaterole FROM pg_roles WHERE rolname=current_user),
            'puede_crear_bases', (SELECT rolcreatedb FROM pg_roles WHERE rolname=current_user),
            'rol_fidelizacion_existe', EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fidelizacion'),
            'bases', COALESCE((SELECT json_object_agg(datname, pg_get_userbyid(datdba)=current_user)
                               FROM pg_database WHERE datname IN ('fidelizacion', 'fidelizacion_ev3')), '{}'::json));
        """, "No se pudo consultar el catálogo de RDS desde Pago."))
    for name, owned in summary["bases"].items():
        try:
            details = schema_summary(admin, name)
        except RolloutError:
            details = {"estado_esquema": "sin acceso desde Pago"}
        summary["bases"][name] = {"propiedad_de_pago": owned, **details}
    summary["configuracion_guardada"] = stored_config() is not None
    print(json.dumps(summary, indent=2), flush=True)


def aws_json(arguments, failure):
    result = subprocess.run(["aws", "--region", "us-east-1", "--no-cli-pager", "--output", "json", *arguments],
                            env=role_environment(), capture_output=True, timeout=30)
    if result.returncode:
        raise RolloutError(failure)
    return json.loads(result.stdout)


def find_rds(connection):
    described = aws_json(["rds", "describe-db-instances"],
                         "El perfil de Pago no pudo consultar RDS. Use --stage-db-admin con un administrador autorizado.")
    candidates = [db for db in described["DBInstances"] if db["Engine"] == "postgres"
                  and db.get("Endpoint", {}).get("Address") == connection["PGHOST"]
                  and db["Endpoint"]["Port"] == int(connection["PGPORT"])]
    if len(candidates) != 1:
        raise RolloutError("No se encontró el RDS exacto de Pago. Use --stage-db-admin con un administrador autorizado.")
    return candidates[0]


def managed_admin(connection):
    database = find_rds(connection)
    secret_id = (database.get("MasterUserSecret") or {}).get("SecretArn")
    if not secret_id:
        raise RolloutError("RDS no informa un secreto maestro administrado. Use --stage-db-admin.")
    result = aws_json(["secretsmanager", "get-secret-value", "--secret-id", secret_id],
                      "El perfil de Pago no pudo leer el secreto maestro de RDS. Use --stage-db-admin.")
    secret = json.loads(result["SecretString"])
    if secret.get("username") != database["MasterUsername"] or not secret.get("password"):
        raise RolloutError("El secreto administrado no coincide con el usuario maestro de ese RDS.")
    return dict(connection, PGUSER=secret["username"], PGPASSWORD=secret["password"])


def rds_network(connection):
    config = stored_config()
    address, port = validate_config(config)
    if (address, port) != (connection["PGHOST"], int(connection["PGPORT"])):
        raise RolloutError("La configuración de Fidelización no apunta al RDS de Pago.")
    database = find_rds(connection)
    print(json.dumps({"identifier": database["DBInstanceIdentifier"], "port": port}), flush=True)


def admin_prompt(connection):
    if not sys.stdin.isatty():
        raise RolloutError("Abra una sesión interactiva de Session Manager en la EC2 de Pago.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        username = getpass.getpass("Usuario administrador de RDS (oculto): ").strip()
        password = getpass.getpass("Contraseña de RDS (oculta): ")
    if not username or not password or username == connection["PGUSER"]:
        raise RolloutError("Se requiere una cuenta de RDS autorizada para administrar Fidelización.")
    return dict(connection, PGUSER=username, PGPASSWORD=password)


def verify_existing(admin, config, values):
    address, port = validate_config(config)
    uri = urlsplit(config["FIDELIZACION_DB_URL"].removeprefix("jdbc:"))
    if ((address, port) != (admin["PGHOST"], int(admin["PGPORT"]))
            or config["FIDELIZACION_DB_USER"] == admin["PGUSER"]):
        raise RolloutError("El SecureString debe usar el mismo RDS y un usuario exclusivo de Fidelización.")
    if config["INTERNAL_SERVICE_KEY"] != values.get("INTERNAL_SERVICE_KEY"):
        raise RolloutError("La clave privada de Fidelización difiere de la configurada en Pago.")
    app = dict(admin, PGDATABASE=uri.path[1:], PGUSER=config["FIDELIZACION_DB_USER"],
               PGPASSWORD=config["FIDELIZACION_DB_PASSWORD"], PGSSLMODE=parse_qs(uri.query)["sslmode"][0])
    ready = psql(app, """
        SELECT has_schema_privilege('public', 'USAGE') AND has_schema_privilege('public', 'CREATE');
        """, "La conexión a la base existente falló con el usuario guardado en el SecureString.")
    if ready != "t":
        raise RolloutError("El usuario de Fidelización requiere USAGE y CREATE en el esquema public de su base.")
    print("PostgreSQL de Fidelización verificado con la configuración existente.", flush=True)


def bootstrap(connection, values):
    admin = dict(connection, PGDATABASE="postgres")
    config = stored_config()
    if config is not None:
        validate_config(config)
    jdbc = f"jdbc:postgresql://{admin['PGHOST']}:{admin['PGPORT']}/{DATABASE}?sslmode={admin['PGSSLMODE']}"
    inventory = psql(admin, """
        SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fidelizacion'),
               COALESCE((SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='fidelizacion'), '-'),
               (SELECT rolcreaterole FROM pg_roles WHERE rolname=current_user),
               (SELECT rolcreatedb FROM pg_roles WHERE rolname=current_user);
        """, "No se pudo comprobar el RDS existente desde Pago.")
    role, owner, create_role, create_database = inventory.split("|")
    foreign_owner = owner not in {"-", DATABASE}
    reusable_empty = (foreign_owner and owner == admin.get("PGUSER")
                      and schema_summary(admin, DATABASE)["objetos"] == 0)
    if config is not None and (foreign_owner or config.get("FIDELIZACION_DB_URL") != jdbc
                               or config.get("FIDELIZACION_DB_USER") != DATABASE):
        try:
            verify_existing(admin, config, values)
            return
        except RolloutError:
            # Resume only our interrupted provisioning of an empty database.
            if not reusable_empty or (config["FIDELIZACION_DB_URL"], config["FIDELIZACION_DB_USER"]) != (jdbc, DATABASE):
                raise
    if foreign_owner and not reusable_empty:
        raise RolloutError("La base existente requiere sus credenciales y permisos vigentes. "
                           "Use --prepare-db-admin o --stage-db-admin con el propietario, o --set-config si ya tiene un usuario autorizado.")
    if (role != "t" and create_role != "t") or (owner == "-" and create_database != "t"):
        raise RolloutError("El usuario de Pago no puede crear roles y bases. Se requiere el administrador de RDS.")
    if config is None:
        if role == "t" or (owner != "-" and not foreign_owner):
            raise RolloutError("RDS ya tiene un rol o base de Fidelización. Use sus credenciales vigentes en --set-config.")
        config = {
            "FIDELIZACION_DB_URL": jdbc,
            "FIDELIZACION_DB_USER": DATABASE,
            "FIDELIZACION_DB_PASSWORD": secrets.token_urlsafe(32),
            "KAFKA_BOOTSTRAP_SERVERS": values.get("SPRING_KAFKA_BOOTSTRAP_SERVERS") or values.get("KAFKA_BOOTSTRAP_SERVERS", ""),
            "INTERNAL_SERVICE_KEY": values.get("INTERNAL_SERVICE_KEY", ""),
        }
        validate_config(config)
        put_config(config)
    validate_config(config)
    if config["FIDELIZACION_DB_URL"] != jdbc or config["FIDELIZACION_DB_USER"] != DATABASE:
        raise RolloutError("El SecureString existente corresponde a otro PostgreSQL o usuario.")
    if config["INTERNAL_SERVICE_KEY"] != values.get("INTERNAL_SERVICE_KEY"):
        raise RolloutError("La clave privada de Fidelización difiere de la configurada en Pago.")

    private_password = config["FIDELIZACION_DB_PASSWORD"]
    writer = dict(admin, PGOPTIONS="-c lock_timeout=5000 -c statement_timeout=15000")
    app = dict(admin, PGUSER=DATABASE, PGPASSWORD=private_password)
    if role != "t":
        if not private_password.isascii():
            raise RolloutError("Para crear el rol con ese formato de contraseña use psql y su administrador.")
        verifier = scram(private_password)
        psql(writer, f"CREATE ROLE {DATABASE} LOGIN PASSWORD '{verifier}';",
             "PostgreSQL no pudo crear el rol dedicado de Fidelización.")
    if owner == "-":
        if psql(app, "SELECT 1;", "", allow_failure=True) != "1":
            raise RolloutError("El rol dedicado no pudo autenticarse. Revise el SecureString antes de crear la base.")
        psql(writer, f"CREATE DATABASE {DATABASE} OWNER {DATABASE};",
             "PostgreSQL no pudo crear la base. Revise que el administrador pueda asignar el rol fidelizacion como propietario.")
    elif foreign_owner:
        psql(dict(writer, PGDATABASE=DATABASE), f"""
            BEGIN;
            GRANT CONNECT ON DATABASE {DATABASE} TO {DATABASE};
            GRANT USAGE, CREATE ON SCHEMA public TO {DATABASE};
            COMMIT;
            """, "El propietario no pudo otorgar los permisos de esquema al usuario de Fidelización.")
        verify_existing(admin, config, values)
        return
    psql(dict(app, PGDATABASE=DATABASE), "SELECT 1;",
         "La base de Fidelización existe, pero la conexión con su usuario no se pudo verificar.")
    print("PostgreSQL de Fidelización verificado. SecureString listo para desplegar.", flush=True)


def main(args):
    os.umask(0o077)
    try:
        if (args not in ([], ["inspect"], ["managed-admin"], ["interactive-admin"], ["rds-network"])
                or not Path("/var/run/docker.sock").is_socket()):
            raise RolloutError("La preparación de la base debe ejecutarse en la EC2 de Pago.")
        host = Host()
        host.state_dir = Path("/var/lib/pedidos360-fidelizacion-db")
        with host.locked():
            pago = host.inspect(CONTAINER)
            image = pago["Config"]["Image"]
            if not image.startswith(PACKAGE + "@sha256:") or not pago["State"]["Running"]:
                raise RolloutError("Se requiere el contenedor activo oficial de Pago.")
            variables = pago["Config"]["Env"]
            connection = postgres_env(variables)
            if args == ["inspect"]:
                inspect_database(connection)
            elif args == ["rds-network"]:
                rds_network(connection)
            else:
                if args == ["managed-admin"]:
                    connection = managed_admin(connection)
                elif args == ["interactive-admin"]:
                    connection = admin_prompt(connection)
                bootstrap(connection, env_values(variables))
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, EOFError, getpass.GetPassWarning, subprocess.SubprocessError):
        print("ERROR: No se pudo preparar PostgreSQL con la configuración privada de Pago.", file=sys.stderr)
        return 1
    return 0
