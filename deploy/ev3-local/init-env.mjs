// Generates NEW local-only secrets, refuses overwrite, never prints them.
import { randomBytes } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
const text = ['LOCAL_DB_PASSWORD', 'INTERNAL_SERVICE_KEY', 'LOCAL_TOKEN_KEY']
  .map(name => `${name}=${randomBytes(32).toString('hex')}`).join('\n') + '\n';
await writeFile(new URL('.env', import.meta.url), text, { flag: 'wx', mode: 0o600 });
console.log('Created local .env (ignored). Secrets not printed.');
