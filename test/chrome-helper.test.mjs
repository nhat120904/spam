import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { before, after, test } from 'node:test';
import { chromium } from 'playwright-core';
import { SCHOOL_URL } from '../src/vote.mjs';

let browser;
before(async () => { browser = await chromium.launch({ channel: 'chrome', headless: true }); });
after(async () => { await browser?.close(); });

// Every URL is intercepted and fulfilled locally; no public site is contacted.
async function fixture(t, { school = '1098', criteria = 8, quota = 1, delay = 0,
  url = SCHOOL_URL } = {}) {
  const html = await readFile(new URL('../chrome-helper.html', import.meta.url), 'utf8')
    .catch(error => { if (error.code === 'ENOENT') return null; throw error; });
  assert.ok(html, 'The Chrome helper installer must exist');
  const page = await browser.newPage();
  t.after(() => page.close());
  const alerts = [];
  page.on('dialog', async dialog => { alerts.push(dialog.message()); await dialog.dismiss(); });
  await page.setContent(html);
  const bookmarklet = await page.locator('#prepare-bookmark').getAttribute('href');
  assert.ok(bookmarklet.startsWith('javascript:'), 'The installer must generate a bookmarklet');
  const requests = [];
  await page.route('**/*', async route => {
    const request = route.request();
    requests.push({ method: request.method(), url: request.url() });
    if (request.url() !== url || request.method() !== 'GET') return route.abort();
    const rows = Array.from({ length: criteria }, () => `<div class="rating-wrapper">
      <select class="rating"><option value="1">1</option><option value="5">5</option></select>
      <a href="#" data-rating-value="5">5 sao</a></div>`).join('');
    await route.fulfill({ contentType: 'text/html; charset=utf-8', body: `<!doctype html>
      <button class="btn-vote" data-thhp_id="1098">Bình chọn</button>
      <div id="vote-popup" style="display:none">${rows}
        <span id="err-max-vote">${quota}</span>
        <input name="cf-turnstile-response" value="unchanged-human-captcha">
        <button id="btn-confirm-vote" data-thhp_id="${school}">Bình chọn ngay</button>
      </div><script>
        window.submitClicks = 0;
        document.querySelector('.btn-vote').onclick = () => setTimeout(() => {
          document.querySelector('#vote-popup').style.display = 'block';
        }, ${delay});
        document.querySelectorAll('[data-rating-value]').forEach(star => {
          star.onclick = event => { event.preventDefault();
            star.closest('.rating-wrapper').querySelector('select').value = '5'; };
        });
        document.querySelector('#btn-confirm-vote').onclick = () => {
          window.submitClicks++; fetch('/truong-hoc-hanh-phuc/vote', { method: 'POST' });
        };
      </script>` });
  });
  await page.goto(url);
  const run = async () => {
    await page.evaluate(decodeURIComponent(bookmarklet.slice('javascript:'.length)));
    assert.equal(await page.evaluate(() => window.submitClicks), 0, 'User must submit manually');
    assert.equal(await page.locator('[name="cf-turnstile-response"]').inputValue(),
      'unchanged-human-captcha', 'CAPTCHA must remain untouched');
    assert.deepEqual(requests, [{ method: 'GET', url }], 'No extra network requests are allowed');
    return { alerts, ratings: await page.locator('select.rating').evaluateAll(ss => ss.map(s => s.value)) };
  };
  return { run };
}

test('bookmarklet fills eight ratings after an asynchronous popup, leaving CAPTCHA and submission to the user', async t => {
  const f = await fixture(t, { delay: 100 });
  const result = await f.run();
  assert.deepEqual(result.ratings, Array(8).fill('5'));
  assert.match(result.alerts[0], /Đã chọn 5 sao/);
});

for (const options of [{ school: '999' }, { criteria: 7 }, { quota: 0 }]) {
  test(`bookmarklet leaves ratings unchanged for ${JSON.stringify(options)}`, async t => {
    const f = await fixture(t, options);
    const result = await f.run();
    assert.deepEqual(result.ratings, Array(options.criteria ?? 8).fill('1'));
    assert.equal(result.alerts.length, 1);
    assert.doesNotMatch(result.alerts[0], /Đã chọn 5 sao/);
  });
}

test('bookmarklet refuses a different website before touching its form', async t => {
  const f = await fixture(t, { url: 'https://example.test/school' });
  const result = await f.run();
  assert.deepEqual(result.ratings, Array(8).fill('1'));
  assert.match(result.alerts[0], /trang Trường Tiểu học Thịnh Liệt/);
});
