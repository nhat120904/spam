import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { chromium } from 'playwright-core';

// Public Cloudflare testing key. No production key or target is accepted.
const TEST_SECRET = '1x0000000000000000000000000000000AA';
const CLOUDFLARE_ORIGIN = 'https://challenges.cloudflare.com';
const widgetHtml = readFileSync(new URL('./token-demo.html', import.meta.url), 'utf8');

export function createTokenDemo({ executablePath, artifactDir } = {}) {
  let browser;
  let browserInstance = null;
  let browserLaunches = 0;
  let completed = 0;
  let busy = false;

  const json = (res, status, data) => {
    res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
    res.end(JSON.stringify(data, null, 2));
  };
  const fail = (res, status, error) => json(res, status, { ok: false, mode: 'cloudflare-test', error });

  async function getTestToken() {
    const started = Date.now();
    const requestId = randomUUID();
    const origin = `http://127.0.0.1:${server.address().port}`;
    if (!browser?.isConnected()) {
      browser = await chromium.launch({
        headless: true,
        ...(executablePath ? { executablePath } : { channel: 'chrome' }),
      });
      browserInstance = randomUUID();
      browserLaunches++;
    }
    const context = await browser.newContext({ viewport: { width: 1000, height: 650 } });
    try {
      // The worker can load only its own local fixture and Cloudflare's widget.
      await context.route('**/*', route => {
        const requestOrigin = new URL(route.request().url()).origin;
        return requestOrigin === origin || requestOrigin === CLOUDFLARE_ORIGIN
          ? route.continue() : route.abort();
      });
      const page = await context.newPage();
      await page.goto(`${origin}/widget`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForFunction(() => window.demoResult !== null, undefined, { timeout: 30000 });
      const result = await page.evaluate(() => window.demoResult);
      if (result.error) throw new Error(`test-widget-error: ${result.error}`);
      if (typeof result.token !== 'string' || !result.token.includes('.DUMMY.TOKEN.')) {
        throw new Error('expected-a-cloudflare-dummy-token');
      }

      const verifyResponse = await fetch(`${CLOUDFLARE_ORIGIN}/turnstile/v0/siteverify`, {
        method: 'POST',
        body: new URLSearchParams({ secret: TEST_SECRET, response: result.token }),
        signal: AbortSignal.timeout(10000),
        redirect: 'error',
      });
      if (!verifyResponse.ok) throw new Error(`test-siteverify-http-${verifyResponse.status}`);
      const verification = await verifyResponse.json();
      const response = {
        ok: verification.success === true,
        mode: 'cloudflare-test',
        requestId,
        token: result.token,
        verification,
        headless: true,
        browserInstance,
        browserLaunches,
        elapsedMs: Date.now() - started,
        note: 'Test tokens may repeat and are not valid for production sites.',
      };
      if (artifactDir) {
        await mkdir(artifactDir, { recursive: true });
        await page.screenshot({ path: path.join(artifactDir, 'latest-widget.png'), fullPage: true });
        await writeFile(path.join(artifactDir, 'latest-response.json'), JSON.stringify(response, null, 2) + '\n');
      }
      completed++;
      return response;
    } finally {
      await context.close();
    }
  }

  async function handle(req, res) {
    const host = req.headers.host ?? '';
    if (!/^(127\.0\.0\.1|localhost)(:\d+)?$/.test(host)) return fail(res, 403, 'local-only');
    if (req.method === 'POST' && req.headers.origin && req.headers.origin !== `http://${host}`) {
      return fail(res, 403, 'origin-mismatch');
    }
    const url = new URL(req.url, `http://${host}`);
    if (req.method === 'GET' && url.pathname === '/health') {
      return json(res, 200, {
        ok: true, mode: 'cloudflare-test', headless: true,
        browserConnected: Boolean(browser?.isConnected()), browserInstance,
        browserLaunches, busy, completed,
      });
    }
    if (req.method === 'GET' && url.pathname === '/') {
      return json(res, 200, {
        name: 'Local Turnstile test-token demo',
        mode: 'cloudflare-test',
        request: `curl -X POST http://${host}/api/token`,
        health: '/health',
        note: 'Uses fixed official test keys. Test tokens may repeat.',
      });
    }
    if (req.method === 'GET' && url.pathname === '/widget') {
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
      return res.end(widgetHtml);
    }
    if (req.method !== 'POST' || url.pathname !== '/api/token') return fail(res, 404, 'not-found');
    if (url.search) return fail(res, 400, 'test-demo-accepts-no-parameters');

    let body = '';
    for await (const chunk of req) {
      body += chunk.toString('utf8');
      if (Buffer.byteLength(body) > 1024) return fail(res, 413, 'body-too-large');
    }
    if (body.trim()) {
      let payload;
      try { payload = JSON.parse(body); } catch { return fail(res, 400, 'invalid-json'); }
      if (!payload || Array.isArray(payload) || typeof payload !== 'object' || Object.keys(payload).length) {
        return fail(res, 400, 'test-demo-accepts-no-parameters');
      }
    }
    // One worker at a time; additional clients can retry after the active call.
    if (busy) return fail(res, 409, 'worker-busy');
    busy = true;
    try {
      const result = await getTestToken();
      json(res, result.ok ? 200 : 422, result);
    } catch (error) {
      json(res, error.name === 'TimeoutError' ? 504 : 502, {
        ok: false, mode: 'cloudflare-test', error: 'test-token-failed', message: error.message,
      });
    } finally {
      busy = false;
    }
  }

  const server = createServer((req, res) => {
    handle(req, res).catch(error => {
      if (res.headersSent) return res.destroy();
      fail(res, 500, 'demo-server-error');
      console.error(error.message);
    });
  });
  async function close() {
    await browser?.close();
    server.closeAllConnections();
    if (server.listening) await new Promise(resolve => server.close(resolve));
  }
  return { server, close };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { values } = parseArgs({ options: { port: { type: 'string', default: '3002' } } });
  const port = Number(values.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid local port');
  const demo = createTokenDemo({
    executablePath: process.env.CHROME_EXECUTABLE_PATH || undefined,
    artifactDir: fileURLToPath(new URL('../runtime/token-demo/', import.meta.url)),
  });
  demo.server.on('error', error => { console.error(error.message); process.exitCode = 1; });
  demo.server.listen(port, '127.0.0.1', () => {
    console.log(`Test-token API: http://127.0.0.1:${port}`);
    console.log(`Try: curl -X POST http://127.0.0.1:${port}/api/token`);
  });
  let stopping = false;
  const stop = async () => {
    if (stopping) return;
    stopping = true;
    await demo.close();
  };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
}
