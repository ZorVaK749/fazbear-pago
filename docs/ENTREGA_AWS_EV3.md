# Entrega operativa de Pedidos360 EV3 en AWS

GitHub mantiene el código en `ev3/integracion-integral`. GitHub Actions ejecuta
las suites, construye `Dockerfile.aws` para `linux/amd64` y publica por versión
en GHCR. La ejecución de CI no cambia EC2, Gateway ni la base viva. Usar
durante el despliegue los digests confirmados para la revisión aprobada.
[Referencias GHCR de la entrega](IMAGENES_EV3_2026-11-18.md).

## Checklist antes del corte

- [ ] Confirmar en Actions que el job de publicación terminó en `success` por
  cada servicio. Cotejar commit, versión y digest GHCR. El smoke de CI usa datos
  sintéticos y cuenta como evidencia de integración, con Entra real pendiente.
- [ ] Confirmar cuenta y región AWS `us-east-1`, las EC2 existentes y una EC2 por
  microservicio. Confirmar si Fidelización tiene destino disponible. Verificar
  EBS, espacio, UID/GID 10001, arquitectura, montajes, redes, puertos, health
  check, imagen actual y configuración de rollback de cada contenedor.
- [ ] Pausar escrituras a Productos y la entrega de compras nuevas durante el
  respaldo y corte. Esperar los descuentos ya en curso. Confirmar que la base
  fuente está identificada y que el respaldo refleja los 23 productos reales.
- [ ] Restaurar Productos en una ruta EBS aislada y verificar el SHA256 del
  catálogo completo. Mantener el origen vivo hasta certificar el destino. Un
  snapshot EBS conserva archivos en disco, mientras que H2 en RAM requiere una
  exportación lógica de la base viva.
- [ ] Confirmar el tratamiento de los datos de prueba de Carrito y Pedidos.
  Preparar rutas EBS por servicio y guardar la configuración anterior. Nunca
  montar el mismo archivo en dos JVM.
- [ ] Confirmar RabbitMQ, incluidos exchange `pedidos.exchange` y bindings de
  stock, reportes y notificaciones. Confirmar Kafka desde cada productor o
  consumidor y PostgreSQL para Orden, Pago, Analytics y Fidelización. Confirmar
  URLs privadas `PRODUCTOS_URL`, `CARRITO_URL`, `PEDIDOS_URL`, `ORDEN_URL` y
  `PAGO_URL` según cada servicio, con puerto de host.
- [ ] Configurar `INTERNAL_SERVICE_KEY` privada de al menos 32 caracteres para
  Orden, Pago, Pedidos y Fidelización. La clave compartida debe coincidir.
  Confirmar parámetros y credenciales de BD y brokers desde el archivo privado
  de cada EC2. Mantener `/internal/**` fuera de API Gateway.
- [ ] Confirmar stage `ev3`, JWT Entra con `access_as_user`, CORS y redirect URI
  de la SPA. Para publicar las rutas administrativas de Reportes, confirmar
  el app role asignado en Entra y pasar su valor exacto en `REPORTES_ADMIN_ROLE`.
  La API exige el claim `roles` con ese valor y el scope delegado
  `access_as_user`. Con el valor vacío, solo queda accesible el health de
  Reportes. La pantalla de administración requiere habilitación aparte cuando
  se confirme el contrato de Entra.

## Respaldo de Productos

Usar Java y el JAR H2 de la **misma versión que el origen**. Ejecutar desde
el repo de Productos con acceso JDBC autorizado. El programa lee las siete
columnas del catálogo, exige 23 productos con stock explícito, genera un
dump lógico, lo restaura en otra base y compara el catálogo antes y después,
incluidos IDs, precios y stock. El resultado exitoso incluye un checksum
del dump y otro del catálogo, más el archivo `productosdb.mv.db` restaurado.

El acceso aceptable es una conexión privada ya habilitada a la base viva
(TCP/TLS), o una copia consistente de una base H2 de archivo obtenida por el
operador. Si el origen corre en memoria embebida y carece de conexión SQL
habilitada, el operador debe resolver la extracción con acceso autorizado
a la JVM activa y demostrar equivalencia antes de detenerla. No continuar
desde el JSON histórico, que carece de stock, ni desde `data.sql`.

```bash
git switch ev3/integracion-integral
git pull --ff-only origin ev3/integracion-integral
umask 077
# Cargar CATALOG_H2_URL, CATALOG_H2_USER y CATALOG_H2_PASSWORD desde el entorno
# privado. CATALOG_H2_URL es JDBC H2 file/tcp/ssl, sin opciones ni credenciales.
H2_JAR=/ruta/privada/h2-version-del-origen.jar
BACKUP=/ruta/privada/backups/productos-$(date -u +%Y%m%dT%H%M%SZ)
java -cp "$H2_JAR" deploy/CatalogBackup.java backup "$BACKUP"
(cd "$BACKUP" && sha256sum -c productos.sql.sha256)
test -s "$BACKUP/catalogo.sha256"
```

Custodiar el dump y el archivo restaurado fuera del laboratorio en almacenamiento
privado. Contienen datos y metadatos del motor. Probar la apertura y las
migraciones con la versión del destino sobre **una copia**. Instalar la copia
validada en la ruta EBS aprobada, con propietario y permisos para UID/GID
10001, conservando el nombre `productosdb.mv.db` y las credenciales de la base.
Mantener `SPRING_SQL_INIT_MODE=never`. Antes de levantar el contenedor, correr
`CatalogBackup.java fingerprint` contra esa copia y comparar su salida con
`catalogo.sha256`. Una vez iniciado, consultar el catálogo con una sesión
Entra y cotejar los 23 IDs, precios y stocks antes de habilitar compras.

Para inicializar las recomendaciones desde el catálogo restaurado, habilitar
`EV3_AWS_CATALOG_SNAPSHOT=true` en el primer arranque autorizado de Productos
con Kafka operativo. Esto encola los 23 snapshots en el outbox sin escribir
stock. Verificar que Analytics use esos snapshots y quitar la opción para los
próximos arranques. Si ya existen eventos sintéticos con versiones mayores que
el outbox restaurado, conciliar la proyección y sus versiones antes del corte.

## Comandos por EC2

Usar la ruta del repo y la rama EV3 y asignar `IMAGE` con la referencia completa
`ghcr.io/zorvak749/<paquete>@sha256:<digest>` de la entrega. Registrar el ID de la
imagen actual antes del cambio. Para un paquete privado, autenticarse a GHCR
con una credencial de lectura mediante el mecanismo aprobado. Estos comandos
de preparación no paran el contenedor.

```bash
git switch ev3/integracion-integral
git pull --ff-only origin ev3/integracion-integral
docker inspect --format '{{.Image}} {{.Config.Image}} {{json .Mounts}} {{json .NetworkSettings.Ports}}' "$CURRENT"
docker pull "$IMAGE"
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE"
```

Adaptar la invocación al servicio, preservando argumentos de red y límites de
recursos de la instalación existente. Ejemplo de sustitución **solo después**
del respaldo y corte aprobados, en Productos, Carrito o Pedidos sobre H2
persistente. Para los servicios con PostgreSQL y para nginx, omitir el montaje
H2, usar su configuración real y sustituir los puertos según la tabla. El
frontend sirve HTTP detrás del ingreso HTTPS.

```bash
# Ejemplo de valores para Carrito. IMAGE y CURRENT se fijan desde el inventario.
SERVICE=carrito
HOST_PORT=8083
APP_PORT=8083
EBS_DIR=/opt/fazbear/data/carrito
ENV_FILE=/etc/pedidos360/ev3/carrito.env
test -d "$EBS_DIR" && test -r "$ENV_FILE" # Confirmar además que EBS está montado.

# Ejecutar únicamente durante la ventana y con el rollback acordado.
PREVIOUS="${CURRENT}-previous-$(date -u +%Y%m%dT%H%M%SZ)"
docker stop "$CURRENT" &&
docker rename "$CURRENT" "$PREVIOUS" &&
docker run -d --name "$CURRENT" --restart unless-stopped \
  --env-file "$ENV_FILE" \
  --mount "type=bind,source=$EBS_DIR,target=/var/lib/fazbear/$SERVICE" \
  -p "$HOST_PORT:$APP_PORT" "$IMAGE"
```

| Servicio | GHCR | Puerto host:contenedor | Validación inicial |
| --- | --- | --- | --- |
| Carrito | `fazbear-carrito` | `8083:8083` | `GET /api/carrito/me` con Entra |
| Pedidos | `fazbears-pedidos` | `8082:8082` | Historial propio y confirmación pagada |
| Productos | `fazbears-productos` | `8081:8081` | `GET /api/productos` con Entra y stock cotejado |
| Orden | `fazbear-orden` | `8084:8080` | `GET /api/orden/health` con Entra |
| Notificaciones | `fazbear-notificaciones` | `8085:8085` | `GET /api/notificaciones/health` con Entra |
| Reportes | `fazbear-reportes` | `8086:8086` | `GET /api/reportes/health` |
| Pago | `fazbear-pago` | `8087:8080` | `GET /health` |
| Analytics | `fazbear-analytics-recommendations` | `8088:8080` | `GET /health` |
| Fidelización | `fazbear-fidelizacion` | `8089:8080` | `GET /health`, destino por confirmar |
| Frontend | `fazbears-frontend` | `80:80` | `GET /` y navegación Angular |

## Gateway y verificación final

El 18/11/2026 el frontend público respondió HTTP 200. En el stage `ev3`,
el preflight desde ese origen para cotización, pago y canje devolvió HTTP 204
sin `Access-Control-Allow-Origin` ni `Access-Control-Allow-Headers`.
Corregir la política en Gateway o en la integración que responde a OPTIONS y
repetir la comprobación antes de habilitar el frontend nuevo.

Inventariar desde CloudShell en la cuenta correcta:

```bash
aws apigatewayv2 get-api --region us-east-1 --api-id uuzifgcyd2 \
  --query 'CorsConfiguration' --output json
aws apigatewayv2 get-stage --region us-east-1 --api-id uuzifgcyd2 --stage-name ev3
aws apigatewayv2 get-routes --region us-east-1 --api-id uuzifgcyd2 \
  --query 'Items[].[RouteKey,AuthorizationType,Target]' --output table
aws apigatewayv2 get-integrations --region us-east-1 --api-id uuzifgcyd2 \
  --query 'Items[].[IntegrationId,ConnectionId,RequestParameters]' --output json
curl -i -X OPTIONS 'https://uuzifgcyd2.execute-api.us-east-1.amazonaws.com/ev3/api/orden/cotizaciones' \
  -H 'Origin: https://p5gsy16utd.execute-api.us-east-1.amazonaws.com' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: authorization,content-type,idempotency-key'
```

Si el HTTP API tiene CORS administrado en Gateway, revisar el JSON actual y
guardar una versión actualizada en `cors-ev3.json`. Conservar los orígenes y
métodos autorizados existentes e incluir el origen del frontend, los métodos
GET, POST, PUT, DELETE y OPTIONS, y los headers Authorization, Content-Type e
Idempotency-Key. Aplicar la configuración revisada en la ventana de despliegue:

```bash
aws apigatewayv2 update-api --region us-east-1 --api-id uuzifgcyd2 \
  --cors-configuration file://cors-ev3.json
```

Verificar si el stage usa publicación automática antes de activar la revisión y
repetir los OPTIONS. Si una integración explícita gestiona OPTIONS, corregir en
ese destino y verificar que el preflight sea accesible desde el navegador.

- [ ] Las integraciones privadas reenvían `/api/…` al ALB con el header de
  selección de servicio esperado, y el stage `/ev3` queda fuera del path del
  contenedor. El preflight admite el origen publicado y `Idempotency-Key` en
  Orden, Pago y Fidelización. Hacer la misma comprobación para los POST reales.
- [ ] Confirmar rutas explícitas para catálogo e interacciones, Carrito
  `/me` y mutaciones por propietario, historial Pedidos, Orden
  `/cotizaciones`, `/cotizaciones/{id}` y `/confirmar-pago`, Pago e
  historial, recomendaciones y saldo/movimientos/canjes de Fidelización.
- [ ] Habilitar tráfico en orden controlado. Arrancar Carrito y Pedidos
  primero, verificar dependencias de Orden y Pago, y mantener Productos
  protegido hasta verificar restauración. Publicar frontend al final.
- [ ] Con Entra real, validar catálogo, carrito propio, cotización, pago
  simulado, confirmación repetida sin duplicación, descuento de stock una vez,
  reportes/notificación según permisos, recomendaciones y crédito FazCoins.
  Registrar evidencias sin JWT, datos personales ni claves.
- [ ] Ante fallo, retirar el candidato del tráfico y restaurar el digest y
  configuración anteriores con datos compatibles. Si el contenedor anterior
  usaba H2 en RAM, arrancarlo de nuevo no devuelve esos datos. Para Productos
  conservar el respaldo verificado y registrar compras realizadas después del
  corte antes de decidir una restauración.
