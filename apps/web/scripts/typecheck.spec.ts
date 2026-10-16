// The BFF, the shared types and the scripts are not compiled by the Angular build (only the browser app is), and the
// test transform strips types without checking them across files. This runs the compiler over everything.
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { expect, it } from 'vitest';

const WEB_ROOT = path.resolve(import.meta.dirname, '..');

it('tsc --noEmit over every source and spec file reports nothing', () => {
  const result = spawnSync(process.execPath, ['./node_modules/typescript/bin/tsc', '--noEmit', '-p', 'tsconfig.spec.json'], { cwd: WEB_ROOT, encoding: 'utf8', timeout: 180_000 });
  expect(result.stdout + result.stderr, 'type errors').toBe('');
  expect(result.status).toBe(0);
}, 200_000);
