import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { defineBffContract, signIn } from '../server/testing/bff-contract';
import { ORDER_ID, SESSION_PASSWORD, TEST_JWT } from '../server/testing/gateway-script';
import { sendProblem } from '../server/testing/fake-gateway';
import { renderLogCall } from '../server/testing/log-capture';
import { ROUTE_FILES } from '../server/testing/harness';
import { buildProduction, liveServers, startProductionBff, startServer, WEB_ROOT } from './production-server';

// The BFF claims are proven against the PRODUCTION build (`vite build`, then `node dist/analog/server/index.mjs`),
// not only a dev server or the in-process h3 app: the Nitro bundle is what ships, and it is where a route that
// is mapped differently, a module duplicated per entry, or a middleware not registered would show.
beforeAll(() => buildProduction());

// Every server this file starts is stopped by the end of it (a stray server would keep a port and an upstream connection).
afterAll(() => {
  expect(liveServers(), 'production servers still running after the suite').toBe(0);
});

defineBffContract('BFF in the production build (node dist/analog/server/index.mjs)', () => startProductionBff());

describe('production build: the server\'s own output', () => {
  it('R-session: the JWT, its signature and the sealed cookie are in no line the production server writes (login, a proxied call, a refusal, an id, a stream)', async () => {
    const bff = await startProductionBff();
    try {
      const cookie = await signIn(bff);
      await bff.fetch('/api/orders', { headers: { cookie } });
      bff.gateway.on('GET', '/stock', (_req, res) => sendProblem(res, 500, { type: 'about:blank', title: 'Internal', status: 500, detail: 'boom' }));
      await bff.fetch('/api/stock', { headers: { cookie } });
      await bff.fetch(`/api/orders/${ORDER_ID}`, { headers: { cookie } });
      await bff.fetch('/api/auth/session', { headers: { cookie: `${cookie.slice(0, -4)}AAAA` } });
      const output = renderLogCall([bff.server.output()]);
      expect(output.length, 'the production server wrote nothing: the output is not being captured').toBeGreaterThan(0);
      expect(output, 'the server output carries the JWT').not.toContain(TEST_JWT);
      expect(output, 'the server output carries the JWT signature').not.toContain(TEST_JWT.split('.')[2]!);
      expect(output, 'the server output carries the sealed cookie').not.toContain(cookie.slice('otc_session='.length, 60));
    } finally {
      await bff.stop();
    }
  });

  it('R-local: an unreachable Gateway and a Gateway that does not answer are answered without the Gateway\'s address, which the server logs instead', async () => {
    const bff = await startProductionBff({ WEB_GATEWAY_TIMEOUT_MS: '300' });
    try {
      const cookie = await signIn(bff);
      bff.gateway.on('GET', '/orders', () => undefined); // never answers
      const beforeTimeout = bff.server.output().length;
      const timedOut = await bff.fetch('/api/orders', { headers: { cookie } });
      expect(timedOut.status).toBe(504);
      const timeoutBody = (await timedOut.json()) as { detail: string };
      expect(timeoutBody.detail).toContain('300 ms');
      expect(timeoutBody.detail, 'the 504 detail names the internal Gateway address').not.toContain(new URL(bff.gateway.baseUrl).host);
      expect(bff.server.output().slice(beforeTimeout), 'the Gateway address belongs in a server log line (504)').toContain(bff.gateway.baseUrl);
      await bff.gateway.stop();
      const beforeUnreachable = bff.server.output().length;
      const unreachable = await bff.fetch('/api/orders', { headers: { cookie } });
      expect(unreachable.status).toBe(502);
      expect(((await unreachable.json()) as { detail: string }).detail, 'the 502 detail names the internal Gateway address').not.toContain(new URL(bff.gateway.baseUrl).host);
      expect(bff.server.output().slice(beforeUnreachable), 'the Gateway address belongs in a server log line (502)').toContain(bff.gateway.baseUrl);
    } finally {
      await bff.stop();
    }
  });
});

describe('production build: what the bundle serves and contains', () => {
  it('R-session: a server whose WEB_SESSION_PASSWORD is set but shorter than 32 characters refuses to boot, naming the setting', async () => {
    const outcome = await startServer({ WEB_SESSION_PASSWORD: 'too-short', GATEWAY_BASE_URL: 'http://127.0.0.1:9' }).then(
      async (server) => {
        await server.stop(); // it booted when it must not have: stop it so a failing run leaves nothing behind
        return 'the server booted with a 9-character WEB_SESSION_PASSWORD';
      },
      (error: unknown) => String(error),
    );
    expect(outcome).toMatch(/WEB_SESSION_PASSWORD must be at least 32 characters/);
  });

  it('every route file the filesystem has is a route the production server answers (and none answers 404 with a session)', async () => {
    const bff = await startProductionBff();
    try {
      const cookie = await signIn(bff);
      const concrete = (name: string) => name.replace('{id}', '9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f');
      for (const file of ROUTE_FILES) {
        if (file.name.endsWith('/stream') || file.name.includes('**')) continue; // held open by design; covered by the contract's stream cases
        const response = await bff.fetch(concrete(file.name), { method: (file.method ?? 'get').toUpperCase(), headers: { cookie, 'Content-Type': 'application/json' }, body: file.method === 'post' ? '{}' : undefined });
        expect(response.status, `${file.method} ${file.name} is not a route in the production build (answered ${response.status})`).not.toBe(404);
        expect(response.headers.get('content-type') ?? '', `${file.name} answered the SPA shell, not an API response`).not.toContain('text/html');
      }
    } finally {
      await bff.stop();
    }
  });

  it('serves the SPA shell for page URLs (client routing) and a 404 problem document for unknown /api paths', async () => {
    const bff = await startProductionBff();
    try {
      for (const page of ['/', '/login', '/orders']) {
        const response = await bff.fetch(page);
        expect(response.status, page).toBe(200);
        expect(await response.text(), page).toContain('<app-root');
      }
      const unknown = await bff.fetch('/api/does-not-exist');
      expect(unknown.status).toBe(404);
      expect(unknown.headers.get('content-type')).toContain('application/problem+json');
      expect(((await unknown.json()) as { code: string }).code).toBe('NOT_FOUND');
    } finally {
      await bff.stop();
    }
  });

  it('the page the server answers is the BUILT one: it names hashed assets, each is served as JavaScript or CSS, and it is the index.html in dist/client', async () => {
    const bff = await startProductionBff();
    try {
      const html = await (await bff.fetch('/login')).text();
      expect(html, 'the server answered the SOURCE index.html').not.toContain('/src/main.ts');
      expect(html).toBe(readFileSync(path.join(WEB_ROOT, 'dist', 'client', 'index.html'), 'utf8'));
      const script = /<script[^>]+type="module"[^>]+src="([^"]+)"/.exec(html)?.[1];
      expect(script, 'the page has no module script').toMatch(/^\/assets\/index-[\w-]+\.js$/);
      const asset = await bff.fetch(script!);
      expect(asset.status).toBe(200);
      expect(asset.headers.get('content-type') ?? '').toMatch(/javascript/);
      expect((await asset.text()).length, 'the script is empty or an HTML page').toBeGreaterThan(5_000);
      const style = /<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/.exec(html)?.[1];
      expect((await bff.fetch(style!)).headers.get('content-type') ?? '').toContain('text/css');
      expect(readdirSync(path.join(WEB_ROOT, 'dist', 'analog', 'public')).sort(), 'the static directory is not the client build').toEqual(expect.arrayContaining(['assets', 'index.html']));
    } finally {
      await bff.stop();
    }
  });

  it('R-session (no transfer state): after sign-in, the pages and every static asset carry no JWT, no Angular transfer state, and no server-only setting name', async () => {
    const bff = await startProductionBff();
    try {
      const cookie = await signIn(bff);
      for (const page of ['/', '/orders', '/login']) {
        const html = await (await bff.fetch(page, { headers: { cookie } })).text();
        expect(html, `${page} carries the JWT`).not.toContain(TEST_JWT);
        expect(html, `${page} carries Angular transfer state`).not.toMatch(/ng-state|__NG_STATE|TransferState/i);
        expect(html, `${page} is server-rendered with state`).not.toMatch(/<script[^>]+type="application\/json"/i);
      }
      const client = path.join(WEB_ROOT, 'dist', 'client');
      const files: string[] = [];
      const walk = (dir: string) => {
        for (const entry of readdirSync(dir)) {
          const full = path.join(dir, entry);
          if (statSync(full).isDirectory()) walk(full);
          else files.push(full);
        }
      };
      walk(client);
      expect(files.length, 'the client bundle walk found nothing').toBeGreaterThan(3);
      for (const file of files.filter((f) => /\.(js|html|css|json|map)$/.test(f))) {
        const text = readFileSync(file, 'utf8');
        for (const secret of [TEST_JWT, SESSION_PASSWORD, 'WEB_SESSION_PASSWORD', 'GATEWAY_BASE_URL', 'WEB_GATEWAY_TIMEOUT_MS', 'iron-webcrypto', 'otc.web.generatedSessionPassword']) {
          expect(text.includes(secret), `${path.relative(WEB_ROOT, file)} contains ${secret}`).toBe(false);
        }
      }
    } finally {
      await bff.stop();
    }
  });
});

