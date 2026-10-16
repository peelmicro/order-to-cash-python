// Feature 29 acceptance item 2: "types generated from specs/shared/openapi.yaml with a drift check".
// `types:check` regenerates in memory and compares with the committed file. It is armed here with a
// ONE-LINE spec-side change made in a COPY (specs/shared/ is read-only): the check must fail and name
// the file and the first differing line; against the unchanged spec it must pass.
import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';

const WEB_ROOT = path.resolve(import.meta.dirname, '..');
const REAL_SPEC = path.resolve(WEB_ROOT, '..', '..', 'specs', 'shared', 'openapi.yaml');
const scratch = mkdtempSync(path.join(tmpdir(), 'otc-types-'));
afterAll(() => rmSync(scratch, { recursive: true, force: true }));

function check(env: Record<string, string>) {
  return spawnSync(process.execPath, ['scripts/openapi-types.mjs', 'check'], { cwd: WEB_ROOT, env: { PATH: process.env['PATH'] ?? '', ...env }, encoding: 'utf8', timeout: 60_000 });
}

describe('types:check (the generated types against specs/shared/openapi.yaml)', () => {
  it('passes against the real spec: the committed src/generated/openapi.ts is a fresh generation', () => {
    const result = check({});
    expect(result.status, result.stdout + result.stderr).toBe(0);
    expect(result.stdout).toContain('types:check OK');
  });

  it('fails, naming the file and the first differing line, when the spec gains one property (made in a copy)', () => {
    const copy = path.join(scratch, 'openapi.yaml');
    copyFileSync(REAL_SPEC, copy);
    const original = readFileSync(copy, 'utf8');
    const anchor = '    LoginRequest:\n';
    expect(original, 'the anchor the mutation needs is gone from the spec').toContain(anchor);
    // One line added under the LoginRequest schema's properties: a new optional field.
    const mutated = original.replace(/(    LoginRequest:\n(?:.*\n)*?      properties:\n)/, `$1        rememberMe:\n          type: boolean\n`);
    expect(mutated, 'the mutation did not change the copy').not.toBe(original);
    writeFileSync(copy, mutated);
    const result = check({ OPENAPI_SPEC_PATH: copy });
    expect(result.status, result.stdout + result.stderr).toBe(1);
    expect(result.stderr).toContain('types:check FAILED');
    expect(result.stderr).toContain('src/generated/openapi.ts');
    expect(result.stderr).toContain('rememberMe');
  });

  it('fails when the committed file does not exist (a missing artifact is not a pass)', () => {
    const result = check({ OPENAPI_TYPES_PATH: path.join(scratch, 'absent.ts') });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain('does not exist');
  });

  it('the real spec was never touched: the copy is the only thing mutated', () => {
    expect(readFileSync(REAL_SPEC, 'utf8')).not.toContain('rememberMe');
  });
});
