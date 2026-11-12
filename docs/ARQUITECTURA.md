# Diseño propuesto — ms-pago

## Límites y tecnología

Autoridad del resultado de pago; no saldo FazCoins, stock, correo o creación libre
de pedidos. Java 21, Spring Boot 3.x soportado por fijar, Maven, Resource Server
Azure JWT, Spring Kafka, PostgreSQL/Flyway. Moneda/escala por aprobar, no float.

Tablas: payment, payment_attempt, card_guard, refund, idempotency_record,
outbox_event, inbox_event. Estados CREATED/PROCESSING/APPROVED/DECLINED/BLOCKED/
UNKNOWN y reembolsos. Timeout → UNKNOWN/conciliación, no nueva captura automática.

## API sugerida, todavía inexistente

- POST `/api/pagos`: `{cotizacionId,metodo:SIMULADO,instrumentoPruebaId}`;
  Idempotency-Key obligatoria, devuelve pagoId/estado/importe/moneda/simulacion.
- GET `/api/pagos/{id}` y `/api/pagos/me?cursor=...`: solo propietario.
- POST `/api/pagos/{id}/reembolsos`: rol interno, operacionId/motivo/referenciaAjusteId;
  importe desde ajuste backend verificado, no cantidad monetaria libre de Angular.

JWT: firma, issuer, audience, exp/nbf y tenant; usuario derivado del principal.
Propuesta `(tid,oid)` pendiente de mapeo con localAccountId histórico; scopes
delegados y roles app-only internos separados. Recurso ajeno → 404; no token → 401;
sin rol → 403; key con otro cuerpo → 409; bloqueado → 429/Retry-After.

Necesita cotización backend inmutable/expirable, de dueño verificado, con catálogo,
importe/moneda/versionado canónicos. Ese contrato **aún no existe**. No usar precios
del actual payload de Orden como autoridad. Un pago exitoso único por operación;
coordinar orden tras pago en fase autorizada posterior sin duplicar pedido.creado.

## Antifraude y seguridad

Instrumentos de prueba backend; no recibir ni persistir PAN/CVV. Futura Webpay usa
tokenización/redirección y confirmación backend oficial, no callback cliente como prueba.
Huella HMAC de instrumento estable (no clientId/hash simple PAN), secreto externo.
Bloqueo transaccional por tarjeta en PostgreSQL, entre usuarios y entre instancias.
Ventana propuesta inclusiva `[ahora-10s,ahora]` con reloj BD: 1..3 no bloqueados por
esta regla, cuarto intento distinto registrado y bloqueado antes del adaptador.
Repetir misma Idempotency-Key no suma; misma key/cuerpo distinto → 409.
Duración de bloqueo/desbloqueo/retención por aprobar; no confundir con ventana.
Logs y eventos sin PAN/CVV/JWT/email. No eventos de tarjeta en topics generales.

## Eventos e integración

Kafka sugerido: pago.aprobado.v1, pago.rechazado.v1, pago.bloqueado.v1,
pago.reembolsado.v1. Key pagoId para pago/reembolso; alerta por huella opaca en
topic restringido. Envelope: eventId UUID, eventType/schemaVersion, occurredAt UTC,
producer, aggregateId/version, correlationId, data. Aprobado: cotizacionId, ownerKey,
importe, importe elegible, moneda, metodo, simulacion y referenciaOrden si existe.
Reembolso: reembolsoId e importe elegible devuelto; nunca saldo FazCoins.

Outbox en la transacción de pago, publicación al menos una vez, consumers inbox y
unicidad de causa. Reintentos/backoff/DLT sin replay automático destructivo.
Fidelización acredita solo resultado confiable, analytics consume sin tarjetas.
Kafka no decide bloqueo síncrono. RabbitMQ pedido.creado v2 conserva rol operativo;
sin bridge ni publicaciones en este bloque.

## Pendiente de aprobación

Cotización y coordinación Orden/Productos/Pedidos, identidad, moneda/redondeo,
duración antifraude, roles Entra, retención, alojamiento y contratos versionados.
No hay implementación, tests ejecutables, CI activa, imagen o E2E.
