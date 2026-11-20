# Validación y despliegue de los extras EV3

Validar primero la entrega base y conservar el [manifiesto anterior](IMAGENES_EV3_2026-11-18.md)
como referencia de rollback. Las ramas de trabajo son `ev3/webpay-integracion`
en Pago, Orden, Pedidos y Angular, y `ev3/analytics-extras` en Analytics.
GitHub Actions valida y publica candidatos por digest. El equipo opera AWS.

## Imágenes verificadas en GHCR

| Servicio | Commit | GitHub Actions | Imagen para `docker pull` |
| --- | --- | --- | --- |
| Pago | `8592218` | [44433036627](https://github.com/ZorVaK749/fazbear-pago/actions/runs/44433036627) | `ghcr.io/zorvak749/fazbear-pago@sha256:2e93d9d7b905480c1704bbc31644ba3e2e67410fd1fe0da6ca8c54ac49c61c12` |
| Orden | `5d9de82` | [44432122848](https://github.com/ZorVaK749/fazbear-orden/actions/runs/44432122848) | `ghcr.io/zorvak749/fazbear-orden@sha256:201f125eb4090476ee5217aa26e06fe6de739c703cc229b80a3c84ae0b7dd875` |
| Pedidos | `579fe35` | [44431117247](https://github.com/ZorVaK749/fazbears-pedidos/actions/runs/44431117247) | `ghcr.io/zorvak749/fazbears-pedidos@sha256:e425eb1c1bda1f078e478a146eb94eb2aa478227bac888e280240201e9f00281` |
| Angular | `d4cd3f1` | [44432242966](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/44432242966) | `ghcr.io/zorvak749/fazbears-frontend@sha256:3a9f0f7cbc096712e24b264b7f4b0821db12f275d5ad94f7eb05ffec125528c5` |
| Analytics | `695de7e` | [44431691251](https://github.com/ZorVaK749/fazbear-analytics-recommendations/actions/runs/44431691251) | `ghcr.io/zorvak749/fazbear-analytics-recommendations@sha256:3d6a8cd2454a1a6af597b28f845bf87d089e0ec87430839c463422354529d87e` |

Carrito, Productos, Notificaciones, Reportes y Fidelización conservan sus
[digests de la entrega base](IMAGENES_EV3_2026-11-18.md).

La [fase obligatoria](https://github.com/ZorVaK749/fazbear-pago/actions/runs/44430271344)
verificó el cuarto intento bloqueado, la alerta única, su aislamiento por
usuario y el flujo completo de pago simulado, pedido, Kafka y FazCoins.
El [smoke de las ramas nuevas](https://github.com/ZorVaK749/fazbear-pago/actions/runs/44433036533)
cubre la compatibilidad de ese flujo con los extras desactivados.
Los casos de Webpay usan un proveedor de prueba controlado. Analytics ejercita
Kafka y un WebSocket real en CI, con DynamoDB sustituido por un cliente de
prueba. Su suite reportó 45 pruebas ejecutadas y una omitida. Angular pasó
11 archivos de pruebas, incluidos el retorno Webpay y la reconexión.
Una prueba directa de creación y consulta en el sandbox oficial devolvió
`INITIALIZED` con el monto, orden y sesión esperados. El recorrido de
aprobación desde el navegador queda pendiente del corte en AWS.

## Webpay Plus de integración

La activación de la imagen ya instalada en la EC2 de Pago se puede hacer con
el [comando SSM y el procedimiento de recuperación](../deploy/aws/README.md).

Pago conserva el endpoint simulado y su regla antifraude. La modalidad Webpay
usa la API REST oficial Webpay Plus v1.2 en `webpay3gint.transbank.cl`.
La regla de cuatro intentos en diez segundos se verifica con los instrumentos
simulados. El flujo Webpay no recibe un identificador estable de tarjeta antes
de autorizar, así que no aplica esa regla a partir de datos parciales de la tarjeta.
El monto sale de la cotización de Orden en CLP y debe ser entero. Angular
envía el token por formulario al dominio de integración de Transbank. El
backend verifica monto, orden de compra, sesión, estado `AUTHORIZED` y código
`0` antes de registrar `APPROVED`. Orden comprueba además el propietario,
tenant y cotización antes de crear un Pedido.

Pago serializa la reserva por cotización. Una transacción Webpay activa o de
resultado incierto impide el cobro simulado sobre esa cotización. Un retorno
de cancelación o expiración consulta el estado. Pago registra el retorno normal
en PostgreSQL antes de invocar el commit. Ante un commit de resultado incierto
se consulta el estado. El reintento por ID puede confirmar la misma transacción
si Pago registró el retorno normal y Transbank todavía informa `INITIALIZED`.
Ante una creación sin
respuesta se conserva la reserva incierta y se evita repetir la creación.
Un reinicio después de una aprobación puede recuperarse por el ID público del
pago usando la cuenta que hizo la compra.

En esta entrega, Webpay de integración queda identificado como
`WEBPAY_INTEGRACION` en el contrato interno y como
`APPROVED_WEBPAY_INTEGRATION` en Pedidos. El ledger académico FazCoins conserva
las aprobaciones y reversiones simuladas. La anulación por API queda disponible
para el simulador. Las respuestas Webpay de integración inician el flujo de
pedido correspondiente y quedan fuera de ese ledger académico.

### Configuración y rutas

- Pago aplica Flyway V3 a V5 a PostgreSQL. Orden aplica Flyway V2. En Pedidos H2
  y PostgreSQL se usan las columnas existentes. Respaldar previamente los
  tres almacenes. Revisar la matriz de datos y corte de la guía base.
- Usar `WEBPAY_ENABLED=true` solo tras levantar Pago, Orden, Pedidos y
  Angular compatibles. Cargar `WEBPAY_COMMERCE_CODE` y `WEBPAY_API_KEY`
  mediante el mecanismo privado del equipo. Definir
  `WEBPAY_RETURN_URL=https://<frontend>/checkout/webpay` con el origen
  HTTPS real. La URL debe abrir Angular directamente al recargar.
- API Gateway debe enrutar con JWT `access_as_user` estos endpoints de Pago:
  `GET /api/pagos/webpay/capacidad`, `POST /api/pagos/webpay`,
  `POST /api/pagos/webpay/retorno` y `POST /api/pagos/webpay/{id}/estado`.
  El preflight debe admitir el origen de Angular y `Idempotency-Key`.
- Revisar que el ingreso del frontend y los logs del navegador no persistan
  la query de retorno de Transbank. El token de transacción únicamente se
  usa para conciliar con el proveedor y nunca se imprime en evidencias.
  Angular limpia la query al procesarla.
- Probar con tarjetas e identidades de prueba documentadas por Transbank.
  Verificar aprobación, rechazo, cancelación, retorno después de expirar,
  reintento en la misma cuenta y recuperación de una respuesta perdida.
  Confirmar que el pedido se crea una vez y que el flujo simulado conserva
  su alerta antifraude y movimientos FazCoins.

[Guía Webpay Plus de Transbank](https://github.com/TransbankDevelopers/transbank-developers-docs/blob/master/documentacion/webpay-plus/README.md)
· [Referencia REST de Transbank](https://github.com/TransbankDevelopers/transbank-developers-docs/blob/master/referencia/webpay/README.md)

La prueba automatizada de Pago simula la REST de Transbank y comprueba los
métodos HTTP, una interrupción en commit y estado, la evidencia guardada
en PostgreSQL y la posterior recuperación del mismo pago. Angular prueba el
reintento de confirmación con la misma clave ante un fallo de Orden. La
validación contra el sandbox de Transbank se realiza después del despliegue.

Un pago iniciado antes de Flyway V5 puede no tener registrado el retorno.
Si sigue pendiente después de actualizar, conservar la pestaña y reenviar
el POST original de retorno desde el panel Red del navegador con la misma
cuenta. Así Pago puede reconocer el retorno sin iniciar otra transacción.
Mantener el cuerpo y los encabezados del retorno dentro del navegador.

### Release de recuperación del retorno

Actualizar primero Pago y comprobar Flyway V5 y la salud del Target Group.
El script conserva el entorno y el contenedor anterior, y verifica el SHA256
de una copia privada de los registros de pago antes del corte. La migración
agrega un indicador a `webpay_transaction` y usa el mismo PostgreSQL.
En una interrupción, consultar `--status` o `--verify` con el mismo digest.

```bash
python3 deploy/aws/webpay_release.py --apply --image \
  ghcr.io/zorvak749/fazbear-pago@sha256:f1c7dc048ab725b16e585d49d0442d7850a2af4625c11e97740c949734ebf608 &&
python3 deploy/aws/frontend_image.py --apply --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:573dedf028c811125f904c73a75d4bb6957382e3b972323033c8af3436406b48
```

[CI de Pago](https://github.com/ZorVaK749/fazbear-pago/actions/runs/44654639004)
· [CI de Angular](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/44654645553)

- [x] Respaldar los registros de Pago y comprobar su SHA256.
- [x] Confirmar Pago con Flyway V5, Webpay de integración activo y Target Group healthy.
- [x] Confirmar estable en ECS la revisión `:5` de Fargate con el digest de recuperación.
- [ ] Conciliar el intento de 25.980 CLP y confirmar el pedido asociado.

El catálogo de FazCoins conserva los endpoints protegidos de Fidelización.
Si un GET autenticado recibe `404 Ruta no encontrada`, comprobar la regla
del listener y el Target Group de Fidelización antes de publicar cambios
en el Gateway. La UI informa indisponibilidad de FazCoins sin cambiar la
verificación de Webpay.

El inventario del stage confirmó las cuatro rutas de Fidelización en
`integrations/qamokas`. La búsqueda por el puerto 8089 no encontró un Target
Group. Las búsquedas por nombre de Fidelización y FazCoins no encontraron
un Target Group, una instancia EC2 etiquetada o un servicio en el clúster
`pedidos360-ev3-infra`. Queda pendiente asignar una EC2 al microservicio.

Para desplegarlo, usar la imagen verificada
`ghcr.io/zorvak749/fazbear-fidelizacion@sha256:627283e9b8b68869ecd9ec8498bdf9423e9ef68e13f9f7c052eff486bd33b2c0`
con el perfil `ev3-aws`. Se puede reutilizar el servidor RDS actual con una
base y un usuario dedicados a Fidelización, y el broker Kafka de EV3.
Configurar `FIDELIZACION_DB_URL`, `FIDELIZACION_DB_USER`,
`FIDELIZACION_DB_PASSWORD`, `KAFKA_BOOTSTRAP_SERVERS`, `PAGO_URL`
y la clave compartida `INTERNAL_SERVICE_KEY` mediante el entorno privado
de la EC2. Publicar el puerto 8089 del host hacia el 8080 del contenedor.
Una vez confirmado `GET /health`, registrar la instancia en un Target Group
con health check `/health` y enlazar las rutas al destino mediante una regla
del listener interno. Verificar saldo, movimientos y recompensas con sesión
iniciada y usar un pago simulado para comprobar el abono de FazCoins.
[CI de Fidelización](https://github.com/ZorVaK749/fazbear-fidelizacion/actions/runs/44362087350)

### EC2 de Fidelización en AWS Academy

Desde CloudShell, en el clon operativo, comprobar el VPC, la integración JWT
existente y el listener, y crear una instancia `t3.micro` con créditos
estándar y un volumen raíz cifrado. El comando reutiliza la subred y el
perfil SSM de Pago. Si la subred usa IP pública para salir, conserva solo
los grupos reutilizables que carecen de entrada abierta a internet.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/fidelizacion.py --plan &&
python3 deploy/aws/fidelizacion.py --create-ec2
```

Las instancias `i-05bbd23de4ff0bdea` e `i-082693721a3cda5f9` terminaron
con `Client.UserInitiatedShutdown`. La segunda alcanzó `running` y terminó
antes de preparar PostgreSQL. Revisar el evento `TerminateInstances` con
un rol que tenga `cloudtrail:LookupEvents` para identificar el origen antes
de solicitar otro reemplazo.

```bash
aws cloudtrail lookup-events --region us-east-1 \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=i-082693721a3cda5f9 \
  --query 'Events[?EventName==`TerminateInstances`].{Hora:EventTime,Actor:Username,Id:EventId}' \
  --output table
```

El inventario de la cuenta mostró nueve EC2 en ejecución. La instancia
`ec2-frontend` (`i-0644c1d2ca954f9aa`) comparte el VPC de Pago y está
`Online` en SSM. Para alojar allí Fidelización, verificar el checkout
Fargate y la desconexión del Target Group anterior y ejecutar el
despliegue en un paso desde CloudShell.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/fidelizacion.py --reuse-frontend
```

El modo verifica que la instancia esté fuera de los grupos conectados a
balanceadores, comprueba que el puerto 8089 no tenga entrada pública y
prepara PostgreSQL. Añade el grupo de seguridad de Fidelización a la
lista de grupos existentes, etiqueta el destino y levanta su contenedor.
Conserva los discos, el nombre y los contenedores existentes. El
operador necesita además `ecs:DescribeServices`,
`ssm:DescribeInstanceInformation`, `ec2:ModifyInstanceAttribute` y
`ec2:CreateTags`. `--verify` puede comprobar el servicio en esa EC2.

Si la EC2 está etiquetada y PostgreSQL ya fue verificado desde Pago, pero
la conexión desde Fidelización falla, autorizar el puerto configurado en
RDS desde el grupo exclusivo de Fidelización. El modo requiere
`rds:DescribeDBInstances`, `ec2:DescribeNetworkInterfaces`,
`ec2:DescribeSecurityGroups` y `ec2:AuthorizeSecurityGroupIngress`.
Conserva las reglas existentes y reutiliza una regla equivalente.

```bash
python3 deploy/aws/fidelizacion.py --allow-rds --instance-id i-0644c1d2ca954f9aa &&
python3 deploy/aws/fidelizacion.py --reuse-frontend
```

Si la prueba de dependencias confirma RDS y Kafka pero falta el health
privado de Pago, autorizar `TCP/8087` desde el grupo exclusivo de
Fidelización. `--allow-pago` conserva los grupos y el contenedor de Pago.
Utiliza un grupo de Pago exclusivo si ya recibe tráfico del ALB en ese
puerto. En su defecto, crea un grupo exclusivo para esta conexión y quita
sus reglas de salida predeterminadas antes de asociarlo a Pago. El perfil
del operador debe poder consultar y actualizar los grupos EC2. Si hace
falta un grupo nuevo, también requiere `ec2:RevokeSecurityGroupEgress`.

```bash
python3 deploy/aws/fidelizacion.py --allow-pago --instance-id i-0644c1d2ca954f9aa &&
python3 deploy/aws/fidelizacion.py --reuse-frontend
```

Para reintentar con el laboratorio activo, indicar el ID de la instancia
que se confirmó terminada. `--retry-ec2` conserva una instancia dedicada
existente o solicita una sola EC2 por ID anterior y espera que arranque.
Comprueba el estado y los metadatos que AWS aún publica sobre el ID
anterior. Si AWS ya lo retiró de su inventario, el ID indicado por el
operador identifica el intento. Si la nueva instancia vuelve a terminar,
el script muestra el motivo de AWS.

```bash
python3 deploy/aws/fidelizacion.py --retry-ec2 ID_EC2_TERMINADA
```

Con la EC2 de Fidelización en ejecución, preparar la base y el usuario
dedicados y luego enlazar el microservicio al balanceador. Si la búsqueda
por etiquetas todavía no muestra la instancia, indicar su ID. El script
comprueba el estado, el VPC y la identidad de Fidelización mediante las
etiquetas o el token de lanzamiento registrado por EC2.

```bash
instance_id=ID_EC2_EN_EJECUCION
python3 deploy/aws/fidelizacion.py --prepare-db --instance-id "$instance_id" &&
python3 deploy/aws/fidelizacion.py --deploy --instance-id "$instance_id"
```

`--prepare-db` usa el RDS de Pago. Comprueba privilegios de PostgreSQL antes
de crear la base y el rol, genera una contraseña exclusiva y guarda la
configuración en Parameter Store. Si la base `fidelizacion` ya existe
vacía y pertenece al usuario de Pago, conserva el propietario y concede
al rol dedicado acceso a esa base y su esquema `public`. Si hay objetos o
el propietario es distinto, usa la configuración privada vigente cuando
esté disponible y comprueba el acceso. El
perfil SSM de Pago requiere leer y escribir el SecureString de Fidelización
y el perfil de la EC2 nueva requiere leerlo.

`--inspect-db` muestra qué bases de Fidelización existen en RDS, si Pago
es su propietario, cuántos objetos tienen y si hay un SecureString guardado.
Es de solo lectura y no muestra credenciales ni registros de clientes.

```bash
python3 deploy/aws/fidelizacion.py --inspect-db
```

Si Pago no es propietario y no hay configuración autorizada, intentar
la preparación con el secreto maestro ya administrado por RDS.

```bash
python3 deploy/aws/fidelizacion.py --prepare-db-admin &&
python3 deploy/aws/fidelizacion.py --reuse-frontend
```

El perfil de Pago necesita `rds:DescribeDBInstances`,
`secretsmanager:GetSecretValue` sobre el secreto maestro correspondiente
y `kms:Decrypt` si usa una clave de cliente. El script usa las credenciales
en memoria y guarda en Parameter Store únicamente la configuración del
usuario dedicado de Fidelización.

Si RDS no tiene un secreto maestro accesible, publicar el mismo asistente
en la EC2 de Pago y abrir una sesión interactiva con un administrador
autorizado. CloudShell prepara el asistente con `--stage-db-admin`.

```bash
python3 deploy/aws/fidelizacion.py --stage-db-admin
```

En EC2, seleccionar `i-0241836a7e45a2e3f` y abrir **Conectar → Session
Manager**. El operador necesita acceso a esa sesión y a `sudo` en la
instancia. Dentro de la sesión, ejecutar:

```bash
sudo python3 /var/lib/pedidos360-fidelizacion-db/admin.pyz
```

El asistente solicita el usuario y la contraseña del propietario en
prompts ocultos. Tras verificar PostgreSQL, ejecutar `--reuse-frontend`
desde CloudShell. Si la base contiene objetos, el propietario debe
revisar los permisos vigentes antes de definir el usuario del servicio.

Si el usuario de Pago carece de privilegios de creación o de asignación
del propietario, o el perfil no puede escribir en Parameter Store,
preparar la base desde una sesión administrativa PostgreSQL autorizada
dentro del VPC. Si `--prepare-db` dejó el rol y el SecureString listos,
crear solo la base con el propietario `fidelizacion` y repetir la
verificación. En una instalación nueva, desde `psql` conectado a
`postgres`, usar estos comandos solo si la base y el rol están ausentes:

```sql
CREATE ROLE fidelizacion LOGIN;
\password fidelizacion
CREATE DATABASE fidelizacion OWNER fidelizacion;
```

La URL JDBC debe usar la base `fidelizacion` o `fidelizacion_ev3` y TLS,
por ejemplo `jdbc:postgresql://HOST_RDS:5432/fidelizacion?sslmode=require`.
Iniciar `psql` con `-W` para que la contraseña del administrador se ingrese
en el prompt, desde una EC2 con conectividad autorizada a RDS. Usar el
bootstrap de Kafka y la clave interna que ya usa Pago. Cuando todavía no
exista el SecureString, `--set-config` recoge los valores con eco
desactivado y los guarda en la cuenta. Para una base existente usar el
usuario ya autorizado en esa base, con `USAGE` y `CREATE` en `public` y
acceso al historial Flyway y a los datos que ya existan. La EC2 lee el
parámetro mediante su perfil SSM.

```bash
python3 deploy/aws/fidelizacion.py --set-config &&
python3 deploy/aws/fidelizacion.py --deploy
```

El segundo comando instala Docker en la EC2 dedicada, comprueba alcance de
RDS, Kafka y Pago, levanta la imagen GHCR, verifica `/health`, registra el
destino y enlaza el prefijo de Fidelización al listener existente. El
Target Group debe quedar `healthy`. `--verify` comprueba el servicio y su
destino. Validar con sesión iniciada en el navegador.

El rol del operador necesita lectura del Gateway, VPC Link, EC2 y ALB,
`ec2:RunInstances`, permisos de etiquetas y creación de grupo de seguridad,
`iam:PassRole` para el perfil ya autorizado, creación de Target Group y
regla y registro de destinos del ALB. También requiere `ssm:PutParameter`
y permisos de Run Command. El perfil de la EC2 requiere acceso SSM y lectura
del SecureString con descifrado. Si un permiso del laboratorio falta, el
comando indica la operación AWS que falló.

## DynamoDB y dashboard

Analytics aplica Flyway V2 en su PostgreSQL. PostgreSQL mantiene la proyección
de recomendaciones. Solo al habilitar DynamoDB, el consumo de Kafka encola
el historial normalizado de interacciones en la misma transacción que las
proyecciones. El escritor usa `PutItem` condicional por evento, conserva las
entregas pendientes ante fallos y reconoce como entregado un evento ya presente.

- Usar una tabla aprobada con `pk` de tipo String, valor `tenant#owner`,
  y `sk` de tipo String, valor UUID del evento. Configurar TTL en
  `expiresAt` como Number en segundos Unix. La retención predeterminada
  es 30 días desde el evento. Habilitar con `ANALYTICS_DYNAMODB_ENABLED=true`,
  `ANALYTICS_DYNAMODB_TABLE`, `AWS_REGION` y, si procede,
  `ANALYTICS_DYNAMODB_RETENTION_DAYS`.
- Asignar al rol de la instancia EC2 o de la tarea ECS solo
  `dynamodb:PutItem` sobre el ARN de la tabla. El SDK descubre credenciales
  temporales por la cadena estándar. La retención y las consultas de
  comprobación corresponden al operador con su rol.
- Habilitar el dashboard con `ANALYTICS_DASHBOARD_ENABLED=true`,
  `ANALYTICS_DASHBOARD_ORIGIN=https://<frontend>` y
  `ANALYTICS_DASHBOARD_WSS_URL=wss://<ingreso-compatible>/ws/analytics`.
  Configurar TLS y soporte Upgrade WebSocket en un ingreso aprobado, por
  ejemplo un ALB con listener HTTPS, apuntando al mismo Analytics
  de puerto 8088 en EC2 o al contenedor de puerto 8080 en ECS.
  La ruta del API HTTP para emitir tickets y el endpoint WebSocket son
  conexiones independientes.
- Exponer `POST /api/analytics/me/dashboard-ticket` con JWT y
  `access_as_user`. Analytics valida el origen del WebSocket y consume un
  ticket de un uso en el primer frame. Abrir **Mi actividad**, generar una
  vista y actividad de carrito desde la misma cuenta y comprobar las tres
  métricas de la última hora y la reconexión. Probar con otra cuenta para
  verificar el aislamiento.

```bash
aws dynamodb describe-table --region "$AWS_REGION" --table-name "$ANALYTICS_DYNAMODB_TABLE" \
  --query 'Table.[TableStatus,KeySchema]'
aws dynamodb describe-time-to-live --region "$AWS_REGION" --table-name "$ANALYTICS_DYNAMODB_TABLE"
```

Política de escritura para el rol de Analytics. Sustituir región, cuenta y
tabla por el ARN confirmado del recurso aprobado.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "dynamodb:PutItem",
    "Resource": "arn:aws:dynamodb:REGION:ACCOUNT_ID:table/TABLE_NAME"
  }]
}
```

## Actualización controlada en AWS

Mantener las flags de extras deshabilitadas inicialmente. Confirmar los
digests de los commits probados, agregar las variables privadas al mecanismo
existente y respaldar antes de migrar. Levantar Pedidos, Orden, Pago y
Analytics compatibles antes de Angular. Activar cada extra por separado al
validar sus dependencias y rutas.

```bash
# Ejecutar dentro del repo del servicio en su EC2.
git fetch origin "$RELEASE_BRANCH"
git switch "$RELEASE_BRANCH"
git pull --ff-only origin "$RELEASE_BRANCH"
docker pull "$IMAGE_BY_DIGEST"
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE_BY_DIGEST"
```

Usar el inventario y los comandos de [sustitución por EC2](ENTREGA_AWS_EV3.md).
Mantener puertos, montajes, argumentos y redes del contenedor actual. Para
Analytics en una tarea ECS existente, registrar una revisión de su task
definition derivada de la revisión actual, cambiar solo la imagen y
configuración aprobada, y actualizar el servicio al ARN de la nueva revisión.
El broker Kafka existente conserva su task definition y datos.

```bash
aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
  --query 'services[0].[taskDefinition,desiredCount,runningCount,deployments[0].rolloutState]'
# task-reviewed.json contiene la definición lista para registrar, conservando
# roles, logs, volúmenes, red y port mappings. Secretos mediante referencias.
aws ecs register-task-definition --cli-input-json file://task-reviewed.json \
  --query 'taskDefinition.taskDefinitionArn' --output text
aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --task-definition "$NEW_TASK_DEFINITION_ARN"
aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
```

Para rollback, deshabilitar primero el extra afectado y mantener sus datos.
Con transacciones Webpay ya registradas, conservar binarios compatibles con
esa modalidad para reconciliar pendientes y evitar que Pago antiguo trate
una aprobación Webpay como un pago simulado. Conservar los respaldos, el
historial y la cola de entregas a DynamoDB. El catálogo vivo de 23 productos
y su stock se protegen con el procedimiento de la guía base.

## Release CLP

| Servicio | CI | Imagen verificada por digest |
| --- | --- | --- |
| Productos | [44588436397](https://github.com/ZorVaK749/fazbears-productos/actions/runs/44588436397) | `ghcr.io/zorvak749/fazbears-productos@sha256:b6738b92eb0372d30782154e2c709b3f162c2afe87d03a46be84a42ef1ddee37` |
| Carrito | [44587396847](https://github.com/ZorVaK749/fazbear-carrito/actions/runs/44587396847) | `ghcr.io/zorvak749/fazbear-carrito@sha256:0972d9b0082649b842d46fadab78c960b61d3699d7009bb6ea9a927ae3b04270` |
| Orden | [44587392466](https://github.com/ZorVaK749/fazbear-orden/actions/runs/44587392466) | `ghcr.io/zorvak749/fazbear-orden@sha256:29c351c0208ee67fff3c496b39305af67a22d6769fcb3574899a712918204f87` |
| Notificaciones | [44587395075](https://github.com/ZorVaK749/fazbear-notificaciones/actions/runs/44587395075) | `ghcr.io/zorvak749/fazbear-notificaciones@sha256:7338142218d895e20fd0710cea5e229e1de7b4ba5e03504032103a02cc7e72f8` |
| Frontend | [44587395754](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/44587395754) | `ghcr.io/zorvak749/fazbears-frontend@sha256:010cd44c011df91d13101b5f7be744861324161ca0803d760191f5ce1de53606` |

- [x] Publicar las cinco imágenes y verificar los digests en GHCR.
- [x] Confirmar H2 montado en Productos con el inventario SSM.
- [x] Abrir y verificar los respaldos de los 23 productos con el driver de H2 de la imagen activa.
- [x] Aplicar los precios CLP en una copia, comprobar IDs y stock, y confirmar el Target Group healthy.
- [x] Actualizar Carrito, Orden y Notificaciones por digest y verificar sus Target Groups.
- [x] Registrar la revisión Fargate `:4` con el digest CLP y comprobar el checkout público actualizado.
- [x] Confirmar que el catálogo vuelve a cargar desde el navegador con sesión iniciada.
- [x] Confirmar en ECS la revisión `:5` con el frontend CLP y la recuperación de Webpay.
- [ ] Validar carrito guardado, nueva cotización y pago Webpay en el entorno de integración.

La sesión del laboratorio recibió una denegación explícita de
`voc-cancel-cred` al consultar la revisión `:4` de Fargate. Una sesión
posterior confirmó estable la revisión `:5`. El checkout público entrega
el botón Webpay y el código CLP. Queda por confirmar el resultado del pedido.

Tras el HTTP 503 del catálogo, la consulta de EC2 devolvió `running`, el
Target Group devolvió `healthy` y el operador confirmó que el catálogo
volvió a cargar. La interfaz con el mensaje de error corregido pasó
[CI de Angular](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/44597769930)
y quedó publicada en GHCR para un despliegue posterior.

El orden del cambio, el comando de inventario y las condiciones para recuperar
el despliegue están en la [guía de CLP](../deploy/aws/README.md#cambio-de-catálogo-a-clp).
La [prueba integrada de CLP](https://github.com/ZorVaK749/fazbear-pago/actions/runs/44588570206)
usa un catálogo y pagos sintéticos en GitHub Actions.

Con Productos verificado y las compras pausadas, actualizar los tres backends
restantes y Fargate desde CloudShell. El comando de backends comprueba todos
los servicios antes de iniciar el primer corte.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/clp_backends.py --apply &&
python3 deploy/aws/frontend_image.py --apply --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:010cd44c011df91d13101b5f7be744861324161ca0803d760191f5ce1de53606
```

El script conserva la red, los montajes y la configuración de los
contenedores existentes. Configura `PRODUCTOS_URL` para que Carrito consulte
la IP privada actual de Productos. `--dry-run` adelanta el inventario;
`--status --service carrito` muestra el diario del servicio indicado.
`--verify --service carrito` comprueba una activación pendiente sin
reiniciar el contenedor. `--recover --service carrito` recupera un corte
interrumpido antes de iniciar el candidato.

Si el registro de una revisión de Fargate termina antes de que ECS confirme
estabilidad, retomar la comprobación de la revisión que ya usa el servicio.

```bash
python3 deploy/aws/frontend_image.py --verify --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:010cd44c011df91d13101b5f7be744861324161ca0803d760191f5ce1de53606
```
