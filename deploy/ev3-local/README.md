# Pedidos360 EV3 — entorno integral exclusivamente local

Esta carpeta vive en `fazbear-pago`, rama `ev3/integracion-integral`. Se conecta
con las ramas de igual nombre de seis repos backend y Angular. No usa ni modifica
AWS, contenedores R2 o bases H2 existentes. No reutiliza puertos/volúmenes de F2.1.

## Requisitos y repositorios

Docker Desktop Linux (aproximadamente 6 GiB libres para el laboratorio), Compose,
Node 22+ y Git. Java 21/Maven si se ejecutan tests fuera de Docker. Los proyectos
se construyen desde código de las ramas integrales; no descarga imágenes propias
publicadas ni sobrescribe tags utilizados en AWS.

Clonar/checkout sin cambiar ramas de trabajo anteriores, o usar worktrees. Layout
predeterminado junto a `fazbear-pago-ev3-integral`:

- `fazbear-analytics-ev3-integral` → ZorVaK749/fazbear-analytics-recommendations.
- `fazbear-fidelizacion-ev3-integral` → ZorVaK749/fazbear-fidelizacion.
- `fazbear-productos-ev3-integral` → ZorVaK749/fazbears-productos.
- `fazbear-carrito-ev3-integral` → ZorVaK749/fazbear-carrito.
- `fazbear-orden-ev3-integral` → ZorVaK749/fazbear-orden.
- `fazbear-pedidos-ev3-integral` → ZorVaK749/fazbears-pedidos.
- Angular `fazbear-frontend-ev3-integral` → ZorVaK749/fazbears-frontend.

Todos sobre `ev3/integracion-integral`. Se pueden definir ANALYTICS_REPO,
FIDELIZACION_REPO, PRODUCTOS_REPO, CARRITO_REPO, ORDEN_REPO y PEDIDOS_REPO en `.env`
con paths absolutos o relativos a esta carpeta para otro layout.

Frontend opcional: definir FRONTEND_REPO si cambia el layout y ejecutar Compose
con `--profile ui up -d --build`; UI en `http://localhost:18092`, proxy /api al
gateway. El login sigue siendo Entra y requiere redirect URI registrado; no hay
bypass ni token sintético almacenado por Angular. Para modo navegador Entra quitar
el override JWKS LAB como se explica abajo; el smoke LAB no valida ese login.

## Arranque (desde raíz del repositorio Pago)

```text
node deploy/ev3-local/init-env.mjs
docker --context desktop-linux compose -f deploy/ev3-local/compose.yml up -d --build
node deploy/ev3-local/smoke.mjs
```

El primer comando genera tres secretos **locales** en `.env` de esta carpeta,
ignorado por Git, y se niega a sobrescribir. No imprimir `compose config` completo:
incluye valores resueltos. En Linux elegir contexto/socket local correspondiente.
El primer build/pull puede tardar varios minutos. API gateway `127.0.0.1:18090`.
BD/Kafka/RabbitMQ no tienen puertos host publicados. Puerto18091 es firmante LAB.
Volúmenes exclusivos `pedidos360-ev3-integral_*` conservan datos al recrear API.

**No `prune`, ni `down -v`, ni reutilizar nombres del rescate.** Para retirar solo
este laboratorio sin borrar datos: `docker compose -f deploy/ev3-local/compose.yml down`.
Rotar el secreto de inicialización PostgreSQL no cambia contraseñas del volumen
existente. No reemplazar este entorno por bases de producción o dumps H2 reales.

## Flujo comprobable

Productos → cotización Orden con precio backend → Pago simulado → outbox Kafka →
FazCoins verificando estado Pago. Confirmación Orden consulta Pago y crea un solo
Pedido. Productos/Carrito publican interacciones → Kafka → proyección/afinidades
Analítica → API recomendaciones. RabbitMQ conserva compra/stock operativo separado.

`smoke.mjs` utiliza HTTP real a través del gateway, identidades sintéticas nuevas
en cada corrida y los contenedores reales. No mocks de los tres microservicios.
Comprueba precio/backend, pago/antifraude/idempotencia/owner, confirmación de pedido,
acreditación real, canjes/insuficiencia/concurrencia, recomendaciones y reinicios de
consumidores. Guarda solo nombres/resultados en `evidence.local.json` ignorado;
nunca JWT/claves/cuerpos sensibles. Respeta ventana previa esperando diez segundos,
no borra ledger/pagos de corridas anteriores.

## Identidad: dos modos explícitos

Por defecto el laboratorio usa perfil **ev3-local**, JWKS de `lab-auth` con RSA
efímera en RAM, claims sintéticos y secreto LAB para emitir tokens de prueba.
Solo namespace oid `00000000-0000-4000-8000-*`. Firmas y validadores siguen activos.
**No es Entra, login productivo ni permisos Azure modificados**. No tokens del
usuario en scripts/Git. Reiniciar firmante rota su clave y requiere tokens nuevos.

Para Angular con login Entra real, quitar LOCAL_JWT_JWK_SET_URI del entorno de los
servicios y configurar redirect/consentimiento de la SPA existente según README
frontend; los servicios verifican JWKS Azure normal. No mezclar tokens Entra y
firmante LAB. Las pruebas de UI con HTTP simulado no certifican login Azure real.

## Límites y futura AWS

- Todo pago/reembolso y ledger son de simulación; no tarjeta, CVV o token bancario.
- Cashback inicial 5% floor; 1 FazCoin equivale a 1 CLP para contabilidad de prueba.
  Canje digital persiste una recompensa; no descuento de precios ni pago con puntos.
- Kafka y PostgreSQL locales no usan TLS/ACL separados. Clave interna es adaptación
  local, nunca credencial publicada o enviada al navegador. Gateway oculta /internal.
- Para AWS faltan respaldo H2 real/R3 autorizado, PG durable/backups, secretos/roles
  mínimos, TLS/ACL Kafka, observabilidad/retención, red interna y revisión de Entra.
  Este desarrollo no autoriza desplegar ni reemplazar servicios existentes.
- Ver informe consolidado para resultados exactos y pendientes no validados.
