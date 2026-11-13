# EV3 integral — manifiesto de implementación

Fecha: 12/11/2026. Todos los repos en `ev3/integracion-integral`, sin merge a main,
sin despliegues AWS ni publicación/sobrescritura de imágenes. Este manifiesto se
versiona en un commit documental posterior al commit funcional de Pago listado.

| Repo GitHub (ZorVaK749) | Commit funcional |
|---|---|
| [fazbear-pago](https://github.com/ZorVaK749/fazbear-pago/tree/ev3/integracion-integral) | [0e84f26](https://github.com/ZorVaK749/fazbear-pago/commit/0e84f26dcf1d78d04a9bd73d677986b152fcd651) |
| [fazbear-analytics-recommendations](https://github.com/ZorVaK749/fazbear-analytics-recommendations/tree/ev3/integracion-integral) | [21a069c](https://github.com/ZorVaK749/fazbear-analytics-recommendations/commit/21a069c8ced61ce6cca80a964e28dc16a751e805) |
| [fazbear-fidelizacion](https://github.com/ZorVaK749/fazbear-fidelizacion/tree/ev3/integracion-integral) | [860876b](https://github.com/ZorVaK749/fazbear-fidelizacion/commit/860876b38547445f3ebc9920889f15235b2f2be9) |
| [fazbears-productos](https://github.com/ZorVaK749/fazbears-productos/tree/ev3/integracion-integral) | [fec4572](https://github.com/ZorVaK749/fazbears-productos/commit/fec45729887800374b69fbe6354abd5c53b26e40) |
| [fazbear-carrito](https://github.com/ZorVaK749/fazbear-carrito/tree/ev3/integracion-integral) | [779a74b](https://github.com/ZorVaK749/fazbear-carrito/commit/779a74be27666c4afa2badbd42a7620a7773efb3) |
| [fazbear-orden](https://github.com/ZorVaK749/fazbear-orden/tree/ev3/integracion-integral) | [d5a982e](https://github.com/ZorVaK749/fazbear-orden/commit/d5a982e53212bfbf3a7ccc92a3ec5b1e5bd0444f) |
| [fazbears-pedidos](https://github.com/ZorVaK749/fazbears-pedidos/tree/ev3/integracion-integral) | [bebc102](https://github.com/ZorVaK749/fazbears-pedidos/commit/bebc10246583987ab9ba74cd5a4778ece096452a) |
| [fazbears-frontend](https://github.com/ZorVaK749/fazbears-frontend/tree/ev3/integracion-integral) | [5fb7ae1](https://github.com/ZorVaK749/fazbears-frontend/commit/5fb7ae15373f38f36987f0115795be89a3d2daea) |

## Resultados locales

388 casos distintos aprobados: Pago41, Analytics36, Fidelización21, Productos40,
Carrito62, Orden20, Pedidos47 y Angular121. Cero fallos/errores finales; opt-in real
PostgreSQL/Kafka de productores ejecutado por separado o dentro de verify según
sección18 del [informe acumulativo](Informe_Fazbear_EV3.md). Builds Java/Angular y
ocho imágenes Docker locales construidos; UI servida en18092, proxy401 sin token.
Npm audit0 hallazgos; advertencia de bundle Angular610.95kB/500kB conservada.

Smoke integral nueve grupos aprobados, incluido igualdad exacta de wallet/resumen
tras reiniciar ambos consumidores y nueva interacción consumida después. Evidencia
local ignorada en `deploy/ev3-local/evidence.local.json`; solo resultados/UUID de
corrida, no identidades/tokens. Configuración/arranque en [README local](../deploy/ev3-local/README.md).

## Alcance de CI y pendientes

Correcciones CI posteriores al commit funcional: Orden `e22592e` y Pedidos
`3447323` corrigen las comillas del healthcheck Docker en Actions; los primeros
intentos fallaron creando PostgreSQL antes de ejecutar tests, sin fallos funcionales
observados en esos intentos. Commits funcionales de la tabla no cambian por ello.

Workflows de validación sin deploy ni push de imágenes. Además de los tests locales,
se consultó la API GitHub: las ocho revisiones siguientes terminaron **success**.

| Repo | GitHub Actions aprobado |
|---|---|
| Pago `0e84f26` | [43347954979](https://github.com/ZorVaK749/fazbear-pago/actions/runs/43347954979) |
| Analytics `21a069c` | [43347921374](https://github.com/ZorVaK749/fazbear-analytics-recommendations/actions/runs/43347921374) |
| Fidelización `860876b` | [43347935906](https://github.com/ZorVaK749/fazbear-fidelizacion/actions/runs/43347935906) |
| Productos `fec4572` | [43347966603](https://github.com/ZorVaK749/fazbears-productos/actions/runs/43347966603) |
| Carrito `779a74b` | [43347921572](https://github.com/ZorVaK749/fazbear-carrito/actions/runs/43347921572) |
| Orden `e22592e` | [43348127703](https://github.com/ZorVaK749/fazbear-orden/actions/runs/43348127703) |
| Pedidos `3447323` | [43348134306](https://github.com/ZorVaK749/fazbears-pedidos/actions/runs/43348134306) |
| Angular `5fb7ae1` | [43347935951](https://github.com/ZorVaK749/fazbears-frontend/actions/runs/43347935951) |

CI de productores omite por defecto su caso opt-in PostgreSQL/Kafka, ejecutado
localmente con éxito; las suites CI no equivalen al smoke conjunto ni a Entra real.
El commit documental de este manifiesto puede originar otra ejecución Pago, no
incluida en las revisiones funcionales verificadas arriba.
Workflows históricos que publican imágenes no tienen esta rama entre sus triggers.
Login Entra real, AWS/R3/respaldo H2 real y hardening productivo no certificados.
Pago/coins son simulación académica, no procesamiento bancario ni checkout con coins.
Ver restricciones y fallos resueltos en sección18 del informe.
