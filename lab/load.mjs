import { performance } from 'node:perf_hooks';
import { mkdir, writeFile } from 'node:fs/promises';
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export async function runLocalLoad({ port = 3000, count = 10000, concurrency = 20, onProgress = () => {} } = {}) {
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('port must be a local numeric port');
  if (!Number.isInteger(count) || count < 1 || count > 10000) throw new Error('count must be between 1 and 10000');
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 50) throw new Error('concurrency must be between 1 and 50');
  // No arbitrary URL parameter: this runner can only address the loopback lab.
  const origin = `http://127.0.0.1:${port}`;
  const get = (pathname, options = {}) => fetch(`${origin}${pathname}`, {
    ...options, redirect: 'error', signal: AbortSignal.timeout(10000),
  });
  const initialResponse = await get('/api/state');
  const initial = await initialResponse.json();
  if (initial.labId !== 'local-vote-lab-v1' || initial.scenario !== 'open' || initial.captchaMode !== 'mock') {
    throw new Error('Load testing requires this lab in open + mock mode');
  }
  const cookie = initialResponse.headers.get('set-cookie')?.split(';')[0];
  if (!cookie) throw new Error('The lab did not establish a test session');
  let next = 0;
  let completed = 0;
  let success = 0;
  let errors = 0;
  const codes = {};
  const latencies = [];
  const started = performance.now();
  async function worker() {
    while (next < count) {
      next++;
      const start = performance.now();
      try {
        const response = await get('/api/test-token', { method: 'POST', headers: { cookie } });
        if (!response.ok) throw new Error('Local token issue failed');
        const { token } = await response.json();
        const body = new URLSearchParams({ thhp_id: '1098', captcha: token });
        for (let i = 0; i < 8; i++) body.append('rating[]', '5');
        const vote = await get('/truong-hoc-hanh-phuc/vote', { method: 'POST', body, headers: { cookie } });
        const result = (await vote.text()).trim();
        const code = `${vote.status}:${['0','1','2','3'].includes(result) ? result : 'other'}`;
        codes[code] = (codes[code] ?? 0) + 1;
        if (vote.status === 200 && result === '1') success++; else errors++;
      } catch {
        errors++; codes['network-error'] = (codes['network-error'] ?? 0) + 1;
      }
      latencies.push(performance.now() - start);
      completed++;
      if (completed % 1000 === 0 || completed === count) onProgress({ completed, success, errors });
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, count) }, worker));
  const elapsedMs = performance.now() - started;
  const end = await (await get('/api/state', { headers: { cookie } })).json();
  latencies.sort((a, b) => a - b);
  const percentile = p => Number(latencies[Math.min(latencies.length - 1, Math.floor(latencies.length * p))].toFixed(2));
  const report = {
    timestamp: new Date().toISOString(), target: origin, captchaMode: 'mock',
    attempted: completed, success, errors, codes, concurrency,
    elapsedSeconds: Number((elapsedMs / 1000).toFixed(3)),
    votesPerSecond: Number((completed * 1000 / elapsedMs).toFixed(2)),
    workflowLatencyMs: { p50: percentile(0.5), p95: percentile(0.95) },
    serverAcceptedDelta: end.accepted - initial.accepted,
    serverStarsDelta: end.totalStars - initial.totalStars,
  };
  report.countersMatch = report.serverAcceptedDelta === success && report.serverStarsDelta === success * 40;
  return report;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { values } = parseArgs({ options: {
    port: { type: 'string', default: '3000' }, count: { type: 'string', default: '10000' },
    concurrency: { type: 'string', default: '20' },
  } });
  try {
    const report = await runLocalLoad({ port: Number(values.port), count: Number(values.count),
      concurrency: Number(values.concurrency), onProgress: p => console.log(`${p.completed}: ${p.success} success, ${p.errors} errors`) });
    const reportsDir = new URL('../runtime/lab/', import.meta.url);
    await mkdir(reportsDir, { recursive: true });
    const output = new URL('load-report.json', reportsDir);
    await writeFile(output, `${JSON.stringify(report, null, 2)}\n`);
    console.log(JSON.stringify(report, null, 2));
    console.log(`Report: ${fileURLToPath(output)}`);
    if (report.errors || !report.countersMatch) process.exitCode = 1;
  } catch (error) {
    console.error(error.message); process.exitCode = 1;
  }
}
