# Código ejecutable F2.1

`main/java/cl/pedidos360/pago/`: aplicación, API/DTO, servicio transaccional JDBC,
Security/JWT, fixtures controladas y errores. Esquema Flyway en
`main/resources/db/migration`; configuración en `application.yml`.

`test/java/`: integración PostgreSQL real y claves efímeras solo de test.
Sin stubs bancarios, Kafka, Webpay, outbox ni llamadas a servicios antiguos.
