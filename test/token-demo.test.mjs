import assert from 'node:assert/strict';
import { test } from 'node:test';
import { request } from 'node:http';
import { createTokenDemo } from '../lab/token-demo.mjs';

async function fixture(t) {
  const demo = createTokenDemo();
  await new Promise(resolve => demo.server.listen(0, '127.0.0.1', resolve));
  t.after(() => demo.close());
  return `http://127.0.0.1:${demo.server.address().port}`;
}

test('health identifies test mode without starting a browser', async t => {
  const origin = await fixture(t);
  const response = await fetch(`${origin}/health`);
  const data = await response.json();
  assert.equal(response.status, 200);
  assert.equal(data.mode, 'cloudflare-test');
  assert.equal(data.headless, true);
  assert.equal(data.browserLaunches, 0);
});

test('API rejects custom targets and keys before starting a browser', async t => {
  const origin = await fixture(t);
  for (const payload of [{ url: 'https://example.com' }, { sitekey: 'custom-key' }]) {
    const response = await fetch(`${origin}/api/token`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error, 'test-demo-accepts-no-parameters');
  }
  assert.equal((await (await fetch(`${origin}/health`)).json()).browserLaunches, 0);
});

test('API rejects query parameters and malformed JSON', async t => {
  const origin = await fixture(t);
  const query = await fetch(`${origin}/api/token?url=https://example.com`, { method: 'POST' });
  assert.equal(query.status, 400);
  const malformed = await fetch(`${origin}/api/token`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: '{',
  });
  assert.equal(malformed.status, 400);
  assert.equal((await malformed.json()).error, 'invalid-json');
});

test('API rejects oversized bodies', async t => {
  const origin = await fixture(t);
  const response = await fetch(`${origin}/api/token`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: ' '.repeat(2048),
  });
  assert.equal(response.status, 413);
});

test('API rejects foreign origins and hostnames', async t => {
  const origin = await fixture(t);
  const foreignOrigin = await fetch(`${origin}/api/token`, {
    method: 'POST', headers: { origin: 'https://example.com' },
  });
  assert.equal(foreignOrigin.status, 403);
  // Node fetch replaces Host with the URL authority; http.request sends it literally.
  const foreignHostStatus = await new Promise((resolve, reject) => {
    const req = request(`${origin}/health`, { headers: { host: 'example.com' } }, res => {
      res.resume();
      res.on('end', () => resolve(res.statusCode));
    });
    req.on('error', reject);
    req.end();
  });
  assert.equal(foreignHostStatus, 403);
});
