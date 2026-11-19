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
import uuid
import zipfile

from clp_inventory_host import datasource
from webpay_host import Host, RolloutError, env_values

NAME = "ms-productos"
OLD_IMAGE = "ghcr.io/zorvak749/fazbears-productos@sha256:cf5779c2fa85e461a222f826035b874b6f2fa312e47190077a3e2e61f6447c1f"
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

    def h2_jar(self, current, work):
        boot_jar = work / "app.jar"
        self.docker("cp", f"{current['Id']}:/app/app.jar", str(boot_jar),
                    failure="No se pudo leer el driver H2 de la imagen que ejecuta Productos.")
        with zipfile.ZipFile(boot_jar) as bundled:
            jdbc_jars = [name for name in bundled.namelist() if re.fullmatch(r"BOOT-INF/lib/h2-[0-9.]+\.jar", name)]
            if len(jdbc_jars) != 1:
                raise RolloutError("El ejecutable de Productos debe contener un solo driver H2.")
            (work / "h2.jar").write_bytes(bundled.read(jdbc_jars[0]))

    def read_catalog(self, current, db, backup):
        with tempfile.TemporaryDirectory(prefix="verify-", dir=self.state_dir) as tmp:
            work = Path(tmp)
            self.h2_jar(current, work)
            shutil.copyfile(backup, work / "catalog.mv.db")
            command = [
                "docker", "--host", "unix:///var/run/docker.sock", "run", "--rm", "-i",
                "--network", "none", "--log-driver", "none", "--read-only", "--user", "0:0",
                "--mount", f"type=bind,src={work},dst=/work", "--entrypoint", "java",
                current["Image"], "-Duser.home=/work", "-cp", "/work/h2.jar", "org.h2.tools.Shell",
            ]
            # In stdin only. Never put database credentials in Docker arguments, SSM or logs.
            inputs = "\n".join(("jdbc:h2:file:/work/catalog;IFEXISTS=TRUE;ACCESS_MODE_DATA=r", "",
                                db.username, db.password,
                                f"CALL CSVWRITE('/work/catalog.csv', '{ROW_SQL}');", "exit", ""))
            env = {key: value for key, value in os.environ.items() if not key.startswith("DOCKER_")}
            subprocess.run(command, input=inputs.encode(), capture_output=True, env=env, check=True, timeout=40)
            try:
                return catalog_rows((work / "catalog.csv").read_text(encoding="utf-8"))
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

    def status(self):
        state = self.state()
        print(f"Productos CLP · fase {state.get('phase', 'none')}")
        if state.get("phase") == "prepared":
            print(f"Respaldo preliminar privado: prepare-{state['id']}.mv.db")


def main(args):
    os.umask(0o077)
    mode, = args
    host = ProductsHost()
    try:
        if mode == "status":
            host.status()
        elif mode == "prepare":
            with host.locked():
                host.prepare()
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
