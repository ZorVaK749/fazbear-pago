"""Inspect a private, validated copy of the live mounted H2 database."""

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler
import uuid
import zipfile

from clp_inventory_host import datasource
from webpay_host import Host, NoRedirect, RolloutError, env_values

NAME = "ms-productos"
OLD_IMAGE = "ghcr.io/zorvak749/fazbears-productos@sha256:cf5779c2fa85e461a222f826035b874b6f2fa312e47190077a3e2e61f6447c1f"
CLP_IMAGE = "ghcr.io/zorvak749/fazbears-productos@sha256:b6738b92eb0372d30782154e2c709b3f162c2afe87d03a46be84a42ef1ddee37"
STATE_DIR = Path("/var/lib/pedidos360-clp-productos")
ROW_SQL = "SELECT ID, NOMBRE, DESCRIPCION, PRECIO, CATEGORIA, IMAGEN_URL, STOCK FROM PRODUCTOS ORDER BY ID"
FIELDS = ("ID", "NOMBRE", "DESCRIPCION", "PRECIO", "CATEGORIA", "IMAGEN_URL", "STOCK")


@dataclass(frozen=True)
class Database:
    host_file: Path
    container_path: PurePosixPath
    options: str
    username: str
    password: str


def database(current):
    if datasource(current, "productos") != ("H2 en archivo con montaje", True):
        raise RolloutError("Se requiere una base H2 de archivo bajo un montaje persistente y verificable.")
    env = env_values(current["Config"]["Env"])
    if env.get("SPRING_PROFILES_ACTIVE") != "ev3-aws":
        raise RolloutError("El contenedor de Productos requiere revisión del perfil activo.")
    url = env.get("SPRING_DATASOURCE_URL") or env.get("PRODUCTOS_DB_URL") or (
        "jdbc:h2:file:/var/lib/fazbear/productos/productosdb;"
        "AUTO_SERVER=FALSE;DB_CLOSE_DELAY=-1;DB_CLOSE_ON_EXIT=FALSE")
    path, sep, settings = url.removeprefix("jdbc:h2:file:").partition(";")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path) or ".." in PurePosixPath(path).parts:
        raise RolloutError("La ruta H2 requiere revisión manual.")
    options = set(settings.upper().split(";")) - {""}
    if options - {"AUTO_SERVER=FALSE", "DB_CLOSE_DELAY=-1", "DB_CLOSE_ON_EXIT=FALSE", "IFEXISTS=TRUE"}:
        raise RolloutError("Las opciones JDBC de H2 requieren revisión manual.")
    db_path = PurePosixPath(path)
    mounts = [m for m in current["Mounts"] if PurePosixPath(m["Destination"]) in db_path.parents]
    mount = max(mounts, key=lambda m: len(PurePosixPath(m["Destination"]).parts))
    if mount["Type"] not in {"bind", "volume"} or not mount["RW"]:
        raise RolloutError("El montaje efectivo de H2 no es persistente y escribible.")
    root = Path(mount["Source"]).resolve(strict=True)
    relative = db_path.relative_to(PurePosixPath(mount["Destination"]))
    mounted_file = root / (str(relative) + ".mv.db")
    if mounted_file.resolve(strict=True) != mounted_file or not stat.S_ISREG(mounted_file.lstat().st_mode):
        raise RolloutError("No se encontró un archivo H2 regular en el montaje esperado.")
    user = env.get("SPRING_DATASOURCE_USERNAME", env.get("PRODUCTOS_DB_USER", "sa"))
    password = env.get("SPRING_DATASOURCE_PASSWORD", env.get("PRODUCTOS_DB_PASSWORD", ""))
    if not user.strip() or any(c in user + password for c in "\r\n\0"):
        raise RolloutError("El formato del usuario o la contraseña H2 requiere revisión manual.")
    return Database(mounted_file, db_path, sep + settings, user, password)


def sha256(path):
    with path.open("rb") as data:
        digest = hashlib.sha256()
        for block in iter(lambda: data.read(1024 * 1024), b""):
            digest.update(block)
        return digest.hexdigest()


def copy_stable(source, destination):
    """Check the copied bytes against two reads of the intact source."""
    if source.stat().st_size > shutil.disk_usage(destination.parent).free // 3:
        raise RolloutError("Espacio insuficiente para copias verificadas del catálogo.")
    first = sha256(source)
    with source.open("rb") as original, destination.open("xb") as backup:
        shutil.copyfileobj(original, backup, length=1024 * 1024)
        backup.flush()
        os.fsync(backup.fileno())
    if sha256(source) != first or sha256(destination) != first:
        raise RolloutError("H2 cambió mientras se copiaba. Haga la preparación con el catálogo en reposo.")
    fd = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return first


def catalog_rows(content):
    reader = csv.DictReader(io.StringIO(content, newline=""))
    if tuple(reader.fieldnames or ()) != FIELDS:
        raise RolloutError("La copia H2 no contiene la estructura de catálogo esperada.")
    rows = list(reader)
    ids, names = set(), set()
    for row in rows:
        price = Decimal(row["PRECIO"])
        pid, stock = int(row["ID"]), int(row["STOCK"])
        if (None in row or pid < 1 or pid in ids or not row["NOMBRE"].strip() or row["NOMBRE"] in names
                or stock < 0 or not price.is_finite() or price <= 0):
            raise RolloutError("La copia tiene productos, stock o precios que requieren revisión manual.")
        ids.add(pid)
        names.add(row["NOMBRE"])
    if len(rows) != 23:
        raise RolloutError(f"Se esperaban 23 productos y la copia contiene {len(rows)}.")
    return rows


def verify_prices(before, after, plan):
    original = {row["ID"]: row for row in before}
    if len(plan) != 23 or {row["ID"] for row in after} != original.keys():
        raise RolloutError("El catálogo de la copia candidata tiene una identidad distinta.")
    for row in after:
        previous = original[row["ID"]]
        if any(row[field] != previous[field] for field in FIELDS if field != "PRECIO"):
            raise RolloutError("La copia candidata cambió datos de catálogo o stock.")
        prices = plan.get(row["NOMBRE"])
        if prices is None or Decimal(previous["PRECIO"]) not in prices or Decimal(row["PRECIO"]) != prices[1]:
            raise RolloutError("Los precios de la copia candidata no coinciden con el plan CLP.")


def clone_database(db, backup, tag):
    directory = ".clp-" + tag
    parent = db.host_file.parent / directory
    parent.mkdir(mode=0o700)
    source_mode = db.host_file.stat()
    clone = parent / db.host_file.name
    copy_stable(backup, clone)
    os.chown(clone, source_mode.st_uid, source_mode.st_gid)
    os.chmod(clone, stat.S_IMODE(source_mode.st_mode) & 0o770)
    os.chown(parent, source_mode.st_uid, source_mode.st_gid)
    return clone, db.container_path.with_name(directory) / db.container_path.name


class ProductsHost(Host):
    def __init__(self):
        self.state_dir = STATE_DIR
        self.journal = STATE_DIR / "current.json"

    def source(self):
        current = self.inspect(NAME)
        if (current["Config"]["Image"] != OLD_IMAGE or not current["State"]["Running"]
                or current["State"]["Paused"] or current["HostConfig"]["AutoRemove"]):
            raise RolloutError("El contenedor de Productos cambió o no está en ejecución.")
        return current

    def h2_jar(self, current, work, plan):
        boot_jar = work / "app.jar"
        self.docker("cp", f"{current['Id']}:/app/app.jar", str(boot_jar),
                    failure="No se pudo leer el driver H2 de la imagen que ejecuta Productos.")
        with zipfile.ZipFile(boot_jar) as bundled:
            jdbc_jars = [name for name in bundled.namelist() if re.fullmatch(r"BOOT-INF/lib/h2-[0-9.]+\.jar", name)]
            if len(jdbc_jars) != 1:
                raise RolloutError("El ejecutable de Productos debe contener un solo driver H2.")
            (work / "h2.jar").write_bytes(bundled.read(jdbc_jars[0]))
            if plan:
                return {name: (Decimal(old), Decimal(clp)) for name, old, clp in
                        (line.split("\t") for line in
                         bundled.read("BOOT-INF/classes/precios-clp-v1.tsv").decode("utf-8").splitlines())}
        return None

    def read_catalog(self, current, db, backup, *, plan=False):
        with tempfile.TemporaryDirectory(prefix="verify-", dir=self.state_dir) as tmp:
            work = Path(tmp)
            prices = self.h2_jar(current, work, plan)
            shutil.copyfile(backup, work / "catalog.mv.db")
            command = [
                "docker", "--host", "unix:///var/run/docker.sock", "run", "--rm", "-i",
                "--network", "none", "--log-driver", "none", "--read-only", "--user", "0:0",
                "--mount", f"type=bind,src={work},dst=/work", "--entrypoint", "java",
                current["Image"], "-Duser.home=/work", "-cp", "/work/h2.jar", "org.h2.tools.Shell",
            ]
            # In stdin only. Never put database credentials in Docker arguments, SSM or logs.
            inputs = ["jdbc:h2:file:/work/catalog;IFEXISTS=TRUE;ACCESS_MODE_DATA=r", "",
                      db.username, db.password, f"CALL CSVWRITE('/work/catalog.csv', '{ROW_SQL}');"]
            if plan:
                inputs.append("CALL CSVWRITE('/work/migration.csv', 'SELECT VERSION FROM CATALOG_PRICE_MIGRATION');")
            env = {key: value for key, value in os.environ.items() if not key.startswith("DOCKER_")}
            subprocess.run(command, input="\n".join(inputs + ["exit", ""]).encode(),
                           capture_output=True, env=env, check=True, timeout=40)
            try:
                rows = catalog_rows((work / "catalog.csv").read_text(encoding="utf-8"))
                if plan and list(csv.DictReader((work / "migration.csv").read_text(encoding="utf-8").splitlines())) != [
                        {"VERSION": "clp-v1"}]:
                    raise RolloutError("La copia candidata no confirma la migración CLP.")
                return rows, prices
            except FileNotFoundError:
                raise RolloutError("El driver H2 no pudo consultar la copia. Verifique credenciales y compatibilidad.") from None

    def prepare(self):
        current = self.source()
        db = database(current)
        tag = uuid.uuid4().hex[:12]
        backup = self.state_dir / f"prepare-{tag}.mv.db"
        digest = copy_stable(db.host_file, backup)
        self.read_catalog(current, db, backup)
        self.save({"id": tag, "container": current["Id"], "sha256": digest}, "prepared")
        print("Respaldo preliminar abierto con el mismo driver H2 · 23 productos con stock verificado.")
        print(f"SHA256 de la copia: {digest}")
        self.status()

    def apply(self):
        current = self.source()
        prepared = self.state()
        if prepared.get("phase") != "prepared" or prepared.get("container") != current["Id"]:
            raise RolloutError("Ejecute --prepare sobre el contenedor actual antes del corte.")
        initial_backup = self.state_dir / f"prepare-{prepared['id']}.mv.db"
        if sha256(initial_backup) != prepared["sha256"]:
            raise RolloutError("El respaldo preliminar no coincide con su SHA256.")
        db = database(current)
        conf = current["Config"]
        if (conf["Entrypoint"] != ["java", "-jar", "app.jar"] or conf["WorkingDir"] != "/app"
                or conf.get("Cmd") or current["HostConfig"]["NetworkMode"] in {"host", "none"}):
            raise RolloutError("El arranque o la red de Productos requiere revisión para el corte.")
        # Resolve the complete runtime configuration and pull the image before interrupting service.
        self.candidate_config(current, {}, image=CLP_IMAGE, replace_keys=set())
        self.docker("pull", CLP_IMAGE, failure="No se pudo preparar la imagen CLP.")
        state = {"id": uuid.uuid4().hex[:12], "previous": current["Id"], "prepared": prepared["id"]}
        self.save(state, "stopping")
        try:
            self.docker("stop", "-t", "35", current["Id"])
            stopped = self.inspect(current["Id"])
            if stopped["State"]["Running"] or stopped["State"]["ExitCode"] not in {0, 143}:
                raise RolloutError("Productos no terminó con un cierre ordenado.")
            backup = self.state_dir / f"cold-{state['id']}.mv.db"
            state["sha256"] = copy_stable(db.host_file, backup)
            before, _ = self.read_catalog(current, db, backup)
            clone, path = clone_database(db, backup, state["id"])
            state["database"] = str(path)
            options = db.options.rstrip(";")
            if "IFEXISTS=TRUE" not in options.upper().split(";"):
                options += ";IFEXISTS=TRUE"
            overrides = {"SPRING_DATASOURCE_URL": f"jdbc:h2:file:{path}{options}",
                         "EV3_AWS_CATALOG_MIGRATE_CLP": "true"}
            self.stage(state, current, db, overrides, clone, before)
            print(f"Respaldo en frío SHA256: {state['sha256']}")
            print("Migración verificada en copia · mismos 23 IDs y stock por producto.")
            config = self.candidate_config(current, overrides, image=CLP_IMAGE, replace_keys=set())
            state["candidate"] = self.create(self.candidate_name(state), config)
            self.save(state, "prepared_for_switch")
            self.docker("rename", current["Id"], f"{NAME}-before-clp-{state['id']}")
            self.docker("rename", state["candidate"], NAME)
        except (RolloutError, OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError,
                InvalidOperation, zipfile.BadZipFile) as error:
            self.recover(state)
            detail = f" Motivo: {error}" if isinstance(error, RolloutError) else ""
            raise RolloutError("Se canceló el corte y se restauró el contenedor original de Productos." + detail) from None

        # From this point the new database can receive legitimate traffic and stock changes.
        self.save(state, "activation_requested")
        self.docker("start", state["candidate"])
        self.wait_http(state["candidate"])
        self.save(state, "active")
        print("Productos CLP responde en el puerto 8081.")

    def stage(self, state, current, db, overrides, clone, before):
        isolated = dict(overrides, EV3_AWS_CATALOG_SNAPSHOT="false", EV3_KAFKA_INITIAL_DELAY_MS="900000",
                        SPRING_KAFKA_BOOTSTRAP_SERVERS="127.0.0.1:1",
                        SPRING_RABBITMQ_ADDRESSES="127.0.0.1:1",
                        SPRING_RABBITMQ_LISTENER_SIMPLE_AUTO_STARTUP="false",
                        SPRING_RABBITMQ_LISTENER_DIRECT_AUTO_STARTUP="false")
        config = self.candidate_config(current, isolated, image=CLP_IMAGE, replace_keys=set())
        config.pop("NetworkingConfig", None)
        config["HostConfig"] = dict(config["HostConfig"], NetworkMode="bridge", PortBindings={},
                                    PublishAllPorts=False, RestartPolicy={"Name": "no"},
                                    LogConfig={"Type": "json-file", "Config": {"max-size": "5m"}})
        test = self.create(f"{NAME}-clp-test-{state['id']}", config)
        state["stage"] = test
        self.save(state, "validating_copy")
        try:
            self.docker("start", test)
            deadline = time.monotonic() + 85
            while time.monotonic() < deadline:
                if not self.inspect(test)["State"]["Running"]:
                    raise RolloutError("El contenedor de prueba no completó el arranque.")
                if b"Started ProductosApplication" in self.docker("logs", "--tail", "40", test):
                    time.sleep(8)
                    break
                time.sleep(2)
            else:
                raise RolloutError("La copia candidata no quedó lista para comprobar el catálogo.")
        finally:
            self.docker("stop", "-t", "15", test)
        candidate = self.inspect(test)
        if candidate["State"]["Running"] or candidate["State"]["ExitCode"] not in {0, 143}:
            raise RolloutError("El contenedor de prueba no terminó con un cierre ordenado.")
        before_start, price_plan = self.read_catalog(candidate, db, clone, plan=True)
        verify_prices(before, before_start, price_plan)
        self.docker("rm", test)

    def candidate_name(self, state):
        return f"{NAME}-clp-{state['id']}"

    def recover(self, state):
        if state.get("phase") not in {"stopping", "validating_copy", "prepared_for_switch"}:
            raise RolloutError("Recuperación automática disponible solo antes de activar el candidato.")
        stage = self.find(state["stage"]) if "stage" in state else None
        if stage and stage["State"]["Running"]:
            self.docker("stop", "-t", "15", stage["Id"])
        previous = self.inspect(state["previous"])
        displaced = self.find(NAME)
        if displaced and displaced["Id"] != previous["Id"]:
            if displaced["Id"] != state.get("candidate") or displaced["State"]["Running"]:
                raise RolloutError("El nombre activo requiere revisión antes de recuperar Productos.")
            self.docker("rename", displaced["Id"], self.candidate_name(state))
        if previous["Name"] != "/" + NAME:
            self.docker("rename", previous["Id"], NAME)
        if not previous["State"]["Running"]:
            self.docker("start", previous["Id"])
        self.wait_http(previous["Id"])
        self.save(state, "recovered")

    def wait_http(self, expected_id):
        opener = build_opener(ProxyHandler({}), NoRedirect())
        deadline = time.monotonic() + 70
        while time.monotonic() < deadline:
            if self.inspect(NAME)["Id"] != expected_id:
                raise RolloutError("El nombre activo cambió durante la verificación.")
            try:
                with opener.open("http://127.0.0.1:8081/api/productos", timeout=2) as response:
                    if response.status == 200:
                        return
            except HTTPError as error:
                if error.code == 401:
                    return
            except (URLError, OSError):
                pass
            time.sleep(3)
        raise RolloutError("Productos no respondió en el puerto 8081. Revise --status.")

    def status(self):
        state = self.state()
        print(f"Productos CLP · fase {state.get('phase', 'none')}")
        if state.get("phase") == "prepared":
            print(f"Respaldo preliminar privado: prepare-{state['id']}.mv.db")
        if "previous" in state:
            print(f"Contenedor anterior: {state['previous'][:12]}")
        if "candidate" in state:
            print(f"Contenedor CLP: {state['candidate'][:12]}")
        if "database" in state:
            print(f"Ruta H2 CLP en el contenedor: {state['database']}")


def main(args):
    os.umask(0o077)
    mode, = args
    host = ProductsHost()
    try:
        if mode == "status":
            host.status()
        elif mode in {"prepare", "apply", "recover"}:
            with host.locked():
                if mode == "recover":
                    host.recover(host.state())
                else:
                    getattr(host, mode)()
        else:
            raise RolloutError("Modo no admitido.")
    except RolloutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, InvalidOperation, zipfile.BadZipFile):
        print("ERROR: No se completó la comprobación de H2. Revise el diario; la salida de credenciales se conservó privada.",
              file=sys.stderr)
        return 1
    return 0
