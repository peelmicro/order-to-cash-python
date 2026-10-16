// Generates — and drift-checks — the ONE file this app takes wire shapes from:
// src/generated/openapi.ts, derived from specs/shared/openapi.yaml.
//
//   node scripts/openapi-types.mjs generate   # rewrite the committed file
//   node scripts/openapi-types.mjs check      # exit 1 if the committed file is stale
//
// Ported from #8's apps/web/scripts/openapi-types.mjs (openapi-typescript 7.13.0, pinned exactly in
// package.json), itself the translation of #7's packages/contracts/scripts/{generate,check}.mts.
// Without a drift check a spec change would leave this app compiling against the old contract with
// nothing to say so. `check` regenerates in memory and compares byte for byte; it never writes.
//
// OPENAPI_SPEC_PATH / OPENAPI_TYPES_PATH exist so the check's own test can run
// it against a scratch spec and a scratch output without touching either real
// file (specs/shared/ is read-only in this repository).
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import openapiTS, { astToString } from 'openapi-typescript';

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(here, '..');
const repoRoot = path.resolve(appRoot, '..', '..');

const specPath = process.env.OPENAPI_SPEC_PATH ?? path.join(repoRoot, 'specs', 'shared', 'openapi.yaml');
const outputPath = process.env.OPENAPI_TYPES_PATH ?? path.join(appRoot, 'src', 'generated', 'openapi.ts');

const BANNER = [
  '// GENERATED FILE — do not edit by hand.',
  '// Source: specs/shared/openapi.yaml, via `pnpm run types:generate` (scripts/openapi-types.mjs).',
  '// `pnpm run types:check` fails ./quality.sh when this file is stale against the spec.',
  '// Only src/shared/api-types.ts may import it (guarded by src/shared/generated-types.spec.ts).',
  '',
  '',
].join('\n');

export async function render(spec) {
  const ast = await openapiTS(pathToFileURL(spec), { alphabetize: false });
  return BANNER + astToString(ast);
}

async function generate() {
  const content = await render(specPath);
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, content, 'utf8');
  console.log(`types:generate — wrote ${path.relative(appRoot, outputPath)} from ${path.relative(repoRoot, specPath)}`);
}

async function check() {
  const fresh = await render(specPath);
  const committed = await readFile(outputPath, 'utf8').catch(() => null);
  if (committed === null) {
    console.error(`types:check FAILED — ${outputPath} does not exist. Run \`pnpm types:generate\`.`);
    return false;
  }
  if (committed !== fresh) {
    const a = committed.split('\n');
    const b = fresh.split('\n');
    let line = 0;
    while (line < Math.max(a.length, b.length) && a[line] === b[line]) line += 1;
    console.error(`types:check FAILED — ${path.relative(appRoot, outputPath)} is stale against ${path.relative(repoRoot, specPath)}.`);
    console.error(`  first difference at line ${line + 1}:`);
    console.error(`    committed: ${JSON.stringify(a[line] ?? '<end of file>')}`);
    console.error(`    fresh:     ${JSON.stringify(b[line] ?? '<end of file>')}`);
    console.error('  Run `pnpm run types:generate` and commit the result.');
    return false;
  }
  console.log(`types:check OK — ${path.relative(appRoot, outputPath)} matches a fresh generation from ${path.relative(repoRoot, specPath)}.`);
  return true;
}

const mode = process.argv[2];
if (mode === 'generate') {
  await generate();
} else if (mode === 'check') {
  const ok = await check();
  process.exitCode = ok ? 0 : 1;
} else {
  console.error('usage: node scripts/openapi-types.mjs <generate|check>');
  process.exitCode = 2;
}
