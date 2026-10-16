// Every request the browser makes goes through ApiClient and its API_FETCH token. The sweep observes requests
// at that seam, so a request made any other way is invisible to it; this test makes the seam the only way.
// Population: every non-test source file under src/app (excluding the generated spartan components and the
// test helpers by PATH at the walk), read off the disk.
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

const APP = path.resolve(import.meta.dirname);

function sources(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      const rel = path.relative(APP, full).split(path.sep).join('/');
      if (entry.isDirectory()) {
        if (rel !== 'ui' && rel !== 'testing') walk(full);
      } else if (rel.endsWith('.ts') && !rel.endsWith('.spec.ts')) out.push(rel);
    }
  };
  walk(APP);
  return out;
}

/** Request primitives and the files allowed to use them, with the reason. */
const ALLOWED: Record<string, { files: string[]; reason: string }> = {
  'globalThis.fetch': { files: ['api/api-client.ts'], reason: 'the default of the API_FETCH token' },
  EventSource: { files: ['api/api-client.ts'], reason: 'the default of the EVENT_SOURCE token: the live order timeline (stage 2)' },
};

/** The file's code with its comments removed (by the TypeScript printer, not a regex), so prose that names a primitive is not a use of it. Strings stay. */
function code(rel: string): string {
  const file = ts.createSourceFile(rel, readFileSync(path.join(APP, rel), 'utf8'), ts.ScriptTarget.Latest, true);
  return ts.createPrinter({ removeComments: true }).printFile(file);
}

const PRIMITIVES: Array<[name: string, pattern: RegExp]> = [
  ['globalThis.fetch', /\bglobalThis\.fetch\b/],
  ['window.fetch', /\bwindow\.fetch\b/],
  ['bare fetch(', /(?<![.\w$])fetch\s*\(/],
  ['XMLHttpRequest', /\bXMLHttpRequest\b/],
  ['WebSocket', /\bWebSocket\b/],
  ['EventSource', /\bEventSource\b/],
  ['sendBeacon', /\bsendBeacon\b/],
  ['HttpClient', /\bHttpClient\b|provideHttpClient/],
  ['axios/ofetch/$fetch', /from\s+['"](axios|ofetch)['"]|\$fetch\b/],
];

describe('the API seam is the only way to the network', () => {
  const files = sources();

  it('the walk sees the app (a vacuous walk would pass anything)', () => {
    expect(files.length).toBeGreaterThan(8);
    expect(files).toContain('api/api-client.ts');
  });

  it('request primitives appear only where reviewed', () => {
    const hits: Record<string, string[]> = {};
    for (const rel of files) {
      const source = code(rel);
      for (const [name, pattern] of PRIMITIVES) if (pattern.test(source)) (hits[name] ??= []).push(rel);
    }
    const expected = Object.fromEntries(Object.entries(ALLOWED).map(([name, entry]) => [name, entry.files]));
    expect(hits, 'a file makes a request without going through ApiClient/API_FETCH (or a primitive is no longer used: update ALLOWED)').toEqual(expected);
  });

  it('the API client is the only file that builds an /api URL', () => {
    const builders = files.filter((rel) => /['"`]\/api\b/.test(code(rel)));
    expect(builders).toEqual(['api/api-client.ts']);
  });
});
