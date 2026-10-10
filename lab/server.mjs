import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { parseArgs } from 'node:util';

const LAB_ID = 'local-vote-lab-v1';
const DAY_MS = 86_400_000;
const TEST_SECRET = '1x0000000000000000000000000000000AA';
const SCENARIOS = ['open', 'quota', 'phone', 'captcha', 'server-error'];

export function createLabServer({ captchaMode = 'mock' } = {}) {
  if (!['mock', 'turnstile'].includes(captchaMode)) throw new Error('Unknown CAPTCHA mode');
  let scenario = 'open';
  let accepted = 0;
  let requests = 0;
  let criteriaTotals = Array(8).fill(0);
  const tokens = new Map();
  const sessions = new Map();
  const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
  const reset = () => {
    accepted = 0; requests = 0; criteriaTotals = Array(8).fill(0); tokens.clear();
    for (const session of sessions.values()) session.votedAt = 0;
  };
  const state = session => ({ labId: LAB_ID, captchaMode, scenario, accepted, requests,
    totalStars: criteriaTotals.reduce((sum, n) => sum + n, 0), criteriaTotals,
    remaining: scenario === 'quota' ? Number(Date.now() >= session.votedAt + DAY_MS) : 10000 });
  const send = (res, status, body, type = 'text/plain; charset=utf-8') => {
    res.writeHead(status, { 'content-type': type, 'cache-control': 'no-store' });
    res.end(body);
  };
  const json = (res, status, data) => send(res, status, JSON.stringify(data), 'application/json; charset=utf-8');
  const readBody = async req => {
    let length = 0;
    const chunks = [];
    for await (const chunk of req) {
      length += chunk.length;
      if (length > 32768) throw Object.assign(new Error('Body too large'), { status: 413 });
      chunks.push(chunk);
    }
    return Buffer.concat(chunks).toString('utf8');
  };
  const verify = async token => {
    if (captchaMode === 'mock') {
      const expires = tokens.get(token);
      tokens.delete(token);
      return Boolean(expires && expires > Date.now());
    }
    const response = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
      method: 'POST', body: new URLSearchParams({ secret: TEST_SECRET, response: token }),
      signal: AbortSignal.timeout(10000), redirect: 'error',
    });
    if (!response.ok) throw Object.assign(new Error('Siteverify unavailable'), { status: 503 });
    return (await response.json()).success === true;
  };
  async function handle(req, res) {
    const host = req.headers.host ?? '';
    if (!/^(127\.0\.0\.1|localhost)(:\d+)?$/.test(host)) return send(res, 403, 'local-only');
    const origin = `http://${host}`;
    if (req.method === 'POST' && req.headers.origin && req.headers.origin !== origin) {
      return send(res, 403, 'origin-mismatch');
    }
    let sid = /(?:^|;\s*)lab_session=([a-f0-9-]{36})(?:;|$)/.exec(req.headers.cookie ?? '')?.[1];
    if (!sid || !sessions.has(sid)) {
      sid = randomUUID(); sessions.set(sid, { votedAt: 0 });
      res.setHeader('Set-Cookie', `lab_session=${sid}; Path=/; HttpOnly; SameSite=Lax`);
    }
    const session = sessions.get(sid);
    const url = new URL(req.url, origin);
    if (req.method === 'GET' && url.pathname === '/') return send(res, 200, html, 'text/html; charset=utf-8');
    if (req.method === 'GET' && url.pathname === '/api/state') return json(res, 200, state(session));
    if (req.method === 'POST' && url.pathname === '/api/reset') {
      reset(); return json(res, 200, state(session));
    }
    if (req.method === 'POST' && url.pathname === '/api/scenario') {
      let data;
      try { data = JSON.parse(await readBody(req)); } catch { return send(res, 400, 'invalid-json'); }
      if (!SCENARIOS.includes(data.scenario)) return send(res, 400, 'invalid-scenario');
      scenario = data.scenario; reset(); return json(res, 200, state(session));
    }
    if (req.method === 'POST' && url.pathname === '/api/test-token') {
      if (captchaMode !== 'mock') return send(res, 409, 'mock-mode-only');
      const token = `lab.${randomUUID()}`;
      tokens.set(token, Date.now() + 300000);
      return json(res, 200, { token });
    }
    if (req.method === 'POST' && url.pathname === '/truong-hoc-hanh-phuc/vote') {
      requests++;
      const form = new URLSearchParams(await readBody(req));
      const ratings = form.getAll('rating[]');
      if (form.get('thhp_id') !== '1098' || ratings.length !== 8 || ratings.some(r => !/^[1-5]$/.test(r))) {
        return send(res, 400, 'invalid-ballot');
      }
      if (scenario === 'server-error') return send(res, 500, '');
      const captcha = form.get('captcha');
      if (scenario === 'captcha' || !captcha || !await verify(captcha)) return send(res, 200, '3');
      if (scenario === 'phone') return send(res, 200, '2');
      if (scenario === 'quota' && Date.now() < session.votedAt + DAY_MS) return send(res, 200, '0');
      // All counter updates happen synchronously after validation, without awaits.
      accepted++;
      ratings.forEach((rating, i) => { criteriaTotals[i] += Number(rating); });
      session.votedAt = Date.now();
      return send(res, 200, '1');
    }
    return send(res, 404, 'not-found');
  }
  return createServer((req, res) => handle(req, res).catch(error => {
    if (res.headersSent) return res.destroy();
    send(res, error.status ?? 500, 'lab-error');
  }));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { values } = parseArgs({ options: {
    port: { type: 'string', default: '3000' }, turnstile: { type: 'boolean', default: false },
  } });
  const port = Number(values.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid local port');
  const server = createLabServer({ captchaMode: values.turnstile ? 'turnstile' : 'mock' });
  server.on('error', error => { console.error(error.message); process.exitCode = 1; });
  server.listen(port, '127.0.0.1', () => {
    console.log(`Vote lab: http://127.0.0.1:${port}`);
    console.log(`CAPTCHA: ${values.turnstile ? 'Cloudflare official test keys' : 'local mock tokens'}; data stays in memory.`);
  });
}
