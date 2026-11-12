# Docker, CI y AWS propuestos — nada desplegado

Multi-stage Maven/JRE 21 no root, healthcheck sin detalles sensibles; secretos
externos. CI futura: test/build en PR; publicación GHCR solo en rama/evento
aprobados, tags sha-commit y digest, escaneo/SBOM, Actions fijadas por SHA.
Imagen propuesta: `ghcr.io/zorvak749/fazbear-pago`.

AWS requiere capacidad EC2 autorizada, TG/health, ruta `/api/pagos` y subrutas
en Gateway/ALB existentes, PostgreSQL durable con backups probados, Kafka privado
TLS/SASL/ACL, SSM/secretos/IAM/SG mínimos, métricas y conciliación. Webpay sandbox
después. Evaluar límites Academy/costo antes de provisionar. No workflow activo,
Dockerfile o infraestructura en esta inicialización documental.
