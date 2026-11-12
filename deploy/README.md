# Docker, CI y AWS propuestos — nada desplegado

**Actualización F2.1:** Dockerfile multi-stage/no-root y Compose PostgreSQL/API ya
existen para laboratorio local. Ver README raíz. Lo siguiente conserva propuestas
futuras: no CI, imagen publicada, infraestructura ni despliegue AWS implementados.

Multi-stage Maven/JRE 21 no root, healthcheck sin detalles sensibles; secretos
externos. CI futura: test/build en PR; publicación GHCR solo en rama/evento
aprobados, tags sha-commit y digest, escaneo/SBOM, Actions fijadas por SHA.
Imagen propuesta: `ghcr.io/zorvak749/fazbear-pago`.

AWS requiere capacidad EC2 autorizada, TG/health, ruta `/api/pagos` y subrutas
en Gateway/ALB existentes, PostgreSQL durable con backups probados, Kafka privado
TLS/SASL/ACL, SSM/secretos/IAM/SG mínimos, métricas y conciliación. Webpay sandbox
después. Evaluar límites Academy/costo antes de provisionar. No hay workflow activo
ni infraestructura AWS nueva. El Dockerfile actual es exclusivamente local.
