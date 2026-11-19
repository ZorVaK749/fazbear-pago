# Activación Webpay en la EC2 de Pago

Ejecutar desde AWS CloudShell o un equipo con AWS CLI v2, Python 3.8 o posterior
y acceso al repositorio. El comando utiliza SSM para operar sobre la EC2
`i-0241836a7e45a2e3f` en `us-east-1`, con el contenedor `ev3-pago` y la
imagen [verificada en GHCR](https://github.com/ZorVaK749/fazbear-pago/actions/runs/44433036627)
fijada en `sha256:2e93d9d7b905480c1704bbc31644ba3e2e67410fd1fe0da6ca8c54ac49c61c12`.
La EC2 debe ser un nodo Linux administrado por SSM y tener Bash, Python, Docker,
`base64` y `gzip`. La modalidad SecureString también requiere AWS CLI en la EC2.
Antes de consultar el inventario, el script comprueba con STS que la sesión
corresponda a la cuenta de laboratorio `767398096661`.

## Uso

```bash
git clone -b ev3/webpay-integracion https://github.com/ZorVaK749/fazbear-pago.git
cd fazbear-pago
python3 deploy/aws/webpay.py --dry-run
python3 deploy/aws/webpay.py --apply
python3 deploy/aws/webpay.py --status
```

En un clon existente de la rama, actualizar con `git pull --ff-only`.
`--dry-run` y `--status` consultan AWS y emiten una invocación SSM de inspección.
El dry run verifica el entorno y los permisos del archivo sin leer valores de
SecureString. Si hay más de un Target Group que coincide, añadir
`--target-group-arn "$PAGO_TARGET_GROUP_ARN"` a cada comando. Para el corte se
exige que el registro de Pago en 8087 sea el único destino del grupo y que
comience en estado `healthy`.

Antes de activar, comprobar que `psql` está disponible para el rollback y
validar la lectura de credenciales desde la EC2 con
`python3 deploy/aws/webpay.py --dry-run --check-credentials`. Esta opción
comprueba acceso y formato en memoria. La salida muestra el sistema de la EC2
y el resultado de la comprobación.

En Amazon Linux 2023, `python3 deploy/aws/webpay.py --prepare-rollback`
instala el cliente `postgresql15` si falta y ensaya la consulta de solo lectura
contra RDS con el datasource de Pago. El contenedor continúa en ejecución.
El diagnóstico de un datasource ambiguo devuelve solo los nombres de variables.
Los límites conocidos de memoria de JVM y tamaño de pool se conservan en Pago.

Durante el corte hay una interrupción breve. El script valida que el contenedor
actual use la imagen fijada, el puerto 8087:8080, UID:GID 10001:10001, 640 MiB y
`unless-stopped`. Crea un candidato con la configuración Docker y el entorno
activos, modifica las cuatro variables Webpay, respalda el archivo, conserva
el contenedor anterior detenido y sustituye `pago.env` de forma atómica.
Usa la imagen local en EC2 por digest. Al finalizar exige HTTP 200 con modalidad
`SIMULATION_AND_WEBPAY_INTEGRATION` y salud del Target Group en observaciones
separadas por al menos un intervalo de health check.

El respaldo y el diario quedan en `/etc/pedidos360/ev3/.webpay-rollout/`, con
permisos de root. El contenedor anterior queda como
`ev3-pago-previous-<id>`. Conservar ambos durante la validación.
Confirmar en el frontend una transacción con Entra y tarjetas de integración.
La ruta autenticada `GET /api/pagos/webpay/capacidad` responde HTTP 204
cuando Webpay está habilitado. La respuesta se entrega sin cuerpo.
El script usa el retorno fijo
`https://p5gsy16utd.execute-api.us-east-1.amazonaws.com/checkout/webpay`.
Las rutas JWT existentes se mantienen.

## CORS de Webpay en el Gateway

Si el navegador bloquea el `OPTIONS` de Webpay o el Gateway responde 204
sin encabezados CORS, usar:

```bash
python3 deploy/aws/webpay_cors.py --dry-run
python3 deploy/aws/webpay_cors.py --apply
```

El comando revisa la cuenta y el stage `ev3`, y agrega el origen del frontend
y los métodos y encabezados faltantes a la política CORS del HTTP API
`uuzifgcyd2`. Conserva los valores existentes. El cambio se aplica al API,
cuya política CORS comparten sus stages. Para un stage con despliegue manual,
revisar los cambios pendientes antes de publicar. Las rutas y autorizadores
permanecen vigentes. El operador necesita `apigateway:GET` para el API y el
stage, y `apigateway:PATCH` sobre el API para aplicar.

`--verify` consulta los preflights de las cinco rutas del checkout y confirma
401 en capacidad sin JWT. Esa comprobación evita crear pagos o pedidos.

## Imagen de checkout en Fargate

`frontend_image.py --dry-run --image <GHCR@sha256:...>` identifica el servicio
activo de la familia `pedidos360-ev3-frontend-fg` y muestra la revisión actual.
`--apply` registra una revisión que conserva los roles, la configuración de
tarea y los contenedores existentes. Actualiza el servicio con el digest
indicado, espera a ECS y comprueba el botón Webpay en el JavaScript público.
`--verify` comprueba solamente el frontend público.

El operador requiere `ecs:ListClusters`, `ecs:ListServices`,
`ecs:DescribeServices`, `ecs:DescribeTaskDefinition`,
`ecs:RegisterTaskDefinition` y `ecs:UpdateService`. Cuando corresponda,
también requiere `iam:PassRole` para los roles actuales y `ecs:TagResource`
para conservar etiquetas. La salida registra la revisión anterior para
restaurarla desde ECS si el operador lo decide.

## Credenciales e IAM

**Opción principal, Parameter Store.** El responsable del laboratorio carga
dos parámetros `SecureString` en `us-east-1`, con los valores de integración
de la [referencia oficial de Transbank](https://github.com/TransbankDevelopers/transbank-developers-docs/blob/master/referencia/webpay/README.md).

Desde una sesión interactiva de CloudShell, ejecutar
`python3 deploy/aws/webpay.py --create-parameters`. Solicita ambos valores
con el eco de terminal desactivado. Los entrega a AWS CLI mediante un
archivo anónimo en memoria y los guarda en Parameter Store como
`SecureString` Standard y conserva parámetros que ya existan. Esta acción
requiere `ssm:PutParameter` para los dos nombres y usa la clave administrada
por AWS de Parameter Store. También se pueden crear desde la consola.

| Parámetro | Variable |
| --- | --- |
| `/pedidos360/ev3/webpay/commerce-code` | `WEBPAY_COMMERCE_CODE` |
| `/pedidos360/ev3/webpay/api-key` | `WEBPAY_API_KEY` |

El operador de CloudShell necesita:

- `ec2:DescribeInstances`, `elasticloadbalancing:DescribeTargetGroups` y
  `elasticloadbalancing:DescribeTargetHealth` para localizar y validar el destino.
- `ssm:SendCommand` limitado a
  `arn:aws:ec2:us-east-1:ACCOUNT_ID:instance/i-0241836a7e45a2e3f` y al documento
  `arn:aws:ssm:us-east-1::document/AWS-RunShellScript`. El documento permite
  ejecutar comandos como root en el nodo autorizado.
- `ssm:ListCommandInvocations` y `ssm:GetCommandInvocation` para consultar la ejecución.

El rol de la **EC2** conserva el acceso de nodo administrado de SSM y agrega
`ssm:GetParameters` limitado a estos recursos:

```text
arn:aws:ssm:us-east-1:ACCOUNT_ID:parameter/pedidos360/ev3/webpay/commerce-code
arn:aws:ssm:us-east-1:ACCOUNT_ID:parameter/pedidos360/ev3/webpay/api-key
```

Para una clave KMS administrada por el equipo, añadir `kms:Decrypt` sobre su
ARN y permitir al rol en la política de la clave. Usar condiciones de servicio
y contexto de cifrado para los dos parámetros si el laboratorio las admite.
La cuenta operadora necesita permisos de escritura de parámetros solo si
también le corresponde provisionarlos. El despliegue prefiere SecureString
frente a Secrets Manager por su alcance de dos parámetros y el uso de SSM
existente. El código y el key viajan desde Parameter Store a la EC2 y se
escriben localmente como configuración de root. Run Command recibe el
código del script y sus opciones.

**Alternativa si el laboratorio limita el rol.** Provisionar por un canal
privado autorizado `/etc/pedidos360/ev3/webpay.credentials` con propietario
`root`, modo `0600` y los dos campos `WEBPAY_COMMERCE_CODE` y
`WEBPAY_API_KEY` en formato `NOMBRE=valor`. Agregar `--source host-file`
a `--dry-run` y `--apply`. Cargar los valores fuera del historial de shell y
de sesiones grabadas. Tanto `pago.env` como el entorno Docker son accesibles
para administradores de la EC2. Evitar compartir sus volcados.

## Recuperación y rollback

```bash
python3 deploy/aws/webpay.py --status
python3 deploy/aws/webpay.py --recover
python3 deploy/aws/webpay.py --rollback
```

- **Antes de iniciar el candidato.** Un fallo recuperable restaura el
  contenedor anterior y los bytes originales de `pago.env`.
  `--recover` completa esa restauración si la sesión se interrumpió.
- **Después de solicitar el arranque.** El candidato pudo recibir tráfico
  aunque haya fallado SSM, el health o el Target Group. `--recover` recupera
  el mismo contenedor Webpay. Corregir primero la causa si el error persiste.
  Si el cliente se desconectó, consultar el Command ID de SSM para saber si
  el comando sigue ejecutándose antes de invocar recuperación.
- **Rollback después del arranque.** Ejecutar en ventana de mantenimiento
  y confirmar que esta EC2 es el único escritor de Webpay para el RDS.
  El script necesita `psql` en la EC2 y usa el datasource del contenedor.
  Detiene el candidato, ejecuta una consulta de solo lectura sobre
  `webpay_transaction` y `payment` con el usuario y search path del servicio, y restaura el anterior
  únicamente si la consulta demuestra la ausencia de transacciones Webpay.
  Ante registros o una consulta inconclusa, vuelve a iniciar el candidato.
  Con datos históricos o una configuración PostgreSQL personalizada, conservar
  Webpay habilitado y conciliar con el procedimiento operativo del equipo.

El rollback conserva PostgreSQL y las migraciones Flyway aplicadas. La
comprobación PostgreSQL usa TLS y admite una URL JDBC de un solo host con
`sslmode=require`, `verify-ca` o `verify-full`. Con verificación de CA, el
certificado debe estar disponible para `psql` en la EC2.

## Pruebas

```bash
python3 -B -m unittest discover -s deploy/aws/tests -v
```

GitHub Actions ejecuta estas pruebas aisladas con Docker, AWS y PostgreSQL
simulados en los límites del script. El workflow de prueba carece de rol AWS
y los cambios en `deploy/aws` no disparan una publicación GHCR nueva.
# Cambio de catálogo a CLP

El catálogo de la EV3 pasa a precios enteros en CLP con una equivalencia fija
de laboratorio de 1.000 CLP por unidad anterior. Los importes históricos de
pedidos, pagos y cotizaciones se conservan con el valor original registrado.
Los carritos guardados conservan sus ítems y cantidades y muestran los precios
vigentes desde Productos.

## Inventario de solo lectura

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/clp_inventory.py --service productos
```

El inventario muestra qué motor usa el contenedor, y si el directorio H2 tiene
un montaje de escritura. También admite `carrito`, `orden` y `notificaciones`.
Requiere `ssm:SendCommand` con `AWS-RunShellScript` sobre cada EC2 y
`ssm:ListCommandInvocations` y `ssm:GetCommandInvocation`. La EC2 debe estar
administrada por SSM. No se imprimen credenciales ni rutas de conexión.

## Orden del cambio

1. Pausar nuevas compras y cambios en el catálogo durante la ventana. Dejar
   terminar descuentos de stock en curso. Las cotizaciones nuevas tienen una
   vigencia configurada en Orden. Esperar que venzan las vigentes del catálogo
   anterior antes de reabrir compras. Mantener el mecanismo de confirmación
   para pagos Webpay ya aprobados.
2. Obtener un respaldo verificable de la fuente real de Productos y contrastar
   los 23 IDs, precios y cantidades en una restauración aislada. Para H2 usar
   [el respaldo del catálogo](../../docs/ENTREGA_AWS_EV3.md#respaldo-de-productos).
   Para PostgreSQL usar un dump consistente y restaurarlo en una base aislada.
   Si H2 vive solo en la JVM, conservar el contenedor activo hasta verificar
   una exportación lógica autorizada.
3. Probar Productos sobre una copia del catálogo antes del corte. Conservar
   el volumen y la configuración efectiva del servicio y activar
   `EV3_AWS_CATALOG_MIGRATE_CLP=true` en la nueva imagen. La migración valida
   nombres y valores esperados, actualiza precios dentro de una transacción
   y publica los 23 snapshots a través del outbox existente. Un valor distinto
   de los precios documentados detiene el arranque para revisión.
4. Desplegar Carrito con `PRODUCTOS_URL` igual al origen de Productos que usa
   Orden. La EC2 de Carrito debe alcanzar esa URL privada. Desplegar Orden y
   después Notificaciones, y comprobar salud y Target Groups. Pago, Pedidos,
   Analytics, Reportes y Fidelización conservan sus contratos actuales.
5. Desplegar el frontend con `frontend_image.py --apply --image <digest-GHCR>`.
   Verificar catálogo y carrito preexistente, incluida la Margherita a 12.990
   CLP. Comparar cada ID y stock con el respaldo antes de reabrir compras.
   Luego probar Webpay con una nueva cotización y tarjeta oficial de integración.

Conservar las imágenes anteriores y el respaldo. Solo restaurar precios a
partir del respaldo si todavía no se admitieron nuevas operaciones. Si ya
hubo compras, conservar los registros y conciliar las operaciones antes
de decidir una corrección. No se requiere modificar Pago ni la configuración
de Webpay para este cambio.
