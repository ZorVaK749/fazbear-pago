# Informe técnico acumulativo EV3 — Pedidos360 / Freddy Fazbear's Pizza

## 1. Estado y alcance

**Última actualización:** 12/11/2026.
**Fase actual:** integración integral EV3 — Pago, Analytics y Fidelización ejecutables,
integrados con cinco servicios/UI existentes y probados localmente. Ver sección 18.
R2 aprobado en laboratorio; R3 NO autorizado.
**Bloques completados:** Fase 0 aprobada; carrito F1.1 probado y publicado en rama;
repositorios nuevos inicializados con documentación y diseño propuesto;
F1.2/F1.3 y controles de propietario/identidad de F1.4 implementados,
probados localmente y publicados en ramas específicas. Administración no habilitada.
**Estado:** implementación y validación integral local completadas; publicación de ramas
registrada en sección 18. DESPLIEGUE antiguo BLOQUEADO hasta aprobar conservación
verificable H2; sin cambios AWS/H2 históricos ni rescate real.

EV2 fue terminada y evaluada con **6,9/7,0**, según confirmación del estudiante.
Observación académica comunicada: Gateway frontend con stage `$default`.
No se reabre EV2; se recupera su base funcional en ramas nuevas sin perder
las adaptaciones de infraestructura/CI realizadas para EV3.

Este documento continúa desde cero el registro específico EV3. No sustituye ni
sobrescribe `Informe_Fazbear.md`, `Revision_E2E_Fazbear.md`, el documento maestro,
`Plan_EV3.md` o pasos históricos. Auditoría detallada: [AUDITORIA_EV2_A_EV3.md](AUDITORIA_EV2_A_EV3.md).

## 2. Convenciones de evidencia y estado

| Estado | Significado |
|---|---|
| PLANEADO | Diseño/procedimiento propuesto, no ejecutado |
| IMPLEMENTADO | Cambio existe en la fuente identificada |
| PROBADO | Prueba especificada ejecutada con resultado registrado; alcance explícito |
| PUBLICADO | Commit/imagen/documento enviado al destino remoto identificado |
| DESPLEGADO | Imagen concreta ejecutándose en el entorno identificado con evidencia |
| VALIDADO FUNCIONALMENTE | Recorrido real autenticado y resultado esperado observados |

Estos estados no se infieren unos de otros. Build no implica despliegue; GHCR
no implica EC2; 401 no implica flujo funcional; aceptación SMTP no implica recepción.
Auditoría estática no sustituye tests ni pruebas integrales.

### Estado recibido del usuario al iniciar

Laboratorio nuevo AWS Academy, `us-east-1`: siete EC2, una por aplicación;
dos HTTP API Gateway, ALB interno, VPC Link y TG independientes; Azure Entra ID,
Actions/GHCR y SSM. Usuario y ChatGPT administran esa infraestructura.

- Frontend: `https://p5gsy16utd.execute-api.us-east-1.amazonaws.com`.
- Backend: `https://uuzifgcyd2.execute-api.us-east-1.amazonaws.com`.
- Todas las rutas backend tienen prefijo `/api/`.
- Frontend desplegado, login utilizado y catálogo funcionando tras corregir CORS
  y desplegar nueva imagen: **confirmado por usuario**, sin logs/digest adjuntos en este bloque.
- Carrito, compras, stock, correo y reportes: **no validados funcionalmente en EV3**.

No se ejecutó AWS CLI ni se accedió a credenciales del laboratorio en esta sesión.
El inventario de instancia/digest/configuración efectivo sigue pendiente de evidencia SSM.

## 3. Fuentes de requisitos

Se localizaron los cinco DOCX indicados en `C:\Users\ZorVa\Downloads`.
Se extrajo el texto por ZIP/XML, sin modificar originales. El enunciado no contiene
imágenes; las guías sí y no todas sus capturas se inspeccionaron.

Requisitos verificados en `Enunciado Evaluacion 3.docx`:

1. `ms-pago`: pago simulado permitido, registro seguro y antifraude por **misma tarjeta**,
   **más de tres intentos en diez segundos**, bloqueo preventivo y registro de alerta.
2. Productos/Carrito publican interacciones Kafka; `ms-analytics-recommendations`
   consume historial/actividad reciente y genera recomendaciones dinámicas.
3. Extras: Webpay +5; DynamoDB +2; WebSocket con >=3 métricas +3, según texto.

El título menciona microservicio libre, pero el cuerpo detalla dos componentes.
En el bloque A/B/C el usuario confirmó aprobación del tercer servicio:
**ms-fidelizacion — FazCoins y recompensas** (ver sección 11). Los experimentos
de sensores se conservan históricamente, sin continuarlos como sustitutos.

## 4. Bitácora — F0, bloque 1 (11/11/2026)

### Tarea 1 — Inventario de workspace, ramas y documentación

**Objetivo:** identificar dónde está la base y qué referencias existen realmente.

**Estado anterior:** se conocían ramas históricas y endpoints EV3 proporcionados
por usuario; no estaba comprobada la correspondencia fuente EV2/EV3.

**Revisado:** raíz/parent inmediato del workspace; siete estados Git; branches y
heads remotas; informes históricos; plan anterior; documentos del profesor.

**Resultado real:** el workspace abierto sigue en ramas EV2, limpio; GitHub tiene
las siete ramas `ev3/ci-*`. No se cambiaron ramas. No había documentación EV3
equivalente en `docs/` dentro del workspace. Se crean estos dos documentos nuevos.

**Procedimiento:** snapshots bare de solo auditoría en
`C:\Users\ZorVa\AppData\Local\Temp\opencode\ev3-audit-2558b78f`.
Fetch aislado/lectura de GitHub, sin alterar refs/checkouts de los repos del usuario.
SHA completos en la tabla de la auditoría anexa.

### Tarea 2 — Comparación funcional EV2 → EV3

**Objetivo:** localizar recuperaciones necesarias sin borrar mejoras de EV3.

| Área | Hallazgo de fuente EV3 | Acción propuesta (NO ejecutada) |
|---|---|---|
| Angular/carrito | HttpClient/URL declarados pero sin HTTP; solo signal local; sin inicialización | Recuperar sync y tests EV2 conservando base `/api/` |
| Productos/stock | Modelo sin stock; listener, ledger y tests eliminados | Recuperar vertical de stock compatible con evento v2; conservar CORS/CI nuevos |
| Pedidos | CANCELADO ausente del enum | Recuperar estado y tests; no confundir con borrar/restituir inventario |
| Checkout/acciones/reportes UI | Perdidos signals, timeout/finalización y pruebas | Portar fixes por componente con pruebas asíncronas |
| Orden | Java conservado; publica v2; defaults de URLs del laboratorio viejo | Revisar runtime y base interna `/api/`; no reimplementar orquestador |
| Carrito/notificaciones/reportes backend | Java idéntico a referencia EV2 | Conservar y verificar entorno/CORS/consumo/envío en EV3 |
| Actions/GHCR | Workflows nuevos publican etiqueta mutable ev3-test | Conservar; proponer gate de tests y digest/SHA verificables |

**Causa técnica identificada:** los árboles EV3 combinan adaptaciones nuevas de
despliegue con versiones funcionales anteriores a varios fixes EV2. Se confirma
por contenido, sin afirmar la operación Git histórica que originó la divergencia.

**Contratos revisados:** HTTP carrito/orden/pedidos, `ConfirmarOrdenRequest`,
`PedidoEvent` v2, topología RabbitMQ, endpoint SMTP, SecurityConfig y workflows.
No se alteró ningún contrato. Orden aún confía en precio/usuario/email del body;
no tiene referencia de pago ni idempotency key. Estos riesgos son heredados,
no motivo para duplicar una implementación de pedidos.

**Riesgos:** acumulación de eventos de Productos sin consumidor en esa versión;
CORS viejo en cinco backends; H2 RAM/create-drop y autorización solo authenticated;
retry de compra potencialmente duplicado; no deduplicación universal en email/reportes.
El estado real del broker y overrides AWS no se comprobó.

### Tarea 3 — Clasificación de trabajo experimental

**Objetivo:** no continuar ideas obsoletas como si fueran requisitos actuales.

- `fazbear-telemetria`: sensores y publicador deshabilitado (503); no clickstream.
  Candidato a archivo sin mover/eliminar; patrón de validación/adaptador reutilizable.
- `fazbear-alertas`: umbrales térmicos y dedup; no cumple antifraude por tarjeta.
  Reutilización parcial de patrones, no del dominio.
- `fazbear-monitoreo`: series de sensores/promedios; no recomendaciones de productos.
  Candidato a archivo; persistencia/tests como referencia.
- `ms-incidentes`: sugerencia histórica en conversación, sin proyecto encontrado.
- `Plan_EV3.md`: conservar histórico, superado como hoja de ruta activa.
- No se encontraron ms-pago ni ms-analytics-recommendations en el workspace revisado.

**Contraste de guías:** el ejemplo antifraude por cliente y `>=3` no coincide
con la regla de tarjeta y `>3`; su contador desde el último intento no es una
ventana deslizante correcta. La guía de recomendaciones usa catálogo ficticio
y suma histórica: adaptar a Fazbear, identidad validada, recencia y deduplicación.

## 5. Comandos, verificaciones y resultados del bloque

Ejecutados localmente:

```text
git status --short --branch
git branch -a -vv
git log -1 --format=...
git ls-remote --heads origin
git init --bare / git fetch --depth=1 --no-tags (solo temporales)
git archive / git diff --stat / git diff --name-status
git diff --quiet refs/audit/ev2 refs/audit/ev3 -- src/main/java
Extracción DOCX System.IO.Compression + XML
Comprobaciones estáticas y búsquedas de contratos/dependencias
```

Resultados: siete ramas EV3 verificadas; fuente Java sin diferencias en
carrito/orden/notificaciones/reportes; cuatro comprobaciones de regresión/contrato
coinciden; sin coincidencias de implementación Kafka/pago/extras en las siete fuentes.

**No se ejecutaron** suites unitarias/integración, npm/Maven build, Docker, AWS,
compras, SMTP ni publicación/reenvío de eventos. No se instaló una dependencia nueva.
Los resultados históricos de 26 tests de sensores o tests EV2 no son pruebas nuevas.

**Archivos modificados/creados del proyecto:** exclusivamente
`docs/Informe_Fazbear_EV3.md` y `docs/AUDITORIA_EV2_A_EV3.md`.
No hay commit nuevo, push, release, imagen nueva o despliegue de este bloque.

## 6. Decisiones arquitectónicas propuestas (PLANEADO)

- Recuperación selectiva sobre ramas EV3, nunca rollback masivo de repos.
- Mantener `/api/`, dominios nuevos, MSAL, CORS correcto, CI/GHCR y ALB/VPC Link.
- RabbitMQ conserva compras; Kafka añade comportamiento/recomendaciones y eventos
  de pago/antifraude cuando corresponda, con contratos separados y versionados.
- Antifraude atómico por tarjeta, no depender de que un listener asíncrono alcance
  a bloquear la misma solicitud. ID seguro con token confiable/HMAC backend; no PAN/CVV persistidos.
- Resolver precio oficial, identidad, idempotencia y orden de confirmación antes de conectar ms-pago.
- Decidir Clock/ventana exacta/duración de bloqueo con pruebas controladas; cuarto
  intento dispara la regla, no tercero. Borde exacto de 10s requiere convención explícita.
- Recencia/afinidad deben usar catálogo real de Productos; evitar pesos/categorías
  confiados sin verificación desde Angular. No copiar catálogo de ejemplo.
- Extras solo después de lo obligatorio. No crear recursos cloud por inferencia.

## 7. Plan de ejecución y pausas

1. **Fase 1:** recuperar por bloques pequeños carrito → cancelación → stock →
   UI checkout/reportes/configuración, con regresiones locales y despliegues separados.
2. **Fase 2:** contratos Kafka, tópicos/keys/grupos/DLT y pruebas locales; broker AWS a cargo del usuario.
3. **Fase 3:** pago simulado, cotización de catálogo, registro/idempotencia/antifraude y coordinación con órdenes.
4. **Fase 4:** analytics/recomendaciones y Angular sobre productos reales.
5. **Fase 5:** Webpay/DynamoDB/WebSocket según autorización, costos y enunciado.
6. **Fase 6:** E2E y defensa con evidencia real.

Tras cada 1..3 tareas: actualizar bitácora y publicar CONTROL DE AVANCE; esperar autorización.
No publicar cambios ni imágenes sin autorización explícita de esa fase.

### Próximo bloque recomendado

**F1.1 — Carrito persistido:** preparar copia/rama de trabajo EV3 autorizada,
recuperar integración e inicialización EV2 adaptada a `/api/`, restaurar pruebas
de sync/render/error. Sin cambios AWS ni push en ese bloque salvo permiso adicional.
No avanzar a Kafka/pago mientras se modifica a la vez este flujo base.

## 8. Recuperación y evidencia operacional pendiente

Este bloque no necesita rollback funcional: no se modificó código ni AWS.
Conservar los documentos históricos y experimentos; no moverlos o eliminarlos.

Para futuros deploys usuario + ChatGPT deben aportar instance IDs nuevos,
digest actual/anterior por contenedor, overrides no secretos y salud TG/ALB.
Respaldar configuración privada antes del swap, conservar restart policies y
rollback por digest. H2 RAM no se recupera con rollback de imagen.
No usar scripts EV2 con IDs antiguos, `latest` o alias mutable como identidad de release.
No pedir inspección completa que exponga Env/SMTP/RabbitMQ/tokens.

**Sin evidencia SSM/navegador nueva de este bloque.** La única validación EV3
comunicada al inicio es frontend/login/catálogo. Los demás recorridos siguen pendientes.

## 9. Control de cierre del bloque

- [x] Inventario de workspace/ramas reales.
- [x] Comparación de carrito, stock, checkout, estados y contrato de orden.
- [x] Clasificación experimental contra documentos disponibles.
- [x] Informe y auditoría creados localmente, sin borrar historia.
- [x] Autorización de F1.1 (recibida después del cierre de Fase 0).
- [x] Implementación y pruebas locales del carrito F1.1 (ver bitácora siguiente).
- [ ] Publicación/despliegue/E2E de F1.1 y otras recuperaciones: requieren autorización/evidencia.

**PAUSADO — esperando autorización del usuario.**

## 10. Bitácora — F1.1, recuperación del carrito (11/11/2026)

Horario local de pruebas: 21:42..21:49, UTC-03. Los logs Angular expresan
12/11/2026 00:42..00:49 UTC; corresponden a la misma ejecución local del 11/11.

### Alcance autorizado y estado anterior

El usuario aprobó Fase 0 y autorizó exclusivamente restaurar el carrito del
frontend EV3, su integración con MSAL/navbar y la barrera antes de confirmar.
Prohibidos commits, push, publicaciones, despliegues, cambios backend/AWS y avance
a stock, Kafka, pagos/recomendaciones o arreglos generales de checkout.

Estado anterior EV3: signal local sin HTTP, sin carga al iniciar sesión y sin
espera de sincronización antes de construir la solicitud de orden.

### Actividad 1/3 — Preparación, comparación y revisión de seguridad

- `git ls-remote --heads origin ...` confirmó EV3 en
  **`dbbc6ca7ad1e0468609a4ef2cfd2fa99d18c5b49`** y EV2 en
  `44b907ad93636f45f66808223e30d7e424c43e3e`.
- El checkout histórico `fazbear-frontend` estaba limpio en `VP_AVANCE_EV2` y
  permanece ahí. No se modificó `main` ni se sustituyó ese checkout.
- Se descargó la referencia EV3 y creó el worktree independiente:

```text
Carpeta: C:\Users\ZorVa\Desktop\UN\CLOUDNTV\Proyecto semestral\fazbear-frontend-ev3-carrito
Rama local: ev3/recuperar-carrito-f1-1
HEAD/base: dbbc6ca7ad1e0468609a4ef2cfd2fa99d18c5b49 (sin nuevos commits)
```

- Comparados servicio/spec de carrito EV2, servicio EV3, App, navbar, drawer,
  checkout y tipos de OrdenService. No se copiaron en bloque archivos históricos
  que restauraran URLs viejas o eliminaran CI/MSAL nuevos.
- Revisado backend `ms-carrito` en snapshot EV3 `49fddca7...`: controller acepta
  `usuarioId` arbitrario por path; servicio usa ese ID sin contrastarlo con JWT;
  SecurityConfig exige `authenticated()` pero no propiedad del recurso. Falta de
  autorización de propietario **confirmada en fuente**, sin prueba de explotación AWS.
- El origen CORS Java sigue siendo `https://w8xu8o4pd7.execute-api.us-east-1.amazonaws.com`.
  Corregirlo para permitir el frontend nuevo requiere un bloque backend autorizado.

### Actividad 2/3 — Recuperación selectiva IMPLEMENTADA localmente

#### Servicio de carrito

- Base preservada: `https://uuzifgcyd2.execute-api.us-east-1.amazonaws.com/api/carrito`.
- GET idempotente después de autenticar; App y navbar comparten la misma carga.
- Cuenta activa de MSAL preferida; fallback solo si existe una única cuenta cacheada.
  Con varias sin selección no se elige la primera arbitrariamente. Sin cuenta no
  hay HTTP ni carrito `anonimo` utilizable para comprar.
- Se mantiene `localAccountId` en la URL por compatibilidad EV2; no se lo declara
  equivalente a `sub`. Identidad interna de sesión también incluye homeAccountId/tenantId.
- Todas las operaciones capturan la sesión/UID al encolarse. Cambio de cuenta o
  salida cancela suscripciones antiguas, descarta cola vieja y borra solo memoria
  local; nunca elimina el carrito remoto al hacer logout.
- GET/POST/DELETE serializados FIFO; `itemId` proviene de la respuesta real.
- Cambios de cantidad calculan delta en el momento de ejecutar contra el último
  estado confirmado, no contra una cantidad optimista antigua. Un objetivo ya
  aplicado no produce otro POST. Dos altas intencionales sí suman dos unidades.
- Validación de respuesta: dueño esperado, array de ítems, IDs/cantidades válidos,
  precio finito y ausencia de producto duplicado. No se inventan IDs ni éxito local.
- `sincronizado()` espera también operaciones añadidas mientras aguardaba la cola.
- Timeout HTTP del carrito: 15 segundos. No se reenvían automáticamente escrituras.
  Tras error se cancela la cola dependiente y se hace un GET de revalidación.
  Aunque ese GET funcione, se exige revisar y pulsar ACTUALIZAR antes de comprar.
  Si GET falla, lo mostrado es último estado conocido, **no prueba de persistencia**.

#### Diferencia deliberada con EV2

La UI muestra **estado confirmado por backend**, no una actualización optimista
que parezca persistida antes de recibir respuesta. Se informa “Sincronizando”.
Esto reduce rollbacks ambiguos y sobrescrituras de respuestas con varias operaciones.
No hay localStorage con datos de carrito/tokens añadido por esta tarea.

#### Integración UI/MSAL y límite de checkout

- App conserva `handleRedirectObservable`, selecciona la cuenta del resultado
  cuando existe e inicializa después; escucha estado None/cambio de cuenta/logout
  con desuscripción al destruirse. No se alteró MSALInstanceFactory ni interceptor.
- Navbar usa la misma cuenta seleccionada e inicializa idempotentemente. Logout
  limpia estado local antes de redirigir. El control admin por email sigue siendo
  presentación, no una nueva autorización backend.
- Drawer muestra sincronización/error/ACTUALIZAR, controla navegación duplicada
  y espera la cola antes de ir a checkout. Cantidades/quitar/vaciar se deshabilitan
  en la UI mientras sincroniza, sin bloquear altas intencionales en catálogo.
- Checkout solo se modificó para solicitar un snapshot confirmado, validar que
  sesión/revisión siguen vigentes y construir el payload desde ese snapshot.
  No confirma con carrito incierto/vacío ni después de destruirse durante la espera.
- La limpieza tras respuesta de orden solo se programa si sigue vigente la misma
  sesión/revisión. Un resultado tardío de A no borra el carrito de B ni cambios nuevos.
- `ConfirmarOrdenRequest.items` ahora usa `Omit<ItemCarrito, 'id'>[]`: separación
  de tipos frontend; **el JSON y contrato HTTP de ms-orden no cambiaron**.
- Se conservaron los manejadores generales existentes de la petición de orden.
  No se restauraron en este bloque los demás fixes generales de checkout, pedidos
  o reportes ni se desarrolló pago real, Kafka, stock o compensaciones.

### Archivos funcionales/pruebas afectados

Todos los siguientes son relativos a **`fazbear-frontend-ev3-carrito/`**, no al checkout histórico:

| Archivo | Cambio |
|---|---|
| `src/app/core/services/carrito.service.ts` | Servicio persistido, FIFO, sesión y recuperación segura |
| `src/app/core/services/carrito.service.spec.ts` | Nuevas/adaptadas pruebas EV2→EV3 y casos concurrentes/fallos |
| `src/app/app.ts` | Inicialización y eventos MSAL ligados al carrito |
| `src/app/app.spec.ts` | Sustituye test scaffold obsoleto por ciclo MSAL/carrito |
| `src/app/shared/navbar/navbar.component.ts` | Identidad coherente, init y salida local |
| `src/app/shared/navbar/navbar.component.spec.ts` | Init, contador y logout |
| `src/app/features/cart/carrito.component.ts` | Estado sincronizando/error y espera de navegación |
| `src/app/features/cart/carrito.component.spec.ts` | Mantiene accesibilidad y agrega errores/barrera de navegación |
| `src/app/features/checkout/checkout.component.ts` | Solo barrera/snapshot/limpieza de carrito y mensaje de sincronización |
| `src/app/features/checkout/checkout-carrito.spec.ts` | Confirmación mock, espera, fallos y aislamiento de sesión |
| `src/app/core/services/orden.service.ts` | Tipo de items sin el ID interno del carrito; JSON sin cambios |
| `src/app/core/auth/auth.config.spec.ts` | Verifica que /api/carrito siga en el protectedResourceMap |

**Sin diferencias contra la base EV3:** `auth.config.ts`, `app.config.ts`,
`.github/workflows/`, `package.json`, `package-lock.json`. No hay dependencias nuevas.
Los otros microservicios, ramas históricas y experimentos anteriores permanecen intactos.
Los dos documentos de `docs/` se actualizan en la raíz del workspace, como en Fase 0.

### Actividad 3/3 — Pruebas/build y resultados reales

Comandos ejecutados en el worktree:

```text
npm ci --no-audit --no-fund
npm test -- --watch=false
npm run build
git diff --check
git diff --exit-code <base-EV3> -- src/app/core/auth/auth.config.ts src/app/app.config.ts .github/workflows package.json package-lock.json
```

- `npm ci`: 387 paquetes según lockfile existente. Aviso npm sobre install scripts
  pendientes de cuatro dependencias; no se aprobó su ejecución global ni se actualizó npm.
- Primer intento de tests detectó un error TypeScript: el ID requerido para ítem
  confirmado no pertenece al DTO de orden. Corregido solo el tipo `Omit<..., 'id'>`.
- Ejecuciones intermedias: 52, 57 y 58 pruebas aprobadas al ampliar cobertura.
- **Resultado final: 59/59 pruebas, 6 archivos de test, cero fallos.**
- **Build de producción correcto**; salida en `dist/fazbear-frontend` del worktree.
- Warnings registrados: bundle inicial **608,11 kB** contra presupuesto 500 kB;
  estilos de checkout **5,04 kB** contra 4 kB. No se elevaron límites ni se suprimieron warnings.
- `git diff --check`: sin errores de whitespace. Git advierte conversión LF/CRLF
  según configuración local; no se cambió esa configuración.
- Comparación explícita de archivos protegidos (MSAL/interceptor/CI/dependencias): sin diferencias.

Cobertura comprobada: alta, altas repetidas, deltas +/- y objetivo repetido, cantidad
cero/quitar por itemId, quitar tras POST pendiente, vaciado, carga de instancia nueva
(simulación de recarga), init duplicada, cuenta activa/ambigua, cambio de identidad,
logout, respuestas malformadas/ajenas, 403/500/503/red/timeout, revalidación fallida,
cola cancelada, refresh explícito, snapshot copiado, barrera con nuevas operaciones,
doble clic de navegación/confirmación y resultados tardíos de otra sesión.

Las pruebas usan TestBed/HttpTestingController y mocks de MSAL/OrdenService
**solo en tests**. En runtime siguen MSAL e interceptor oficiales, sin token ficticio
ni desactivación de JWT. No hubo HTTP real al backend AWS, compras, SMTP o eventos.
No se ejecutaron Docker/Actions/GHCR ni se realizaron pruebas con una cuenta Azure real.

### Estado por nivel

| Nivel | Resultado F1.1 |
|---|---|
| PLANEADO | Recuperación aprobada; backend CORS/propiedad y E2E posteriores pendientes |
| IMPLEMENTADO | Sí, cambios locales del frontend en worktree dedicado |
| PROBADO LOCALMENTE | Sí, 59 tests y build de producción |
| PUBLICADO | **No**, sin commit/push/release/imagen GHCR |
| DESPLEGADO | **No**, AWS intacto |
| VALIDADO E2E | **No**, requiere backend compatible, despliegue y navegador |

### Riesgos, límites y recuperación

1. **Propiedad backend pendiente:** frontend no puede asegurar que otro cliente
   no modifique usuarioId manualmente. Ver A-09/F1.1 de la auditoría.
2. **CORS backend pendiente:** permitir `https://p5gsy16utd.execute-api.us-east-1.amazonaws.com`
   en ms-carrito, coherente con Gateway/ALB y preflight. No wildcard/desactivar JWT.
3. **Concurrencia limitada a esta instancia Angular:** no hay bloqueo distribuido
   entre pestañas/dispositivos. El POST por delta existente puede crear cantidad
   inválida si otro cliente elimina el ítem antes del decremento. Proponer PUT de
   cantidad/versionado y validación backend en bloque posterior, no modificarlo aquí.
4. Cancelar/timeout de HTTP no revierte una escritura ya recibida. Sin idempotencia
   backend no prometer exactamente una operación tras recarga o pérdida de respuesta.
5. Una mutación posterior al snapshot evita limpieza adicional del frontend, pero
   Orden backend actualmente vacía todo el carrito: resolver coordinación/versionado
   si se exige concurrencia con compras. No se añadió reserva de inventario.
6. Estado confirmado del carrito no certifica precio oficial ni autorización de compra;
   ambas validaciones siguen siendo responsabilidad backend pendiente antes de pagos.
7. Persistencia por recarga frontend depende de ms-carrito vivo; H2 en memoria puede
   perder datos al reiniciar. No se migró BD. No hay cola durable de acciones frontend.
8. Fuera de alcance: timeout/render general de orden, stock, cancelación de pedidos,
   correo/reportes y nuevos eventos. Las regresiones Fase 0 de esas áreas siguen pendientes.

No se necesita rollback AWS porque no se desplegó. No descartar ni borrar el
worktree con cambios: puede revisarse con `git -C fazbear-frontend-ev3-carrito diff`.
La copia histórica conserva el estado aprobado. Para una futura entrega se revisará
el diff, se autorizará commit/integración en `ev3/ci-frontend` y después CI/digest/swap.
El workflow actual solo se dispara en su rama configurada; crear una rama local
no publicó ni ejecutó ese pipeline.

### Próxima actividad propuesta y pausa

Revisar este diff y autorizar (o ajustar) el enfoque confirmado/no optimista.
Después, **bloque separado autorizado de ms-carrito**: corregir CORS y propiedad
con mapeo JWT/MSAL comprobado y tests A/B, antes de declarar E2E seguro. Alternativamente
el usuario puede priorizar otras tareas, sin iniciarlas automáticamente.

Necesidades AWS posteriores (usuario + ChatGPT): digest/configuración anterior,
stage/rutas `/api/carrito`, CORS/preflight, salud TG/ALB y preservación de H2/config.
Desplegar backend y frontend aprobados de manera controlada, luego GET/POST/DELETE
autenticados, recarga, cambio de cuenta y prueba de acceso ajeno rechazada.
No se requieren nuevas rutas para el contrato actual del carrito ni cambios AWS hoy.

**PAUSADO — esperando autorización. No hay commits ni push de esta fase.**

## 11. Bitácora — bloques A/B/C, publicación y diseño (11/11/2026)

Esta sección actualiza el estado posterior al cierre local de la sección 10;
los cierres anteriores permanecen como evidencia histórica, no como estado actual.

### Autorización y límites

Usuario autorizó commit/push de F1.1, inicializar tres repositorios y diseñar antes
de implementar. No autorizó merge a main/ev3/ci-frontend, despliegues AWS, cambios
a otros servicios existentes ni implementación completa de nuevos microservicios.
La elección del tercero es definitiva: **ms-fidelizacion — FazCoins y recompensas**.
No se continuaron ni eliminaron fazbear-telemetria/alertas/monitoreo.

### Actividad A/3 — Publicación F1.1

- Revisado diff funcional y alcance de los doce archivos, sin ampliar cambios.
- `git diff --check` correcto; comparación contra base de auth.config.ts,
  app.config.ts, workflows, package.json y package-lock.json sin diferencias.
- Reejecución `npm test -- --watch=false`: **59/59, seis archivos**, 11/11/2026
  22:18 UTC-03 (log Angular 12/11/2026 01:18 UTC).
- `npm run build`: correcto. Warnings inalterados: bundle inicial 608,11 kB frente
  a 500 kB y CSS checkout 5,04 kB frente a 4 kB; budgets sin modificar.
- Commit descriptivo y `git push -u origin ev3/recuperar-carrito-f1-1` exitosos.
- **SHA completo:** `92cbbcad3eb8598266e9a117af3e1cc42a2ca94e`.
- Rama: https://github.com/ZorVaK749/fazbears-frontend/tree/ev3/recuperar-carrito-f1-1
- Commit: https://github.com/ZorVaK749/fazbears-frontend/commit/92cbbcad3eb8598266e9a117af3e1cc42a2ca94e
- Base sigue siendo `dbbc6ca7ad1e0468609a4ef2cfd2fa99d18c5b49`.
  Worktree limpio tras commit; no merge ni cambios adicionales de código.
- El workflow solo escucha push a ev3/ci-frontend o ejecución manual. No se ejecutó
  dispatch ni se publicó imagen. Publicar esta rama no despliega ni valida E2E.
- `gh` no está disponible en PATH ni en las ubicaciones estándar consultadas;
  no se creó PR. Preparación manual, con **base ev3/ci-frontend**:
  https://github.com/ZorVaK749/fazbears-frontend/compare/ev3/ci-frontend...ev3/recuperar-carrito-f1-1?expand=1
  Seleccionar **Create draft pull request**, no fusionar. Título sugerido:
  `F1.1: recuperar carrito persistido con aislamiento de sesión y sincronización`.
  Descripción: 59 tests, build con warnings conocidos, CORS/ownership backend pendientes,
  sin validación AWS. No se solicitó ningún token/credencial.

### Actividad B/3 — Repositorios comprobados e inicializados

`git ls-remote` de las tres URLs terminó con código 0 y sin referencias. `git clone`
confirmó repositorios vacíos: **ya existían**, no se crearon repositorios remotos.
Los permisos Git existentes permitieron publicar, sin necesitar GitHub CLI.

| Repositorio GitHub | Rama inicial publicada | SHA completo |
|---|---|---|
| [fazbear-pago](https://github.com/ZorVaK749/fazbear-pago/tree/ev3/diseno-inicial) | ev3/diseno-inicial | `42173751d7267028696043738d887e72fc683a18` |
| [fazbear-analytics-recommendations](https://github.com/ZorVaK749/fazbear-analytics-recommendations/tree/ev3/diseno-inicial) | ev3/diseno-inicial | `01249e3775911966cf8493b1396ddd9e021aa21f` |
| [fazbear-fidelizacion](https://github.com/ZorVaK749/fazbear-fidelizacion/tree/ev3/diseno-inicial) | ev3/diseno-inicial | `fe318e807f32e836ff88f828b6cdd7bcb7fe0f88` |

Clones en carpetas de igual nombre en la raíz del workspace. Cada commit inicial
contiene exactamente seis archivos: `.gitignore`, `README.md`, `docs/ARQUITECTURA.md`,
`src/README.md`, `tests/README.md` y `deploy/README.md`. README y guías describen
estructura futura, no endpoints funcionando. No pom.xml, lógica, Dockerfile,
workflows activos, publicación GHCR ni pruebas funcionales de los servicios nuevos.
`git diff --cached --check` correcto antes de cada commit, worktrees limpios.
No se crearon/modificaron ramas main de los repositorios existentes.

### Actividad C/3 — Diseño técnico propuesto

Documento transversal nuevo: [ARQUITECTURA_NUEVOS_SERVICIOS_EV3.md](ARQUITECTURA_NUEVOS_SERVICIOS_EV3.md).
Detalla responsabilidades, tecnología, REST, JWT, entidades, almacenamiento,
Kafka/RabbitMQ, integraciones, seguridad/idempotencia, pruebas, Docker/CI y AWS.
Los documentos transversales de `docs/` siguen locales en la raíz sin Git; el
diseño específico de cada servicio sí está publicado dentro de su repositorio.

- **Pago:** Java 21/Spring Boot/PostgreSQL, cotización backend canónica, simulación
  identificada, idempotencia, antifraude síncrono por instrumento. Cuarto intento
  dentro de diez segundos bloqueado antes de cobrar; no tercer intento/clientId.
  No PAN/CVV; huella opaca derivada de instrumento backend. Kafka para resultados
  y alertas, no para decidir bloqueo eventual. Webpay posterior, sin credenciales hoy.
- **Analytics:** Kafka desde Productos/Carrito con catálogo real, proyección durable,
  ranking inicial determinista por recencia/afinidad y fallback, filtros de
  disponibilidad, deduplicación/versiones, identidad pseudónima y privacidad.
  Productores y endpoints de interacción aún no implementados.
- **Fidelización:** PostgreSQL durable, wallet y ledger append-only, reglas
  versionadas, crédito solo por pago confiable confirmado, inbox/outbox y unicidad
  de causa, canjes/reservas atómicos para evitar sobregiro/doble crédito/doble canje.
  **5% propuesto, no aprobado ni activo**; conversión/redondeo/topes/reversos pendientes.
  Angular FAZCOINS se conectará después, no administra saldo.
- **Bus:** RabbitMQ conserva pedido.creado v2 y procesamiento operativo. Kafka
  agrega comportamiento/resultados de pago/fidelización con contratos versionados;
  no reemplazo del bus ni bridge que duplique pedidos.

### Riesgos y decisiones de aprobación

1. CORS/ownership de ms-carrito siguen pendientes, sin autorización backend en este bloque.
2. Cotización confiable no existe aún en el contrato actual de Orden. Debe aprobarse
   coordinación pago→orden sin ejecutar antes compras ni duplicar pedido.creado.
3. Mapeo JWT `(tid,oid)`/localAccountId histórico debe verificarse, no asumir `sub`.
4. Falta aprobar moneda/escala (catálogo actual tiene decimales), duración de bloqueo
   y política de reintentos/conciliación para resultado externo UNKNOWN.
5. Reglas económicas FazCoins (5%, conversión, redondeo, elegibilidad, reembolsos con
   monedas gastadas) necesitan aprobación. Saldo demo no equivale a fondos reales.
6. Kafka/PostgreSQL/capacidad EC2/permisos Academy y backups no existen como evidencia
   de estos nuevos servicios. Definir costo/operación antes de provisionar.
7. No exactly-once global: outbox/inbox/unique constraints deben probarse con crash,
   duplicados y desorden. La arquitectura documental no demuestra esas garantías.

### Estado por nivel después de A/B/C

| Componente | IMPLEMENTADO | PROBADO LOCALMENTE | PUBLICADO | DESPLEGADO / VALIDADO E2E |
|---|---|---|---|---|
| Carrito F1.1 frontend | Sí | 59 tests + build | Código en rama y SHA arriba; sin imagen | No / No |
| Tres nuevos servicios | Solo estructura/documentación; lógica NO | Revisión documental/Git, sin tests funcionales | Seis archivos por repo en SHA arriba | No / No |
| Arquitectura/informe transversal | Documento propuesto local | Revisión de consistencia, no runtime | No: raíz del workspace sin Git | No aplica |

### Próximo bloque recomendado y pausa

Primero aprobar contratos de identidad/cotización/orden y políticas pendientes.
Luego autorizar por separado la corrección ownership/CORS de carrito con tests A/B.
Después elegir el primer bloque local de ms-pago: esqueleto, persistencia,
seguridad/idempotencia/antifraude, sin Webpay ni AWS. Esto no inicia ese trabajo.

**PAUSADO — esperando aprobación. Sin fusiones, AWS, compras reales, SMTP, eventos
RabbitMQ/Kafka ni implementación funcional de los tres nuevos servicios.**

## 12. Bitácora — F1.2, propietario y CORS ms-carrito (11/11/2026)

### Actividad 1/3 — Preparación e identidad

Autorización exclusiva: código/tests de Carrito, build, commit y push a rama
específica. No Angular/Orden/otros servicios, merge, AWS ni nuevos microservicios.

- `git ls-remote` confirmó `ev3/ci-carrito` en
  **`49fddca7d0819ea0ec8e4d5014293057d3a93eb1`**.
- Checkout histórico `fazbear-carrito` limpio en `VP_AVANCE_EV2`, preservado.
- Worktree nuevo `fazbear-carrito-ev3-seguridad`, rama `ev3/seguridad-carrito-f1-2`.
- Revisados controller, seguridad, servicio, entidades, propiedades, tests y build;
  fuente instalada MSAL y snapshot EV3 de Orden solo en lectura.
- Referencia oficial consultada:
  https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference
  oid identifica usuario/service principal dentro del tenant; tid identifica el
  tenant; sub es pairwise por aplicación; scp caracteriza permisos delegados.
- MSAL `@azure/msal-common/dist/cache/entities/AccountEntity.mjs:112-116` usa
  clientInfo.uid → ID-token oid → ID-token sub para localAccountId; perfiles de
  tenant también usan oid/sub. **No equivale universalmente al access-token oid**.
  No se inspeccionaron tokens reales ni se comprobó el mapeo del laboratorio.

**Criterio elegido:** identidad lógica `(tid validado del tenant único, oid GUID)`.
Se conserva oid como clave persistida/URL bajo tenant fijo. No soporte multitenant;
cambiar tenant reutilizando BD requiere migración/aislamiento primero.
Firma/issuer/audience/tiempos siguen validados; ahora también tid configurado.

Los cuatro endpoints exigen path == oid y scope delegado exacto `access_as_user`
antes de llamar al servicio; pasan el oid verificado, no un usuario libre del body.
JWT válido sin identidad/scope o acceso ajeno → **403**, sin crear carrito.
Sin JWT o con firma/issuer/audience/tenant/exp/nbf inválidos → **401**.
Sin fallback a sub/email/homeAccountId, aliases ni bypass admin/app-only.

### Actividad 2/3 — Implementación y pruebas

CORS central Spring Security para `/api/carrito/**`, eliminando anotación antigua:
orígenes exactos `https://p5gsy16utd.execute-api.us-east-1.amazonaws.com` y
`http://localhost:4200`; GET/POST/DELETE/OPTIONS; Authorization/Content-Type;
maxAge 3600s; sin wildcard y sin credenciales cookie. Bearer explícito conservado.
Preflight sin JWT antes de autenticación; requests reales siguen protegidos.
Tests verifican CORS también en respuestas 401/403 y rechazan origen EV2/ajenos,
host parecido, métodos y headers no aprobados.

**A-12 adicional:** POST enlazaba entidad JPA con ID asignable desde JSON. Nuevo DTO
solo copia productoId/nombreProducto/cantidad/precioUnitario a entidad sin ID;
ignora IDs/usuario/relaciones del cliente. Evita mass assignment de ítem ajeno usando
path propio. No cambia JSON válido de Angular, deltas ni reglas de negocio existentes.

Archivos relativos a `fazbear-carrito-ev3-seguridad/` (10 en el commit):

| Archivo | Cambio |
|---|---|
| `src/main/java/com/fazbear/carrito/config/SecurityConfig.java` | tid, CORS central y JWKS configurable |
| `src/main/java/com/fazbear/carrito/security/CarritoOwnerAuthorization.java` | Política compartida oid/tid/scope |
| `src/main/java/com/fazbear/carrito/controller/CarritoController.java` | Principal JWT y autorización previa al servicio |
| `src/main/java/com/fazbear/carrito/controller/AgregarItemRequest.java` | DTO sin IDs/relaciones persistentes |
| `src/main/java/com/fazbear/carrito/model/Carrito.java` | Comentario de identidad, sin cambio de esquema |
| `src/main/resources/application.properties` | Tenant explícito coherente con issuer |
| `src/test/java/com/fazbear/carrito/LocalJwtTestSupport.java` | RSA efímero/JWKS loopback y propiedades de test |
| `src/test/java/com/fazbear/carrito/CarritoSecurityIntegrationTests.java` | Seguridad, CORS y regresiones |
| `src/test/java/com/fazbear/carrito/CarritoApplicationTests.java` | Contexto local sin Azure |
| `docs/SEGURIDAD_CARRITO_F1_2.md` | Política/compatibilidad/pruebas/procedimiento futuro |

Sin diferencias en pom/dependencias, Dockerfile/workflow, servicio ni repositorio
JPA. Ningún código de otros servicios o Angular modificado. Informes acumulativos
se mantienen locales en raíz sin Git, como en fases anteriores.

#### Evidencia real

- Java 21.0.12.1, Maven 3.9.x, Boot 4.1.1 existente; release 17 del pom conservado.
- `mvn -B -DskipTests package`: compilación inicial, no cuenta como pruebas.
- `mvn -B test`: 39 aprobadas en ejecución intermedia.
- **`mvn -B clean verify`: 44 tests, cero fallos/errores/omitidos, BUILD SUCCESS**.
  Ejecución 11/11/2026 22:40 UTC-03: 43 casos de integración + uno de contexto.
- JAR: `target/carrito-0.0.1-SNAPSHOT.jar` generado y repackaged correctamente.
- `git diff --check`, `git diff --cached --check` correctos; comparación explícita
  de archivos protegidos sin diferencias. Avisos LF/CRLF, sin cambiar config Git.
- Warnings conservados: H2Dialect explícito, open-in-view y auto-attach de
  Mockito/ByteBuddy en Java 21. Sin ocultarlos ni modificar configuración global.

JWT RS256 firmados por claves efímeras de test, JWKS público en loopback aleatorio;
decoder Nimbus/validadores/filtros/controlador/servicio/JPA/H2 **reales**. Sin helper
jwt() que salte decoder ni JwtDecoder mock. No Azure, tokens reales o brokers.
jwk-set-uri por defecto vacío conserva discovery Azure; solo propiedades dinámicas
de test seleccionan el JWKS local, nunca configuración runtime final.

Cobertura: propio/ajeno y sin JWT en cuatro endpoints; oid ausente/inválido/no
string, sub distinto o igual sin oid, scope, roles/admin/app-only, mismo oid en
otro tenant; tid inválido/ausente/numérico, firma/issuer/audience/exp/nbf; CORS
preflight/request; altas repetidas/ID/lectura/delta/total/quitar/vaciar, itemId
ajeno e inyección por body; DELETE con Bearer original sin Origin como el de Orden.

### Actividad 3/3 — Publicación y documentación

- **SHA:** `8478261e454f43f0fdfd9b7a847e814e5a553f5d`.
- Commit: `fix(carrito): autorizar propietario Azure y actualizar CORS EV3`.
- Push autorizado a `ev3/seguridad-carrito-f1-2`, worktree limpio.
- Rama: https://github.com/ZorVaK749/fazbear-carrito/tree/ev3/seguridad-carrito-f1-2
- Commit: https://github.com/ZorVaK749/fazbear-carrito/commit/8478261e454f43f0fdfd9b7a847e814e5a553f5d
- Sin merge a main/CI. Workflow publicar-carrito.yml escucha ev3/ci-carrito o
  dispatch; esta rama no lo dispara. Sin dispatch, imagen GHCR, tag o release.
- Sin PR creado (GitHub CLI no disponible); comparación para Draft con base CI:
  https://github.com/ZorVaK749/fazbear-carrito/compare/ev3/ci-carrito...ev3/seguridad-carrito-f1-2?expand=1

### Compatibilidad y riesgos pendientes

Angular no requiere cambio **si** localAccountId coincide exactamente con oid del
access token del tenant activo. Guest/clientInfo/sub/cache o capitalización distinta
pueden producir 403. Si ocurre, proponer resolución de identidad backend validada
(posible /me), misma clave para carrito/orden y migración con evidencia de propiedad.
Nunca aceptar indistintamente sub/oid/IDs enviados libremente por el navegador.

Orden EV3 reenvía Bearer original al DELETE Carrito y usa usuarioId del request.
Ese contrato se conserva para el oid propio (base interna debe incluir /api).
Solo se probó el contrato de entrada a Carrito, **no la integración real Orden**.
ID distinto se rechaza; Orden actualmente considera fallo de limpieza no crítico
después de crear/publicar pedido. Su ownership sigue fuera de alcance y no se
agregó excepción de seguridad para que borre carritos ajenos.

Persisten H2 mem/create-drop, consola H2 histórica permitAll, precios/cantidades
cliente, concurrencia entre pestañas e idempotencia de escrituras. A-11 no resuelto.
Revisar exposición de H2-console por Gateway/ALB; deshabilitarlo en producción
requiere bloque autorizado. H2 tests no demuestra durabilidad/concurrencia distribuida.

### Procedimiento AWS recomendado — NO ejecutado

1. Revisar diff y correspondencia localAccountId/oid para cuentas A/B en tenant
   activo, sin compartir JWT/cookies/Authorization; solo resultados/booleanos.
2. Usuario/ChatGPT reúne por SSM digest/config actual, instancia/TG/puerto/rutas,
   issuer/audience/tenant y base interna Carrito en Orden (/api). No usar IDs/IPs EV2.
3. Antes de reinicio, acordar conservación/exportación si hay carritos valiosos:
   H2 mem/create-drop pierde datos. Rollback de imagen Docker no los recupera.
4. Autorizar por separado PR/publicación/despliegue; imagen por digest y tests antes
   de publicar (Dockerfile histórico skipTests). No mover ev3-test ni ejecutar CI hoy.
5. Swap controlado, salud TG y rutas /api/carrito; comprobar CORS/preflight efectivo
   en Spring y Gateway. No abrir endpoints de health para evitar JWT por conveniencia.
6. Con carritos desechables/autorización: A solo A, B solo B, A→B 403 sin efectos;
   sin JWT 401; agregar/delta/quitar/vaciar/recargar/cambiar cuenta. DELETE delegado
   aislado para probar limpieza, **sin confirmar compras reales ni RabbitMQ**.
7. Registrar evidencia de ambos componentes antes de declarar E2E. Si se requiere
   adaptación Angular/Orden, detener y pedir autorización específica.

Procedimiento detallado también publicado en `docs/SEGURIDAD_CARRITO_F1_2.md` del repo.

| Nivel | F1.2 |
|---|---|
| IMPLEMENTADO | Propietario/CORS y DTO seguro |
| PROBADO LOCALMENTE | 44 tests firmados + clean verify |
| PUBLICADO | Código/pruebas/documento en rama y SHA arriba; sin imagen |
| DESPLEGADO | No |
| VALIDADO E2E | No; identidad real/infraestructura pendientes |

Próximo bloque propuesto: revisión de identidad y preparación autorizada de
despliegue/pruebas A/B. Si mapeo falla, priorizar bloque coordinado de identidad
sin relajar política. No Kafka, pagos, FazCoins ni recomendaciones.

**PAUSADO — esperando autorización.**

## 13. Bitácora — F1.3, contrato de identidad frontend/backend (12/11/2026)

### Actividad 1/3 — Backend /me y reglas compartidas

Autorización exclusiva del usuario: contrato de identidad Carrito/Angular,
pruebas/build, commits/push en ramas nuevas; sin imágenes, merge, AWS, compras,
Kafka/RabbitMQ/pagos/FazCoins ni cambios al servicio Orden.

Referencias conservadas limpias, sin nuevos commits en las ramas anteriores:

- Frontend: `ev3/recuperar-carrito-f1-1`,
  `92cbbcad3eb8598266e9a117af3e1cc42a2ca94e`.
- Backend: `ev3/seguridad-carrito-f1-2`,
  `8478261e454f43f0fdfd9b7a847e814e5a553f5d`.

Nuevos worktrees `fazbear-frontend-ev3-identidad` y `fazbear-carrito-ev3-identidad`,
ambos en rama `ev3/identidad-carrito-f1-3` de sus respectivos repositorios.

**Contrato final:** GET `/api/carrito/me`, sin parámetros de identidad reconocidos,
devuelve únicamente `{usuarioId: oidValidado, tenantId: tidValidado}` con
`Cache-Control: no-store`. No devuelve JWT/scopes/email ni crea/lee un carrito.
Mapping literal GET tiene prioridad sobre `/{usuarioId}`; no existe carrito `me`.
Los parámetros usuarioId/tenantId no cambian el principal ni el resultado.

`requireIdentity(jwt)` comparte oid/tid/scope con `requireOwner(jwt,path)`; este
último sigue exigiendo igualdad del path con oid en las cuatro operaciones.
Mismos decoder Nimbus, firma/JWKS, issuer/audience/vigencia, tenant único y scope
delegado access_as_user de F1.2. 401 sin token/tenant inválido, 403 sin oid válido
o scope. Sin bypass admin/app-only ni cambios CORS/dependencias/seguridad adicional.

### Actividad 2/3 — Frontend y regresión

Inicialización serial: **/me → GET carrito verificado → escrituras FIFO**.
Se conserva MSAL/interceptor y la URL Gateway `/api/carrito`; no se deduce oid de
localAccountId/sub/ID token ni se acepta propietario de un formulario o parámetro.

- Identidad backend almacenada solo en memoria dentro de su sesión; init/refresh
  concurrentes comparten cola. No localStorage ni alias persistido.
- localAccountId/homeAccountId/tenantId MSAL quedan como clave de aislamiento local,
  no como identificador de propietario remoto.
- Forma de respuesta/segmento de URL y tenant deben ser coherentes con la autoridad
  Azure configurada (`AZURE_TENANT_ID`); no exigir tenant de origen guest == recurso.
  Frontend no valida criptográficamente claims: lo hace el backend en cada operación.
- Antes/después de await se verifica sesión/cuenta; cambio/logout cancela HTTP y
  tareas antiguas. Incluso respuesta ya entregada con continuación pendiente no
  dispara GET ni cambia la identidad de una sesión nueva.
- Error/timeout/404 de /me bloquea carga/escrituras/checkout, sin fallback. ACTUALIZAR
  reintenta lecturas y no reproduce cambios descartados. Sin retry automático POST.
- Snapshot confirmado incluye usuarioId backend y tenantId local. Checkout ya
  mapeaba snapshot.usuarioId al payload Orden: no cambia JSON ni el backend Orden;
  tenantId/metadatos internos no se envían a ese contrato. Se mantienen barrera,
  revisión de sesión, estado confirmado e itemIds y limpieza protegida de F1.1.

#### Archivos afectados en los commits

Backend (4, relativos a `fazbear-carrito-ev3-identidad/`):

1. `src/main/java/com/fazbear/carrito/controller/CarritoController.java`: GET /me.
2. `src/main/java/com/fazbear/carrito/security/CarritoOwnerAuthorization.java`: identidad compartida.
3. `src/test/java/com/fazbear/carrito/CarritoIdentityIntegrationTests.java`: 12 casos nuevos.
4. `docs/IDENTIDAD_CARRITO_F1_3.md`: contrato/compatibilidad/despliegue.

Frontend (5, relativos a `fazbear-frontend-ev3-identidad/`):

1. `src/app/core/services/carrito.service.ts`: resolver identidad por sesión antes de cargar.
2. `src/app/core/services/carrito.service.spec.ts`: adaptar escenarios previos al handshake.
3. `src/app/core/services/carrito-identidad.spec.ts`: 21 casos nuevos de identidad/races/errores.
4. `src/app/features/checkout/checkout-carrito.spec.ts`: handshake y dos pruebas nuevas Orden.
5. `docs/IDENTIDAD_CARRITO_F1_3.md`: contrato frontend, pruebas y procedimiento.

Sin cambios en auth.config.ts/app.config.ts/interceptor, workflows, package/lockfile,
checkout runtime u OrdenService frontend; backend sin cambios pom/dependencias,
Dockerfile/workflow, config/propiedades, esquema o servicio/JPA. Los informes
transversales se actualizan en raíz sin Git, no están publicados en esos commits.

#### Pruebas y builds ejecutados

Backend: **`mvn -B clean verify`: 56/56, cero fallos/errores/omitidos, BUILD SUCCESS**.
12/11/2026 00:02 UTC-03. Conserva 44 de F1.2 y agrega 12; JAR ejecutable generado.
JWT RS256 efímeros firmados/JWKS loopback; Nimbus y validadores/filtros/JPA reales.
Prueba /me A/B, dos campos/no-store, sin efectos BD, parámetros sin autoridad,
sin token/oid/scope, tenant inválido, CORS, rutas anteriores y rechazo de alias
para mutaciones. Sin Azure/tokens reales ni infraestructura externa.

Frontend:

- `npm ci --no-audit --no-fund`: 387 paquetes según lockfile, sin dependencias nuevas.
  Avisos de cuatro install scripts pendientes, sin aprobación global.
- Primera regresión adaptada: 59/59 pasan; ampliación detectó tipo inferido de
  categoria demasiado amplio en fixture nuevo. Corregido tipando como Producto,
  sin cambios runtime para hacerlo pasar.
- **`npm test -- --watch=false`: 82/82, siete archivos**, 12/11 00:06 UTC-03
  (log Angular 03:06 UTC). Conserva los 59 escenarios y agrega 21 de identidad + 2
  checkout. Comparación UTF-8 con Git verificó los 59 nombres anteriores presentes.
- **`npm run build`: correcto**, inicial **608,13 kB / budget 500**, CSS checkout
  **5,04 kB / budget 4**. Presupuestos sin modificar, warnings visibles.
- HttpTestingController y mocks MSAL/OrdenService solo en tests. Comprueba uid
  backend distinto de localAccountId y tenant recurso distinto de origen, FIFO,
  inicialización compartida, cambio/logout, cancelación, respuesta tardía ya
  entregada, 401/403/404/503/red/timeout/DTO inválido, ACTUALIZAR, snapshot viejo,
  bloqueo de checkout y usuarioId correcto en Orden (sin tenantId extra).

Diff/checks de whitespace e invariantes protegidos correctos. Advertencias backend
H2Dialect/open-in-view/Mockito se conservan como en F1.2; no se ocultaron.

### Actividad 3/3 — Publicación y documentación

| Repositorio | Rama publicada | SHA completo |
|---|---|---|
| ZorVaK749/fazbear-carrito | ev3/identidad-carrito-f1-3 | `cfcc7e39dfc4ae4a92ed4405134a056df363ce33` |
| ZorVaK749/fazbears-frontend | ev3/identidad-carrito-f1-3 | `9f1a11e353c930a60c1403aad45a413477895ba9` |

- Backend: https://github.com/ZorVaK749/fazbear-carrito/commit/cfcc7e39dfc4ae4a92ed4405134a056df363ce33
- Frontend: https://github.com/ZorVaK749/fazbears-frontend/commit/9f1a11e353c930a60c1403aad45a413477895ba9
- Push de ambos exitoso. Sin merge a main/ev3/ci-*, sin dispatch, release o imagen.
  Workflows existentes escuchan ramas CI, no estas ramas de trabajo.
- No PR creado (CLI no disponible). Comparar con ramas base F1.1/F1.2 para review
  incremental; si luego se apunta a CI incluirá cambios acumulados y requerirá
  aprobación expresa. Nada se fusiona automáticamente.

### Compatibilidad y riesgos

No migración ni mezcla automática de datos. Carrito guardado bajo oid del tenant
fijo sigue accesible. Clave histórica sub/clientInfo.uid/otro alias puede quedar
fuera del carrito actual y aparentar vacío: reconciliar solo con prueba de
propiedad y autorización aparte; nunca aceptar IDs indistintamente.

Orden recibe el oid correcto por el payload de checkout y reenvía el mismo Bearer
para DELETE; pruebas cubren payload mock/entrada Carrito, no Orden real ni compra.
No se corrigen validación de propietario/total del propio Orden o otros servicios.

**Dependencia adicional encontrada, no modificada:** historial
`features/orders/orders.component.ts:223-224` y perfil
`features/perfil/perfil.component.ts:217-222` aún toman primera cuenta/localAccountId
para consultar pedidos. Si difiere del oid usado al crear, podrían no mostrar los
pedidos nuevos. Requieren bloque coordinado de identidad/ownership con Pedidos;
no se amplía silenciosamente el alcance a esas pantallas ni al microservicio.

Persisten H2 efímero/console, precios cliente, concurrencia e idempotencia backend.
Tampoco se probó Azure real, CORS/Gateway/ALB actuales, persistencia tras restart o
flujo E2E. La selección del Bearer sigue a cargo del interceptor MSAL preservado.

### Procedimiento futuro, no ejecutado, y pausa

1. Revisar/aprobar diff conjunto y plan de datos históricos/H2 antes de reiniciar.
2. Autorizar aparte publicación de imágenes por digest y despliegue controlado.
3. **Backend primero** (F1.2 + /me): confirmar issuer/audience/tenant, forwarding
   literal `/api/carrito/me` y rutas previas, TG/ALB/Gateway y CORS/preflight.
4. Desplegar frontend después; frontend nuevo con backend viejo falla cerrado en
   /me y no debe tener fallback. Rollback debe coordinar compatibilidad de ambos;
   una imagen anterior no recupera H2 ni migra claves históricas.
5. Con autorización/cuentas/carritos desechables, verificar /me A/B sin compartir
   tokens, operaciones propias/ajenas, logout/recarga/respuestas tardías y fallos.
   DELETE delegado aislado sin ejecutar compra, SMTP o RabbitMQ.
6. Registrar digests/config y resultados antes de E2E. Proponer como próximo bloque
   resolver alcance de historial/perfil/Pedidos y preparar revisión de identidad
   integrada; ninguna implementación/despliegue iniciados sin nueva autorización.

| Nivel | F1.3 |
|---|---|
| IMPLEMENTADO | /me backend y consumo por sesión/checkout frontend |
| PROBADO LOCALMENTE | Backend 56, frontend 82 y builds correctos |
| PUBLICADO | Código/pruebas/documentos en dos ramas y SHAs arriba; sin imágenes |
| DESPLEGADO | No |
| VALIDADO E2E | No |

**PAUSADO — esperando autorización. Sin AWS, compras reales, Kafka/RabbitMQ,
pagos ni FazCoins.**

## 14. Bitácora — F1.4, identidad y seguridad de Pedidos (12/11/2026)

### Actividad 1/3 — Revisión y alcance de autorización

F1.3 aprobada por usuario en implementación/pruebas locales, aún no desplegada.
Autorización exclusiva F1.4: frontend identidad Perfil/Historial y backend Pedidos,
tests/build/commits/push; no Orden, merge/CI, imágenes, AWS ni nuevas funcionalidades EV3.

Bases confirmadas:

- Frontend `ev3/identidad-carrito-f1-3`: `9f1a11e353c930a60c1403aad45a413477895ba9`.
- Pedidos `ev3/ci-pedidos`: `e4438d1b6ba2c7e7eb6b622728e7d9abec1a7a88`.
- Nuevos worktrees: `fazbear-frontend-ev3-pedidos` y `fazbear-pedidos-ev3-seguridad`.
  Checkouts históricos EV2 y worktrees F1.1/F1.2/F1.3 preservados.

Revisión encontró: GET global descargado/filtrado en Angular; consultas propias
por localAccountId/primera cuenta; cuatro listas ADMIN_EMAILS (Navbar, Perfil,
Historial y Reportes); controller Pedidos sin ownership y POST enlazando entidad
JPA con IDs asignables; enum EV3 perdió CANCELADO. Orden snapshot EV3 inspeccionado
solo en lectura, sin ejecutarlo.

**No se suministró evidencia verificable de app roles/asignaciones Azure reales**.
No se inspeccionó Azure ni se afirma que esos roles no existan en el tenant.
Por instrucción del usuario, se mantiene cierre administrativo: sin bypass por
email/roles inventados ni contrato positivo administrativo no comprobable. Rutas
conservadas, pero administración siempre 403 hasta otra autorización/verificación.

### Actividad 2/3 — Implementación y pruebas

#### Pedidos: política final de esta fase

Identidad `(tenant único validado, oid GUID)` y scope delegado exacto access_as_user,
como Carrito. Decoder conserva firma/issuer/audience/tiempos y valida tid explícito;
sin JWT/validación inválida 401, identidad/scope incorrectos 403. Sin email/sub como
autorización ni permisos app-only. Datos siguen por oid en tenant fijo; cambiar
tenant sobre la misma BD exige aislamiento/migración.

| Ruta | Resultado autorizado |
|---|---|
| GET /api/pedidos | 403; listado administrativo cerrado |
| GET /api/pedidos/{id} | Propio 200; ajeno o inexistente 404 |
| GET /api/pedidos/usuario/{usuarioId} | oid propio 200, otro usuario 403 |
| POST /api/pedidos | Deriva propietario JWT; body ausente se deriva, si existe debe coincidir; ajeno 403 |
| PUT /api/pedidos/{id}/estado | Solo cancelación propia PENDIENTE→CANCELADO; repetir CANCELADO propio es idempotente |
| DELETE /api/pedidos/{id} | 403; eliminación administrativa cerrada |

PUT administrativo/reinicio de estado y POST declarando PREPARANDO/COMPLETADO/
CANCELADO denegados 403. PUT cancelando PREPARANDO/COMPLETADO → 409; ajeno o
inexistente → 404; estado inválido/ausente → 400. No se revela existencia ajena.
UPDATE transaccional condicionado por id/propietario/PENDIENTE evita una carrera
read-modify-write; tests incluyen dos cancelaciones concurrentes.

Nuevo DTO de creación no enlaza IDs/relaciones JPA del cliente y fuerza PENDIENTE,
preservando campos de negocio que usa Orden. No permite sobrescribir pedidos/ítems
ajenos por un ID en JSON. Email/total/precio recibidos **no son datos certificados**.
Se recupera CANCELADO de EV2; cancelar no publica eventos, repone stock, reembolsa
ni revierte reportes automáticamente.

CORS central Spring Security: frontend actual exacto y localhost:4200,
GET/POST/PUT/DELETE/OPTIONS y Authorization/Content-Type, sin wildcard/cookies.
Preflight antes de autenticación; solicitudes reales protegidas, origen EV2/ajenos
rechazados. No modificación de Gateway/ALB ni validación CORS AWS.

#### Frontend: identidad y consultas compartidas

Carrito expone señal readonly con identidad ya obtenida de /me y número de sesión,
sin endpoint adicional ni consultas /me paralelas. Señal se limpia en logout/cambio;
esIdentidadActual verifica sesión, oid/tid y cuenta activa. localAccountId solo
permanece para clave local de sesión y tests, no como ID remoto ni perfil mostrado.

Nuevo MisPedidosService singleton comparte GET propio entre Perfil/Historial,
cancela GET/PUT viejos, limpia estado al cambiar sesión y rechaza respuestas ajenas.
Guardas de generación/cuenta previenen callbacks tardíos. Timeout 15s y error
visible/ACTUALIZAR; no éxito optimista ni retry de cancelación. Revalida al volver
a las pantallas sin duplicar consulta pendiente o resolver /me de nuevo. Signals
actualizan vistas sin detectChanges tardío sobre componentes destruidos.

Se retiran las cuatro ADMIN_EMAILS. Sin roles verificables, UI administrativa
cerrada: Perfil/Navbar no anuncian admin por correo, Historial no llama GET global
ni ofrece PREPARAR/COMPLETAR/ELIMINAR. Reportes no consulta API ni concede acceso
por email, incluso invocando cargar; **esto no asegura el backend Reportes**, que
no se modificó. Funcionalidad admin histórica sigue en referencias Git y requiere
otro bloque de seguridad para habilitarse, no se declara recuperada operativamente.

**Checkout intacto**: comparación explícita de toda su carpeta contra F1.3 sin
diferencias. MSAL/auth/interceptor, app.ts/config, dependencias/lockfile/workflows
preservados. Backend pom/Dockerfile/workflow sin diferencias.

#### Archivos cambiados

Frontend (9, relativos a `fazbear-frontend-ev3-pedidos/`):
`src/app/core/services/{carrito.service.ts,pedido.service.ts,mis-pedidos.service.ts}`;
`src/app/features/orders/{orders.component.ts,pedidos-identidad.spec.ts}`;
`src/app/features/perfil/perfil.component.ts`;
`src/app/features/reportes/reportes.component.ts`;
`src/app/shared/navbar/navbar.component.ts`; `docs/IDENTIDAD_PEDIDOS_F1_4.md`.

Backend (14, relativos a `fazbear-pedidos-ev3-seguridad/`):
`src/main/java/com/fazbear/pedidos/config/SecurityConfig.java`;
`controller/{PedidoController.java,CrearPedidoRequest.java}`;
`security/PedidoAuthorization.java`; `model/{EstadoPedido.java,Pedido.java}`;
`repository/PedidoRepository.java`; `service/{PedidoService.java,PedidoServiceImpl.java}`
(las rutas abreviadas anteriores están bajo el mismo paquete principal);
`src/main/resources/application.properties`;
`src/test/java/com/fazbear/pedidos/{PedidosApplicationTests.java,LocalJwtTestSupport.java,PedidoSecurityIntegrationTests.java}`;
`docs/SEGURIDAD_PEDIDOS_F1_4.md`.

#### Resultados reales

- `npm ci --no-audit --no-fund`: 387 paquetes según lockfile; avisos de scripts
  pendientes sin aprobación global, sin dependencias nuevas.
- Frontend: primera regresión 82/82; ampliación 97/97; final
  **`npm test -- --watch=false`: 98/98, ocho archivos**, 82 anteriores sin editar
  sus tests + 16 nuevos Perfil/Historial/Reportes/sesiones/cancelación.
- **`npm run build`: correcto**, inicial **608,48 kB / 500 kB**, CSS checkout
  **5,04 kB / 4 kB**. Warnings visibles, no se elevaron presupuestos.
- Backend: primera suite 43/43; final **`mvn -B clean verify`: 45/45**, cero
  fallos/errores/omitidos, BUILD SUCCESS/JAR ejecutable. 44 integración + contexto.
- Finales 12/11/2026 ~10:07 UTC-03 (frontend Angular 13:07 UTC). Java 21 con release
  17 del pom existente, Boot 4.1.1. Warnings H2Dialect/open-in-view/Mockito visibles.
- Backend usa JWT RS256 efímeros firmados y JWKS loopback; Nimbus/validadores/
  filtros/controller/servicio/JPA/H2 reales. Sin JWT reales, Azure, brokers, SMTP
  ni llamadas al servicio Orden. Frontend HTTP/MSAL simulados solo en tests.
- Diff checks correctos; advertencias Git LF/CRLF sin cambiar configuración global.

Cobertura: A solo propios, B no lee/cancela A, GETglobal/DELETE/estado administrativo
rechazados incluso con rol/email de prueba, usuario falso en body e IDs persistentes,
seis rutas sin JWT, firma/issuer/audience/tid/tiempos/oid/scope, CORS, JSON Orden,
CANCELADO/transiciones/carrera/replay; UI comparte consulta con ID backend != ID
MSAL, cuenta/logout/respuestas tardías/timeout/errores y actualización de ambas vistas.

### Actividad 3/3 — Publicación y documentación

| Repo | Rama publicada | SHA completo |
|---|---|---|
| ZorVaK749/fazbears-frontend | ev3/identidad-pedidos-f1-4 | `84b523dda8a2fd7fa8cdf0da7b8018f0fd7e08c0` |
| ZorVaK749/fazbears-pedidos | ev3/identidad-seguridad-pedidos-f1-4 | `b566153989403b83b025b07e830d5601d317f848` |

- Frontend: https://github.com/ZorVaK749/fazbears-frontend/commit/84b523dda8a2fd7fa8cdf0da7b8018f0fd7e08c0
- Pedidos: https://github.com/ZorVaK749/fazbears-pedidos/commit/b566153989403b83b025b07e830d5601d317f848
- Push autorizado de ambos, sin merge a main/CI. Workflows conservados solo
  escuchan ramas CI/dispatch; sin dispatch, imagen/release ni tag GHCR actualizado.
- Documentos por servicio publicados en sus commits. Informes acumulativos en
  raíz del workspace sin Git permanecen locales, como en las fases anteriores.

### Compatibilidad Orden y plan separado

Snapshot EV3 cda0597f... de Orden: copia usuarioId/email/ítems del request, calcula
total con precios de ese request, añade PENDIENTE y POST a base msPedidosUrl +
`/pedidos` con el Bearer original delegado. Base debe conservar /api; espera
respuesta con id numérico. Después publica pedido.creado y hace DELETE Carrito.

Contrato de creación se conserva para oid propio y token con tenant/audience/scope
correctos; sin excepción de Origin ni token de servicio inventado. Si usuarioId
es ajeno, POST falla antes de persistir; no reasignar silenciosamente porque Orden
podría luego publicar con el ID incorrecto. Ninguna compra/Orden real ejecutados.
No se rompe el POST normal observado; cualquier consumidor de GETglobal, DELETE
o avances administrativos ahora recibe 403 hasta política aprobada.

Plan posterior, no implementado: validar propietario en Orden antes de efectos,
cotización/precios/moneda/cantidad canónicos desde backend, idempotencia y coordinación
con eventos/limpieza. Pedido propio creado por POST directo aún es posible con
token delegado; no prueba pago ni origen exclusivo ms-orden. Precios/email/total
no son autoridad económica ni identidad aunque se mantenga compatibilidad JSON.

### Azure pendiente y despliegue coordinado propuesto (NO ejecutado)

1. Usuario/ChatGPT verifica App Registration/API/tenant/audience/issuer, scope
   access_as_user/consentimiento y define permisos administrativos granulares reales.
2. Aprobar app roles y allowedMemberTypes/asignaciones Enterprise Application;
   comprobar roles en access tokens de esta API con evidencia saneada, no ID token
   o email. No compartir JWT/Authorization/cookies/secretos. No se accedió a Azure.
3. Nuevo bloque autorizado para política positiva de roles, transiciones/pruebas
   A/B/admin y capacidades UI verificadas por backend. Configurar roles en Azure
   **no habilita por sí solo** los commits de esta fase: administración sigue cerrada.
4. Aprobar diff/cierre admin y preservación de datos antes de imágenes/despliegue.
   Usuario/ChatGPT recoge digest/config/TG/rutas/puertos por SSM sin IDs EV2.
5. Backend Carrito /me F1.3 y Pedidos F1.4 primero; después frontend F1.4. Verificar
   rutas /api, CORS/preflight, tenant/audience/scope y salud Gateway/ALB/TG.
6. H2 mem/create-drop y consola histórica persisten: conservar/exportar datos si
   corresponde antes de restart. Rollback de imagen no recupera H2 ni migra aliases.
7. Pruebas A/B y cancelación solo en registros desechables/autorizados, sin compra,
   SMTP/RabbitMQ. Registrar digests/config/evidencia antes de VALIDADO E2E.

Otros riesgos: históricos sub/alias requieren reconciliación probada, no email;
Reportes y demás backends no asegurados por el bloqueo de UI, ni revisados/cambiados
fuera del alcance. Cancelación no compensa stock, reportes o pagos.

| Nivel | F1.4 |
|---|---|
| IMPLEMENTADO | Identidad Perfil/Historial, propiedad Pedidos, CORS y cancelación |
| PROBADO LOCALMENTE | Backend 45, frontend 98 y builds correctos |
| PUBLICADO | Dos ramas/SHAs arriba, sin imágenes |
| ADMINISTRACIÓN HABILITADA | No: política Azure pendiente, rutas cerradas |
| DESPLEGADO / VALIDADO E2E | No / No |

Próximo bloque propuesto: revisar matriz de acceso y obtener/aprobar evidencia de
roles Azure y política administrativa; recién entonces autorizar implementación
positiva y/o preparación de despliegue del modo usuario con cierre admin aceptado.
No iniciar Kafka/pagos/recomendaciones/FazCoins ni infraestructura nueva.

**PAUSADO — esperando autorización.**

## 15. Bloque especial — conservación de H2 antes del despliegue (12/11/2026)

El usuario decidió conservar los datos actuales. La aprobación de código/pruebas
de F1.3/F1.4 **no autoriza reemplazar procesos que contienen H2 mem**. No se avanza
con imágenes/despliegue hasta aprobar método verificable de conservación.

### Actividad 1/3 — Inspección de fuentes y límites

Usuario informa ms-carrito:8083/ms-pedidos:8082 activos, aparentemente H2 mem sin
volúmenes/datasource externo, Java 21 JRE Alpine, sin jcmd/jstack/jar, con unzip/
wget/Docker. /h2-console responde 401 sin JWT sin consola registrada demostrada.
**No se accedió a AWS ni se comprobó directamente esa configuración**.

Fuentes candidatas revisadas mediante git show, sin modificar microservicios:

- Carrito antiguo: `49fddca7d0819ea0ec8e4d5014293057d3a93eb1`.
- Pedidos antiguo: `e4438d1b6ba2c7e7eb6b622728e7d9abec1a7a88`.

No hay evidencia digest→artefacto→fuente suficiente para afirmar que esas revisiones
sean exactamente las imágenes activas. El plan exige vinculación antes de depender
de endpoints/esquema; tags mutables y label source por sí solos no la demuestran.

Hallazgo decisivo: GET Carrito usa getOrCreate y puede **crear** registro. No se
enumerarán usuarios ni se ofrecerá exportación real de Carrito mediante ese GET.
Pedidos GET propio usa findByUsuarioId sin escritura en fuente. GET global carece
de política administrativa suficiente; no se usará como bypass ni se enumerarán IDs.
Un 401 de consola no prueba que exista, ni copiar JAR/imagen captura heap H2.

**Conclusión:** APIs autorizadas disponibles no permiten demostrar copia completa
y no invasiva. Se puede añadir recuperación parcial de pedidos propios, pero no
demostrar ausencia de usuarios/aliases/filas desconocidas ni high-water de secuencias.

### Actividad 2/3 — Prototipo externo y restauración sintética

Archivos locales en `tools/rescate-h2/`:

- `rescate.mjs`: exportación propia limitada, parser JSON numérico exacto, SQL offline,
  manifiestos/hashes/permisos y entrada oculta de credenciales.
- `rescate.test.mjs`: 23 tests con HTTP/JWKS y datos sintéticos.
- `fixtures.mjs`: datos ficticios, sin usuarios/credenciales reales.
- `synthetic-roundtrip.mjs` + `RestoreSynthetic.java`: harness exclusivamente local,
  dos BD archivo nuevas; no attach, JDBC remoto o endpoints reales.
- `README.md` y `.gitignore`: uso/límites, artefactos privados ignorados.

Exportador usa Node 22+ sin dependencias externas. CLI real requiere Linux/directorio
privado, pide JWT propio en prompt oculto (no chat/argumentos/historial/env/archivos),
valida RS256/JWKS Microsoft y issuer/audience/tid/oid/scope/tiempos, deriva owner del
token verificado y hace solo dos GET propios a URL fija. Sin GET global, Carrito,
rutas de mutación, selección de otro usuario, redirects, retries, brokers o BD.
Credencial solo RAM; no garantía de wipe criptográfico JS, por lo que cliente/
terminal privados son requisitos. Logs/manifiestos no contienen JWT ni owner/PII;
JSON/SQL sí contienen datos privados y requieren cifrado/custodia fuera del lab.

Respuestas 200 se conservan en bytes exactos/UTF-8 y hashes; directorios nuevos 0700/
archivos exclusivos 0600 bajo Linux. Timeout 15s, límite 20MiB; errores no imprimen
headers/cuerpos/identidad. Manifiesto siempre completeBackup=false y completitud/
snapshot global UNPROVEN. Dos muestras iguales no demuestran copia global.

prepare solo genera SQL para BD nueva y aislada, requiere --accept-partial. Conserva
IDs, fechas, estados, nulos y snapshots, reconstruye FK desde nesting sin REST/JPA.
No transforma aliases a oid ni corrige datos históricos silenciosamente. Parser
exacto evita pérdida de Long >2^53/NUMERIC; rechaza duplicados/campos inesperados/
truncamientos. Schema de staging explícito, no DDL integral de H2 extraído. Ajuste
max visible+1 es **solo staging**, high-water original desconocido impide promoverlo
como recuperación fiel de secuencias o garantía de no reutilizar IDs eliminados.

Resultados locales reales:

```text
node --test tools/rescate-h2/rescate.test.mjs
node tools/rescate-h2/synthetic-roundtrip.mjs <JAR H2 2.4.240 local>
```

- **23/23 tests Node aprobados**, cero fallos/omitidos.
- **Dos H2 archivo sintéticas creadas, restauradas, cerradas y reabiertas** con
  Java 21/H2 2.4.240 local. Verificados todos los campos/counts, PK/FK, rechazo de
  huérfano, próximos IDs de padres/hijos y persistencia tras reapertura.
- Incluye Long >2^53, decimales, CANCELADO, fecha, alias, nulls, Unicode/comillas/
  backslash y carrito vacío. Son fixtures, no datos de usuarios recuperados.
- SQL PostgreSQL generado y reglas de representación probadas; **sin ejecución
  PostgreSQL ni arranque JPA de migración real**. ACL Windows solo con sintéticos,
  no certificadas para datos reales. Versiones locales no prueban versión desplegada.
- Sin red real de exportación/Azure/Gateway, sin secretos, bases remotas, contenedores
  activos, attach, instrumentación, señales, compras, SMTP, RabbitMQ o Kafka.

### Actividad 3/3 — Plan, matriz y decisión de pausa

Nuevo entregable: [PLAN_RESCATE_H2_EV3.md](PLAN_RESCATE_H2_EV3.md), con matriz de
recuperables/no recuperables, endpoints, custodia/exportación, restauración aislada,
comparativa PostgreSQL/H2 archivo, criterios de completitud y pasos CloudShell.

PostgreSQL es objetivo recomendado para operación/backups si permisos/costo Academy
lo permiten. H2 archivo con volumen persistente es puente provisional, no backup.
Ambos exigen ddl-auto=validate, esquema/driver/dialecto correctos, copia independiente
fuera del lab y restore ensayado; no importar por API que regenere IDs/fechas.
No se crearon motores, contenedores, volúmenes ni infraestructura AWS.

Para afirmar conservación completa faltan inventario SQL de todas las tablas/
objetos del origen, universo de PK/counts/checksums independientes de usuarios
conocidos, high-water real, snapshot/quiescencia acreditados (GET Carrito también
es escritor), custodia y restauración total comparada. Dos JSON iguales o conteos
del propio archivo no prueban que no falten registros. Si se excluyen cuentas/
settings/metadatos, no llamar al resultado copia integral H2.

Analizadas **solo como propuestas**: acceso SQL legítimo ya existente (no demostrado),
agente que alcance DataSource Spring/H2 ya activo con classloader correcto y exporte
SCRIPT/metadatos. Nueva JVM con igual jdbc:h2:mem abre otra BD, no la fuente.
H2 SCRIPT requiere derechos admin y bloquea objetos; no suponer snapshot global ni
omitir datos/metadatos silenciosamente. Consultada documentación H2 comandos SCRIPT/
BACKUP. No se ejecutan attach/agentes/heapdump/depuradores/checkpoint ni instalación
de herramientas dentro de contenedores; pausas/GC/OOM/filtración son riesgos serios.

Próximos pasos propuestos, todos pendientes de aprobación:
1. Identificar digest/artefacto/esquema real con evidencia saneada, sin compartir
   inspect/env/logs/credenciales completos. Copia offline de JAR no es copia de datos.
2. Aprobar recuperación propia parcial como defensa adicional si aporta valor y
   custodia cifrada; no usarla como respaldo total ni autorización para acceder a terceros.
3. Elegir acceso nativo legítimo o aprobar diseño/ensayo invasivo por separado,
   sin ejecutarlo aún. Cumplir criterios de completitud antes de aprobar despliegue.

| Nivel | Rescate H2 |
|---|---|
| IMPLEMENTADO LOCALMENTE | Prototipo limitado y preparación offline |
| PROBADO LOCALMENTE | 23 tests y dos H2 archivo sintéticas |
| EXPORTADO REAL / BACKUP COMPLETO DEMOSTRADO | No / No |
| PUBLICADO | No; archivos nuevos locales en raíz sin Git |
| CAMBIOS AWS/JVM ACTIVA | Ninguno |
| DESPLIEGUE PERMITIDO POR ESTE BLOQUE | No; conservación pendiente |

**PAUSADO — esperando autorización. DESPLIEGUE BLOQUEADO: no hay todavía un
método aprobado que demuestre la conservación completa de los datos actuales.**

## 16. Rescate R2 — JVM activa en laboratorio aislado (12/11/2026)

### Actividad 1/3 — Imágenes exactas y preparación local

Usuario autoriza exclusivamente réplicas locales y datos sintéticos, incluyendo
instrumentación; prohíbe AWS y extracción de JVM reales. Docker Desktop inicialmente
apagado: el usuario lo inició tras revisar cargas automáticas. Endpoint verificado
npipe local desktop-linux, motor Linux/amd64 Docker 29.7.2; ningún daemon remoto,
AWS CLI, SSM o imagen de producción modificada.

Descargados los dos índices por digest aportados y seguidos hasta manifest amd64/
config; coinciden con los Image ID que el usuario obtuvo en AWS. Docker Desktop
containerd muestra aquí el índice en inspect.Id, no el config digest: diferencia
registrada y resuelta, no se compararon indebidamente valores de distinta capa OCI.

| Servicio | Índice SHA-256 | Config/Image ID SHA-256 |
|---|---|---|
| fazbear-carrito | 99274a38c2cb1cf0529b51b8fbfdb06653a12338afbf5c5967e5d6b8cea98d6d | c09d17290bcc75af510f6ca5d036c23b62add0a35cd3c495a2ceb27a868cd277 |
| fazbears-pedidos | c6a51819a39b8766f05bbbe26e14acc8eb442cf6761f57e38f3f9427b46ab6cc | e8d04e02bf3b1b212884ed454cbf38b2e5a77971f23d9d9b1db76e06f681cd64 |

JAR copiado de las imágenes a artefactos locales para inspección offline; nunca
recompilado desde repositorio como sustituto. Confirmados Boot 4.1.1, Context 7.0.9,
HikariCP 7.0.2, H2 2.4.240 y configuración mem/create-drop. Sin revision label y
sin atribuir un commit antiguo no probado. SHA JAR y manifest plataforma completos
en PLAN_RESCATE_H2_EV3.md sección 12.

Cada réplica usa network none, sin puertos publicados, rootfs readonly, cap-drop ALL,
no-new-privileges, 768MiB, 1 CPU, 128 pids y /tmp tmpfs 64MiB. Main PID 1 conserva
JRE original 21.0.13+9-LTS/app.jar; JDK musl auxiliar readonly para Attach/jcmd,
digest 82801f9dcdcbad5a05082aba8c86d1da5b72ccb498e71318b1f91b5a477887b3.
No Docker build/push ni privileged/PID host. Fixtures JWT loopback con claves RAM
permiten discovery y firmas con decoder original, 401 sin token y 200 autenticado;
no se desactiva seguridad ni se contacta Azure.

### Actividad 2/3 — Extracción nativa y restauración verificadas

JDK Attach API carga agente guardado para LAB. Instrumentation solo localiza la
SpringApplication ya cargada; reflexión sobre shutdownHook.contexts (internals de
Boot 4.1.1) y bean dataSource existente. Confirmados HikariDataSource y
LaunchedClassLoader; URL mem esperada. No otra conexión a nueva H2 por nombre ni
driver externo en JVM fuente. Sin transformer/redefinición, debugger o heap dump.

seed controlado solo en bases vacías de fixture. Export/check no modifican tablas:
SCRIPT NOPASSWORDS sobre la conexión del pool vivo, archivo exclusivo y SHA-256.
Ese SQL excluye contraseñas: no se presenta como copia integral de autenticación.
Snapshot de todas las tablas de usuario, hashes de celdas/filas (LOB/null), columnas/
tipos/escala/defaults, PK/FK, constraints/checks, índices/vistas y contadores.

Por servicio: 3 padres+2 hijos y tabla R2_EXTRA.UNMAPPED con 2 filas adicionales,
incluyendo alias/desconocidos, padre vacío, CLOB/BLOB/null, id >2^53 y estado
histórico CANCELADO auxiliar (no cambio de enum de Pedidos). Índice explícito/vista
y secuencia independiente. Identity bases 1001/2001 se preservan aunque max id
visible sea 41/31; secuencia base 27/incremento 5. Nada de max(id)+1 reconstruido.

Cuatro dumps finales (dos por servicio), cuatro restauraciones en archivos nuevos
y verificación adicional reabriendo cada archivo desde otra JVM nueva, con H2
extraído de la imagen. Todas las tablas/valores, esquema lógico e identidades/
secuencias comparadas. jcmd 1 VM.version también funcionó localmente, sin restart;
no es por sí mismo una herramienta de respaldo relacional.

| Resultado final | Carrito | Pedidos |
|---|---|---|
| Tablas/filas usuario | 3/7 | 3/7 |
| Dumps restaurados y reabiertos | 2 | 2 |
| SQL bytes | 2340 | 2510 |
| SHA-256 (ambos dumps iguales por servicio) | bd108a13664475fd449e33f0940af843ea081259fe1a3a6d2e40d990fdab5060 | 53b890b4bf3ebaf3f704194a1dbd738ab94a9b9ece0eb649849029143b0d5b54 |
| Export+inventarios ms | 81/27 | 163/92 |
| HTTP durante ventana | 80/80 con 200 | 80/80 con 200 |
| Máxima latencia HTTP ms observada | 212 | 218 |
| Host PID antes/después | 3617/3617 | 4312/4312 |
| JVM startTime antes/después | 1794505208220/1794505208220 | 1794505265771/1794505265771 |
| StartedAt UTC invariante | 2026-11-12T17:40:05.906622447Z | 2026-11-12T17:41:03.517879009Z |
| RestartCount / vivo después | 0 / sí | 0 / sí |

Contenedores positivos finales r2-5cf8cbee-carrito y r2-5cf8cbee-pedidos permanecen
vivos; contenido fuente/counters sin cambios después de las exportaciones. No hubo
medición exhaustiva de pausas GC/safepoints: los tiempos HTTP no prueban pausa cero.

Pruebas/rechazos registrados:

- **8/8 verificaciones R2** sobre evidencia positiva/negativa aprobadas.
- **23/23 tests previos** y ensayo de dos H2 archivo R1 reejecutados, correctos.
- Corrida ampliada falló por nombres físicos regenerados de un índice auxiliar H2.
  Filas/IDs/constraints coincidían. Comparación ajustada sin omitir índices:
  estructura/orden/uniqueness para generados, nombre también para explícitos.
  No se promete preservar nombres físicos auxiliares que H2 regenera.
- Guard cliente sin marker rechazado antes de attach; guard agente probado antes
  de acceder a Instrumentation, también rechazado. No modo producción.
- Dos réplicas negativas nuevas recibieron una escritura HTTP sintética en barrera
  de 4s después del inventario inicial. Ambas exportaciones fallaron de forma
  esperada, SQL cuarentenado, JVM vivas/restarts=0. No alteraron réplicas positivas.
  No prueba detección universal de carreras/ABA ni snapshot global bajo tráfico.

Evidencia local ignorada: tools/rescate-h2/artifacts/r2-run-L4oUs5/report.json y
r2-negative-f9SuSq/report.json. Los SQL/DB/JAR/reportes no se publican. Son fixtures,
no datos AWS. No se pidieron ni usaron tokens reales aunque el usuario mencionó
disponer de token; el laboratorio usa únicamente claves/JWT sintéticos.

### Actividad 3/3 — Documentación, publicación y propuesta real

Código R2 en tools/rescate-h2/r2/: lab.mjs, negative.mjs, evidence.test.mjs,
NativeAgent.java, AttachClient.java, FixtureServer.java, Probe.java, ArtifactInspect.java,
RestoreNative.java, GuardProbe.java, agent.mf y README.md. Se incluyen herramientas
R1 como dependencia del conjunto reproducible, solo fuente/fixtures sintéticos.
Plan actualizado sección 12 con evidencia y propuesta R3 detallada.

Publicación autorizada exclusivamente de código/documentación en repositorio
ZorVaK749/fazbears-frontend, rama **ev3/rescate-h2-r2**, worktree
fazbear-frontend-rescate-r2, base `84b523dda8a2fd7fa8cdf0da7b8018f0fd7e08c0`.
**Commit de herramientas/plan:** `9df6f7d61a36bbd24666f2a3af98edb6842cba20`.
Sin cambios de aplicación, main, ramas CI o workflow; sin imágenes publicadas.
El informe acumulativo se añade en commit documental posterior; los resultados
remotos se verifican al cierre. Los originales en la raíz se mantienen también.

Propuesta R3, **no ejecutada ni autorizada por R2**:

1. Artefacto export-only revisado, sin seed/SQL arbitrario y con aprobación/nonce,
   proceso/imagen/JAR/DataSource esperados. No copiar R2 a AWS ni reiniciar para
   añadir markers; sus guards se niegan en JVM reales.
2. Preflight de versión musl/JDK/PID/starttime/attach, esquema/pool/classloader y
   permisos del mismo UID. Docker/SSM con autorización de operador: acceso Docker
   es privilegio alto; no usar privileged/ptrace como parche si falla.
3. Inventario/budget previo: heap/headroom/RAM/disco, filas/LOBs/tamaño estimado.
   32MiB de salida y timeout 20s del prototipo NO acotan toda asignación interna de
   SCRIPT ni garantizan cancelación dura. Éxito con <3KiB no demuestra escalabilidad.
4. Quiescencia/snapshot acreditados de todos los escritores, incluido GET Carrito
   getOrCreate, Orden/jobs/consumidores/clientes. Gate de ingreso requiere aprobación
   AWS/operativa nueva; no detener JVM, purgar/republicar brokers ni suponer que UI
   inactiva basta. Sin garantías, no declarar conservación.
5. Directorios privados/custodia/cifrado/copia fuera de Academy. No añadir volumen
   recreando contenedor vivo. Cualquier archivo temporal/agente en fuente requiere
   permiso explícito futuro; no tocar app.jar, logs con SQL o credenciales.
6. SHA origen/copia/descifrado, restore nuevo sin app/create-drop, comparación total
   de tablas/valores/IDs/relaciones/objetos/counters y reapertura en otra JVM. Definir
   qué se excluye: NOPASSWORDS no conserva autenticación íntegra ni heap/transacciones
   abiertas/otras bases. Evaluar PostgreSQL solo después de esta conservación.
7. Postflight fuente viva, misma JVM, fingerprints/counters y JDBC retornado. Abortos
   ante cambios, permisos insuficientes, recursos inciertos, bloqueo/latencia/OOM,
   checksum/restore fallidos o custodia no demostrada; no matar JVM para cancelar.

Detach no descarga clases de agente o Attach Listener; no se promete retirada sin
huella. Sin transformers ni tareas de agente persistentes; streams/JDBC cerrados.
Contenedores locales quedan vivos para revisión, incluso los de evidencia fallida;
no limpieza automática/borrados amplios. Se puede autorizar limpieza selectiva local
por label luego, nunca de recursos reales.

| Nivel | R2 |
|---|---|
| IMPLEMENTADO / PROBADO | Mecanismo LAB-only, dos imágenes exactas, dumps/restores sintéticos |
| PRUEBAS FINALES | 8 R2 + 23 previas aprobadas; negativos esperados documentados |
| PUBLICACIÓN | Rama de código/docs, sin binarios/dumps/datos reales ni imágenes |
| AWS / JVM REALES / DATOS REALES RESPALDADOS | Ninguno / ninguna / ninguno |
| RESCATE REAL O DESPLIEGUE AUTORIZADOS | No |

Recomendación: revisar R2 y aprobar diseño/inventario/protocolo de consistencia y
custodia R3 antes de considerar una extracción real. No avanzar con despliegue por
la sola existencia de una réplica restaurada.

**PAUSADO — esperando revisión. PROHIBIDO ejecutar rescate real sin nueva autorización.**

## 17. F2.1 — primer ms-pago ejecutable (12/11/2026)

### Autorización, repositorio y aislamiento

Usuario aprueba R2 local y prioriza funcionalidad obligatoria EV3. Se autoriza
implementar A/B/C en `ZorVaK749/fazbear-pago`, base `ev3/diseno-inicial`
`42173751d7267028696043738d887e72fc683a18`, y publicar solo `ev3/pago-f2-1`.
Original `fazbear-pago` conservado en diseño; worktree separado
`fazbear-pago-ev3-mvp`. Ningún cambio a frontend/Carrito/Pedidos/CI o ramas main.
El informe acumulativo se incorpora a este repositorio y se refleja en la copia
raíz del workspace; no se publica esta fase en otro repositorio.

R3 sigue sin autorización. No EC2, SSM, servicios antiguos, JVM/H2 reales, broker,
compras ni modificaciones a contenedores del laboratorio R2.

### Actividad A — proyecto, seguridad y persistencia

- Java 21.0.12.1 host, Maven 3.9.16, Spring Boot **3.5.16 estable 3.x** verificado
  en Maven Central, no RC. BOM gestiona Flyway 11.7.2 y Testcontainers 1.21.4.
- Proyecto ejecutable, JDBC/BigDecimal, Flyway V1 sobre PostgreSQL 17.7.
  Sin dependencia H2 ni repositorios en memoria.
- Tablas payment, payment_attempt, antifraud_decision, idempotency_record,
  fixture_operation, simulation_instrument y card_guard; PK/FK/checks/índices,
  una aprobación por operación mediante índice único parcial.
- JWT normal con JWKS Azure RS256, issuer v2, audience, exp/nbf, tenant/oid UUID y
  scope delegado access_as_user. Owner exclusivamente `(tid,oid)`, nunca email/sub.
  Roles administrativos no inventados. Sin JWT → 401; sin scope → 403.
- Fixtures opt-in (Compose sí, configuración normal no): 24 operaciones backend
  de 12990.00 CLP, dos owners sintéticos, vencimiento siete días desde inserción;
  instrumentos sim-approved y sim-declined globales. No PAN/CVV/tokens bancarios.
  Ningún endpoint público para definir precio, dueño o cotización libre.

Commit A: `9c21e3f9a9d10b9d13dc5306fe6795556e56e0dd`.

### Actividad B — procesamiento e idempotencia/antifraude

- POST `/api/pagos`: operacionId, metodo=SIMULADO, instrumentoPruebaId y header
  Idempotency-Key. Importe/moneda/owner/expiración obtenidos del fixture backend.
  Campos desconocidos, incluidos importes/fecha/PAN/CVV/owner, rechazados.
- APPROVED, DECLINED o BLOCKED persistidos. 201 nuevo aprobado/rechazado;
  429 bloqueado. Resultado simulado nunca equivale a captura bancaria real.
- GET `/api/pagos/{id}` y `/api/pagos/me?limit=50`: solo propios, límite 1..100;
  ajeno e inexistente devuelven 404. Sin endpoint global/admin.
- Una transacción READ COMMITTED: reserva idempotente → lock operación → lock
  global instrumento → clock_timestamp() BD → conteo ventana inclusiva
  `[ahora−10s,ahora]` → pago/intento/decisión/key → commit antes de responder.
- Primeros tres intentos permitidos por esta regla; cuarto y siguientes bloqueados,
  incluyendo conteo compartido entre usuarios. DECLINED y BLOCKED cuentan también.
  No agrupación clientId, reloj cliente o mutex Java. Locks PostgreSQL coordinan
  conexiones/instancias; no despliegue multiinstancia real ensayado en esta fase.
- Misma key/contenido: resultado exacto guardado, sin intentos nuevos; 200 replay
  o 429 si bloqueado. Contenido distinto → 409. Namespace `(tid,oid)`, hash SHA-256
  canónico versionado y key acotada; unicidad de aprobación por operación.
- No hold obligatorio 30 minutos ni duración inventada. Ventana deslizante,
  duración adicional pendiente. Sin Retry-After fijo engañoso.
- Rollback conjunto ante fallo, locks/SQL con timeout, sin reintento automático de
  escritura. Reintentar manualmente con misma key/contenido ante 503 o respuesta
  perdida; un 503 no demuestra que un commit incierto no ocurrió.
- Errores estables sin SQL/cuerpos/JWT/secretos; sin logging propio de instrumentos.

Commit B: `c5ee7272420658954797eb52b312f21f2b9c4a76`.

### Actividad C — pruebas, Docker y documentación

JUnit/Spring Security real, JWT RSA con claves efímeras RAM solo en tests,
PostgreSQL Testcontainers real; no Azure/bancos/servicios antiguos para probar.
Docker Desktop Linux local 29.7.2/Compose 5.3.1; API Docker de tests 1.44 para
compatibilidad con Engine 29. No tests omitidos cuando falta PostgreSQL/Docker.

Cobertura: aprobación/rechazo, cuarto intento entre owners, instrumentos
independientes, ventana exacta a microsegundo e intentos fuera/dentro de diez
segundos, tiempo BD adquirido después de esperar lock, doce llamadas concurrentes
distintas y doce replays, keys distintas sobre misma operación, índice único BD,
owner/operaciones ajenas, expiración, cuerpo/key/límites inválidos, firma y claims
JWT inválidos, scope, fallos de persistencia y fallo diferido en COMMIT.
Una prueba abre el servidor HTTP real en puerto aleatorio y solicita pago firmado.

Dockerfile multi-stage Maven/JRE 21, API con UID 100 no root; Compose exclusivo
`pago-f21-local`, PostgreSQL con volumen `pago_data`, puertos loopback 55432/18085.
Contraseña local aleatoria en `.env` ignorado; no se imprime ni publica. Sin imágenes
subidas a registry. `compose up -d --build` construye localmente; no sustituye
`mvn verify` (Dockerfile omite ejecución de tests al empaquetar).

Arranque local verificado: Flyway V1 success=true, 24 operaciones, 2 instrumentos,
`/health` → 200 SIMULATION_ONLY, `/api/pagos/me` anónimo → 401. API normal conserva
validador Azure, no acepta el firmante de test. Oid de fixtures son sintéticos,
no cuentas Entra reales; peticiones autenticadas de prueba no requieren tokens reales.

Incidencias del ensayo, sin ocultarlas: generación inicial de secreto local usó
API .NET no disponible en Windows PowerShell; corregida con RNG compatible antes
de crear `.env`. Prueba nueva de restart falló primero por tratar conexión rechazada
como terminal y después por reutilizar el puerto host efímero anterior: Docker Desktop
reasigna ese puerto al reiniciar el contenedor y Testcontainers conserva el inspect
original. Se volvió a inspeccionar el puerto real y se acotó la espera de disponibilidad
JDBC a 30s, sin añadir retries a procesamiento ni omitir prueba.

**Resultados finales:** `mvn -B clean verify` → BUILD SUCCESS, **36 tests, 0 fallos,
0 errores y 0 omitidos** (35 PaymentIntegrationTest + 1 PaymentRestartTest),
28.289s en la corrida final 12/11/2026 15:35:33 −03. PostgreSQL 17.7 real.
La primera suite de 33 pasó; las ampliaciones/reintentos fallidos de restart quedan
registrados arriba, no se presentan como corridas exitosas.

Ensayo persistencia aprobado: cerrar instancia Spring, servidor y pool; reiniciar
SOLO PostgreSQL del test, reinspeccionar puerto host; nueva instancia Spring y pool;
GET devuelve mismo pago y POST misma key devuelve mismo resultado. Una fila en cada
tabla pago/intento/decisión/key y 24 operaciones sin duplicar. No equivale a prueba
de failover ni a reiniciar JVM antigua; no se accedió a AWS o al laboratorio R2.

Docker local: imagen construida, API y PostgreSQL vivos, Flyway aplicado, puertos
solo loopback y API sin root. Compose normal no fue debilitado con claves de test.
Artefacto Java ejecutable `target/ms-pago-0.1.0-SNAPSHOT.jar`, tests/reportes/JAR/
`.env` excluidos de Git. No publicación de imagen ni datos reales.

Documentación de ejecución/contrato en README, decisiones/limitaciones en
`docs/DECISIONES_F2_1.md`; planes antiguos anotados para distinguir propuestas de
implementación. Informe acumulativo preserva secciones anteriores y añade F2.1.
Actividad C agrupa tests, Docker y docs en commit de cierre (identificable en
historial de `ev3/pago-f2-1`; no se auto-referencia su hash dentro del mismo commit).
Publicación autorizada únicamente en `ZorVaK749/fazbear-pago`, sin merge/CI/main.

| Control F2.1 | Resultado |
|---|---|
| Actividades A/B/C | Implementadas y verificadas localmente |
| Pago simulado, antifraude y owner/JWT | Funcionales; no cobro real |
| Suite PostgreSQL, HTTP, concurrencia y restart | 36/36 aprobados |
| Maven / Docker local | BUILD SUCCESS / API y BD ejecutándose |
| Bloqueador local | Ninguno al cierre |
| Entra real / Orden / Webpay / E2E Angular | Pendientes, no certificados |
| AWS, datos H2 antiguos, R3 | Sin acceso/cambios, R3 no autorizado |

### Pendientes y próximo paso (no implementados)

- Orden/Productos: referencia/cotización backend inmutable, confiable, con importe,
  owner, moneda/versión/expiración verificables. Orden actual no constituye fuente
  confiable de precios ni un pedido existente es confirmación de pago.
- Pago: Webpay, UNKNOWN/conciliación, callbacks verificados y reembolsos. APPROVED
  aquí solo significa resultado sintético. No integración Orden/Pagos/Angular E2E.
- Fidelización/FazCoins, analytics/Kafka/outbox/inbox y publicaciones RabbitMQ:
  no implementadas; no sustitución del bus RabbitMQ operativo existente.
- Consentimiento/claims Entra real no ensayados con token real; configuración
  productiva/CORS/roles, retención, rate-limit/anti-DoS, TLS/secretos/roles BD,
  backups/hardening/observabilidad/SBOM siguen pendientes de autorización/diseño.
- R3/respaldo H2 real y despliegues antiguos continúan bloqueados. Ningún AWS
  modificado, ningún cobro real ni imagen publicada, sin merge main/ramas CI.

Siguiente paso recomendado: revisar este MVP local y aprobar contrato de operaciones
confiables y un ensayo de integración posterior. No avanzar automáticamente.

**PAUSADO — esperando revisión.** (Estado histórico F2.1, superado por sección 18.)

## 18. Integración integral ejecutable EV3 (12/11/2026)

### Alcance y decisiones

Autorizada la continuación integral sin pausas artificiales. Ocho worktrees aislados
en `ev3/integracion-integral`; no merges, cambios de ramas anteriores ni publicación
de imágenes compartidas. Pago/Analytics/Fidelización: Java21, Boot3.5.16, JDBC/Flyway.
Servicios existentes: Boot4.1.1 conservado, perfiles PostgreSQL explícitos `ev3-local`.
La base recuperada, FIFO/identidad Carrito F1.3 y ownership/admin fail-closed Pedidos
F1.4 permanecen cubiertos por regresiones. No se habilitaron administradores nuevos.

- Productos autoritativo → cotización inmutable Orden → Pago simulado → confirmación
  verificada Orden → Pedido pagado idempotente. No precios ni owner del navegador
  como autoridad; campos de precio extra rechazados en la cotización.
- Pago: instrumentos `sim-approved`/`sim-declined`, ventana inclusiva global de10s,
  cuarto intento bloqueado, bloqueo transaccional/concurrencia e idempotencia;
  historial/intentos/alertas propios y reembolsos totales simulados idempotentes.
- Outbox transaccional Pago a `pago.aprobado.v1`/`pago.reembolsado.v1`. Fidelización
  verifica owner/importe/moneda/estado con `GET /internal/pagos/{id}` autenticado
  por clave de servicio, antes de conciliar; nunca acredita por `pedido.creado`.
- FazCoins: cashback configurable500 puntos base (5%, floor); política congelada
  por pago, wallet/ledger/inbox/canjes PostgreSQL, índices únicos y bloqueo de wallet.
  Recompensa `faz-vip` cuesta100, otorga entitlement digital persistido, no descuento
  de checkout. Reembolso consume saldo disponible y registra deuda por puntos ya
  gastados; saldo gastable nunca negativo, deuda bloquea canjes y abonos la amortizan.
- Productos/Carrito: outboxes durables y eventos reales de catálogo/VIEW/SELECT y
  ADD/UPDATE/REMOVE. Analytics valida envelope/productor/versión, deduplica inbox,
  actualiza proyecciones y ranking por recencia/pesos/categoría/cointeracciones.
  Fallback explícito para cold start, no lista fija presentada como personalización.
  Kafka no sustituye RabbitMQ de compra/stock. Retries, cuarentena y DLT saneadas.
- Angular: checkout cotización→pago→confirmación con claves reutilizables y sesión
  protegida, recomendaciones API y FazCoins reales; reconsulta Producto al agregar
  una recomendación para no usar precio/tipo de proyección obsoleta. Sin PAN/CVV,
  saldos inventados o bypass MSAL. Contratos en README de servicios e INTEGRACION-EV3.md.

Envelope común: `{eventId,eventType,schemaVersion:1,occurredAt,producer,aggregateId,
aggregateVersion,correlationId,data}`. Interacciones: `producto.actualizado.v1`,
`producto.interaccion.v1`, `carrito.actualizado.v1`. Contratos de Pago: docs/EVENTOS.md.

### Evidencia local ejecutada

| Componente | Tests aprobados | Fallos/errores/omitidos finales |
|---|---:|---|
| Pago, PostgreSQL real y restart | 41 | 0/0/0, clean verify |
| Analytics, PostgreSQL/Kafka reales | 36 | 0/0/0, clean verify |
| Fidelización, PostgreSQL/Kafka reales | 21 | 0/0/0, verify |
| Orden, incluye PostgreSQL aislado | 20 | 0/0/0, verify |
| Pedidos, incluye PostgreSQL aislado | 47 | 0/0/0, verify |
| Productos | 40 | 0/0/0 entre suite base y opt-in PostgreSQL/Kafka |
| Carrito | 62 | 0/0/0, verify con opt-in PostgreSQL/Kafka |
| Angular (9 archivos) | 121 | 0 fallos; builds normal/local aprobados |
| Total de casos distintos | **388** | No equivale a388 E2E de navegador |

Los tests legados usan H2 **en memoria de nuevas JVM**, no archivos históricos.
Los nuevos tests de integración usan PostgreSQL/Kafka locales reales. Opt-in de
productores requiere EV3_DOCKER_TEST=true y BD `ev3_productos_test`/`ev3_carrito_test`;
por defecto CI base los omite. Orden/Pedidos CI configura su PostgreSQL desechable.
Workflows nuevos validan, no despliegan ni publican imágenes. Resultado remoto CI
se debe consultar aparte: una suite local aprobada no implica Actions aprobado.

Smoke HTTP real contra gateway18090, Kafka3.9.1/PostgreSQL17.7/RabbitMQ4.1 y siete
backends en proyecto Docker **pedidos360-ev3-integral**, con JWT RSA sintéticos.
Nueve grupos aprobados (`EV3_LOCAL_INTEGRATION_PASSED`):

1. Cotización backend y rechazo de precio cliente.
2. Pago/replay, un intento y aislamiento entre owners.
3. Pago real del simulador → Kafka → crédito FazCoins verificado.
4. Confirmación Pedido una sola vez, sin segundo abono por orden.
5. Canje, replay, insuficiencia y gasto concurrente sin saldo gastable negativo.
6. Productos/Carrito→Kafka, ADD/UPDATE/REMOVE consumidos y ranking personalizado.
7. Cuarto intento antifraude compartido entre usuarios.
8. Reembolso y reversa/deuda por puntos ya canjeados.
9. Reinicio Analytics/Fidelización: igualdad exacta de wallet/resumen antes/después
   y consumo de una nueva interacción tras el restart.

UI Docker opcional construida y levantada en18092: GET /200, proxy protegido
/api/pagos/me401 sin token y gateway /internal/pagos/test404. Esto comprueba
servido/proxy, no login Entra ni checkout E2E de navegador.

Evidencia automática privada `deploy/ev3-local/evidence.local.json`, sin tokens ni
secretos. El harness no borra datos entre corridas; puede agotar stock de semillas.
Duplicados de eventos, rollback, versiones y reintentos se ensayan además en suites
de consumidor; replay HTTP no se confunde con redelivery Kafka.

### Fallos encontrados y corregidos

- Docker Desktop apagado: arranque local autorizado; tests no omitidos para ocultarlo.
  Compatibilidad Testcontainers/Docker API1.44 fijada en configuración de tests.
- Fidelización JWKS LAB rechazado bajo Compose y URI sin host lanzaba NPE: override
  limitado a perfiles locales/hosts permitidos; pruebas de rechazo conservadas.
- Carrito emite REMOVE con cantidad restante0: validador Analytics corregido y
  regresión añadida; ADD0/cantidades negativas continúan rechazados.
- Orden aceptaba campos extra aunque no confiaba sus precios: deserialización
  estricta en perfil integral y smoke400, imagen reconstruida.
- Empaquetado Pago sobre target interrumpido: clean verify reconstruyó jar ejecutable.
- Nginx tenía upstream resuelto al inicio: ensayo de reinicio falló inicialmente.
  Resolver Docker dinámico con TTL2s/whitelist de rutas y eliminación de X-Service-Key
  público; rerun completo aprobado. No se ocultó timeout debilitando estados HTTP.
- Spy KafkaTemplate de Carrito no coincidía con bean genérico Boot: envolver tipo
  borrado en test, sin reemplazar Kafka real; verify62/62 aprobado.
- Angular no aceptaba categoría libre de recomendación como Producto: consulta al
  catálogo y regresión. Auditoría npm inicial18 hallazgos, final **0** tras Angular
  22.2.6/build+CLI22.2.7; conflicto de peer-tree resolvió regenerando lock limpio,
  guardando dependencias generadas anteriores en temporal, sin --force/legacy-peers.
- Bundle productivo610.95kB excede advertencia500kB; build aprueba, no se elevó umbral.

### Arranque reproducible y seguridad de laboratorio

Desde repo Pago de esta rama, con siblings integrales según deploy/ev3-local/README.md:

```text
node deploy/ev3-local/init-env.mjs
docker --context desktop-linux compose -f deploy/ev3-local/compose.yml up -d --build
node deploy/ev3-local/smoke.mjs
```

Inicializar .env **solo una vez**; existe localmente y no se sobrescribe. No publicar
compose config resuelto. Variables *_REPO permiten otro layout. UI opcional perfil
`ui`, puerto18092; firmante LAB18091, gateway18090, todos loopback. PostgreSQL/Kafka/
RabbitMQ sin puertos públicos en stack normal; perfil validation usa PostgreSQL55439.
No ejecutar prune/down -v ni tocar R2/H2. Retiro conservador: compose down sin -v.

LAB firma en RAM identidades UUID ficticias, valida firma/issuer/audience/tid/oid/scope,
pero **no acredita login Entra real**. Para navegador Entra se debe quitar override
LOCAL_JWT_JWK_SET_URI de los backends y registrar redirect/consent de la SPA. No se
insertaron tokens sintéticos en almacenamiento Angular ni se cambiaron permisos Azure.

### Límites pendientes y AWS

Sin despliegue/reinicio AWS, compras reales, cambios R3, merge protegido, publicación
de secretos ni sobrescritura de tags. Ninguna copia H2 real rescatada por este trabajo.
Pendientes: login/consent/redirect Entra en navegador, respaldo H2 real verificable y
autorización R3 antes de despliegues antiguos; PostgreSQL durable/backups/roles,
Kafka privado TLS/ACL/SASL, secretos/IAM/red/retención/observabilidad/rate-limit,
transporte interno seguro, SBOM/escaneo y hardening productivo. Pago no es adquirente
bancario; no captura real/partial refunds. Reserva distribuida de stock y atomicidad
global pago/pedido/reembolso/compensación requieren una saga adicional: no se promete
exactly-once distribuido. Implementación integrada local no certifica producción.

### Publicación y trazabilidad

Los commits de implementación de ocho repos se registran en
`docs/COMMITS_INTEGRACION_EV3.md` al publicar; todos rama `ev3/integracion-integral`.
Este informe sustituye los pendientes **locales** F2.1, no sus restricciones AWS.
