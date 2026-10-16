// Where the secrets live. The browser bundle must not be able to reach the session password, the Gateway's
// address or the JWT, so the code that holds them is confined, and the confinement is checked by walking the
// source, comments removed by the TypeScript printer (a name in prose is not a use). Populations are read off
// the disk; the spec files and the test helpers are excluded BY PATH at the walk.
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

const WEB = path.resolve(import.meta.dirname, '..', '..');
const SRC = path.join(WEB, 'src');

function walk(root: string, skip: (rel: string) => boolean): string[] {
  const out: string[] = [];
  const visit = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      const rel = path.relative(SRC, full).split(path.sep).join('/');
      if (skip(rel)) continue;
      if (entry.isDirectory()) visit(full);
      else if (rel.endsWith('.ts') && !rel.endsWith('.spec.ts')) out.push(rel);
    }
  };
  visit(root);
  return out;
}

const code = (rel: string) => ts.createPrinter({ removeComments: true }).printFile(ts.createSourceFile(rel, readFileSync(path.join(SRC, rel), 'utf8'), ts.ScriptTarget.Latest, true));

const appFiles = walk(path.join(SRC, 'app'), (rel) => rel === 'app/ui' || rel === 'app/testing');
const serverFiles = walk(path.join(SRC, 'server'), (rel) => rel === 'server/testing');
const sharedFiles = walk(path.join(SRC, 'shared'), () => false);

const importsOf = (rel: string) => [...code(rel).matchAll(/(?:import|export)\s[^;]*?from\s+['"]([^'"]+)['"]|import\(['"]([^'"]+)['"]\)/g)].map((m) => m[1] ?? m[2]!);

describe('the source populations are not vacuous', () => {
  it('the walks see the app, the BFF and the shared types', () => {
    expect(appFiles.length).toBeGreaterThan(8);
    expect(serverFiles.length).toBeGreaterThan(20);
    expect(sharedFiles).toContain('shared/api-types.ts');
  });
});

describe('browser code cannot reach server-only code', () => {
  it('no file under src/app imports src/server, a Node module, h3, nitro or the server config', () => {
    const offenders = appFiles.flatMap((rel) => importsOf(rel).filter((spec) => /(^|\/)server(\/|$)/.test(spec) || /^node:/.test(spec) || /^(h3|nitropack|iron-webcrypto|ofetch)(\/|$)/.test(spec)).map((spec) => `${rel} imports ${spec}`));
    expect(offenders, 'browser code reaches server-only code').toEqual([]);
  });

  it('the browser source never reads configuration: no process.env, no import.meta.env, no runtimeConfig', () => {
    const offenders = appFiles.filter((rel) => /process\.env|import\.meta\.env|runtimeConfig|useRuntimeConfig/.test(code(rel)));
    expect(offenders, 'browser code reads configuration').toEqual([]);
  });

  it('the name of the token, and of every server setting, appears in no browser file', () => {
    const names = ['accessToken', 'WEB_SESSION_PASSWORD', 'GATEWAY_BASE_URL', 'GATEWAY_PORT', 'WEB_COOKIE_SECURE', 'Authorization', 'Bearer'];
    const offenders = appFiles.flatMap((rel) => names.filter((name) => code(rel).includes(name)).map((name) => `${rel} names ${name}`));
    expect(offenders, 'browser code names the token or a server-only setting').toEqual([]);
  });

  it('the shared module holds types only (no value import, nothing runnable)', () => {
    for (const rel of sharedFiles) expect(code(rel), rel).not.toMatch(/^(?!import type|export type)import\s/m);
  });

  it('vite.config.ts defines no public value from the server settings', () => {
    const config = readFileSync(path.join(WEB, 'vite.config.ts'), 'utf8');
    expect(config).not.toMatch(/GATEWAY|SESSION_PASSWORD|VITE_|define\s*:/);
  });
});

describe('server code', () => {
  it('imports no Angular, TanStack or browser source', () => {
    const offenders = serverFiles.flatMap((rel) => importsOf(rel).filter((spec) => /^@angular\//.test(spec) || /^@tanstack\//.test(spec) || /\/app\//.test(spec) || /^@spartan/.test(spec)).map((spec) => `${rel} imports ${spec}`));
    expect(offenders, 'server code imports browser code').toEqual([]);
  });

  it('reads process.env in exactly one module: server/lib/config.ts', () => {
    expect(serverFiles.filter((rel) => /process\.env/.test(code(rel))), 'process.env is read outside server/lib/config.ts').toEqual(['server/lib/config.ts']);
  });

  it('imports its framework explicitly (no reliance on Nitro auto-imports, which the type checker and the tests cannot see)', () => {
    const autoImported = ['defineEventHandler', 'readBody', 'getHeader', 'getQuery', 'getRouterParam', 'setResponseHeader', 'useSession'];
    const offenders = serverFiles.flatMap((rel) => {
      const source = code(rel);
      return autoImported.filter((name) => new RegExp(`\\b${name}\\b`).test(source) && !new RegExp(`import\\s*\\{[^}]*\\b${name}\\b[^}]*\\}\\s*from\\s*'h3'`).test(source) && !source.includes(`function ${name}`)).map((name) => `${rel} uses ${name} without importing it from h3`);
    });
    expect(offenders, 'server code relies on auto-imports').toEqual([]);
  });

  it('the JWT is not written to any log: no console call or logger mentions the access token', () => {
    const offenders = serverFiles.filter((rel) => /console\.\w+\([^)]*(accessToken|token|Authorization)/i.test(code(rel)));
    expect(offenders, 'a server file logs the access token').toEqual([]);
  });
});

describe('h3 is pinned', () => {
  it('R-pin: h3 is an exact version in package.json (no range) and the lockfile resolves that same version, because the BFF reasons from its internals (sessionHeader, _decodePath, getRequestURL) by line', () => {
    const pkg = JSON.parse(readFileSync(path.join(WEB, 'package.json'), 'utf8')) as { dependencies: Record<string, string> };
    const version = pkg.dependencies['h3'];
    expect(version, 'h3 is not an exact version (a range lets the lockfile drift silently)').toMatch(/^\d+\.\d+\.\d+$/);
    const lock = readFileSync(path.join(WEB, 'pnpm-lock.yaml'), 'utf8');
    expect(lock, 'the lockfile does not resolve the pinned h3').toContain(`      h3:\n        specifier: ${version}\n        version: ${version}\n`);
  });
});
