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
de cancelación o expiración consulta el estado, y solo el retorno normal
puede iniciar el commit. Ante un commit sin respuesta se consulta el estado
y se reintenta la verificación del mismo pago. Ante una creación sin
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

- Pago aplica Flyway V3 y V4 a PostgreSQL. Orden aplica Flyway V2. En Pedidos H2
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
