import { chromium } from 'playwright-core';
import { mkdir, writeFile } from 'node:fs/promises';
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';
import { runVote } from '../src/vote.mjs';

const { values } = parseArgs({ options: {
  port: { type: 'string', default: '3000' }, api: { type: 'boolean', default: false },
  headed: { type: 'boolean', default: false },
} });
const port = Number(values.port);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid local port');
const origin = `http://127.0.0.1:${port}`;
const configuration = await (await fetch(`${origin}/api/state`, {
  redirect: 'error', signal: AbortSignal.timeout(5000),
})).json();
if (configuration.labId !== 'local-vote-lab-v1') throw new Error('Target must be the local Vote Lab');

const browser = await chromium.launch({ channel: 'chrome', headless: !values.headed });
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
const providerHosts = new Set();
await page.route('**/*', route => {
  const url = new URL(route.request().url());
  if (url.origin === origin) return route.continue();
  if (configuration.captchaMode === 'turnstile' && url.protocol === 'https:' && url.hostname === 'challenges.cloudflare.com') {
    providerHosts.add(url.hostname); return route.continue();
  }
  return route.abort();
});
try {
  await page.goto(origin, { waitUntil: 'domcontentloaded', timeout: 15000 });
  const result = await runVote(page, { submit: true, transport: values.api ? 'api' : 'page',
    captchaTimeoutMs: 45000, responseTimeoutMs: 15000,
    onEvent: event => console.log(event),
  });
  const state = await (await page.request.get(`${origin}/api/state`)).json();
  const dir = new URL('../runtime/lab/', import.meta.url);
  await mkdir(dir, { recursive: true });
  const name = `vote-${port}-${values.api ? 'api' : 'page'}`;
  const screenshot = new URL(`${name}.png`, dir);
  await page.screenshot({ path: fileURLToPath(screenshot), timeout: 5000 });
  const report = { checkedAt: new Date().toISOString(), target: origin, browser: browser.version(),
    captchaMode: configuration.captchaMode, providerHosts: [...providerHosts], ...result,
    server: { accepted: state.accepted, totalStars: state.totalStars, requests: state.requests },
    screenshot: fileURLToPath(screenshot),
  };
  const output = new URL(`${name}.json`, dir);
  await writeFile(output, `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify(report, null, 2));
  console.log(`Report: ${fileURLToPath(output)}`);
  if (result.outcome !== 'success') process.exitCode = 1;
} finally {
  await browser.close();
}
