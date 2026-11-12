# Pruebas requeridas — aún no ejecutadas

JUnit 5 + Spring Security Test + Testcontainers PostgreSQL/Kafka.
1/2/3 intentos no bloqueados por regla y 4 bloqueado; 9.999/10/10.001s; misma tarjeta
con usuarios/instancias distintos, tarjetas distintas, carrera concurrente, replay
idempotente no contado, alerta única. PAN/CVV ausentes de API/BD/logs/eventos.
JWT y ownership A/B; cotización ajena/alterada/expirada; doble pago; UNKNOWN y
conciliación; crash/outbox/duplicados/reembolsos; contrato y migraciones reales.
Pruebas simuladas locales no certifican Webpay ni AWS. No cobros reales.
