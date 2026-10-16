// Inherited acceptance item (#8 backlog id 99): the web app names its stack, from ONE definition, in three
// places: the header of every signed-in page, the sign-in page, and the browser-tab title.
//
// Units: the "every signed-in page" claim is about PAGES, so every page file on disk is rendered through the
// real file router and the label is looked for where the claim puts it. The public set is a literal and
// everything else is derived by subtraction, so a page that stops sitting under the signed-in layout FAILS
// here rather than leaving the population.
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { STACK_LABEL } from './lib/stack-label';
import { kindOf, PAGE_FILES, runPage, WEB_ROOT, type ActionScript } from './testing/page-sweep';

/** Pinned here, not imported: substituting the definition (say, with #8's label) must fail too. */
const EXPECTED_LABEL = '#9 · Python / Angular';

/** Where each page must show the label. Pages NOT listed are signed-in pages and must show it in the header. */
const PUBLIC_PAGES: Record<string, 'login'> = { '/login': 'login' };

const TIMEOUT = 60_000;

function captureScript(route: string, into: string[]): ActionScript {
  return {
    route,
    name: 'capture stack label',
    run: async () => {
      for (const element of document.querySelectorAll('[data-testid="stack-label"]')) {
        into.push(`${element.closest('header') ? 'header' : element.closest('main') ? 'main' : 'elsewhere'}: ${element.textContent?.trim()}`);
      }
    },
  };
}

describe('the stack label', () => {
  it('is the reviewed text', () => {
    expect(STACK_LABEL, 'src/app/lib/stack-label.ts: the label is not the reviewed one').toBe(EXPECTED_LABEL);
  });

  it('the public page set names only pages that exist', async () => {
    const urls: string[] = [];
    for (const file of PAGE_FILES) if ((await kindOf(file)) === 'page') urls.push(file.url);
    expect(Object.keys(PUBLIC_PAGES).filter((url) => !urls.includes(url)), 'PUBLIC_PAGES entries with no page file').toEqual([]);
  });

  it(
    'names the stack in the browser-tab title of every page',
    async () => {
      for (const file of PAGE_FILES) {
        if ((await kindOf(file)) !== 'page') continue;
        const run = await runPage(file.url);
        expect(run.renderError, `${file.rel} crashed`).toBeUndefined();
        expect(run.title, `browser-tab title of ${file.url}: document.title does not contain the stack label`).toContain(EXPECTED_LABEL);
      }
    },
    TIMEOUT * 2,
  );

  it(
    'shows the label where it belongs on every page: the login page body, the signed-in header everywhere else',
    async () => {
      for (const file of PAGE_FILES) {
        if ((await kindOf(file)) !== 'page') continue;
        const found: string[] = [];
        const run = await runPage(file.url, { action: captureScript(file.url, found) });
        expect(run.renderError, `${file.rel} crashed while rendering`).toBeUndefined();
        const where = PUBLIC_PAGES[file.url] ?? 'signed-in header';
        const place = where === 'login' ? 'main' : 'header';
        expect(found, `${where === 'login' ? 'login page' : 'signed-in header'} of ${file.url} (${file.rel}): the stack label is missing`).toContain(`${place}: ${EXPECTED_LABEL}`);
        expect(found.filter((entry) => entry.startsWith('elsewhere')), `${file.url}: the label is shown outside the header / the login body`).toEqual([]);
      }
    },
    TIMEOUT * 2,
  );

  it('has one definition: no other source file writes the label text', () => {
    // Population: every non-test source file under src/ plus index.html, read off the disk (the spec files and src/app/testing excluded by PATH).
    const src = path.join(WEB_ROOT, 'src');
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        const rel = path.relative(src, full).split(path.sep).join('/');
        if (entry.isDirectory()) {
          if (rel !== 'app/testing' && rel !== 'generated') walk(full);
        } else if (/\.(ts|mjs|css|json|html)$/.test(entry.name) && !/\.spec\.ts$/.test(entry.name)) files.push(rel);
      }
    };
    walk(src);
    expect(files, 'the source population is empty: the walk is broken').toContain('app/lib/stack-label.ts');
    const sources = [...files.map((rel) => [rel, readFileSync(path.join(src, rel), 'utf8')] as const), ['index.html', readFileSync(path.join(WEB_ROOT, 'index.html'), 'utf8')] as const];
    // Any spelling of the pair, not only the exact label, so a drifted copy is caught too.
    const pattern = /Python\s*\/\s*Angular|#9\s*·/gi;
    const hits = sources.flatMap(([rel, text]) => (text.match(pattern) ?? []).map((match) => `${rel}: ${match}`));
    expect(hits, 'the stack label is written in more than one place (or not in src/app/lib/stack-label.ts)').toEqual(['app/lib/stack-label.ts: #9 ·', 'app/lib/stack-label.ts: Python / Angular']);
  });
});
