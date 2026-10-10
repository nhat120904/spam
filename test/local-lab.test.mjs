import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createLabServer } from '../lab/server.mjs';
import { runLocalLoad } from '../lab/load.mjs';

async function lab(t) {
  const server = createLabServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  const port = server.address().port;
  const origin = `http://127.0.0.1:${port}`;
  const first = await fetch(`${origin}/api/state`);
  const cookie = first.headers.get('set-cookie').split(';')[0];
  const request = (pathname, options = {}) => fetch(`${origin}${pathname}`, {
    ...options, headers: { cookie, ...options.headers }, redirect: 'error',
  });
  const token = async () => (await (await request('/api/test-token', { method: 'POST' })).json()).token;
  const vote = async (captcha, { school = '1098', ratings = ['5','5','5','5','5','5','5','5'] } = {}) => {
    const body = new URLSearchParams({ thhp_id: school, captcha });
    ratings.forEach(rating => body.append('rating[]', rating));
    return request('/truong-hoc-hanh-phuc/vote', { method: 'POST', body });
  };
  const scenario = value => request('/api/scenario', { method: 'POST',
    headers: { 'content-type': 'application/json' }, body: JSON.stringify({ scenario: value }) });
  const state = async () => (await request('/api/state')).json();
  return { server, origin, port, request, token, vote, scenario, state };
}

test('local API records eight scores and rejects a reused mock token', async t => {
  const f = await lab(t);
  const token = await f.token();
  assert.equal(await (await f.vote(token)).text(), '1');
  assert.equal(await (await f.vote(token)).text(), '3');
  const state = await f.state();
  assert.equal(state.accepted, 1);
  assert.equal(state.totalStars, 40);
  assert.deepEqual(state.criteriaTotals, [5,5,5,5,5,5,5,5]);
});

test('local API rejects missing CAPTCHA and malformed ballots without incrementing totals', async t => {
  const f = await lab(t);
  assert.equal(await (await f.vote('')).text(), '3');
  assert.equal((await f.vote(await f.token(), { school: '999' })).status, 400);
  assert.equal((await f.vote(await f.token(), { ratings: ['5'] })).status, 400);
  assert.equal((await f.state()).accepted, 0);
});

test('quota scenario permits one vote per fixed session, then returns 0', async t => {
  const f = await lab(t);
  await f.scenario('quota');
  assert.equal(await (await f.vote(await f.token())).text(), '1');
  assert.equal(await (await f.vote(await f.token())).text(), '0');
  assert.equal((await f.state()).accepted, 1);
});

for (const [scenario, status, body] of [['phone', 200, '2'], ['captcha', 200, '3'], ['server-error', 500, '']]) {
  test(`local scenario ${scenario} returns HTTP ${status} and body ${JSON.stringify(body)}`, async t => {
    const f = await lab(t);
    await f.scenario(scenario);
    const response = await f.vote(await f.token());
    assert.equal(response.status, status);
    assert.equal(await response.text(), body);
    assert.equal((await f.state()).accepted, 0);
  });
}

test('load runner sends exactly 100 local ballots and verifies the server counter', async t => {
  const f = await lab(t);
  const report = await runLocalLoad({ port: f.port, count: 100, concurrency: 4 });
  assert.equal(report.attempted, 100);
  assert.equal(report.success, 100);
  assert.equal(report.errors, 0);
  assert.equal(report.serverAcceptedDelta, 100);
  assert.equal(report.serverStarsDelta, 4000);
  assert.equal((await f.state()).accepted, 100);
});

test('load runner stops before posting if the lab is in quota mode', async t => {
  const f = await lab(t);
  await f.scenario('quota');
  await assert.rejects(runLocalLoad({ port: f.port, count: 10 }), /open.*mock/);
  assert.equal((await f.state()).requests, 0);
});

test('load runner only accepts a local numeric port and a bounded request count', async () => {
  await assert.rejects(runLocalLoad({ port: 'https://example.com', count: 10 }), /port/);
  await assert.rejects(runLocalLoad({ port: 3000, count: 10001 }), /count/);
  await assert.rejects(runLocalLoad({ port: 3000, count: 10, concurrency: 0 }), /concurrency/);
});
