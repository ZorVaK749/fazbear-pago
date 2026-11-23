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
- [x] Consultar el intento de 25.980 CLP en Pago, Transbank y Orden.
- [x] Verificar Pago con Flyway V6 y el frontend en Fargate `:7`.
- [x] Confirmar el pedido de integración #65 por 11.990 CLP y comprobar la vista **Pago efectuado**.
- [x] Confirmar en AWS el cierre del intento vencido y la vuelta al checkout. La consulta autenticada del intento de CLP 25.980 devolvió HTTP 200 y `EXPIRED`.
- [ ] Validar en AWS la nueva verificación automática al volver de Transbank.

Para investigar ese intento desde CloudShell, usar una consulta de solo
lectura a Pago, Transbank de integración y la cotización en Orden:

```bash
python3 deploy/aws/webpay_payment_status.py --payment-id ID_DEL_INTENTO
```

La consulta muestra el estado local, la evidencia de retorno y el
resultado de Transbank. Si las referencias coinciden y Transbank confirma
`AUTHORIZED` con código `0`, verificar el mismo intento desde el checkout
para terminar la conciliación. Ante un error o estado incierto, conservar
el registro para evitar un pedido o pago duplicado. El diagnóstico de
Orden requiere `psql` en su EC2.

La consulta del intento de 25.980 CLP devolvió `PENDING` en Pago,
`INITIALIZED` en Transbank con referencias coincidentes y una cotización
sin pedido asociado. El frontend con la vista **Pago efectuado** quedó
estable en la revisión `:6` de Fargate.

Con Flyway V6, **Verificar el mismo pago** puede cerrar un intento de
integración como `EXPIRED` después de 30 minutos. Debe seguir pendiente,
carecer de retorno normal registrado y responder `INITIALIZED` sin código
de resultado, con monto y referencias coincidentes. Se conserva el
historial del intento. El checkout ofrece volver para una nueva cotización
cuando recibe `EXPIRED`.

Desde CloudShell, instalar Pago V6 y el frontend que interpreta
`EXPIRED`. Pago comprueba V5 antes del cambio, guarda un respaldo
y valida V6 y el Target Group al terminar.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/webpay_release.py --apply --migration 6 --image \
  ghcr.io/zorvak749/fazbear-pago@sha256:55b7339291e1f8453d19ab75623978dcf42a342517a0236671564f20665cee0d &&
python3 deploy/aws/frontend_image.py --apply --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:02b89a1406e4f1c9773ca5847ba3341083054d2073f8a6b988dc5c8ed04fb238
```

Con ambas imágenes activas, recargar la pestaña que conserva el intento,
pulsar **Verificar el mismo pago** si sigue disponible y confirmar el
mensaje de vencimiento y la vuelta al checkout.

[CI de Pago V6](https://github.com/ZorVaK749/fazbear-pago/actions/runs/44671595477)
· [CI de Angular](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/44671606376)
· [Integración EV3](https://github.com/ZorVaK749/fazbear-pago/actions/runs/44671595425)

### Verificación automática al volver de Transbank

El frontend muestra **Verificando pago** y comprueba el mismo intento.
Si el resultado sigue pendiente, realiza hasta tres consultas adicionales
antes de ofrecer el reintento manual. Cuando Orden confirma la compra,
la vista **Pago efectuado** muestra el monto y el número de pedido.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/frontend_image.py --apply --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:d48cfc9e73ee4b52844b3bbe7cad099e57e461e6895c0690e9a9186cfcfa6378
```

[CI del frontend](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/44745393022)

El catálogo de FazCoins conserva los endpoints protegidos de Fidelización.
Si un GET autenticado recibe `404 Ruta no encontrada`, comprobar la regla
del listener y el Target Group de Fidelización antes de publicar cambios
en el Gateway. La UI informa indisponibilidad de FazCoins sin cambiar la
verificación de Webpay.

### Recomendaciones, navegación e historial en CLP

- [x] Mostrar recomendaciones con las tarjetas del catálogo y ocultar estrategia, fecha de cálculo y motivo interno.
- [x] Compactar la navegación y habilitar el menú de cuenta con acceso a Perfil y Configuración.
- [x] Excluir del historial y de los totales del perfil los pedidos con importes fraccionarios. La API de Pedidos omite la moneda histórica, así que se usan el total y los precios unitarios para identificar los ejemplos heredados. Los pedidos siguen registrados en la base.
- [x] Verificar 134 pruebas de Angular, la compilación y el manifiesto publicado en GHCR.
- [x] Confirmar Fargate estable en la revisión `:9` y comprobar el botón Webpay en el checkout público.
- [x] Comprobar HTTP 200 en `/perfil`, `/actividad`, `/pedidos` y `/checkout`, y HTTP 404 al solicitar el archivo Angular anterior `chunk-Y7KOawDr.js`.
- [ ] Verificar con sesión iniciada `Mi actividad`, `Mi perfil`, `Configuración de cuenta` y el pedido `#65` en `Mis pedidos`.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/frontend_image.py --apply --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:77a21b84629487aa8133316f02b267d7e68feb089596fc7d045375c7f5316c0e
```

[CI y publicación del frontend](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/44748929352)

### Hora de Santiago en Mis pedidos

Pedidos registra `fecha_creacion` mediante `LOCALTIMESTAMP` para compras confirmadas y la API serializa el valor sin desplazamiento. En el despliegue EV3 la hora observada corresponde a UTC. El frontend la convierte a `America/Santiago` para mostrarla en formato de 24 horas. Los registros existentes conservan sus valores.

- [x] Verificar en CI 135 pruebas, incluida la conversión de `01:06 UTC` del 21 de noviembre a `22:06` del día anterior en Santiago.
- [x] Verificar el manifiesto de la nueva imagen en GHCR.
- [x] Confirmar Fargate estable en la revisión `:10` y verificar que `/pedidos` sirve el módulo con `America/Santiago` y formato de 24 horas.
- [x] Confirmar que el pedido `#97` muestre `20 nov 2026, 22:06` con sesión iniciada. Se observó en **Mis pedidos** el 22 de noviembre.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/frontend_image.py --apply --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:1edf966790467c7b9fc5f37c5420bb23d453bfbd2dcb880eb9fe55a098560e53
```

[CI y publicación de la corrección](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/44848399825)

### Estado de Fidelización en AWS

Despliegue confirmado en `ec2-frontend` (`i-0644c1d2ca954f9aa`) con
`deploy/aws/fidelizacion.py --reuse-frontend` en `4524761`. El contenedor
`ev3-fidelizacion` publica el puerto 8089 y el Target Group
`fazbear-tg-fidelizacion` enruta `/api/fidelizacion/*` desde el ALB interno.
El stage `ev3` conserva las cuatro rutas JWT en `integrations/qamokas`.

- [x] Verificar que el checkout público sigue servido por Fargate.
- [x] Verificar las credenciales dedicadas en `pedidos360-ev3-postgres`.
- [x] Comprobar desde la EC2 PostgreSQL por TCP/5432, Kafka por TCP/9092 y el health de Pago por HTTP/8087.
- [x] Confirmar HTTP 200 en `/health` y comprobar el digest del contenedor.
- [x] Confirmar el Target Group healthy en dos observaciones separadas por al menos 30 s.
- [x] Confirmar con sesión iniciada que el checkout muestra saldo, movimientos y recompensas. Se observó saldo de 0 Fz, movimientos vacíos e Insignia Faz VIP por 100 Fz. El canje devolvió 422 por saldo insuficiente.
- [x] Confirmar un movimiento `AWARD` de un pago simulado aprobado en CLP. El 22 de noviembre el checkout pasó de 0 a 675 Fz disponibles y mostró un abono de 675 Fz por la compra simulada de CLP 13.500.

Para la validación de solo lectura, abrir el checkout y pulsar
**Actualizar FazCoins**. Verificar HTTP 200 en saldo, movimientos y
recompensas. Un saldo cero con recompensas visibles es válido. Revisar los
movimientos existentes para confirmar un abono sin generar un pedido
adicional. Un nuevo pedido de prueba debe usar inventario de pruebas.

El despliegue utiliza la imagen verificada
`ghcr.io/zorvak749/fazbear-fidelizacion@sha256:627283e9b8b68869ecd9ec8498bdf9423e9ef68e13f9f7c052eff486bd33b2c0`
con el perfil `ev3-aws`. Se puede reutilizar el servidor RDS actual con una
base y un usuario dedicados a Fidelización, y el broker Kafka de EV3.
Configurar `FIDELIZACION_DB_URL`, `FIDELIZACION_DB_USER`,
`FIDELIZACION_DB_PASSWORD`, `KAFKA_BOOTSTRAP_SERVERS`, `PAGO_URL`
y la clave compartida `INTERNAL_SERVICE_KEY` mediante el entorno privado
de la EC2. El puerto 8089 del host apunta al 8080 del contenedor.
[CI de Fidelización](https://github.com/ZorVaK749/fazbear-fidelizacion/actions/runs/44362087350)

### Historial de FazCoins en el frontend

El checkout muestra el concepto, el importe en Fz y la hora de Santiago.
Los códigos del servicio y los identificadores internos quedan fuera de la
vista. Las 135 pruebas de Angular pasaron y el manifiesto se verificó en
GHCR. Fargate quedó estable en la revisión `:11`. Con sesión iniciada se
confirmó la vista del movimiento **Abono por compra simulada · +675 Fz**,
con fecha **22 nov 2026, 18:42** y saldo disponible de 675 Fz.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/frontend_image.py --apply --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:5f2b43acfe51345b3974a1914f4be77857ccdd7ab5ca5328b05d44fa5de1937e
```

[CI y publicación del historial](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/45073964424)

### EC2 de Fidelización en AWS Academy

Desde CloudShell, en el clon operativo, verificar el contenedor, el
listener y el Target Group de la EC2 en uso.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/fidelizacion.py --verify --instance-id i-0644c1d2ca954f9aa
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

## Stage ev3 del frontend

La entrega debe abrir en `https://p5gsy16utd.execute-api.us-east-1.amazonaws.com/ev3/`.
La ruta y el stage `$default` del Gateway se revisan por separado. El
procedimiento prepara rutas explícitas y un deployment del stage `ev3`
usando la integración existente de Fargate. El ingreso anterior permanece
disponible durante la transición de Entra y Webpay.

Fargate quedó estable en la revisión `:15`. CloudShell confirmó las rutas
explícitas del stage `ev3`, el checkout público y la redirección HTTP 303
del POST de retorno. El verificador también comprobó el checkout y el
POST sintético desde fuera de CloudShell.

Transbank usa POST al anular la compra en integración. La corrección de
Angular y Nginx mantiene el stage al redirigir al checkout y pasa los campos
del formulario al navegador en un fragmento temporal. [Documentación de Transbank](https://github.com/TransbankDevelopers/transbank-developers-docs/blob/master/documentacion/webpay-plus/README.md#resumen-de-flujos)

- [x] Desplegar Fargate `:15` y verificar el checkout y el POST de retorno sintético por `/ev3/`.
- [x] Configurar Pago con el retorno `/ev3/checkout/webpay`, comprobar Flyway V6 y verificar el Target Group.

El corte de Pago activó el digest `sha256:2a4c4fca0fe4b6895e0308609fea76c545879fb271e030d83ad4e6a74136dd19`.
El script generó el respaldo de PostgreSQL anterior al cambio y verificó su
SHA256. Pago respondió HTTP 200 y el Target Group estuvo healthy en dos
comprobaciones separadas por al menos 30 segundos.

1. Agregar `https://p5gsy16utd.execute-api.us-east-1.amazonaws.com/ev3/`
   a **Redirect URIs** de tipo **Single-page application** en el registro
   de la aplicación Entra. Conservar la URI actual durante las pruebas.
2. Desplegar Angular y preparar el stage de API Gateway desde CloudShell.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/frontend_gateway.py --dry-run &&
python3 deploy/aws/frontend_image.py --apply --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:b83a0c7bd4db18ef65de682203e0947c775b5218f4734329c7d9d424d3561c59 &&
python3 deploy/aws/frontend_gateway.py --prepare
```

Con el stage `ev3` ya preparado, usar `--apply --stage ev3` en
`frontend_image.py` y `--verify` en `frontend_gateway.py`. La prueba del
contenedor en CI comprueba el retorno GET y la redirección POST en ambas
rutas, así como el rechazo de campos repetidos.

3. Abrir `/ev3/` en una ventana privada e iniciar sesión. En **Menú**,
   añadir un producto si el carrito está vacío. Pulsar **Carrito** arriba
   a la derecha y **Proceder al pago** al pie del panel. Comprobar
   `/ev3/checkout` y, desde **Mis pedidos**, `/ev3/pedidos`. Cerrar sesión
   desde el menú de perfil y confirmar que la redirección conserva `/ev3/`.
4. Con la sesión validada, configurar el retorno nuevo de Pago y probar
   una compra Webpay de integración. El script exige que el stage
   nombrado esté desplegado, sirva Angular y redirija el POST de retorno
   con HTTP 303 antes de enviar cambios a Pago. La prueba usa un formulario
   sintético y termina en la redirección, sin consultar transacciones.
   La base permanece en Flyway V6.

```bash
cd "$HOME/pedidos360-ops-pago" &&
python3 deploy/aws/webpay_release.py --apply --migration 6 --return-stage ev3 --image \
  ghcr.io/zorvak749/fazbear-pago@sha256:2a4c4fca0fe4b6895e0308609fea76c545879fb271e030d83ad4e6a74136dd19
```

5. Hacer dos intentos de prueba desde el stage `ev3`. Primero aprobar
   una compra y comprobar el retorno a `/ev3/checkout/webpay` y el recibo
   **Pago efectuado**. Después iniciar otro intento y elegir **Anular
   compra** en Transbank. Comprobar el retorno a la misma ruta, el mensaje
   de cierre sin pago confirmado y que **Mis pedidos** muestre solo el
   pedido aprobado en estas pruebas.
6. Una vez conciliadas las transacciones iniciadas con la URL anterior,
   revisar el retiro de la ruta y del stage `$default` por separado y
   comprobar el acceso público por `/ev3/`. Después del retiro, usar
   `frontend_image.py --verify --stage ev3` en las verificaciones.

Antes de ese retiro, consultar el inventario Webpay en Pago. La consulta
de PostgreSQL agrupa por estado los intentos Webpay sin resolver y emite
solo totales. Incluye los intentos anteriores y posteriores al corte.

```bash
python3 deploy/aws/webpay_payment_status.py --pendientes-webpay &&
python3 deploy/aws/frontend_gateway.py --dry-run
```

CloudShell encontró un intento `PENDING`, las rutas explícitas completas y
la ruta y el stage `$default` presentes. Se debe cotejar el intento antiguo
de CLP 25.980 con Pago, Transbank y Orden antes de decidir su cierre.

La consulta previa a la recuperación confirmó que el intento de CLP 25.980 conservaba `PENDING`,
sin retorno registrado, con Transbank `INITIALIZED` y con Orden sin pedido
asociado. Para reconciliarlo, iniciar sesión con la cuenta original y abrir
`/ev3/checkout/webpay?recuperar=<UUID_DEL_PAGO>`. Pulsar **Verificar el mismo
pago**. El frontend usa la ruta de estado protegida por JWT y Pago aplica
su regla de vencimiento al intento existente. Después del mensaje de
vencimiento, volver a consultar
`webpay_payment_status.py --pendientes-webpay`.

```bash
python3 deploy/aws/frontend_image.py --apply --stage ev3 --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:75037433d018705160a25608f9e3b1ae796f2340e49c35e06a83e9c0ea87f0e9 &&
python3 deploy/aws/frontend_gateway.py --verify
```

[CI del frontend con recuperación del intento](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/45106202659)

- [x] Confirmar Fargate `:18` con el digest de recuperación y verificar que el módulo público de `/ev3/checkout/webpay` sirve **Verificar el mismo pago** desde el enlace de recuperación.

La verificación desde `/ev3/checkout/webpay` devolvió HTTP 200 y `EXPIRED`
para el intento de CLP 25.980. CloudShell volvió a consultar Pago y obtuvo
`total_sin_estado_final: 0`.

- [x] Confirmar que quedan cero intentos Webpay sin estado final en Pago.

### Retiro de `$default` del frontend

- [x] Retirar la ruta y el stage `$default` de Angular. El 23 de noviembre se verificaron por HTTPS `/ev3/`, el checkout y el retorno POST de Webpay. La raíz y una ruta sin coincidencia devolvieron HTTP 404.

CloudShell confirmó cero intentos pendientes antes del retiro y guardó
el respaldo en `~/pedidos360-frontend-default.json`.

En una ventana privada, abrir `/ev3/`, iniciar sesión y salir desde el menú
de perfil. Confirmar que el regreso de Entra conserva `/ev3/` y que
**Mis pedidos** abre con sesión iniciada. Después, aplicar el retiro desde
CloudShell.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/frontend_gateway.py --retire-default
```

El comando verifica las rutas públicas de `ev3`, vuelve a consultar el total
de pagos y conserva la configuración de la ruta y el stage anteriores en
`~/pedidos360-frontend-default.json`. Después retira ambos recursos del
Gateway de Angular y comprueba el checkout de `/ev3/`, el retorno POST
de Webpay y HTTP 404 en la raíz y en una ruta desconocida bajo `/ev3/`.
[Enrutamiento de HTTP API en AWS](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-routes.html#http-api-routing)

Para volver a habilitar el acceso anterior, ejecutar el comando de
restauración desde el mismo directorio. El comando comprueba nuevamente
el acceso público.

```bash
python3 deploy/aws/frontend_gateway.py --restore-default
```

[CI de Angular y Nginx](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/45085027149)
· [CI de Pago](https://github.com/ZorVaK749/fazbear-pago/actions/runs/45081571579)
· [CI de scripts AWS](https://github.com/ZorVaK749/fazbear-pago/actions/runs/45085224333)

### Sincronización del carrito tras Webpay

El navegador mostró el pedido `#131` por CLP 12.990 y la anulación de otro
intento volvió a `/ev3/checkout/webpay` con el mensaje de cierre sin pago
confirmado. El artículo de la compra aprobada permaneció en el carrito.

- [x] Confirmar la anulación desde Transbank bajo `/ev3/checkout/webpay` y que esa prueba no cree un pedido adicional.
- [x] Desplegar Carrito por digest y Fargate `:16`, verificar ambos servicios y comprobar el retorno sintético por `/ev3/`.
- [x] Confirmar Fargate `:17` con la corrección de reintentos y verificar el checkout y el retorno POST por `/ev3/`.
- [ ] Comprobar tras el despliegue que el contador y el carrito persistido se vacían al confirmar un pago con Webpay.

Carrito reutilizó el montaje H2 y su Target Group quedó healthy en dos
observaciones separadas por al menos 30 segundos. Fargate quedó estable en
`:16`. El JavaScript público de `/ev3/checkout` contiene la limpieza
condicional y el Gateway devolvió HTTP 303 para el POST de prueba.

La compra `#132` mostró **Pago efectuado** en `/ev3/checkout/webpay` y el
aviso de revisar el carrito. La limpieza autenticada queda pendiente de
diagnóstico. El Gateway respondió 401 sin JWT en la ruta de limpieza y
el preflight de esa ruta permitió `DELETE` con `authorization` desde el
frontend. FazCoins mostró los abonos previos del simulador, de acuerdo con
la política de fidelización de esta entrega.

Si Firefox perdió el registro de red, `cart_cleanup_status.py` revisa la
ruta y busca el estado HTTP alrededor de la hora de compra en los registros
de acceso de API Gateway. Es una consulta de solo lectura y su salida
excluye rutas completas, revisiones e identificadores de clientes.
La consulta del pedido `#132` confirmó la ruta por ítem con JWT. El stage
backend `ev3` carecía de un grupo de registros de acceso, por lo que la
respuesta de esa operación sigue sin identificarse.

La prueba Angular del regreso a una vista nueva verificó que Carrito
recibe la revisión cotizada y queda vacío cuando coincide. Otra prueba
reprodujo el caso de un error HTTP 503 al iniciar Webpay, seguido de una
edición del carrito. El reintento ahora conserva la revisión vinculada a
la cotización original y deja guardado el carrito editado.

Con Carrito ya actualizado, aplicar la corrección de reintentos al frontend.

```bash
cd "$HOME/pedidos360-ops-pago" &&
python3 deploy/aws/frontend_image.py --apply --stage ev3 --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:3bfd7a74c8ae6354d1565224292925f93129e67542203a28264d17036749e296 &&
python3 deploy/aws/frontend_gateway.py --verify
```

[CI de la corrección de reintentos](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/45103663612)

El frontend guarda en la pestaña la referencia del carrito al iniciar
Webpay. Después de confirmar el pedido, Carrito elimina los artículos
solo si la revisión aún coincide. La comprobación y la eliminación usan
la misma transacción. La ruta aprovecha el `DELETE` por ítem protegido
por JWT que ya existe en API Gateway. La actualización reaprovecha el
montaje H2 actual y las pruebas cubren el conflicto por un carrito editado.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/clp_backends.py --apply --service carrito --image \
  ghcr.io/zorvak749/fazbear-carrito@sha256:149b0394ccb03a7db9565bd760ef8406041ae398dd2cb30feb57b0bf1322cc66 &&
python3 deploy/aws/frontend_image.py --apply --stage ev3 --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:b896f1d20460a74b9cf2ab7c2cc2514fa904fe8a1f3bab76464a792ff397b024 &&
python3 deploy/aws/frontend_gateway.py --verify
```

En una compra posterior desde `/ev3/checkout`, al ver **Pago efectuado**,
pulsar **Volver al checkout** y recargar la página. El carrito debe seguir
vacío. Si se editó en otra pestaña durante el pago, el recibo pide revisar
su contenido y los artículos quedan guardados.

Para volver a la versión anterior tras una activación completa, aplicar
primero la imagen del frontend `sha256:b83a0c7bd4db18ef65de682203e0947c775b5218f4734329c7d9d424d3561c59`
y después la de Carrito `sha256:0972d9b0082649b842d46fadab78c960b61d3699d7009bb6ea9a927ae3b04270`
con los mismos comandos. Esto cambia las imágenes y conserva el montaje H2.

[CI de Carrito](https://github.com/ZorVaK749/fazbear-carrito/actions/runs/45089516706)
· [CI del frontend](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/45089454610)

## Validación de Kafka desde Mi actividad

El resumen autenticado de **Mi actividad** consulta
`GET /api/analytics/me/resumen`. Los contadores corresponden a
interacciones que Analytics ya guardó después de consumir los eventos.
El Gateway devuelve 401 sin sesión y admite desde el frontend el
preflight del GET con `Authorization`.

1. Con sesión iniciada, abrir **Mi actividad** y anotar **Vistas de productos**
   y **Productos agregados al carrito**.
2. En el menú, pulsar el nombre de un producto y añadir una unidad de un
   producto que todavía no esté en ese carrito.
3. Volver a **Mi actividad**, pulsar **Actualizar resumen** y comparar.
   Cada contador debería aumentar en uno. Si la proyección tarda, esperar
   unos segundos y volver a consultar el resumen.
4. Registrar los valores antes y después. En otra sesión de prueba, los
   eventos de esta cuenta deben quedar fuera de sus contadores.

El resumen usa la API HTTP. La sección **Actividad en vivo** conserva
su conexión WSS y tiene una verificación propia.

La imagen pasó 137 pruebas de Angular. Fargate quedó estable en la revisión
`:12` y `/actividad` sirve el módulo con el resumen y los contadores nuevos.
El 22 de noviembre, con la revisión `:13`, el navegador mostró HTTP 200
en el resumen, HTTP 202 en el POST de interacciones de Productos y HTTP
200 al añadir una unidad al carrito. El carrito con productos y sus
controles fueron utilizables con F12 acoplado abajo.

El resumen autenticado, actualizado después de añadir el producto, pasó
de **42 a 44 interacciones**, de **13 a 14 selecciones del catálogo** y
de **11 a 12 adiciones al carrito**. Las vistas siguieron en 3. Esto
confirma el consumo de un evento de selección de Productos y uno de
adición de Carrito en Analytics a través de Kafka. Queda verificar el
efecto sobre las recomendaciones y repetir con otra cuenta de prueba.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/frontend_image.py --apply --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:174fe8463a195bcf321f28a4582e63dacaeeb0c0730df7476ed6c6fe2225d298
```

[CI del resumen de actividad](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/45075375541)

## Consulta de antifraude simulado

Si el navegador muestra un `201` con estado `DECLINED`, Pago registró un
rechazo del simulador. Los `204` de las solicitudes `OPTIONS` pertenecen al
preflight CORS. Tomar el `pagoId` de ese `POST /api/pagos` como referencia.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/webpay_payment_status.py --antifraude --payment-id UUID_DEL_PAGO_SIMULADO
```

La consulta de solo lectura muestra los intentos de la misma cuenta e
instrumento en el minuto anterior y posterior al pago de referencia, con
hora de Santiago, estado, contador de la ventana y presencia de alerta.
Para una serie aislada de cuatro intentos en diez segundos, el cuarto debe
quedar `BLOCKED`, con contador 4 y alerta registrada.

El 22 de noviembre se observó en el checkout de AWS una secuencia de tres
rechazos simulados (`201`) seguida por dos bloqueos (`429`). La respuesta
del primer bloqueo indicó `BLOCKED` y `simulacion: true`. La consulta de
Pago por SSM confirmó que los tres rechazos dejaron los contadores en 1,
2 y 3. El cuarto intento llegó **7,051 segundos** después del primero,
quedó `BLOCKED` con contador **4** y guardó su alerta. El quinto fue un
intento distinto, también bloqueado, con contador **5** y su propia alerta.
La idempotencia al repetir una misma operación está cubierta en CI.

## DynamoDB y dashboard

El 22 de noviembre, el navegador obtuvo HTTP 200 en el resumen autenticado
y HTTP 403 en `POST /api/analytics/me/dashboard-ticket`. La ruta del ticket
depende de `ANALYTICS_DASHBOARD_ENABLED` en Analytics. El valor por defecto
de ese perfil es desactivado. El frontend de AWS consulta el resumen y
reserva la solicitud de tickets para una compilación con
`analyticsLiveEnabled` activado.

La corrección del frontend también cierra el menú de perfil al pulsar
fuera. La revisión `:13` de Fargate quedó estable y sirve la corrección
junto con el resumen de actividad. El inventario SSM de `ev3-analytics`
encontró el flag sin configurar y la URL WSS ausente. La vista en vivo
queda pendiente de habilitación y el resumen HTTP sigue disponible.

```bash
cd "$HOME/pedidos360-ops-pago" &&
git pull --ff-only origin ev3/webpay-integracion &&
python3 deploy/aws/frontend_image.py --apply --image \
  ghcr.io/zorvak749/fazbears-frontend@sha256:d5200675d9719223dac3f57654b64a432d928410edbeb07b92e117d7d86bc14c &&
python3 deploy/aws/clp_inventory.py --service analytics
```

[CI de la corrección del menú y del ticket](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/45076758861)

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
