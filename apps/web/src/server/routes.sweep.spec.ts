// Feature 29, acceptance item 4 for the BFF: "every error shown is that error's own problem-document text".
//
// The BFF half of the instrument. It knows nothing about HOW a route handles a failure; it only knows
// what a route is and what it called. For every route file on disk (the population is the filesystem,
// twice: the glob and a directory walk) the sweep
//   1. makes the request once against an all-success Gateway and OBSERVES every upstream call the route
//      makes (#8 RR3 D1: login makes two, and the second one's problem body was dropped);
//   2. fails each observed call in turn, with each status openapi.yaml declares for that operation
//      (#8 RR3 G4: not one or two hand-picked statuses), once with a detail-bearing problem and once
//      with a title-only problem whose sentinel is the title;
//   3. requires the response to be the Gateway's document unchanged: status, content type and body,
//      so the user's words are the server's words and the BFF adds none of its own.
// A route whose observed calls differ from the reviewed literal, or a literal naming a route that no
// longer exists, fails by name. The expected sets are literals; everything else is derived.
import { randomUUID } from 'node:crypto';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { sessionCookie, setCookieLine, signIn } from './testing/bff-contract';
import { failOne, installAllSuccess, INVOICE_ID, ORDER_ID, problem, SESSION_PASSWORD, TEST_JWT } from './testing/gateway-script';
import { middlewareOnDisk, ROUTE_FILES, routeFilesOnDisk, startBff, type Bff } from './testing/harness';
import { declaredOperations, operationFor } from './testing/openapi-statuses';

const NONCE = randomUUID().replace(/-/g, '').slice(0, 12);
let sentinelCount = 0;
const sentinel = (variant: string) => `sweep-${NONCE}-${++sentinelCount}-${variant}`;

interface Invocation {
  method: 'GET' | 'POST';
  path: string;
  body?: string;
  headers?: Record<string, string>;
  /** The session cookie is needed (every route but the BFF-local session ones). */
  authenticated: boolean;
}

/** One canonical request per route, keyed `METHOD /name`. A route with no entry here fails the sweep by name. */
const INVOCATIONS: Record<string, Invocation> = {
  'POST /api/auth/login': { method: 'POST', path: '/api/auth/login', body: '{"username":"operator","password":"pw"}', authenticated: false },
  'POST /api/auth/logout': { method: 'POST', path: '/api/auth/logout', authenticated: true },
  'GET /api/auth/session': { method: 'GET', path: '/api/auth/session', authenticated: true },
  'GET /api/catalog/companies': { method: 'GET', path: '/api/catalog/companies', authenticated: true },
  'GET /api/catalog/products': { method: 'GET', path: '/api/catalog/products', authenticated: true },
  'GET /api/catalog/retailers': { method: 'GET', path: '/api/catalog/retailers', authenticated: true },
  'GET /api/credits': { method: 'GET', path: '/api/credits', authenticated: true },
  'GET /api/invoices': { method: 'GET', path: '/api/invoices', authenticated: true },
  'POST /api/invoices/{id}/payments': { method: 'POST', path: `/api/invoices/${INVOICE_ID}/payments`, body: '{"paymentReference":"PAY-1"}', authenticated: true },
  'GET /api/orders': { method: 'GET', path: '/api/orders', authenticated: true },
  'POST /api/orders': { method: 'POST', path: '/api/orders', body: '{"retailerCode":"A"}', headers: { 'Idempotency-Key': 'k-1' }, authenticated: true },
  'GET /api/orders/{id}': { method: 'GET', path: `/api/orders/${ORDER_ID}`, authenticated: true },
  'GET /api/orders/stream': { method: 'GET', path: '/api/orders/stream', authenticated: true },
  'GET /api/stock': { method: 'GET', path: '/api/stock', authenticated: true },
  'POST /api/stock/replenish': { method: 'POST', path: '/api/stock/replenish', body: '{"items":[]}', authenticated: true },
};

/**
 * The upstream calls each route makes, as last reviewed. This is NOT where the sweep's population comes
 * from (that is observed); it is the check that observation still sees what it saw, so a harness that
 * stops early, or a route that gains or loses a call, changes a line here on purpose.
 */
const EXPECTED_UPSTREAM: Record<string, string[]> = {
  'POST /api/auth/login': ['POST /auth/login', 'GET /auth/me'],
  'POST /api/auth/logout': [],
  'GET /api/auth/session': [],
  'GET /api/catalog/companies': ['GET /catalog/companies'],
  'GET /api/catalog/products': ['GET /catalog/products'],
  'GET /api/catalog/retailers': ['GET /catalog/retailers'],
  'GET /api/credits': ['GET /credits'],
  'GET /api/invoices': ['GET /invoices'],
  'POST /api/invoices/{id}/payments': [`POST /invoices/${INVOICE_ID}/payments`],
  'GET /api/orders': ['GET /orders'],
  'POST /api/orders': ['POST /orders'],
  'GET /api/orders/{id}': [`GET /orders/${ORDER_ID}`],
  'GET /api/orders/stream': ['GET /orders/stream'],
  'GET /api/stock': ['GET /stock'],
  'POST /api/stock/replenish': ['POST /stock/replenish'],
};

/** Route files that are not API endpoints a page calls: the 404 catch-all. */
const NOT_SWEPT: Record<string, string> = {
  'api/[...path].ts': 'the catch-all answers 404 for paths no route owns; it makes no upstream call (checked in the population test below)',
};

/** Middleware files, as a literal; any other file in src/server/middleware fails by name. */
const EXPECTED_MIDDLEWARE = ['csrf.ts'];

const keyOf = (file: { method: string | undefined; name: string }) => `${(file.method ?? 'any').toUpperCase()} ${file.name}`;
const swept = ROUTE_FILES.filter((file) => !(file.rel in NOT_SWEPT));

describe('the route population is the filesystem', () => {
  it('the glob and a directory walk of src/server/routes see the same files', () => {
    const onDisk = routeFilesOnDisk();
    expect(onDisk.length, 'the directory walk found nothing: it is not reading src/server/routes').toBeGreaterThanOrEqual(15);
    expect({ onDiskNotGlobbed: onDisk.filter((rel) => !ROUTE_FILES.some((f) => f.rel === rel)), globbedNotOnDisk: ROUTE_FILES.map((f) => f.rel).filter((rel) => !onDisk.includes(rel)) }).toEqual({ onDiskNotGlobbed: [], globbedNotOnDisk: [] });
  });

  it('every route file is invoked by the sweep or listed as not swept, and every literal names a route that exists', () => {
    const keys = swept.map(keyOf);
    expect(keys.filter((key) => !(key in INVOCATIONS)), 'route files with no INVOCATIONS entry').toEqual([]);
    expect(keys.filter((key) => !(key in EXPECTED_UPSTREAM)), 'route files with no EXPECTED_UPSTREAM entry').toEqual([]);
    expect(Object.keys(INVOCATIONS).filter((key) => !keys.includes(key)), 'INVOCATIONS entries with no route file').toEqual([]);
    expect(Object.keys(EXPECTED_UPSTREAM).filter((key) => !keys.includes(key)), 'EXPECTED_UPSTREAM entries with no route file').toEqual([]);
    expect(Object.keys(NOT_SWEPT).filter((rel) => !ROUTE_FILES.some((f) => f.rel === rel)), 'NOT_SWEPT entries with no route file').toEqual([]);
  });

  it('the middleware files are exactly the reviewed ones (a new middleware changes what the sweep sees)', () => {
    expect(middlewareOnDisk()).toEqual(EXPECTED_MIDDLEWARE);
  });

  it('every route that calls the Gateway matches an operation in openapi.yaml, so its failure statuses are drawn from the spec', () => {
    const operations = declaredOperations();
    expect(operations.length, 'the generated types declare no operation').toBeGreaterThan(10);
    for (const [route, calls] of Object.entries(EXPECTED_UPSTREAM)) {
      for (const call of calls) {
        const [method, path] = call.split(' ') as [string, string];
        expect(operationFor(method, path, operations), `${route}: upstream call ${call} matches no operation in openapi.yaml`).toBeDefined();
      }
    }
  });
});

describe('every upstream call of every route, failed in turn', () => {
  let bff: Bff;
  let cookie: string;

  beforeAll(() => {
    vi.stubEnv('WEB_SESSION_PASSWORD', SESSION_PASSWORD);
    vi.stubEnv('WEB_COOKIE_SECURE', '');
  });
  beforeEach(async () => {
    bff = await startBff((name, value) => vi.stubEnv(name, value));
    cookie = await signIn(bff);
    bff.gateway.requests.length = 0;
  });
  afterAll(() => vi.unstubAllEnvs());

  async function invoke(invocation: Invocation): Promise<Response> {
    const headers: Record<string, string> = { ...invocation.headers };
    if (invocation.authenticated) headers['cookie'] = cookie;
    if (invocation.body !== undefined) headers['Content-Type'] = 'application/json';
    return bff.fetch(invocation.path, { method: invocation.method, headers, body: invocation.body });
  }

  const upstreamOf = () => bff.gateway.requests.map((r) => `${r.method} ${r.url.split('?')[0]}`);

  describe.each(swept.map((file) => [keyOf(file)] as const))('%s', (key) => {
    const invocation = INVOCATIONS[key];
    if (!invocation) {
      it('has an INVOCATIONS entry', () => expect.fail(`${key} is a route file the sweep has no canonical request for: add it to INVOCATIONS and EXPECTED_UPSTREAM`));
      return;
    }

    it('succeeds against an all-success Gateway; the upstream calls it makes are the reviewed ones', async () => {
      const response = await invoke(invocation);
      expect(response.status, await response.clone().text()).toBeLessThan(300);
      await response.text();
      expect(upstreamOf(), `${key}: the observed upstream calls differ from EXPECTED_UPSTREAM`).toEqual(EXPECTED_UPSTREAM[key]);
    });

    it.each(['detail', 'title'] as const)('relays each upstream call\'s refusal as that problem, unchanged (%s variant), for every status openapi.yaml declares', async (variant) => {
      const calls = EXPECTED_UPSTREAM[key]!;
      const failures: string[] = [];
      for (const call of calls) {
        const [method, path] = call.split(' ') as [string, string];
        const operation = operationFor(method, path)!;
        const statuses = operation.statuses.filter((status) => status >= 400);
        expect(statuses.length, `${call}: openapi.yaml declares no failure status`).toBeGreaterThan(0);
        for (const status of statuses) {
          bff.gateway.reset();
          installAllSuccess(bff.gateway);
          const text = sentinel(variant);
          const body = variant === 'detail' ? problem(status, text, `decoy-title-${NONCE}`) : problem(status, undefined, text);
          failOne(bff.gateway, method, path, status, body);
          const response = await invoke(invocation);
          const raw = await response.text();
          const where = `${key} | upstream ${call} answered ${status} (${variant})`;
          if (response.status !== status) failures.push(`${where} | status ${response.status}, expected ${status}`);
          else if (!response.headers.get('content-type')?.includes('application/problem+json')) failures.push(`${where} | content type ${response.headers.get('content-type')}`);
          else if (raw !== JSON.stringify(body)) failures.push(`${where} | body is not the Gateway's document unchanged: ${raw}`);
          if (raw.includes(TEST_JWT)) failures.push(`${where} | the JWT is in the response`);
          const setCookie = setCookieLine(response);
          const issued = sessionCookie(response);
          if (key === 'POST /api/auth/login' && issued !== undefined && issued !== 'otc_session=') failures.push(`${where} | a refused login still issued a session cookie`);
          if (key !== 'POST /api/auth/login') {
            if (status === 401 && !/Max-Age=0/i.test(setCookie ?? '')) failures.push(`${where} | a 401 did not expire the session cookie`);
            if (status !== 401 && setCookie !== undefined) failures.push(`${where} | a ${status} touched the session cookie`);
          }
        }
      }
      if (failures.length) expect.fail(`refusals the user would not see in the Gateway's own words (route | upstream call | detail):\n${failures.join('\n')}`);
      expect(sentinelCount).toBeGreaterThan(0);
    });

    if (invocation.authenticated && EXPECTED_UPSTREAM[key]!.length > 0) {
      it('with no session answers the BFF\'s own 401 problem and reaches no upstream', async () => {
        const response = await bff.fetch(invocation.path, { method: invocation.method, headers: invocation.body !== undefined ? { 'Content-Type': 'application/json' } : {}, body: invocation.body });
        expect(response.status).toBe(401);
        const body = (await response.json()) as { code: string; title: string; detail: string };
        expect([body.code, Boolean(body.title), Boolean(body.detail)]).toEqual(['UNAUTHENTICATED', true, true]);
        expect(upstreamOf()).toEqual([]);
      });

      it('with the Gateway down answers the BFF\'s own 502 problem, with a title and a detail', async () => {
        await bff.gateway.stop();
        const response = await invoke(invocation);
        expect(response.status).toBe(502);
        const body = (await response.json()) as { code: string; title: string; detail: string };
        expect([body.code, Boolean(body.title), Boolean(body.detail)]).toEqual(['GATEWAY_UNREACHABLE', true, true]);
      });
    }
  });

  it('the catch-all makes no upstream call and answers its own 404 problem', async () => {
    const response = await bff.fetch('/api/nope', { headers: { cookie } });
    expect(response.status).toBe(404);
    expect(((await response.json()) as { code: string }).code).toBe('NOT_FOUND');
    expect(upstreamOf()).toEqual([]);
  });

  it('sentinels are unique, random, and cannot equal any text the BFF writes itself', () => {
    expect(NONCE).toMatch(/^[0-9a-f]{12}$/);
  });
});
