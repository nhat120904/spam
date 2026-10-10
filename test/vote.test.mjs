import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createServer } from 'node:http';
import { chromium } from 'playwright-core';
import { runVote, submissionBlock } from '../src/vote.mjs';

let browser;
before(async () => { browser = await chromium.launch({ channel: 'chrome', headless: true }); });
after(async () => { await browser?.close(); });

// Local fixture exercises real DOM clicks, form encoding and browser networking.
// It never calls the public voting site or a CAPTCHA provider.
async function fixture(t, { status = 200, body = '1', quota = 1, captcha = true,
  criteria = 8, hang = false, wrongSchool = false, quotaAfterSelection = null } = {}) {
  const requests = [];
  const rows = Array.from({ length: criteria }, (_, i) => `
    <div class="rating-wrapper"><select class="rating" name="rating_type_${i + 1}" style="display:none">
      ${[1,2,3,4,5].map(n => `<option value="${n}">${n}</option>`).join('')}
    </select>${[1,2,3,4,5].map(n => `<a href="#" data-rating-value="${n}">${n} sao</a>`).join('')}</div>`).join('');
  const server = createServer(async (req, res) => {
    if (req.method === 'POST') {
      let raw = '';
      for await (const part of req) raw += part;
      const form = new URLSearchParams(raw);
      requests.push({ school: form.get('thhp_id'), ratings: form.getAll('rating[]'), captcha: form.get('captcha'), cookie: req.headers.cookie });
      if (!hang) { res.writeHead(status, { 'Content-Type': 'text/plain' }); res.end(body); }
      return;
    }
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.setHeader('Set-Cookie', 'fixture-session=present; Path=/');
    res.end(`<!doctype html><button class="btn-vote" data-thhp_id="1098">Bình chọn</button>
      <div id="vote-popup" style="display:none">${rows}
      <strong id="err-max-vote">${quota}</strong>
      <input name="cf-turnstile-response" type="hidden" value="${captcha ? 'local-fixture-only' : ''}">
      <a id="btn-confirm-vote" href="#" data-thhp_id="${wrongSchool ? '999' : '1098'}">Bình chọn ngay</a></div>
      <script>
      window.submitClicks = 0;
      document.querySelector('.btn-vote').onclick = () => document.querySelector('#vote-popup').style.display='block';
      document.querySelectorAll('[data-rating-value]').forEach(a => a.onclick = e => {
        e.preventDefault(); a.closest('.rating-wrapper').querySelector('select').value = a.dataset.ratingValue;
        if (${JSON.stringify(quotaAfterSelection)} !== null && [...document.querySelectorAll('select.rating')].every(s => s.value === '5')) {
          document.querySelector('#err-max-vote').textContent = ${JSON.stringify(quotaAfterSelection)};
        }
      });
      document.querySelector('#btn-confirm-vote').onclick = async e => {
        e.preventDefault();
        window.submitClicks++;
        const p = new URLSearchParams({thhp_id: document.querySelector('#btn-confirm-vote').dataset.thhp_id,
          captcha: document.querySelector('[name="cf-turnstile-response"]').value});
        document.querySelectorAll('select.rating').forEach(s => p.append('rating[]',s.value));
        const r = await fetch('/truong-hoc-hanh-phuc/vote', {method:'POST',body:p});
        const b = await r.text(); if (b === '3') alert('Vui lòng xác minh mã Captcha!');
      };
      </script>`);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const page = await browser.newPage();
  t.after(async () => {
    await page.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  await page.goto(origin);
  const run = (opts = {}) => runVote(page, { submit: true, captchaTimeoutMs: 300,
    responseTimeoutMs: 1000, ...opts });
  return { page, requests, run };
}

test('inspect selects all eight ratings without sending a POST', async t => {
  const f = await fixture(t);
  const r = await f.run({ submit: false });
  assert.equal(r.outcome, 'inspected');
  assert.deepEqual(r.form.ratings, ['5','5','5','5','5','5','5','5']);
  assert.equal(f.requests.length, 0);
});

test('success sends one correctly encoded vote and never exposes the CAPTCHA token', async t => {
  const f = await fixture(t);
  let recorded = false;
  const r = await f.run({ beforeSubmit: async () => { recorded = true; assert.equal(f.requests.length, 0); } });
  assert.equal(recorded, true);
  assert.equal(r.outcome, 'success');
  assert.equal(f.requests.length, 1);
  assert.deepEqual(f.requests[0], { school: '1098', ratings: ['5','5','5','5','5','5','5','5'], captcha: 'local-fixture-only', cookie: 'fixture-session=present' });
  assert.equal(r.request.captchaPresent, true);
  assert.equal(JSON.stringify(r).includes('local-fixture-only'), false);
});

test('direct API sends one form POST with session cookies, without clicking stars or the submit button', async t => {
  const f = await fixture(t);
  const r = await f.run({ transport: 'api' });
  assert.equal(r.outcome, 'success');
  assert.equal(await f.page.evaluate(() => window.submitClicks), 0);
  assert.deepEqual(await f.page.locator('select.rating').evaluateAll(ss => ss.map(s => s.value)), ['1','1','1','1','1','1','1','1']);
  assert.equal(f.requests.length, 1);
  assert.deepEqual(f.requests[0], { school: '1098', ratings: ['5','5','5','5','5','5','5','5'], captcha: 'local-fixture-only', cookie: 'fixture-session=present' });
  assert.equal(JSON.stringify(r).includes('local-fixture-only'), false);
  assert.equal(JSON.stringify(r).includes('fixture-session'), false);
});

for (const options of [{ status: 500 }, { body: '3' }, { hang: true }]) {
  test(`direct API ${JSON.stringify(options)} never retries`, async t => {
    const f = await fixture(t, options);
    const r = await f.run({ transport: 'api', responseTimeoutMs: 300 });
    assert.equal(r.outcome, options.body === '3' ? 'captcha-rejected' : 'unknown');
    assert.equal(await f.page.evaluate(() => window.submitClicks), 0);
    assert.equal(f.requests.length, 1);
  });
}

test('direct API without a CAPTCHA stops before making any request', async t => {
  const f = await fixture(t, { captcha: false });
  assert.equal((await f.run({ transport: 'api' })).outcome, 'captcha-timeout');
  assert.equal(f.requests.length, 0);
});

test('quota zero stops before any submission', async t => {
  const f = await fixture(t, { quota: 0 });
  assert.equal((await f.run()).outcome, 'quota');
  assert.equal(f.requests.length, 0);
});

test('quota becomes unreadable after rating selection: stop before submitting', async t => {
  const f = await fixture(t, { quotaAfterSelection: 'unavailable' });
  assert.equal((await f.run()).outcome, 'form-changed');
  assert.equal(f.requests.length, 0);
});

for (const [body, outcome] of [['0', 'quota'], ['2', 'phone-required'], ['3', 'captcha-rejected']]) {
  test(`API ${body} reports ${outcome} without resubmitting`, async t => {
    const f = await fixture(t, { body });
    assert.equal((await f.run()).outcome, outcome);
    assert.equal(f.requests.length, 1);
  });
}

test('HTTP 500 is uncertain even if the response body says 1; no retry', async t => {
  const f = await fixture(t, { status: 500, body: '1' });
  const r = await f.run();
  assert.equal(r.outcome, 'unknown');
  assert.equal(r.response.status, 500);
  assert.equal(f.requests.length, 1);
});

test('unexpected response is not treated as success or logged verbatim', async t => {
  const f = await fixture(t, { body: 'private-server-message' });
  const r = await f.run();
  assert.equal(r.outcome, 'unknown');
  assert.equal(JSON.stringify(r).includes('private-server-message'), false);
});

test('missing CAPTCHA stops without submitting', async t => {
  const f = await fixture(t, { captcha: false });
  assert.equal((await f.run()).outcome, 'captcha-timeout');
  assert.equal(f.requests.length, 0);
});

test('response timeout sends at most once and reports an uncertain outcome', async t => {
  const f = await fixture(t, { hang: true });
  assert.equal((await f.run({ responseTimeoutMs: 300 })).outcome, 'unknown');
  assert.equal(f.requests.length, 1);
});

for (const options of [{ criteria: 7 }, { wrongSchool: true }]) {
  test(`changed form ${JSON.stringify(options)} stops before submission`, async t => {
    const f = await fixture(t, options);
    assert.equal((await f.run()).outcome, 'form-changed');
    assert.equal(f.requests.length, 0);
  });
}

test('pending, accepted, quota and uncertain attempts block resubmission for 24 hours', () => {
  const now = Date.parse('2026-10-08T05:00:00Z');
  for (const outcome of ['pending', 'success', 'quota', 'unknown']) {
    const record = { attemptedAt: new Date(now).toISOString(), outcome };
    assert.ok(submissionBlock(record, now + 23 * 3600_000));
    assert.equal(submissionBlock(record, now + 24 * 3600_000), null);
  }
  assert.equal(submissionBlock({ attemptedAt: new Date(now).toISOString(), outcome: 'captcha-rejected' }, now), null);
  assert.equal(submissionBlock({ attemptedAt: 'invalid', outcome: 'pending' }, now), 'invalid-state');
});
