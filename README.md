# ms-pago — integración integral / PEDIDOS360 EV3

## Extensión integral (sobre el MVP probado F2.1)

Rama `ev3/integracion-integral`. Perfil **ev3-local** importa cotizaciones de Orden
(`ORDEN_URL`), calculadas con precios de Productos; nunca importes del navegador.
Configurar `PAGO_DB_URL/USER/PASSWORD`, `KAFKA_BOOTSTRAP_SERVERS` e
`INTERNAL_SERVICE_KEY` aleatoria, mínimo 32 caracteres. Fuera del perfil,
`PAGO_REMOTE_OPERATIONS_ENABLED` y `PAGO_KAFKA_ENABLED` son opt-in explícitos.

- Aprobación crea outbox en la misma transacción; publisher Kafka al menos una vez,
  separado del lock antifraude. Consumidores deduplican por evento y causa.
- `POST /api/pagos/{id}/anulacion`: owner + Idempotency-Key, reembolso total
  **simulado** una sola vez; REFUNDED. No devuelve dinero real ni cancela pedido.
- `GET /api/pagos/{id}/intentos` y `/api/pagos/me/alertas`: solo propios.
- `GET /internal/pagos/{id}`: estado autoritativo para Orden/FazCoins, solo header
  X-Service-Key desde entorno; JWT usuario no lo habilita. Nunca secret en Angular.
  Endpoint no expuesto en Gateway; AWS necesitará IAM/mTLS/TLS/ACL.
- Eventos `pago.aprobado.v1` y `pago.reembolsado.v1`: `docs/EVENTOS.md`.
- `LOCAL_JWT_JWK_SET_URI` solo con perfil ev3-local permite el firmante sintético
  del laboratorio; mantiene firma/issuer/tenant/audience/scope. Nunca usarlo en AWS.
  Omitirlo para Entra real. Replay tras anulación devuelve estado actual REFUNDED.
- FazCoins vive en ms-fidelizacion; crear pedido no acredita puntos.

Entorno conjunto y pruebas en `deploy/ev3-local/`. Las siguientes instrucciones
conservan el laboratorio aislado F2.1; el integral no carga operaciones fixture,
sino cotizaciones nuevas del backend local. No tocar servicios/H2/AWS existentes.

**Solo simulación: APPROVED no equivale a un cobro bancario.** Java 21, Spring Boot
3.5.16, Maven, PostgreSQL 17 y Flyway. Sin H2, brokers ni conexiones a Orden/AWS.
Rama `ev3/pago-f2-1`; sin despliegue ni publicación de imágenes.

## Ejecutar exclusivamente local

Requisitos: Java 21/Maven 3.9+ para tests; Docker Desktop Linux/Compose para BD,
Testcontainers y contenedores. Revisar otras cargas antes de iniciar Docker Desktop.
Compose solo afecta al proyecto `pago-f21-local`; nunca usar prune ni reutilizar
los contenedores del rescate H2.

1. Copiar `.env.example` a `.env` y reemplazar la contraseña **local**, sin compartirla.
2. Ejecutar `docker --context desktop-linux compose up -d --build`.
3. Consultar `http://localhost:18085/health` → `SIMULATION_ONLY`.
4. `docker --context desktop-linux compose logs pago` para comprobar Flyway/arranque.

BD `127.0.0.1:55432`, API `127.0.0.1:18085`, volumen persistente `pago_data`.
Reiniciar/recrear API no borra pagos; `compose down` conserva el volumen.
**No usar `down -v`: elimina los datos locales.** La contraseña de inicialización
PostgreSQL solo se aplica al volumen nuevo; cambiar `.env` no rota la existente.

Para desarrollo: `compose up -d postgres`, exportar PAGO_DB_PASSWORD al proceso
Maven y `mvn spring-boot:run` (API :8080). `.env` la lee Compose, no Java. Activar
`PAGO_FIXTURES_ENABLED=true` si se necesitan fixtures con Maven. No exponer estos
puertos a Internet: Compose no tiene TLS/hardening productivo.

## Pruebas automáticas

```powershell
$env:DOCKER_HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'
mvn -B verify
```

En Linux/macOS usar el socket Docker local y `mvn -B verify`. Testcontainers crea
PostgreSQL real exclusivo, no usa la BD de Compose y falla si no hay Docker.
`src/test/resources/docker-java.properties` fija API 1.44 para Engine 29. Los tests
ejecutan Flyway, firmas RSA reales, filtros Security, HTTP en puerto aleatorio,
concurrencia y fallos de transacción/commit. Claves JWT en RAM **solo en tests**,
sin perfil inseguro en API. Resultados en `target/surefire-reports/`, ignorados.

## Seguridad y fixtures

API normal: firma RS256/JWKS Azure, issuer v2, audience, exp/nbf, tenant, `oid` UUID
y scope delegado `access_as_user`. Configuración pública predeterminada:

- Tenant: `ee0d2c5b-e60b-4c57-9b30-8a38a520c430`.
- Audience: `304fa289-2b72-447b-9c48-f00998f7c22f`.
- Overrides: `AZURE_TENANT_ID`, `AZURE_API_AUDIENCE`.
- Solo `/health` público. Sin roles administrativos ni equivalencias
  email/sub/localAccountId→oid. Sin CORS abierto o integración Angular.

Compose habilita fixtures; por defecto están deshabilitados fuera de Compose.
`FixtureConfig` carga 24 operaciones, 12 por dueño, CLP 12990.00, expiración siete
días desde primera inserción. Reiniciar no renueva expiración ni modifica pagos.

| oid sintético | operación 1 (últimos 12 dígitos: 1..12) |
|---|---|
| `00000000-0000-4000-8000-000000000001` | `10000000-0000-4000-8001-000000000001` |
| `00000000-0000-4000-8000-000000000002` | `10000000-0000-4000-8002-000000000001` |

Instrumentos globales: `sim-approved` y `sim-declined`. Son identificadores de
laboratorio, **no tarjetas ni tokens bancarios**. No PAN/CVV/HMAC de datos reales.
Para otros propietarios crear fixtures revisadas en backend/BD local; no existe
endpoint para crear importes/cotizaciones o elegir dueño libremente. Los oid
anteriores no son cuentas Azure reales: un JWT de otro oid no puede usarlos.
Los tests firman claims sintéticos con claves efímeras y decoder de test, sin
debilitar la configuración Azure del ejecutable normal.

## Contrato

```http
POST /api/pagos
Authorization: Bearer <access-token-de-la-API>
Idempotency-Key: demo-001
Content-Type: application/json

{"operacionId":"10000000-0000-4000-8001-000000000001","metodo":"SIMULADO","instrumentoPruebaId":"sim-approved"}
```

JWT del dueño de operación. No guardar tokens en evidencia/logs/chat. El ejemplo
describe el contrato, no proporciona un JWT Azure para usuarios ficticios. Ensayo
autenticado sin credenciales reales: `mvn verify` incluye petición por socket HTTP.

Respuesta: `pagoId`, `operacionId`, `estado`, `importe`, `moneda`, `simulacion`,
`creadoEn`. No expone identidad, instrumento ni decisiones de otros usuarios.

- APPROVED/DECLINED nuevos → **201**; DECLINED es resultado persistido, no fallo
  de infraestructura. Solo una aprobación por operación, incluso con keys distintas.
- BLOCKED → **429**, pago/intento/decisión persistidos. Sin hold obligatorio ni
  `Retry-After` fijo: nuevas solicitudes cambian la ventana.
- Replay → mismo resultado/ID/fecha, **200** (429 si bloqueado), header
  `Idempotency-Replayed: true`, sin sumar intentos incluso tras expirar la operación.
- Misma key/contenido distinto → **409**. Key obligatoria, 1..128 caracteres
  `[A-Za-z0-9._:-]`, aislada por `(tid,oid)`; contenido canónico tipado.
- `GET /api/pagos/{pagoId}`: dueño; ajeno/inexistente → **404**.
- `GET /api/pagos/me?limit=50`: últimos propios, límite 1..100, sin cursor en MVP.
- Operación ajena/inexistente → 404; expirada/ya aprobada → 409; instrumento
  desconocido/campos extra (importe, PAN, CVV, owner, fecha) → 400; JWT inválido →
  401; sin scope → 403; persistencia → 503 sin SQL/secretos/detalles internos.

## Antifraude y reintentos

Transacción bloquea idempotencia → operación → fila global del instrumento. Obtiene
`clock_timestamp()` PostgreSQL **después** del lock y cuenta intentos de todos los
usuarios en **[ahora−10s, ahora] inclusivo**, también DECLINED/BLOCKED. Intentos 1–3
permitidos por esta regla; cuarto y siguientes bloqueados. Otro instrumento tiene
ventana independiente. Replays/solicitudes inválidas no son intentos. Sin clientId
ni fechas del navegador. No hold extra de 30 minutos; bloqueados siguen contando
hasta salir de la ventana.

Pago/intento/decisión/key en una transacción READ COMMITTED con locks BD, no mutex
Java. Sin llamadas externas durante lock. Timeouts de locks/SQL, sin reintento
automático. Ante fallo o respuesta perdida, reutilizar **misma key/contenido**:
rollback permite ejecutar; commit previo devuelve replay. Un 503 no prueba que
un commit perdido no ocurrió; nunca resolverlo inventando una nueva key.

## Pendientes

Ver `docs/DECISIONES_F2_1.md`, `tests/README.md` e informe acumulativo incluido.
`docs/ARQUITECTURA.md` sigue como referencia histórica. Webpay/capturas reales y AWS
pendientes; Kafka/outbox, Orden y refunds simulados implementados en la extensión.
