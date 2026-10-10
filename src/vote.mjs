export const SCHOOL_URL = 'https://treemvietnam.net.vn/truong-hoc-hanh-phuc/truong-tieu-hoc-thinh-liet-1098.html';
const VOTE_PATH = '/truong-hoc-hanh-phuc/vote';
const DAY_MS = 24 * 60 * 60 * 1000;

export function submissionBlock(record, now = Date.now()) {
  if (!record) return null;
  const attempted = Date.parse(record.attemptedAt);
  const known = ['pending', 'success', 'quota', 'unknown', 'phone-required', 'captcha-rejected'];
  if (!Number.isFinite(attempted) || !known.includes(record.outcome)) return 'invalid-state';
  if (['phone-required', 'captcha-rejected'].includes(record.outcome)) return null;
  return now < attempted + DAY_MS ? 'wait-24-hours' : null;
}

function classify(status, body) {
  // A 500 response may follow a committed vote. Never infer success or retry.
  if (status !== 200) return { outcome: 'unknown', reason: 'http-error' };
  return {
    '1': { outcome: 'success' },
    '0': { outcome: 'quota' },
    '2': { outcome: 'phone-required' },
    '3': { outcome: 'captcha-rejected' },
  }[body.trim()] ?? { outcome: 'unknown', reason: 'unexpected-response' };
}

async function readForm(popup) {
  return popup.evaluate(el => ({
    schoolId: el.querySelector('#btn-confirm-vote')?.getAttribute('data-thhp_id') ?? null,
    remaining: el.querySelector('#err-max-vote')?.textContent.trim() ?? null,
    ratings: [...el.querySelectorAll('select.rating')].map(s => s.value),
    captchaPresent: Boolean(el.querySelector('[name="cf-turnstile-response"]')?.value),
  }));
}

async function postVoteApi(page, captcha, timeoutMs) {
  const origin = new URL(page.url()).origin;
  const url = `${origin}${VOTE_PATH}`;
  const ratings = ['5', '5', '5', '5', '5', '5', '5', '5'];
  const data = new URLSearchParams({ thhp_id: '1098', captcha });
  for (const rating of ratings) data.append('rating[]', rating);
  const request = { method: 'POST', url, schoolId: '1098', ratings, captchaPresent: true };
  let response;
  try {
    // This is a direct HTTP request from Node. The request context shares only
    // the dedicated Chrome profile's cookies; no personal profile is read.
    response = await page.context().request.post(url, {
      data: data.toString(),
      headers: { 'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        origin, referer: page.url(), 'x-requested-with': 'XMLHttpRequest' },
      timeout: timeoutMs, maxRetries: 0, maxRedirects: 0, failOnStatusCode: false,
    });
    const status = response.status();
    const body = await response.text();
    const value = body.trim();
    return { ...classify(status, body), request, response: {
      status, code: ['0', '1', '2', '3'].includes(value) ? value : null, bodyLength: body.length,
    } };
  } catch {
    return { outcome: 'unknown', reason: 'api-request-failed-or-timeout', request };
  } finally {
    await response?.dispose().catch(() => {});
  }
}

// Observe only this page's voting endpoint. Never return headers, cookies,
// raw request bodies, CAPTCHA tokens, or unrecognized response text.
function observeVote(page, timeoutMs) {
  const origin = new URL(page.url()).origin;
  let metadata;
  let settled = false;
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  const matches = request => {
    const url = new URL(request.url());
    return request.method() === 'POST' && url.origin === origin && url.pathname === VOTE_PATH;
  };
  const finish = result => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    page.off('request', onRequest);
    page.off('response', onResponse);
    page.off('requestfailed', onFailed);
    page.off('close', onClose);
    resolve({ ...result, request: metadata ?? null });
  };
  const onRequest = request => {
    if (!matches(request)) return;
    const data = new URLSearchParams(request.postData() ?? '');
    metadata = { method: 'POST', url: `${origin}${VOTE_PATH}`,
      schoolId: data.get('thhp_id'), ratings: data.getAll('rating[]'),
      captchaPresent: Boolean(data.get('captcha')) };
  };
  const onResponse = async response => {
    if (!matches(response.request())) return;
    try {
      const status = response.status();
      const body = await response.text();
      const value = body.trim();
      finish({ ...classify(status, body), response: {
        status, code: ['0', '1', '2', '3'].includes(value) ? value : null,
        bodyLength: body.length,
      } });
    } catch {
      finish({ outcome: 'unknown', reason: 'response-unreadable' });
    }
  };
  const onFailed = request => {
    if (matches(request)) finish({ outcome: 'unknown', reason: 'request-failed' });
  };
  const onClose = () => finish({ outcome: 'unknown', reason: 'page-closed' });
  const timer = setTimeout(() => finish({ outcome: 'unknown', reason: 'response-timeout' }), timeoutMs);
  page.on('request', onRequest);
  page.on('response', onResponse);
  page.on('requestfailed', onFailed);
  page.on('close', onClose);
  return { promise, cancel: () => finish({ outcome: 'unknown', reason: 'submit-interrupted' }) };
}

export async function runVote(page, {
  submit = false, captchaTimeoutMs = 180_000, responseTimeoutMs = 45_000,
  beforeSubmit = async () => {}, onEvent = () => {}, transport = 'page',
} = {}) {
  if (!['page', 'api'].includes(transport)) throw new Error('Unsupported transport');
  const api = transport === 'api';
  // Alerts are informational in the observed workflow. Dismiss other dialogs.
  const dialogHandler = dialog => {
    const action = dialog.type() === 'alert' ? dialog.accept() : dialog.dismiss();
    action.catch(() => {});
  };
  page.on('dialog', dialogHandler);
  const popup = page.locator('#vote-popup');
  try {
    onEvent('opening-form');
    await page.locator('.btn-vote[data-thhp_id="1098"]').first().click();
    await popup.waitFor({ state: 'visible' });
    const initial = await readForm(popup);
    const rows = popup.locator('.rating-wrapper');
    if (initial.schoolId !== '1098' || initial.ratings.length !== 8 || await rows.count() !== 8) {
      return { outcome: 'form-changed', form: initial };
    }
    if (!/^\d+$/.test(initial.remaining)) return { outcome: 'form-changed', form: initial };
    if (Number(initial.remaining) === 0) return { outcome: 'quota', form: initial };

    if (api) {
      if (await popup.locator('select.rating option[value="5"]').count() !== 8) {
        return { outcome: 'form-changed', form: initial };
      }
    } else {
      for (let i = 0; i < 8; i++) {
        const star = rows.nth(i).locator('a[data-rating-value="5"]');
        if (await star.count() !== 1) return { outcome: 'form-changed', form: await readForm(popup) };
        await star.click();
      }
    }
    const selected = await readForm(popup);
    if (!api && selected.ratings.some(r => r !== '5')) return { outcome: 'form-changed', form: selected };
    if (!submit) return { outcome: 'inspected', transport, form: selected };

    onEvent('waiting-for-captcha');
    try {
      await page.waitForFunction(() => Boolean(document.querySelector(
        '#vote-popup [name="cf-turnstile-response"]')?.value), null, { timeout: captchaTimeoutMs });
    } catch {
      return { outcome: 'captcha-timeout', form: await readForm(popup) };
    }
    const ready = await readForm(popup);
    if (ready.schoolId !== '1098' || ready.ratings.length !== 8 || (!api && ready.ratings.some(r => r !== '5'))
      || !/^\d+$/.test(ready.remaining)) {
      return { outcome: 'form-changed', form: ready };
    }
    if (Number(ready.remaining) === 0) return { outcome: 'quota', form: ready };

    const captcha = api ? await popup.locator('[name="cf-turnstile-response"]').inputValue() : null;
    if (api && !captcha) return { outcome: 'captcha-timeout', form: ready };

    // Persist before the click, so an interrupted process cannot silently retry.
    await beforeSubmit();
    if (api) {
      onEvent('posting-api-once');
      return { transport, form: ready, ...await postVoteApi(page, captcha, responseTimeoutMs) };
    }
    const observer = observeVote(page, responseTimeoutMs);
    onEvent('submitting-once');
    try {
      await popup.locator('#btn-confirm-vote').click({ timeout: 10_000 });
    } catch {
      observer.cancel();
    }
    return { transport, form: ready, ...await observer.promise };
  } finally {
    page.off('dialog', dialogHandler);
  }
}
