// Real local HTTP + Kafka + PostgreSQL integration, synthetic identities only.
// Never prints JWTs, lab/internal keys, HTTP bodies on errors, or real credentials.
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { randomUUID, randomBytes } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root = new URL('./', import.meta.url);
const env = Object.fromEntries((await readFile(new URL('.env', root), 'utf8')).trim().split(/\r?\n/).map(line => line.split('=')));
const base = 'http://127.0.0.1:18090';
const alice = '00000000-0000-4000-8000-' + randomBytes(6).toString('hex');
const bob = '00000000-0000-4000-8000-' + randomBytes(6).toString('hex');
const runId = randomUUID();
const checks = [];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const report = { runId, syntheticOnly: true, awsAccess: false, checks, passed: false };
async function eventually(label, test, seconds = 90) {
  let last;
  for (let n = 0; n < seconds * 2; n++) {
    try { const result = await test(); if (result) return result; } catch (e) { last = e; }
    await delay(500);
  }
  throw new Error(`TIMEOUT_${label}${last ? '_CHECK_FAILED' : ''}`);
}
async function token(ownerId) {
  const response = await fetch('http://127.0.0.1:18091/tokens', { method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Lab-Key': env.LOCAL_TOKEN_KEY }, body: JSON.stringify({ ownerId }) });
  assert.equal(response.status, 200, 'Synthetic token issuer failed');
  return (await response.json()).access_token;
}
async function api(path, jwt, method = 'GET', body, key) {
  const headers = { Authorization: `Bearer ${jwt}` };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  const response = await fetch(base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await response.text();
  let data; try { data = JSON.parse(text); } catch { data = null; }
  return { status: response.status, data, replay: response.headers.get('Idempotency-Replayed') };
}
function passed(name) { checks.push({ name, passed: true }); console.log(`PASS ${name}`); }
const compose = ['--context', 'desktop-linux', 'compose', '-f', fileURLToPath(new URL('compose.yml', root))];
function docker(args, input) {
  const result = spawnSync('docker', [...compose, ...args], { encoding: 'utf8', input, timeout: 120000 });
  assert.equal(result.status, 0, 'Scoped Docker command failed');
  return result.stdout.trim();
}
try {
  const a = await token(alice), b = await token(bob);
  await eventually('SERVICES_READY', async () => (await api('/api/productos', a)).status === 200);
  const catalog = (await api('/api/productos', a)).data;
  assert.ok(Array.isArray(catalog) && catalog.length >= 3, 'Backend catalog required');
  const eligible = catalog.filter(p => p.stock >= 5).sort((x, y) => y.precio - x.precio);
  assert.ok(eligible.length, 'Stocked product required');
  const product = eligible[0];
  const quantity = Math.min(20, product.stock, Math.max(1, Math.ceil(2200 / Number(product.precio))));
  assert.ok(quantity * product.precio >= 2000, 'Catalog must support an award sufficient for digital reward');
  const quote = async (jwt, suffix, q = quantity) => {
    const response = await api('/api/orden/cotizaciones', jwt, 'POST', { items: [{ productoId: product.id, cantidad: q }] }, `${runId}-quote-${suffix}`);
    assert.ok([200, 201].includes(response.status), 'Trusted quote creation must succeed');
    return response.data;
  };
  const operation = await quote(a, 'paid');
  assert.equal(Number(operation.importe), Number((Number(product.precio) * quantity).toFixed(2)));
  const invalid = await api('/api/orden/cotizaciones', a, 'POST', { items: [{ productoId: product.id, cantidad: 1, precioUnitario: 0.01 }], importe: 0.01 }, `${runId}-tampered`);
  assert.equal(invalid.status, 400, 'Client price fields must be rejected');
  passed('backend_quote_and_client_price_rejection');

  // Previous local runs share the same global simulator instrument by design.
  // Let their ten-second window expire; never delete prior payment/ledger data.
  await delay(10100);

  const before = await eventually('WALLET_READY', async () => { const r = await api('/api/fidelizacion/me/saldo', a); return r.status === 200 && r.data; });
  const paymentBody = { operacionId: operation.operacionId, metodo: 'SIMULADO', instrumentoPruebaId: 'sim-approved' };
  const payKey = `${runId}-payment`;
  const paid = await api('/api/pagos', a, 'POST', paymentBody, payKey);
  assert.equal(paid.status, 201); assert.equal(paid.data.estado, 'APPROVED');
  assert.equal(Number(paid.data.importe), Number(operation.importe));
  const replay = await api('/api/pagos', a, 'POST', paymentBody, payKey);
  assert.equal(replay.status, 200); assert.equal(replay.data.pagoId, paid.data.pagoId);
  assert.equal((await api(`/api/pagos/${paid.data.pagoId}`, b)).status, 404);
  const attempts = await api(`/api/pagos/${paid.data.pagoId}/intentos`, a);
  assert.equal(attempts.data.length, 1);
  passed('payment_idempotency_and_owner');

  const award = Math.floor(Number(paid.data.importe) * 0.05);
  const target = Number(before.disponible) + Math.max(0, award - Number(before.deuda));
  await eventually('PAYMENT_TO_FAZCOINS', async () => Number((await api('/api/fidelizacion/me/saldo', a)).data?.disponible) === target);
  passed('real_payment_kafka_and_fazcoins_credit');

  const confirm = await api('/api/orden/confirmar-pago', a, 'POST', { operacionId: operation.operacionId, pagoId: paid.data.pagoId }, `${runId}-confirm`);
  assert.equal(confirm.status, 200); assert.ok(confirm.data.pedidoId);
  const confirmReplay = await api('/api/orden/confirmar-pago', a, 'POST', { operacionId: operation.operacionId, pagoId: paid.data.pagoId }, `${runId}-confirm`);
  assert.equal(confirmReplay.data.pedidoId, confirm.data.pedidoId);
  await delay(1500);
  assert.equal(Number((await api('/api/fidelizacion/me/saldo', a)).data.disponible), target, 'Order confirmation must not award coins again');
  passed('verified_payment_order_once_no_order_award');

  const rewards = await api('/api/fidelizacion/recompensas', a);
  assert.equal(rewards.status, 200);
  const reward = rewards.data.find(r => r.id === 'faz-vip');
  assert.ok(reward && reward.costo === 100);
  const redemptionKey = `${runId}-redeem`;
  const redemption = await api('/api/fidelizacion/me/canjes', a, 'POST', { recompensaId: reward.id, cantidad: 1 }, redemptionKey);
  assert.ok([200, 201].includes(redemption.status));
  const redReplay = await api('/api/fidelizacion/me/canjes', a, 'POST', { recompensaId: reward.id, cantidad: 1 }, redemptionKey);
  assert.ok([200, 201].includes(redReplay.status));
  assert.equal(Number((await api('/api/fidelizacion/me/saldo', a)).data.disponible), target - 100);
  const insufficient = await api('/api/fidelizacion/me/canjes', b, 'POST', { recompensaId: reward.id, cantidad: 1 }, `${runId}-insufficient`);
  assert.equal(insufficient.status, 422);
  const concurrent = await Promise.all(Array.from({ length: 5 }, (_, i) => api('/api/fidelizacion/me/canjes', a, 'POST', { recompensaId: reward.id, cantidad: 1 }, `${runId}-concurrent-${i}`)));
  assert.ok(concurrent.every(r => [200, 201, 422].includes(r.status)));
  assert.ok(Number((await api('/api/fidelizacion/me/saldo', a)).data.disponible) >= 0);
  passed('redemption_duplicate_insufficient_and_concurrent');

  const fallback = await eventually('CATALOG_KAFKA_PROJECTION', async () => { const r = await api('/api/recomendaciones/me?limit=6', b); return r.status === 200 && r.data.items?.length && r.data; });
  assert.ok(fallback.estrategia);
  const selected = eligible[Math.min(1, eligible.length - 1)];
  for (let i = 0; i < 3; i++) {
    const interaction = await api(`/api/productos/${selected.id}/interacciones`, a, 'POST', { tipo: i ? 'SELECT' : 'VIEW' });
    assert.ok([200, 201, 202, 204].includes(interaction.status));
  }
  const add = await api(`/api/carrito/${alice}/items`, a, 'POST', { productoId: selected.id, nombreProducto: selected.nombre, cantidad: 1, precioUnitario: selected.precio });
  assert.equal(add.status, 200);
  const cartItem = add.data.items.find(i => i.productoId === selected.id);
  assert.ok(cartItem);
  const update = await api(`/api/carrito/${alice}/items`, a, 'POST', { productoId: selected.id, nombreProducto: selected.nombre, cantidad: 1, precioUnitario: selected.precio });
  assert.equal(update.status, 200);
  assert.ok([200, 204].includes((await api(`/api/carrito/${alice}/items/${cartItem.id}`, a, 'DELETE')).status));
  await eventually('CART_ADD_UPDATE_REMOVE_CONSUMED', async () => {
    const summary = (await api('/api/analytics/me/resumen', a)).data;
    return summary?.porTipo?.ADD >= 1 && summary.porTipo.UPDATE >= 1 && summary.porTipo.REMOVE >= 1;
  });
  const personal = await eventually('DYNAMIC_RECOMMENDATIONS', async () => {
    const r = await api('/api/recomendaciones/me?limit=6', a);
    return r.status === 200 && !String(r.data.estrategia).startsWith('FALLBACK') && r.data;
  });
  assert.ok(personal.items.length);
  passed('product_cart_real_kafka_and_dynamic_recommendations');

  for (let i = 1; i <= 4; i++) {
    const jwt = i % 2 ? a : b;
    const q = await quote(jwt, `fraud-${i}`, 1);
    const result = await api('/api/pagos', jwt, 'POST', { operacionId: q.operacionId, metodo: 'SIMULADO', instrumentoPruebaId: 'sim-declined' }, `${runId}-fraud-${i}`);
    assert.equal(result.status, i === 4 ? 429 : 201);
    assert.equal(result.data.estado, i === 4 ? 'BLOCKED' : 'DECLINED');
  }
  passed('fourth_attempt_cross_user_fraud');

  const refunded = await api(`/api/pagos/${paid.data.pagoId}/anulacion`, a, 'POST', undefined, `${runId}-refund`);
  assert.equal(refunded.status, 200);
  await eventually('REFUND_REVERSAL', async () => {
    const balance = (await api('/api/fidelizacion/me/saldo', a)).data;
    return balance && Number(balance.disponible) >= 0 && Number(balance.deuda) > 0;
  });
  passed('refund_reversal_without_negative_spendable_balance');

  const walletBeforeRestart = (await api('/api/fidelizacion/me/saldo', a)).data;
  const summaryBeforeRestart = (await api('/api/analytics/me/resumen', a)).data;
  docker(['restart', 'analytics', 'fidelizacion']);
  await eventually('CONSUMER_RESTART', async () => (await api('/api/analytics/me/resumen', a)).status === 200 && (await api('/api/fidelizacion/me/saldo', a)).status === 200);
  assert.ok((await api('/api/recomendaciones/me?limit=6', a)).data.items.length);
  assert.deepEqual((await api('/api/fidelizacion/me/saldo', a)).data, walletBeforeRestart);
  assert.deepEqual((await api('/api/analytics/me/resumen', a)).data, summaryBeforeRestart);
  const afterRestart = await api(`/api/productos/${selected.id}/interacciones`, a, 'POST', { tipo: 'VIEW' });
  assert.ok([200, 201, 202, 204].includes(afterRestart.status));
  await eventually('CONSUMPTION_AFTER_RESTART', async () => {
    const summary = (await api('/api/analytics/me/resumen', a)).data;
    return Number(summary?.totalInteracciones) === Number(summaryBeforeRestart.totalInteracciones) + 1;
  });
  passed('consumer_restart_projection_and_wallet_persistence');
  report.passed = true;
} finally {
  await writeFile(new URL('evidence.local.json', root), JSON.stringify(report, null, 2));
}
console.log('EV3_LOCAL_INTEGRATION_PASSED');
