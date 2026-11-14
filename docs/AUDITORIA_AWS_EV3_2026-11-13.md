# Auditoría EV3 y preparación AWS — 13/11/2026

**Cierre documental: 14/11/2026.** Commits y estado de entrega en
[COMMITS_AUDITORIA_AWS_EV3.md](COMMITS_AUDITORIA_AWS_EV3.md).

Rama `ev3/integracion-integral`, ocho repos existentes. No acceso AWS, deploy,
infraestructura creada ni cambios a las siete EC2 EV2. Pago/Analytics+RDS y Kafka
Fargate/ingestión sintética AWS: **informados por el usuario**, no revalidados aquí.
El éxito local anterior no se extrapola a AWS/Entra. Nuevos commits quedan locales
para revisión/publicación explícita; nuevas imágenes GHCR todavía no publicadas.

## Hallazgos y correcciones

| Área | Resultado |
|---|---|
| Antifraude | Regla correcta: lock global por instrumento, reloj PostgreSQL después del lock, `[ahora-10s,ahora]`, bloquea desde4. Tests previos cubren límites microsegundo, concurrencia, instrumentos independientes y usuarios distintos. Nueva regresión4/5 y replay BLOCKED sin intento adicional. No PAN/CVV real: mismo instrumento del simulador representa misma tarjeta. |
| Productos/Carrito→Analytics | Envelope9 campos/tipos/productor y cantidades compatibles. REMOVE0 aceptado. Nueva prueba exporta JSON reales de productores y los consume dos veces sin transformación por Kafka/PostgreSQL: cinco inbox, cuatro interacciones, un catálogo y ranking PERSONALIZED. Contrato comprobado localmente, no entrega desde EC2 EV2. |
| Recomendaciones | SQL usa VIEW1/SELECT2/ADD5/UPDATE3/REMOVE−5, decaimiento90 días, categoría/cointeracción y aislamiento tenant. Excluye inactivos/sin stock; fallback explícito. Suites comprueban ranking dinámico, no se presentó un catálogo fijo como personalización. |
| Orden/Pago/Pedidos | Flujo confiable solo existía en perfil local. Se habilita también en perfil AWS separado y se cierra endpoint legado Orden allí. Se bloquea POST público legado Pedidos en AWS para no saltar la confirmación de Pago; perfiles EV2 conservados. Confirmación tardía ya no abandona un pago previamente aprobado por vencimiento de TTL: se consulta Pago y se conserva rechazo de DECLINED/REFUNDED/mismatch. Tests de retry tras pérdida de commit/vencimiento. |
| FazCoins | Acredita de pago aprobado verificado vía endpoint interno, no por crear Pedido. Wallet/ledger/inbox, dedup por pago, locks, canjes/reversa y deuda ya existentes; reensayados con PostgreSQL/Kafka. No descuento/pago de checkout con coins. |
| Identidad/BD AWS | Perfiles ev3-aws sin importar local; guardas rechazan LAB/JWKS override, perfiles mezclados y H2. Servicios JPA usan validate, no create-drop/update. Pago sin fixtures y con importación Orden/outbox Kafka habilitadas. Entra real sigue pendiente de prueba en los hosts. |
| Docker/GHCR | Dockerfile.aws en8 repos, backend21 no-root, frontend sin certificado privado generado dentro de imagen. Workflow manual build/test; publicación opt-in, tag SHA+run+attempt y digest, sin latest ni acciones AWS. Reusable fijado por commit para callers. |

## Pruebas y reproducción

Resultados finales de Surefire y Angular: **457 casos distintos aprobados**:

| Repo | Tests | Fallos/errores/omitidos finales |
|---|---:|---|
| Pago | 51 | 0/0/0 |
| Analytics | 44 | 0/0/0, contrato productor opt-in ejecutado |
| Fidelización | 29 | 0/0/0 |
| Productos | 51 | 0/0/0, PostgreSQL/Kafka opt-in ejecutado |
| Carrito | 72 | 0/0/0, PostgreSQL/Kafka opt-in ejecutado |
| Orden | 31 | 0/0/0, PostgreSQL real |
| Pedidos | 58 | 0/0/0, PostgreSQL real |
| Angular | 121 | 0 fallos; build production aprobado |

Ocho `Dockerfile.aws` construidos **localmente**, tags exclusivos
`pedidos360-audit/<servicio>:20261113`. Sus IDs locales no son digests publicados
GHCR. No workflow de publicación ejecutado, no nuevos tags remotos creados. Backend
AWSprofile validado por64 casos de guardas/perfiles más regresión de bloqueo Pedido;
no se afirma arranque de esos perfiles en EC2 ni autenticación de un usuario Entra.
Advertencia Angular610.95kB/500kB conservada. No sumar
ejecuciones repetidas del mismo caso como tests distintos. Claves/JWT de las suites
son efímeros en JVM local, nunca configuración de despliegue AWS.

- Pago/Fidelización/Analytics: `mvn -B clean verify`, Docker/Testcontainers real.
- Orden/Pedidos: verify con `TEST_DATABASE_URL/USER/PASSWORD` para PostgreSQL
  desechable. Nunca conectar a una BD de EV2 ni a RDS con estas suites.
- Productores: verify con EV3_DOCKER_TEST=true y PostgreSQL/Kafka de ensayo, nombres
  protegidos `ev3_productos_test`/`ev3_carrito_test`. Windows reservó puertos56431/2;
  Compose admite PRODUCTOS_TEST_PORT/CARRITO_TEST_PORT; se usaron57432/57431.
- Contrato cruzado: desde workspace `powershell -File
  fazbear-pago-ev3-integral/deploy/contracts/verify-producers.ps1`; en Linux `pwsh`.
  Solo JVMs de test y Testcontainers. GitHub workflow manual `contracts.yml` registra
  revisiones exactas; no mezcla credenciales ni eventos AWS con datos de ensayo.
- actionlint1.7.12 valida sintaxis workflows nuevos. No se afirma ejecución remota
  ni autorización GHCR de workflows aún no publicados/registrados en default branch.

Fallo de entorno de pruebas corregido sin cambiar regla de negocio: Windows tenía
56431/56432 reservados; puertos Compose parametrizados. Primer smoke con las nuevas
imágenes pasó seis grupos y luego no pudo cotizar el producto agotado por su propia
compra: harness ahora exige valor/stock suficiente y usa otro producto para intentos
antifraude. No se reseteó stock ni se borraron datos o decisiones de corridas previas.

Rerun final **nueve grupos aprobados**, corrida
`3f600a9d-77a2-4690-b364-baab57ccf0ea`, `EV3_LOCAL_INTEGRATION_PASSED`. Incluye
Pago→Kafka→FazCoins, Pedido una vez, canjes concurrentes, recomendaciones, antifraude,
refund/deuda, reinicios con igualdad de wallet/resumen y nuevo consumo posterior.
Se ejecutaron los jars de `Dockerfile.aws` con override **solo de laboratorio local**
`deploy/ev3-local/compose.audit-images.yml`; esto comprueba su empaquetado y flujo,
no `ev3-aws` autenticado en EC2. Backend images no-root10001 y puerto8080 verificados;
frontend `nginx -t` correcto. Ninguna imagen se subió a GHCR.

## Pendientes/no certificables con esta sesión

1. Preservación H2 viva, migración/catalogo inicial/esquemas JPA y destinos EV3
   aprobados para servicios aún no desplegados. Ningún reemplazo EV2 autorizado.
2. Confirmar digests desplegados, esquemas/versiones RDS, tópicos y `advertised.listeners`
   de Fargate; separar semillas sintéticas y versión de catálogo de eventos reales.
3. Ensayo Entra real (issuer/audience/scopes/oid), rutas Gateway y recorrido entre EC2;
   clave interna privada/red/TLS, privilegios Kafka/RDS y persistencia de broker.
4. Publicar commits, habilitar dispatch/permiso reusable+packages y generar digests
   GHCR; `publish=false` construye, no crea una imagen desplegable remota.
5. No atomicidad distribuida stock/pago/pedido/refund ni compensación automática:
   fallos a mitad requieren replay/conciliación operativa. Reembolso Pago ajusta
   FazCoins, no cancela Pedido/stock. Pago verifica TTL antes de aprobar; Orden puede
   confirmar más tarde solo si Pago devuelve APPROVED autoritativo coincidente.

Procedimiento breve y dependencias por imagen: [AWS_DEPLOY_ROLLBACK.md](AWS_DEPLOY_ROLLBACK.md).
