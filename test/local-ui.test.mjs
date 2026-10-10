import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { chromium } from 'playwright-core';
import { createLabServer } from '../lab/server.mjs';
import { runVote } from '../src/vote.mjs';

let browser;
before(async () => { browser = await chromium.launch({ channel: 'chrome', headless: true }); });
after(async () => { await browser?.close(); });

async function fixture(t) {
  const server = createLabServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  t.after(async () => {
    await page.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  const blocked = [];
  await page.route('**/*', route => {
    if (new URL(route.request().url()).origin === origin) return route.continue();
    blocked.push(route.request().url());
    return route.abort();
  });
  await page.goto(origin);
  return { page, origin, blocked };
}

test('existing vote script selects eight stars, submits once and updates the local page', async t => {
  const f = await fixture(t);
  const result = await runVote(f.page, { submit: true, captchaTimeoutMs: 5000, responseTimeoutMs: 5000 });
  assert.equal(result.outcome, 'success');
  assert.equal(result.request.schoolId, '1098');
  assert.deepEqual(result.request.ratings, ['5','5','5','5','5','5','5','5']);
  await f.page.locator('#result[data-code="1"]').waitFor();
  const state = await (await f.page.request.get(`${f.origin}/api/state`)).json();
  assert.equal(state.accepted, 1);
  assert.equal(state.requests, 1);
  assert.equal(state.totalStars, 40);
  assert.deepEqual(f.blocked, []);
});

test('existing API transport works against the local page without a submit button click', async t => {
  const f = await fixture(t);
  const result = await runVote(f.page, { submit: true, transport: 'api', captchaTimeoutMs: 5000, responseTimeoutMs: 5000 });
  assert.equal(result.outcome, 'success');
  assert.equal(await f.page.locator('#result').textContent(), '');
  const state = await (await f.page.request.get(`${f.origin}/api/state`)).json();
  assert.equal(state.accepted, 1);
  assert.equal(state.requests, 1);
  assert.deepEqual(f.blocked, []);
});
