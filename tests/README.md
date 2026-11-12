# Suite ejecutable F2.1

Resultado 12/11/2026: **36/36 aprobadas, sin omitidas**, `mvn -B clean verify`
BUILD SUCCESS. 35 casos de integración y uno de persistencia tras reinicios.

`mvn -B verify`, Java 21 y Docker local. JUnit 5, Spring Boot/Security real,
Testcontainers PostgreSQL 17.7. Sin Kafka/H2 ni sustitutos de repositorio.

Cobertura:
- APPROVED/DECLINED con importe backend, persistencia en conexión independiente.
- Petición por socket HTTP con JWT RSA firmado efímeramente.
- Intentos 1..3 permitidos y cuarto bloqueado, entre owners distintos.
- Rechazados/bloqueados cuentan, instrumentos distintos aislados.
- Ventana SQL inclusiva: −10s−1µs fuera, −10s dentro, ahora dentro, +1µs fuera;
  procesamiento reciente a −9s bloquea y expirado a −10.1s ya no bloquea.
- Doce llamadas simultáneas: tres aprobaciones/nueve bloqueos; misma key doce
  veces: un pago/un intento. Misma operación/keys distintas: una aprobación.
- Replay exacto y bloqueado, conflicto de contenido, namespace owner, retry tras
  decline, operación ya aprobada, owner/listado/operación ajenos, expiración.
- Fallo de INSERT decisión y fallo diferido al COMMIT: 503, rollback completo,
  reintento manual con misma key sin duplicados. Sin automatic write retry.
- Cerrar instancia Spring/servidor/pool, reiniciar el PostgreSQL exclusivo del test
  y abrir instancia Spring nueva: mismo pago por GET y replay, un solo intento,
  fixtures sin duplicar. Se reinspecciona puerto host efímero tras restart Docker.
- Reloj BD después del lock: otra conexión retiene instrumento, se verifica espera
  en PostgreSQL y timestamp del pago posterior a liberación; índice único real.
- JWT: firma alterada, issuer/audience/tenant/exp/nbf/oid inválidos o ausentes;
  no token, formato inválido, app-only sin scope y scope equivocado.
- Campos monetarios, identidad, fecha/PAN/CVV extra rechazados; key obligatoria,
  instrumento desconocido y límites de consulta.

Ver informe para conteo final y ensayo de reinicios/persistencia. No certifica
configuración Entra real, Webpay, AWS, failover o despliegue multiinstancia.
UNKNOWN/conciliación, outbox/Kafka/refunds siguen como pruebas futuras, no omitidas
silenciosamente dentro del contrato actual.
