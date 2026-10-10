#!/usr/bin/env node
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { chromium } from 'playwright-core';
import { runVote, submissionBlock, SCHOOL_URL } from './src/vote.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
const runtime = path.join(root, 'runtime');
const statePath = path.join(runtime, 'last-attempt.json');

const messages = {
  inspected: 'Đã chọn 5 sao cho 8 tiêu chí. Chế độ kiểm tra không bấm gửi.',
  success: 'API trả mã 1: bình chọn thành công.',
  quota: 'Đã hết lượt bình chọn. Dừng gửi.',
  'phone-required': 'API trả mã 2: trang yêu cầu cập nhật số điện thoại. Hoàn tất trên trang rồi chạy lại.',
  'captcha-rejected': 'API trả mã 3: CAPTCHA bị từ chối. Chưa xác nhận bình chọn thành công.',
  'captcha-timeout': 'Chưa có CAPTCHA hợp lệ trong thời gian chờ. Không bấm gửi.',
  'form-changed': 'Biểu mẫu không khớp với mã trường hoặc 8 tiêu chí đã kiểm tra. Không bấm gửi.',
  unknown: 'Chưa rõ máy chủ đã ghi nhận lượt hay chưa. Không tự gửi lại; chặn gửi trong 24 giờ.',
  error: 'Không hoàn tất kiểm tra/gửi. Xem thông báo lỗi và báo cáo.',
};

function seconds(value, label, max) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 1 || number > max) throw new Error(`${label} phải từ 1 đến ${max} giây.`);
  return number * 1000;
}

async function writeState(record) {
  const temp = `${statePath}.${process.pid}.tmp`;
  await writeFile(temp, `${JSON.stringify(record, null, 2)}\n`, { mode: 0o600 });
  await rename(temp, statePath);
}

async function main() {
  const { values } = parseArgs({ options: {
    submit: { type: 'boolean', default: false },
    api: { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'h', default: false },
    'captcha-timeout': { type: 'string', default: '180' },
    'response-timeout': { type: 'string', default: '45' },
  } });
  if (values.help) {
    console.log(`Bình chọn Thịnh Liệt — Chrome, một lượt mỗi lần chạy

  node vote.mjs                  Kiểm tra biểu mẫu, không gửi
  node vote.mjs --submit         Chọn 5 sao và gửi một lượt
  node vote.mjs --submit --api   POST trực tiếp API sau khi xác minh CAPTCHA
  --captcha-timeout 180          Thời gian chờ CAPTCHA (1–300 giây)
  --response-timeout 45          Thời gian chờ API (1–120 giây)

Chrome dùng hồ sơ riêng tại runtime/chrome-profile.
Nếu CAPTCHA yêu cầu tương tác, hãy tự xác minh trong cửa sổ Chrome.
Chỉ xác minh CAPTCHA; script sẽ tự gửi, không tự bấm nút bình chọn.
Báo cáo và ảnh nằm tại runtime/reports. Không tự gửi lại khi lỗi.
Sau thành công, hết lượt hoặc kết quả chưa rõ: đợi 24 giờ.
Không có chế độ tạo 10.000 phiếu hoặc vượt giới hạn của trang.`);
    return;
  }
  const captchaTimeoutMs = seconds(values['captcha-timeout'], '--captcha-timeout', 300);
  const responseTimeoutMs = seconds(values['response-timeout'], '--response-timeout', 120);
  await mkdir(runtime, { recursive: true, mode: 0o700 });
  if (values.submit) {
    let last;
    try { last = JSON.parse(await readFile(statePath, 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') throw new Error('Không đọc được trạng thái lần gửi trước. Dừng để tránh gửi trùng.'); }
    const block = submissionBlock(last);
    if (block === 'invalid-state') throw new Error('Trạng thái lần gửi trước không hợp lệ. Dừng để tránh gửi trùng.');
    if (block) {
      const next = new Date(Date.parse(last.attemptedAt) + 24 * 3600_000);
      console.log(`Lần gửi trước: ${last.outcome}. Có thể gửi lại sau ${next.toLocaleString('vi-VN')} (giờ máy tính).\nCó thể dùng npm run inspect để kiểm tra trang.`);
      process.exitCode = 2;
      return;
    }
  }

  let context;
  let page;
  let attempt;
  let report;
  let voteRequests = 0;
  let apiRequestAttempts = 0;
  const startedAt = new Date().toISOString();
  const stem = startedAt.replaceAll(':', '-').replaceAll('.', '-');
  const reportsDir = path.join(runtime, 'reports');
  await mkdir(reportsDir, { recursive: true, mode: 0o700 });
  const reportPath = path.join(reportsDir, `${stem}.json`);
  const screenshotPath = path.join(reportsDir, `${stem}.png`);
  try {
    console.log('Mở Google Chrome với hồ sơ riêng...');
    context = await chromium.launchPersistentContext(path.join(runtime, 'chrome-profile'), {
      channel: 'chrome', headless: false, locale: 'vi-VN',
      viewport: { width: 1280, height: 900 }, timeout: 30_000,
    });
    page = context.pages()[0] ?? await context.newPage();
    page.on('dialog', dialog => {
      const action = dialog.type() === 'alert' ? dialog.accept() : dialog.dismiss();
      action.catch(() => {});
    });
    page.on('request', request => {
      const url = new URL(request.url());
      if (request.method() === 'POST' && url.origin === new URL(SCHOOL_URL).origin
        && url.pathname === '/truong-hoc-hanh-phuc/vote') voteRequests++;
    });
    page.setDefaultTimeout(20_000);
    await page.goto(SCHOOL_URL, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    const result = await runVote(page, {
      submit: values.submit, captchaTimeoutMs, responseTimeoutMs, transport: values.api ? 'api' : 'page',
      beforeSubmit: async () => {
        attempt = { attemptedAt: new Date().toISOString(), outcome: 'pending' };
        await writeState(attempt);
        if (values.api) apiRequestAttempts++;
      },
      onEvent: event => {
        const text = {
          'opening-form': 'Mở biểu mẫu và kiểm tra trường 1098...',
          'waiting-for-captcha': 'Chờ CAPTCHA. Nếu trang yêu cầu, tự xác minh trong Chrome; không bấm nút bình chọn.',
          'submitting-once': 'Bấm gửi một lượt, đang chờ phản hồi API...',
          'posting-api-once': 'POST trực tiếp API một lần, đang chờ phản hồi...',
        }[event];
        if (text) console.log(text);
      },
    });
    report = { startedAt, finishedAt: new Date().toISOString(), mode: values.submit ? 'submit' : 'inspect',
      browser: 'Google Chrome', browserVersion: context.browser()?.version() ?? null,
      transport: values.api ? 'api' : 'page',
      page: SCHOOL_URL, ...result };
    if (attempt) await writeState({ ...attempt, outcome: result.outcome });
    else if (values.submit && result.outcome === 'quota') {
      await writeState({ attemptedAt: new Date().toISOString(), outcome: 'quota' });
    }
    console.log(result.outcome === 'inspected' && values.api
      ? 'Đã kiểm tra trường và 8 tiêu chí. Chế độ kiểm tra không POST API.'
      : messages[result.outcome] ?? messages.error);
    if (result.response) console.log(`HTTP ${result.response.status}; mã phản hồi: ${result.response.code ?? '(không nhận dạng)'}.`);
    if (result.reason) console.log(`Chi tiết: ${result.reason}.`);
    if (!['inspected', 'success'].includes(result.outcome)) process.exitCode = result.outcome === 'unknown' ? 4 : 2;
    if (result.outcome === 'success' && !values.api) {
      await page.locator('#vote-popup-success').waitFor({ state: 'visible', timeout: 2000 }).catch(() => {});
    }
  } catch (error) {
    report = { startedAt, finishedAt: new Date().toISOString(), mode: values.submit ? 'submit' : 'inspect',
      page: SCHOOL_URL, transport: values.api ? 'api' : 'page',
      outcome: attempt ? 'unknown' : 'error', reason: 'browser-or-page-error' };
    if (attempt) await writeState({ ...attempt, outcome: 'unknown' });
    console.error(String(error.message).split('\n')[0]);
    console.error(messages[report.outcome]);
    process.exitCode = attempt ? 4 : 2;
  } finally {
    if (page && !page.isClosed()) {
      try {
        await page.screenshot({ path: screenshotPath, timeout: 5000 });
        report.screenshot = screenshotPath;
      } catch { /* A closed/crashed browser still gets a JSON report. */ }
    }
    if (context) await context.close().catch(() => {});
    if (report) {
      report.voteRequestAttempts = voteRequests + apiRequestAttempts;
      await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
      console.log(`Báo cáo: ${reportPath}`);
    }
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 2; });
