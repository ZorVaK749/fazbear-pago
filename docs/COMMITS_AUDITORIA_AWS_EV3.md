# Cierre de auditoría/preparación AWS EV3

Trabajo y pruebas: 13/11/2026. Cierre documental: 14/11/2026.
Rama de los ocho repos: `ev3/integracion-integral`.
**Commits locales preparados; sin push de esta auditoría, publicación GHCR ni deploy AWS.**

| Repo | Commit de cambios auditados |
|---|---|
| fazbear-pago | `d054df1701b4f7062d808a62764f035e610d2811` |
| fazbear-analytics-recommendations | `928eb722108e9b51f9fd09807af0d69f8abb7ed0` |
| fazbear-fidelizacion | `1ee4aa50da64b93f074525e364241488c70816d6` |
| fazbears-productos | `a0a0c4ba60c6cc6c33894dad427fa878c8b08baf` |
| fazbear-carrito | `63cabbc823aafde89b017d5817f3ea7ede30754f` |
| fazbear-orden | `4e2e455baa6b7c5303aa0ed246ba3463a89f27a0` |
| fazbears-pedidos | `e36fd163d7fb2d048646a0ee9efd2cad3e21912b` |
| fazbears-frontend | `bcbb2393f1a289399ab895460c5ce6dd533296c1` |

Pago incluye además el reusable GHCR en
`3f42f4d284bf2cc284cadc2a1b378ce48df934e7`. Los callers de los otros repos están
fijados a ese commit; publicarlo antes de intentar ejecutar esos workflows remotos.
Este manifiesto se agrega en un commit documental posterior al funcional de Pago.

## Resultado verificable

- **457 tests distintos aprobados**: 336 backend y121 Angular; detalle en auditoría.
  Sin fallos/errores/omitidos en ejecuciones finales, incluidos opt-in locales.
- Contrato cruzado con eventos realmente emitidos por Productos/Carrito: Kafka y
  PostgreSQL reales, deduplicación y recomendación personalizada comprobadas.
- Smoke local de nueve grupos aprobado con jars de imágenes nuevas en perfil
  **local**, corrida `3f600a9d-77a2-4690-b364-baab57ccf0ea`; no es certificación AWS.
- Ocho imágenes Dockerfile.aws construidas localmente, nginx y usuario no-root de
  backends comprobados. Workflows nuevos validados con actionlint1.7.12, no ejecutados
  en Actions. No confundirlos con CI aprobada del cierre anterior12/11.

## Qué sigue, solo con aprobación

1. Revisar/publicar commits y registrar workflows manuales/permiso GHCR.
2. Construir/publicar tags únicos por SHA+run+attempt y registrar **digest remoto**.
3. Revisar destinos EV3, esquemas/catálogo/versión de eventos, red Kafka y configuración
   externa de secretos. Carrito/Pedidos bloqueados hasta preservar H2 vivo y verificar
   migración; no tocar las siete EC2 EV2.
4. Validar Entra real y recorrido entre EC2 antes de aprobar rollout por digest.

No se creó infraestructura ni se detuvo/reinició ninguna EC2/JVM EV2. Estado AWS de
Pago/Analytics/RDS/Fargate se tomó del usuario, no de una inspección de sus recursos.

Documentos: [auditoría](AUDITORIA_AWS_EV3_2026-11-13.md),
[despliegue/rollback](AWS_DEPLOY_ROLLBACK.md),
[informe acumulativo, sección19](Informe_Fazbear_EV3.md).
