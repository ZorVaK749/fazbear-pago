# Eventos de pago v1

Topics `pago.aprobado.v1`, `pago.reembolsado.v1`. Productor ms-pago, key pagoId.
Envelope: eventId UUID, eventType igual al topic, schemaVersion=1, occurredAt UTC,
producer=ms-pago, aggregateId=pagoId, aggregateVersion=1 aprobación/2 reembolso,
correlationId=operacionId, data.

Data: pagoId, operacionId, tenantId, ownerId (UUID pseudónimos), importe decimal,
moneda CLP, simulacion=true. Reembolso agrega reembolsoId, importeReembolsado y
totalReembolsado. Sin instrumento/email/JWT/PAN/CVV/secretos.

DB/outbox commit atómico. Publisher bloquea SKIP LOCKED, marca después del ack,
reintenta cinco segundos después de fallo. Ack/commit perdido puede republicar
eventId. No exactly-once DB/Kafka. Conserva pendientes tras reinicios; retención,
alertas de reintentos y DLQ de productor requieren operación futura supervisada.

FazCoins verifica datos económicos/owner/estado con `/internal/pagos/{id}`, además
de inbox única por eventId y acreditación única por pago. REFUNDED no puede dejar
crédito sin reverso aunque eventos lleguen fuera de orden. No acredita pedido.creado.

Kafka local no tiene TLS/ACL, no es producción. AWS exige topics privados,
permisos mínimos por producer/consumer, secretos externos, retención y monitoreo.
Un administrador de BD/Kafka/clave interna sigue siendo principal confiable.
