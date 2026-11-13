// EXPLICIT LOCAL LAB ONLY. No credential copied from Entra, no private key files.
import http from 'node:http';
import { generateKeyPairSync, randomUUID, sign, timingSafeEqual } from 'node:crypto';
const key = process.env.LOCAL_TOKEN_KEY;
if (!key || key.length < 32) throw new Error('LOCAL_TOKEN_KEY_REQUIRED');
const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: 'jwk' }), kid: randomUUID(), alg: 'RS256', use: 'sig' };
const tenant = 'ee0d2c5b-e60b-4c57-9b30-8a38a520c430';
const encoded = x => Buffer.from(JSON.stringify(x)).toString('base64url');
http.createServer(async (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  if (req.method === 'GET' && req.url === '/jwks') return res.end(JSON.stringify({ keys: [jwk] }));
  if (req.method === 'GET' && req.url === '/health') return res.end('{"mode":"SYNTHETIC_JWT_LAB"}');
  const supplied = String(req.headers['x-lab-key'] ?? '');
  if (req.method !== 'POST' || req.url !== '/tokens' || supplied.length !== key.length || !timingSafeEqual(Buffer.from(supplied), Buffer.from(key))) {
    res.statusCode = 401; return res.end('{"code":"UNAUTHORIZED_LAB"}');
  }
  try {
    let body = ''; for await (const part of req) { body += part; if (body.length > 2048) throw new Error(); }
    const { ownerId } = JSON.parse(body);
    // Deliberately synthetic namespace only; each smoke run uses fresh owners.
    if (typeof ownerId !== 'string' || !/^00000000-0000-4000-8000-[a-f0-9]{12}$/.test(ownerId)) throw new Error();
    const now = Math.floor(Date.now() / 1000);
    const payload = { iss: `https://login.microsoftonline.com/${tenant}/v2.0`, aud: '304fa289-2b72-447b-9c48-f00998f7c22f', tid: tenant,
      oid: ownerId, sub: `synthetic-${ownerId}`, scp: 'access_as_user', nbf: now - 5, iat: now, exp: now + 900 };
    const signing = `${encoded({ alg: 'RS256', typ: 'JWT', kid: jwk.kid })}.${encoded(payload)}`;
    const token = `${signing}.${sign('RSA-SHA256', Buffer.from(signing), privateKey).toString('base64url')}`;
    res.end(JSON.stringify({ access_token: token, expires_in: 900, simulation: true }));
  } catch { res.statusCode = 400; res.end('{"code":"INVALID_LAB_REQUEST"}'); }
}).listen(8080, '0.0.0.0');
