import { mkdir, writeFile } from 'node:fs/promises';
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';
import { runLocalLoad } from './load.mjs';

try {
  const { values } = parseArgs({ options: {
    port: { type: 'string', default: '3000' },
  } });
  // Uses Node fetch only. The shared runner requires the loopback mock lab.
  const result = await runLocalLoad({ port: Number(values.port), count: 1, concurrency: 1 });
  const report = { transport: 'http', browserUsed: false, ...result };
  const directory = new URL('../runtime/lab/', import.meta.url);
  await mkdir(directory, { recursive: true });
  const output = new URL('vote-http.json', directory);
  await writeFile(output, `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify(report, null, 2));
  console.log(`Report: ${fileURLToPath(output)}`);
  if (report.success !== 1 || report.errors || !report.countersMatch) process.exitCode = 1;
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
