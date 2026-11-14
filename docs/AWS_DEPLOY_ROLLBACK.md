# EV3: publicación, despliegue manual y rollback (13/11/2026)

**Procedimiento preparado, NO ejecutado en AWS.** Pago/Analytics en EC2 separadas,
PostgreSQL RDS y Kafka Fargate son estado comunicado por el usuario, no un inventario
verificado por esta auditoría. No ejecutar este documento sobre las siete EC2 EV2.

## 1. Bloqueos antes de aprobar un despliegue

- Identificar por escrito las EC2 **EV3** autorizadas. Un microservicio por EC2;
  si faltan destinos aprobados, detenerse, no crearlos ni usar una EC2 EV2.
- **Carrito/Pedidos EV2 con H2 en memoria: no parar/reiniciar JVM/contenedor/host.**
  Snapshot EBS, copiar un volumen o `docker commit` no preserva esa memoria. Hace
  falta exportación consistente mediante la JVM viva/conexión ya habilitada,
  restauración ensayada aparte y cotejo de tablas/conteos/propietarios. Sin método
  seguro disponible y aprobación explícita, su sustitución/migración está bloqueada.
- Registrar digest/configuración anterior y estado Flyway; respaldo RDS/restauración
  verificada por responsable. No `clean`, `baseline-on-migrate`, `ddl-auto=update`,
  reset de offsets/volúmenes, delete/truncate ni rollback automático de esquemas.
- Productos/Carrito AWS usan Hibernate **validate**: requieren esquema PostgreSQL
  existente revisado, incluyendo `ev3_outbox`. No crean/migran su BD legado. Sus
  DDL/migración de datos/catálogo inicial siguen siendo una dependencia operativa.
  Orden/Pedidos incluyen Flyway para **esquemas nuevos vacíos**, no para adoptar
  automáticamente tablas EV2/RDS preexistentes. Nuevos servicios usan sus migraciones.
- Kafka: verificar desde cada EC2 DNS/red a **todos** los `advertised.listeners`, no
  solo bootstrap de Fargate; persistencia del broker/offsets tras reemplazo de task,
  protocolo TLS/SASL y permisos efectivos. No se alteró Kafka/ECS en este trabajo.
- Topics exactos: `producto.actualizado.v1`, `producto.interaccion.v1`,
  `carrito.actualizado.v1`, `pago.aprobado.v1`, `pago.reembolsado.v1`, con sus `.DLT`.
  Mantener grupos `ms-analytics-recommendations-v1` y `ms-fidelizacion-v1` y sus inbox.
  Catalogar los eventos sintéticos AWS previos: versiones artificialmente altas
  pueden impedir aplicar snapshots de un productor con secuencia menor. No borrar
  proyecciones ni resecuenciar producción para ocultarlo; planear baseline/replay
  aprobado, preservando secuencia del outbox y separando datos de ensayo.

## 2. Preparar imágenes GHCR (sin compilar en EC2)

1. Revisar y publicar manualmente los commits de `ev3/integracion-integral`, primero
   Pago. Los otros siete callers fijan el reusable a
   `3f42f4d284bf2cc284cadc2a1b378ce48df934e7` de Pago; ese commit debe ser accesible.
2. Nuevo workflow `ghcr-versioned.yml`: solo `workflow_dispatch`, restringido por
   reusable a esa rama. GitHub puede exigir registrar el workflow en la rama
   predeterminada para habilitar dispatch; tramitarlo mediante revisión, **no hacer
   merges protegidos ni cambiar la rama por cuenta propia**. Las políticas Actions
   deben permitir el reusable entre repos y `GITHUB_TOKEN` con packages:write.
3. Ejecutar primero `publish=false`: tests y build `Dockerfile.aws`. No publica.
   Tras aprobación, `publish=true`: publica, **nunca despliega**. No usa credenciales
   AWS/Azure/RDS: solo token efímero GitHub. Tests de CI usan datos sintéticos
   desechables; productores omiten su caso opt-in PostgreSQL/Kafka en este workflow.
4. Imagen `ghcr.io/zorvak749/<repo>:sha-<SHA-completo>-run-<run-id>-<attempt>`.
   Sin `latest` ni alias compartido. Registrar digest, revisión OCI y resultado CI.
   Construye `linux/amd64`; revisar arquitectura del destino (ARM requiere otro build).
   Se generan provenance/SBOM; no sustituye escaneo/revisión de vulnerabilidades.
5. En EC2 solo autenticar lectura GHCR con credencial mínima **fuera de Git** si
   paquete privado y hacer `docker pull ghcr.io/...@sha256:<digest-aprobado>`.
   No `git pull`/Maven/npm/build en EC2. No inventar digest antes de publicar.

| Servicio | Nombre de paquete GHCR (owner zorvak749) | Dependencias al activar |
|---|---|---|
| Pago | fazbear-pago | RDS propio, Orden, Kafka, clave interna |
| Analytics | fazbear-analytics-recommendations | RDS propio, Kafka, catálogo/interacciones |
| Fidelización | fazbear-fidelizacion | RDS propio, Kafka, Pago, clave interna |
| Productos | fazbears-productos | esquema/catálogo revisados, Kafka y RabbitMQ |
| Carrito | fazbear-carrito | preservación H2/migración aprobada, PostgreSQL, Kafka |
| Orden | fazbear-orden | PostgreSQL, Productos, Pago, Pedidos, RabbitMQ |
| Pedidos | fazbears-pedidos | preservación H2/migración aprobada, PostgreSQL, clave interna |
| Angular (opcional) | fazbears-frontend | rutas Gateway, HTTPS, SPA Entra real |

## 3. Configuración privada del runtime

Backends `Dockerfile.aws`: `SPRING_PROFILES_ACTIVE=ev3-aws`, puerto interno8080,
Java21 no-root. No combinar con local/test; AwsSafety rechaza JWKS LAB, H2 y
configuración destructiva/fixtures según servicio. No se importan perfiles locales.

Todos: `KAFKA_BOOTSTRAP_SERVERS` donde corresponda y credenciales/protocolo Kafka
mediante configuración externa Spring (`spring.kafka.properties.security.protocol`,
`sasl.mechanism`, `sasl.jaas.config`, certificados montados si procede). No se asume
un protocolo de Fargate desconocido ni se desactiva validación TLS. URLs RDS JDBC
PostgreSQL con TLS/verificación del certificado según política RDS y CA confiable.

- `<SERVICIO>_DB_URL`, `<SERVICIO>_DB_USER`, `<SERVICIO>_DB_PASSWORD`, con prefijos
  PAGO, ANALYTICS, FIDELIZACION, PRODUCTOS, CARRITO, ORDEN o PEDIDOS.
- Pago: `ORDEN_URL`. Fidelización: `PAGO_URL`. Orden: `PRODUCTOS_URL`, `PAGO_URL`,
  `PEDIDOS_URL`, `CARRITO_URL`. URLs base internas sin `/api` adicional, DNS estable.
- `INTERNAL_SERVICE_KEY` mínimo32 caracteres, mismo valor **privado** para
  Pago/Orden/Pedidos/Fidelización. Restringir `/internal/**` en SG/proxy, nunca
  publicarlo en Gateway o frontend; proteger transporte interno (TLS/red aprobada).
- Productos/Orden: variables RabbitMQ ya soportadas en sus application.properties;
  mantener procesamiento operativo y consumidores existentes, no sustituir por Kafka.
- Variables Entra existentes tenant/audience e issuer v2 deben coincidir con el
  registro real. **Omitir** `LOCAL_JWT_JWK_SET_URI` y cualquier override de JWKS,
  `PAGO_FIXTURES_ENABLED`, semillas/firmante LAB. Un access token Entra delegado con
  `access_as_user`, `tid` y `oid` válidos es obligatorio. No id_token ni JWT inventado.
- Secrets en almacenamiento/archivo externo aprobado con permisos mínimos; no en
  Dockerfile, build-args, logs, Git o historial de shell. No imprimir docker inspect
  completo/env resuelto, tokens ni JAAS. Angular no necesita secretos de backend.

## 4. Activación y verificación manual

1. Verificar destinos/backup/digests; cerrar exposición mientras se ajustan
   consumidores, esquemas y URLs. Dependencias deben estar listas antes del checkout.
2. Levantar un candidato **EV3**, por digest, sin tocar EV2, con env externo y puerto
   de validación interno distinto. Ejemplo **solo en EC2 EV3 autorizada**:

   ```sh
   docker run -d --name ms-pago-ev3-candidate \
     --env-file /etc/pedidos360/ev3/pago.env \
     -p 127.0.0.1:18080:8080 \
     ghcr.io/zorvak749/fazbear-pago@sha256:<digest-aprobado>
   ```

3. Comprobar migraciones/startup y conectividad real; `/health` solo es liveness,
   no acredita Kafka/RDS/checkout. Probar401 sin token y401 con firma/issuer erróneos.
   Validar llamadas propias y rechazo de acceso cruzado con **Entra real**, sin
   copiar access tokens al informe. No ejecutar el firmante/smoke LAB contra AWS.
4. En ensayo autorizado: catálogo real→cotización→pago SIMULADO→confirmación→un Pedido,
   un crédito FazCoins verificado; replay sin duplicar. Probar VIEW/SELECT/ADD/UPDATE/
   REMOVE→Kafka→resumen y ranking; cuarto/quinto intento mismo instrumento bloqueados,
   canje insuficiente/concurrente, refund/reversa. Conservar IDs/códigos/resultados,
   no cuerpos con PII. No generar compras bancarias. Monitorear lag/outbox/DLT.
5. Solo después, operador cambia tráfico/rutas del destino aprobado y registra
   digest anterior/nuevo. Frontend AWS usa build production con Gateway existente,
   sin proxy LAB ni claves TLS en imagen. HTTPS termina en ingress autorizado;
   verificar rutas Gateway y redirect/consent de SPA antes de ofrecerlo.

## 5. Rollback

Ante fallo de auth/contrato/esquema, aumento DLT o saldo/pedido inconsistente: no
activar candidato, o devolver tráfico al digest **EV3** anterior compatible y su
configuración registrada. Detener únicamente candidato EV3 con autorización;
conservar RDS/outbox/inbox/ledger y offsets. No compensar con deletes ni limpiar Kafka.
No revertir migraciones destructivamente; si el esquema ya no soporta binario previo,
parar rollout y aplicar arreglo forward compatible/restauración ensayada por operador.
Rollback de imagen no revierte pagos ni canjes. Mantener siempre vivas las JVM EV2
H2 hasta completar preservación y aprobación independiente.
