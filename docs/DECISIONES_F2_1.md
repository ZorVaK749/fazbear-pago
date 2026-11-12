# Decisiones y limitaciones — F2.1

## Implementado

- Java 21 / Spring Boot 3.5.16 estable, no RC. BOM gestiona Flyway 11.7.2 y
  Testcontainers 1.21.4. PostgreSQL 17.7 real local y en tests; no H2.
- JDBC explícito y registros Java, no JPA: entidades/tablas payment, payment_attempt,
  antifraud_decision, idempotency_record, card_guard, simulation_instrument y
  fixture_operation. Esquema, índices y constraints versionados por Flyway.
- NUMERIC(19,2)/BigDecimal, CLP 12990.00 sintético. No política bancaria/tributaria
  ni contrato de moneda productivo aprobado. Nunca importe desde Angular.
- Owner `(tid,oid)` validado. Key primaria por owner y SHA-256 canónico versionado
  de tres campos. INSERT ON CONFLICT + SELECT FOR UPDATE dentro de transacción.
- Global lock por instrumento, operación bloqueada e índice único parcial para
  una aprobación. Sin llamadas externas ni reintento automático de escritura.
- Tiempo BD posterior al lock, ventana inclusiva, conteo incluido intento actual
  y decisión persistida atómicamente. Intentos DECLINED/BLOCKED también cuentan.
- `sim-*` es identidad de instrumento de fixture, no hash de PAN: no recibe PAN,
  por tanto no se inventa secreto HMAC. Tokenización real exige revisión futura.
- JWT: firma/claims/owner/scope; decoder test solo en src/test, claves efímeras RAM.
  No llamadas Azure al arrancar, solo JWKS al recibir JWT normal. Los tests no
  prueban consentimiento/configuración real de Entra; esa validación está pendiente.

## Límites deliberados

- No creación pública de fixtures, administración, email privilegiado ni roles
  inventados. Scope API existente; sin CORS porque Angular no está integrado.
- Errores estables sin SQL, cuerpos, tokens, stacktraces o secretos. Sin access
  logging propio de instrumentos/identidades; observabilidad más completa pendiente.
- `/health` es liveness de proceso, no readiness BD. Caída posterior de BD produce
  503 en operaciones, nunca simula éxito. Compose espera PostgreSQL al iniciar.
- Lista propia acotada, sin cursor. Fixtures expiran siete días después de primera
  carga, no se renuevan con restart. Retención/purga/idempotency TTL por aprobar;
  este MVP no borra pagos ni claves automáticamente.
- Sin hold aparte de ventana; duración de bloqueo adicional pendiente. Tráfico
  continuo mantiene ventana saturada; anti-DoS/rate-limit general pendiente.
- Timeouts SQL no son garantía dura de SLA. Reloj BD debe estar sincronizado; no
  probado failover/reloj regresivo ni múltiples nodos reales. Locks son coordinación
  interinstancia; tests usan conexiones/hilos concurrentes contra un PostgreSQL.
- Docker tags versionados, no digest/SBOM/escaneo productivo. API no root, rol BD
  local con DDL para Flyway. Separación de roles, vault/TLS/backups/hardening pendientes.

## Dependencias con Orden y otros servicios

1. Orden/Productos: contrato backend de operación/cotización inmutable con dueño,
   importe, moneda, versión y expiración verificables. No confiar en payload actual
   de precios de Orden. Reemplazar fixture por adaptador revisado en fase posterior.
2. Pago real: proveedor, UNKNOWN/conciliación y política de timeout/reembolso. Este
   simulador solo termina APPROVED/DECLINED/BLOCKED, no captura dinero.
3. Orden debe consumir confirmación confiable de Pago y coordinar una sola orden.
   Pedido existente no confirma pago; APPROVED sintético tampoco confirma cobro.
4. Fidelización no acredita/descuenta FazCoins aquí. Kafka/analytics/outbox no
   implementados; RabbitMQ conserva rol previo, sin publicar desde Pago.
5. AWS/despliegues antiguos bloqueados por respaldo H2 real pendiente. R2 aprobado
   solo en laboratorio; R3 no autorizado. No tocar EC2/JVM/H2 ni contenedores R2.

## Evidencia

Suite exige Docker/PostgreSQL, sin tests omitidos si faltan. Incluye frontera exacta
a microsegundo mediante SQL real con referencia fija; procesamiento usa reloj BD.
Firmas RSA/claims, concurrencia, owner, unicidad, fallos antes y durante commit.
Sin bancos/brokers/Azure/servicios antiguos. Resultados concretos en informe F2.1.
