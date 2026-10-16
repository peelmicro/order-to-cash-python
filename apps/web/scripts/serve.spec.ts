// WEB_PORT: default 3010, honoured from the environment, never 3000 (#8 L1: a leader-side `.env.example`
// value defeated the documented override). commandFor() is pure, so the port a mode would listen on is read
// without starting anything.
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
// @ts-expect-error serve.mjs is plain JavaScript (a script), without type declarations
import { commandFor, DEFAULT_WEB_PORT, webPort } from './serve.mjs';

const WEB_ROOT = path.resolve(import.meta.dirname, '..');

describe('WEB_PORT', () => {
  it('defaults to 3010 for dev and preview when nothing sets it', () => {
    expect(DEFAULT_WEB_PORT).toBe(3010);
    expect(commandFor('dev', {}).args).toEqual(expect.arrayContaining(['--port', '3010']));
    expect(commandFor('preview', {}).env['NITRO_PORT']).toBe('3010');
  });

  it('honours WEB_PORT for dev and preview (a value other than the default must win)', () => {
    expect(commandFor('dev', { WEB_PORT: '4123' }).args).toEqual(expect.arrayContaining(['--port', '4123']));
    expect(commandFor('preview', { WEB_PORT: '4123' }).env).toMatchObject({ NITRO_PORT: '4123', PORT: '4123' });
  });

  it('treats an empty WEB_PORT as unset and rejects a non-port', () => {
    expect(webPort({ WEB_PORT: '  ' })).toBe(3010);
    expect(() => webPort({ WEB_PORT: 'abc' })).toThrow(/WEB_PORT/);
    expect(() => webPort({ WEB_PORT: '70000' })).toThrow(/WEB_PORT/);
  });

  it('the package scripts run through serve.mjs and load the repository .env; nothing in apps/web names port 3000', () => {
    const scripts = JSON.parse(readFileSync(path.join(WEB_ROOT, 'package.json'), 'utf8')).scripts as Record<string, string>;
    for (const name of ['dev', 'start', 'preview']) expect(scripts[name], name).toMatch(/--env-file-if-exists=\.\.\/\.\.\/\.env scripts\/serve\.mjs (dev|preview)$/);
    // Population: every tracked-kind source file of apps/web outside generated/installed/built directories (excluded by PATH at the walk, not by filtering hits).
    const skip = new Set(['node_modules', 'dist', '.angular', '.nitro', '.vitest', 'generated']);
    const hits: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) {
          if (!skip.has(entry.name)) walk(path.join(dir, entry.name));
        } else if (/\.(ts|mjs|json|html|css|md|yaml)$/.test(entry.name) && entry.name !== 'pnpm-lock.yaml' && !entry.name.endsWith('.spec.ts')) {
          const text = readFileSync(path.join(dir, entry.name), 'utf8');
          // Port 3000 used as a value: `:3000`, `=3000`, `port 3000`, `port: 3000` (prose that merely says the port is taken is fine).
          if (/(?::|=|\bport\s+(?:is\s+)?|\bport:\s*)3000\b/i.test(text)) hits.push(path.relative(WEB_ROOT, path.join(dir, entry.name)));
        }
      }
    };
    walk(WEB_ROOT);
    expect(hits, 'files naming port 3000').toEqual([]);
  });
});
