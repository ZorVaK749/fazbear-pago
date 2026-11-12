# ms-pago — PEDIDOS360 EV3

Repositorio de diseño para pagos simulados, antifraude y futura integración Webpay.
Estado: **diseño propuesto, sin lógica implementada ni despliegue**.

## Estructura

- `docs/ARQUITECTURA.md`: límites, API/eventos, seguridad y aceptación.
- `src/README.md`: organización prevista de la aplicación.
- `tests/README.md`: plan de pruebas, no resultados ejecutados.
- `deploy/README.md`: propuesta Docker/CI/AWS, sin infraestructura creada.

Java 21 + Spring Boot + PostgreSQL + Kafka propuestos. RabbitMQ operativo existente
se conserva. No hay todavía pom.xml, comandos de arranque ni imagen publicada.

Antifraude: **cuarto intento de la misma tarjeta dentro de diez segundos**, no
tercero ni agrupación por clientId. No almacenar PAN/CVV. Total y usuario proceden
de backend confiable/JWT, nunca del navegador. Simulación no equivale a cobro real.

Fuente transversal en el workspace: `docs/ARQUITECTURA_NUEVOS_SERVICIOS_EV3.md`.
Este README no implica aprobación de los contratos propuestos ni de AWS.
