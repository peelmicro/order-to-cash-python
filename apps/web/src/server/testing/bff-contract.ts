import { request as httpRequest, type IncomingHttpHeaders } from 'node:http';
import { connect } from 'node:net';
import { EventSource } from 'eventsource';
import { expect } from 'vitest';
import type { Bff } from './harness';
import { installAllSuccess, ME, problem, TEST_JWT, TEST_PASSWORD, ORDER_ID } from './gateway-script';

/** The `name=value` pair of the session cookie from a response, ready to send back. */
export function sessionCookie(response: Response): string | undefined {
  const line = response.headers.getSetCookie().find((cookie) => cookie.startsWith('otc_session='));
  return line?.split(';')[0];
}

export function setCookieLine(response: Response, name = 'otc_session'): string | undefined {
  return response.headers.getSetCookie().find((cookie) => cookie.startsWith(`${name}=`));
}

export async function signIn(bff: Bff): Promise<string> {
  installAllSuccess(bff.gateway);
  const response = await bff.fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'operator', password: TEST_PASSWORD }) });
  expect(response.status, await response.clone().text()).toBe(200);
  const cookie = sessionCookie(response);
  expect(cookie, 'login set no otc_session cookie').toBeDefined();
  return cookie!;
}

/**
 * A raw HTTP GET that hands every chunk to `onChunk` the moment it arrives and returns a handle to
 * close the connection from the client side (what a closed tab does). fetch() would hide
 * chunk-level timing behind its own buffering; a socket-level client does not.
 */
export function openStream(url: string, headers: Record<string, string>): Promise<{ status: number; headers: Record<string, string | string[] | undefined>; chunks: string[]; waitFor: (needle: string, ms?: number) => Promise<void>; close: () => void }> {
  return new Promise((resolve, reject) => {
    const chunks: string[] = [];
    const waiters: Array<() => void> = [];
    const req = httpRequest(url, { headers }, (res) => {
      res.setEncoding('utf8');
      res.on('data', (chunk: string) => {
        chunks.push(chunk);
        for (const wake of waiters.splice(0)) wake();
      });
      res.on('error', () => undefined);
      resolve({
        status: res.statusCode ?? 0,
        headers: res.headers,
        chunks,
        waitFor: (needle, ms = 5000) =>
          new Promise<void>((ok, fail) => {
            const timer = setTimeout(() => fail(new Error(`no chunk containing ${JSON.stringify(needle)} within ${ms} ms; got ${JSON.stringify(chunks.join(''))}`)), ms);
            const check = () => {
              if (chunks.join('').includes(needle)) {
                clearTimeout(timer);
                ok();
              } else waiters.push(check);
            };
            check();
          }),
        close: () => req.destroy(),
      });
    });
    req.on('error', (error) => (chunks.length === 0 ? reject(error) : undefined));
    req.end();
  });
}

/**
 * A request whose target is sent EXACTLY as given. `fetch` and `new URL` normalise `..`, `%2E%2E` and `.` away
 * before a request leaves, which would hide the very paths a hostile client can still send with a raw socket.
 */
export function rawRequest(baseUrl: string, method: string, target: string, headers: Record<string, string> = {}, body?: string): Promise<{ status: number; headers: IncomingHttpHeaders; body: string }> {
  return new Promise((resolve, reject) => {
    const url = new URL(baseUrl);
    const req = httpRequest({ host: url.hostname, port: url.port, method, path: target, headers: { ...headers, ...(body === undefined ? {} : { 'Content-Length': String(Buffer.byteLength(body)) }) } }, (res) => {
      const chunks: Buffer[] = [];
      res.on('data', (chunk: Buffer) => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode ?? 0, headers: res.headers, body: Buffer.concat(chunks).toString('utf8') }));
      res.on('error', reject);
    });
    req.on('error', reject);
    req.end(body);
  });
}

export async function eventually(check: () => boolean, ms: number, what: string): Promise<number> {
  const start = Date.now();
  while (Date.now() - start < ms) {
    if (check()) return Date.now() - start;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`${what}: still false after ${ms} ms`);
}

/**
 * The claims that must hold of the BFF whichever way it runs (in-process over h3, or the
 * production build under node). Registered under `describe(label)` by both specs.
 */
export function defineBffContract(label: string, start: () => Promise<Bff>): void {
  describe(label, () => {
    let bff: Bff;
    beforeEach(async () => {
      bff = await start();
    });
    afterEach(async () => {
      await bff.stop();
    });

    it('R-session: login answers identity only, and seals the JWT into an httpOnly SameSite=Lax Secure cookie that does not contain it', async () => {
      installAllSuccess(bff.gateway);
      const response = await bff.fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'operator', password: TEST_PASSWORD }) });
      const text = await response.text();
      expect(response.status).toBe(200);
      expect(JSON.parse(text), 'the login response body is not identity-only (it must carry no token field)').toEqual({ authenticated: true, username: ME.username, displayName: ME.displayName, roles: ME.roles });
      expect(text, 'the login response BODY carries the JWT').not.toContain(TEST_JWT);
      const cookies = response.headers.getSetCookie();
      expect(cookies.filter((c) => c.startsWith('otc_session=')), 'exactly one session cookie is set').toHaveLength(1);
      const line = setCookieLine(response)!;
      expect(line).toMatch(/;\s*HttpOnly/i);
      expect(line).toMatch(/;\s*SameSite=Lax/i);
      expect(line).toMatch(/;\s*Secure/i);
      expect(line).toMatch(/;\s*Path=\//i);
      expect(line).toMatch(/;\s*Max-Age=43200/i);
      const value = decodeURIComponent(line.split(';')[0]!.slice('otc_session='.length));
      expect(value, 'the cookie value carries the JWT in the clear').not.toContain(TEST_JWT);
      expect(value, 'the cookie value carries the JWT base64-encoded').not.toContain(Buffer.from(TEST_JWT).toString('base64').slice(0, 24));
      expect(value, 'the cookie value carries the JWT payload in the clear').not.toContain(TEST_JWT.split('.')[1]!);
      for (const [name, header] of response.headers) expect(header, `response header ${name} carries the JWT`).not.toContain(TEST_JWT);
    });

    it('R-session: the Gateway receives the token from the session, and a browser-supplied Authorization header is never forwarded', async () => {
      const cookie = await signIn(bff);
      bff.gateway.requests.length = 0;
      const response = await bff.fetch('/api/orders?page=2&pageSize=5', { headers: { cookie, Authorization: 'Bearer attacker-token' } });
      expect(response.status).toBe(200);
      expect(bff.gateway.requests).toHaveLength(1);
      expect(bff.gateway.requests[0]!.url).toBe('/orders?page=2&pageSize=5');
      expect(bff.gateway.requests[0]!.headers['authorization'], 'the Gateway did not receive the session token as its bearer (a browser-supplied Authorization header must never replace it)').toBe(`Bearer ${TEST_JWT}`);
    });

    it('R-session: GET /api/auth/session answers identity only; with no cookie it answers authenticated:false and sets no cookie', async () => {
      const cookie = await signIn(bff);
      const signedIn = await bff.fetch('/api/auth/session', { headers: { cookie } });
      const text = await signedIn.text();
      expect(JSON.parse(text)).toEqual({ authenticated: true, username: ME.username, displayName: ME.displayName, roles: ME.roles });
      expect(text).not.toContain(TEST_JWT);
      const anonymous = await bff.fetch('/api/auth/session');
      expect(await anonymous.json()).toEqual({ authenticated: false });
      expect(anonymous.headers.getSetCookie(), 'an anonymous request must not mint a cookie').toEqual([]);
    });

    it('R-session: a tampered cookie is no session', async () => {
      const cookie = await signIn(bff);
      const tampered = `${cookie.slice(0, -4)}AAAA`;
      expect(tampered).not.toBe(cookie);
      for (const unreadable of [tampered, 'otc_session=garbage']) {
        const response = await bff.fetch('/api/auth/session', { headers: { cookie: unreadable } });
        expect(await response.json()).toEqual({ authenticated: false });
        // An unreadable cookie is CLEARED. h3's useSession would answer it by minting a fresh sealed session.
        const lines = response.headers.getSetCookie().filter((line) => line.startsWith('otc_session='));
        expect(lines.filter((line) => !/^otc_session=;/.test(line)), 'an unreadable cookie was answered with a newly minted session cookie').toEqual([]);
        expect(lines, 'an unreadable cookie must be expired').toHaveLength(1);
        expect(lines[0], 'an unreadable cookie must be expired').toMatch(/;\s*Max-Age=0/i);
      }
    });

    it('R-session: h3\'s default session header (x-otc_session-session) is not an authentication path', async () => {
      const cookie = await signIn(bff);
      const sealed = decodeURIComponent(cookie.slice('otc_session='.length));
      // A (garbage) cookie is present so the request reaches h3's session code, where a valid header would win if h3's header lookup were on.
      const response = await bff.fetch('/api/auth/session', { headers: { cookie: 'otc_session=garbage', 'x-otc_session-session': sealed } });
      expect(await response.json(), 'a sealed session in the x-otc_session-session header authenticated the request').toEqual({ authenticated: false });
      // No cookie at all: the header alone must not be a fallback either.
      const cookieless = await bff.fetch('/api/auth/session', { headers: { 'x-otc_session-session': sealed } });
      expect(await cookieless.json(), 'a cookie-less request carrying only the x-otc_session-session header authenticated').toEqual({ authenticated: false });
    });

    it('R-session: logout expires the cookie (Max-Age=0, same path and attributes) and answers authenticated:false', async () => {
      const cookie = await signIn(bff);
      const response = await bff.fetch('/api/auth/logout', { method: 'POST', headers: { cookie } });
      expect(await response.json()).toEqual({ authenticated: false });
      const line = setCookieLine(response)!;
      expect(line).toMatch(/^otc_session=;/);
      expect(line).toMatch(/;\s*Max-Age=0/i);
      expect(line).toMatch(/;\s*Path=\//i);
      expect(line).toMatch(/;\s*HttpOnly/i);
    });

    it('R-relay: a refused login is relayed with the Gateway\'s own status and problem document, unchanged', async () => {
      const refusal = problem(401, 'The username or password is wrong.', 'Unauthorized', 'INVALID_CREDENTIALS');
      installAllSuccess(bff.gateway);
      bff.gateway.on('POST', '/auth/login', (_req, res) => {
        res.writeHead(401, { 'Content-Type': 'application/problem+json' });
        res.end(JSON.stringify(refusal));
      });
      const response = await bff.fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'operator', password: 'nope' }) });
      expect(response.status).toBe(401);
      expect(response.headers.get('content-type')).toContain('application/problem+json');
      expect(await response.json()).toEqual(refusal);
      expect(setCookieLine(response)?.includes(TEST_JWT) ?? false).toBe(false);
    });

    it('R-relay: status, body bytes and the headers a client acts on are relayed (202 + Retry-After, 201, 200 + Idempotent-Replay)', async () => {
      const cookie = await signIn(bff);
      bff.gateway.on('GET', `/orders/${ORDER_ID}`, (_req, res) => {
        res.writeHead(202, { 'Content-Type': 'application/json', 'Retry-After': '2' });
        res.end('{"orderId":"x","status":"pending",  "keep":"whitespace"}');
      });
      bff.gateway.on('POST', '/orders', (_req, res) => {
        res.writeHead(200, { 'Content-Type': 'application/json', 'Idempotent-Replay': 'true' });
        res.end('{"replayed":true}');
      });
      const pending = await bff.fetch(`/api/orders/${ORDER_ID}`, { headers: { cookie } });
      expect(pending.status).toBe(202);
      expect(pending.headers.get('retry-after')).toBe('2');
      expect(await pending.text(), 'the body is relayed byte for byte, not re-serialised').toBe('{"orderId":"x","status":"pending",  "keep":"whitespace"}');
      const replay = await bff.fetch('/api/orders', { method: 'POST', headers: { cookie, 'Content-Type': 'application/json', 'Idempotency-Key': 'key-123' }, body: '{"a":1}' });
      expect(replay.status).toBe(200);
      expect(replay.headers.get('idempotent-replay')).toBe('true');
      const forwarded = bff.gateway.requests.filter((r) => r.method === 'POST' && r.url === '/orders').at(-1)!;
      expect(forwarded.headers['idempotency-key']).toBe('key-123');
      expect(forwarded.body).toBe('{"a":1}');
    });

    it('R-relay: a Gateway 401 relays the problem and expires the cookie; a 403, 409, 500 and 503 relay and leave the cookie alone (both directions)', async () => {
      const cookie = await signIn(bff);
      for (const status of [401, 403, 409, 500, 503]) {
        const body = problem(status, `detail for ${status}`, `title for ${status}`);
        bff.gateway.on('GET', '/stock', (_req, res) => {
          res.writeHead(status, { 'Content-Type': 'application/problem+json' });
          res.end(JSON.stringify(body));
        });
        const response = await bff.fetch('/api/stock', { headers: { cookie } });
        expect(response.status).toBe(status);
        expect(await response.json()).toEqual(body);
        const line = setCookieLine(response);
        if (status === 401) {
          expect(line ?? '<no Set-Cookie header>', 'a 401 must expire the session cookie').toMatch(/^otc_session=;.*Max-Age=0/i);
        } else {
          expect(line, `a ${status} must not touch the session cookie`).toBeUndefined();
        }
      }
    });

    it('R-local: with no session a proxied route answers its own 401 problem (own words), expires the cookie, and never reaches the Gateway', async () => {
      installAllSuccess(bff.gateway);
      const response = await bff.fetch('/api/orders');
      expect(response.status).toBe(401);
      expect(response.headers.get('content-type')).toContain('application/problem+json');
      const body = (await response.json()) as { code: string; detail: string; title: string };
      expect(body.code).toBe('UNAUTHENTICATED');
      expect(body.detail).toMatch(/sign in/i);
      expect(bff.gateway.requests).toHaveLength(0);
      expect(setCookieLine(response)).toMatch(/Max-Age=0/i);
    });

    it('R-csrf: a cross-site mutation is refused with the BFF\'s own problem and never reaches the Gateway; same-origin and header-less mutations pass; reads are never refused', async () => {
      const cookie = await signIn(bff);
      bff.gateway.requests.length = 0;
      const base = new URL(bff.baseUrl);
      const post = (headers: Record<string, string>) => bff.fetch('/api/stock/replenish', { method: 'POST', headers: { cookie, 'Content-Type': 'application/json', ...headers }, body: '{}' });
      const refused: Array<Record<string, string>> = [{ Origin: 'https://evil.example' }, { 'Sec-Fetch-Site': 'cross-site' }, { 'Sec-Fetch-Site': 'same-site' }, { Origin: 'null' }];
      for (const headers of refused) {
        const response = await post(headers);
        expect(response.status, JSON.stringify(headers)).toBe(403);
        expect(((await response.json()) as { code: string }).code).toBe('CROSS_ORIGIN_REQUEST');
      }
      expect(bff.gateway.requests, 'a refused request reached the Gateway').toHaveLength(0);
      const allowed: Array<Record<string, string>> = [{ Origin: base.origin, 'Sec-Fetch-Site': 'same-origin' }, {}];
      for (const headers of allowed) {
        expect((await post(headers)).status, JSON.stringify(headers)).toBe(200);
      }
      const read = await bff.fetch('/api/orders', { headers: { cookie, Origin: 'https://evil.example', 'Sec-Fetch-Site': 'cross-site' } });
      expect(read.status).toBe(200);
      const login = await bff.fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: 'https://evil.example' }, body: '{"username":"operator","password":"x"}' });
      expect(login.status, 'login CSRF').toBe(403);
    });

    it('R-local: an unreadable login body is the BFF\'s own 400 problem and the Gateway is never called', async () => {
      installAllSuccess(bff.gateway);
      const response = await bff.fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"username": ' });
      expect(response.status).toBe(400);
      expect(((await response.json()) as { code: string }).code).toBe('VALIDATION_FAILED');
      expect(bff.gateway.requests).toHaveLength(0);
    });

    it('R-relay: an id is path-encoded and can never reach another Gateway path', async () => {
      const cookie = await signIn(bff);
      bff.gateway.requests.length = 0;
      await bff.fetch('/api/orders/..%2Fstock', { headers: { cookie } });
      await bff.fetch('/api/invoices/..%2F..%2Fcredits/payments', { method: 'POST', headers: { cookie, 'Content-Type': 'application/json' }, body: '{}' });
      const urls = bff.gateway.requests.map((r) => r.url);
      expect(urls.filter((url) => url === '/stock' || url === '/credits' || url.startsWith('/stock') || url.startsWith('/credits')), 'an id escaped to another Gateway path').toEqual([]);
      expect(urls.every((url) => url.startsWith('/orders/') || url.startsWith('/invoices/')), `unexpected upstream paths: ${urls.join(', ')}`).toBe(true);
    });

    it('R-csrf: the check runs on every path the router can reach: a percent-encoded path (/%61pi/..., /ap%69/...) is refused like /api/... and never reaches the Gateway or sets a session', async () => {
      const cookie = await signIn(bff);
      bff.gateway.requests.length = 0;
      const targets = ['/api/stock/replenish', '/%61pi/stock/replenish', '/ap%69/stock/replenish', '/%61%70%69/stock/replenish'];
      for (const target of targets) {
        for (const headers of [{ Origin: 'https://evil.example' }, { 'Sec-Fetch-Site': 'same-site' }, { 'Sec-Fetch-Site': 'cross-site' }] as Array<Record<string, string>>) {
          const response = await rawRequest(bff.baseUrl, 'POST', target, { cookie, 'Content-Type': 'application/json', ...headers }, '{}');
          expect(response.status, `${target} ${JSON.stringify(headers)}`).toBe(403);
          expect((JSON.parse(response.body) as { code: string }).code).toBe('CROSS_ORIGIN_REQUEST');
        }
      }
      const loginViaEncodedPath = await rawRequest(bff.baseUrl, 'POST', '/%61pi/auth/login', { 'Content-Type': 'application/x-www-form-urlencoded', Origin: 'https://evil.example', 'Sec-Fetch-Site': 'cross-site' }, 'username=attacker&password=attackers-own');
      expect(loginViaEncodedPath.status, 'login CSRF through an encoded path').toBe(403);
      expect([loginViaEncodedPath.headers['set-cookie']].flat().filter(Boolean), 'a refused login set a cookie').toEqual([]);
      const sameSitePlainText = await rawRequest(bff.baseUrl, 'POST', '/ap%69/orders', { cookie, 'Content-Type': 'text/plain', 'Sec-Fetch-Site': 'same-site', Origin: 'https://sibling.example' }, '{"retailerCode":"A"}');
      expect(sameSitePlainText.status, 'same-site text/plain order through an encoded path').toBe(403);
      expect(bff.gateway.requests, 'a refused request reached the Gateway').toHaveLength(0);
    });

    it('R-csrf: the Origin check compares the whole origin: the same host over another scheme or port is refused', async () => {
      const cookie = await signIn(bff);
      bff.gateway.requests.length = 0;
      const own = new URL(bff.baseUrl);
      const siblings = [`https://${own.host}`, `http://${own.hostname}:${Number(own.port) + 1}`, `http://${own.hostname}`];
      for (const origin of siblings) {
        const response = await bff.fetch('/api/stock/replenish', { method: 'POST', headers: { cookie, 'Content-Type': 'application/json', Origin: origin }, body: '{}' });
        expect(response.status, `Origin ${origin}`).toBe(403);
      }
      expect(bff.gateway.requests).toHaveLength(0);
      const same = await bff.fetch('/api/stock/replenish', { method: 'POST', headers: { cookie, 'Content-Type': 'application/json', Origin: own.origin }, body: '{}' });
      expect(same.status, 'the identical origin passes').toBe(200);
    });

    it('R-csrf: a mutation that does not declare application/json is the BFF\'s own 415 on every path and never reaches the Gateway; a bodiless mutation and a JSON one with a charset pass', async () => {
      const cookie = await signIn(bff);
      bff.gateway.requests.length = 0;
      const wrong: Array<[string, string, Record<string, string>, string]> = [
        ['/api/auth/login', 'urlencoded login', { 'Content-Type': 'application/x-www-form-urlencoded' }, 'username=operator&password=x'],
        ['/api/orders', 'text/plain order', { cookie, 'Content-Type': 'text/plain' }, '{"retailerCode":"A"}'],
        ['/%61pi/orders', 'text/plain order via an encoded path', { cookie, 'Content-Type': 'text/plain' }, '{"retailerCode":"A"}'],
        ['/ap%69/auth/login', 'multipart login via an encoded path', { 'Content-Type': 'multipart/form-data; boundary=x' }, '--x--'],
        ['/api/orders', 'a body with no Content-Type', { cookie }, '{"retailerCode":"A"}'],
      ];
      for (const [target, what, headers, body] of wrong) {
        const response = await rawRequest(bff.baseUrl, 'POST', target, headers, body);
        expect(response.status, what).toBe(415);
        expect(String(response.headers['content-type'])).toContain('application/problem+json');
        expect((JSON.parse(response.body) as { code: string }).code, what).toBe('UNSUPPORTED_MEDIA_TYPE');
        expect([response.headers['set-cookie']].flat().filter(Boolean), `${what} set a cookie`).toEqual([]);
      }
      expect(bff.gateway.requests, 'a refused request reached the Gateway').toHaveLength(0);
      const bodiless = await rawRequest(bff.baseUrl, 'POST', '/api/auth/logout', { cookie });
      expect(bodiless.status, 'a mutation with no body and no Content-Type').toBe(200);
      const withCharset = await bff.fetch('/api/stock/replenish', { method: 'POST', headers: { cookie, 'Content-Type': 'Application/JSON; charset=utf-8' }, body: '{}' });
      expect(withCharset.status, 'application/json with a charset').toBe(200);
    });

    it('R-relay: an id that is empty, a dot segment, or holds a path or query separator once decoded is the BFF\'s own 400 and never reaches the Gateway; a plain id is encoded as one segment', async () => {
      const cookie = await signIn(bff);
      bff.gateway.requests.length = 0;
      const refused: Array<[string, string]> = [
        ['GET', '/api/orders/..'],
        ['GET', '/api/orders/%2E%2E'],
        ['GET', '/api/orders/%2e%2e'],
        ['GET', '/api/orders/.'],
        ['GET', '/api/orders/%2E'],
        ['GET', '/api/orders/x%3Fy=1'],
        ['GET', '/api/orders/..%2Fstock'],
        ['POST', '/api/invoices/../payments'],
        ['POST', '/api/invoices/%2E%2E/payments'],
        ['POST', '/api/invoices/./payments'],
        ['POST', '/api/invoices/..%2F..%2Fcredits/payments'],
      ];
      for (const [method, target] of refused) {
        const response = await rawRequest(bff.baseUrl, method, target, { cookie, 'Content-Type': 'application/json' }, method === 'POST' ? '{}' : undefined);
        expect(response.status, `${method} ${target}`).toBe(400);
        expect(String(response.headers['content-type'])).toContain('application/problem+json');
        expect((JSON.parse(response.body) as { code: string }).code, `${method} ${target}`).toBe('VALIDATION_FAILED');
      }
      // A decoded `?` also ends the router's path: `/api/invoices/x%3Fy/payments` is then `/api/invoices/x`, which is no route at all (the 404 problem).
      const cut = await rawRequest(bff.baseUrl, 'POST', '/api/invoices/x%3Fy/payments', { cookie, 'Content-Type': 'application/json' }, '{}');
      expect(cut.status, 'an invoice id cut by a decoded ? is answered by no route').toBe(404);
      expect(bff.gateway.requests.map((r) => `${r.method} ${r.url}`), 'a refused id reached the Gateway').toEqual([]);
      await rawRequest(bff.baseUrl, 'GET', '/api/orders/a%20b.c', { cookie }); // (the fake Gateway has no such order: its own 599 is irrelevant, the path it was asked for is not)
      expect(bff.gateway.requests.map((r) => `${r.method} ${r.url}`)).toEqual(['GET /orders/a%20b.c']);
    });

    it('R-local: an unreachable Gateway answers the BFF\'s own 502 problem naming the cause, not the Gateway\'s words', async () => {
      const cookie = await signIn(bff);
      await bff.gateway.stop();
      const response = await bff.fetch('/api/orders', { headers: { cookie } });
      expect(response.status).toBe(502);
      expect(response.headers.get('content-type')).toContain('application/problem+json');
      const body = (await response.json()) as { code: string; detail: string };
      expect(body.code).toBe('GATEWAY_UNREACHABLE');
      expect(body.detail).toContain('could not be reached');
      expect(body.detail, 'the browser-facing detail names the internal Gateway address').not.toContain(new URL(bff.gateway.baseUrl).host);
    });

    it('R-stream: a frame reaches the client while the upstream is still open; Last-Event-ID, orderId and the bearer token reach the Gateway', async () => {
      const cookie = await signIn(bff);
      let upstreamRes: import('node:http').ServerResponse | undefined;
      bff.gateway.on('GET', '/orders/stream', (_req, res) => {
        upstreamRes = res;
        res.writeHead(200, { 'Content-Type': 'text/event-stream' });
        res.write('event: stream.ready\ndata: {"cursor":"0"}\n\n');
      });
      const stream = await openStream(`${bff.baseUrl}/api/orders/stream?orderId=${ORDER_ID}`, { cookie, 'Last-Event-ID': '1755511234901-18', Accept: 'text/event-stream' });
      try {
        expect(stream.status).toBe(200);
        expect(String(stream.headers['content-type'])).toContain('text/event-stream');
        expect(stream.headers['cache-control'], 'an intermediary may transform or cache the stream').toBe('no-cache, no-transform');
        expect(stream.headers['x-accel-buffering'], 'a buffering reverse proxy may hold frames back').toBe('no');
        await stream.waitFor('event: stream.ready');
        expect(bff.gateway.open.size, 'the upstream response must still be open when the first frame arrives').toBe(1);
        upstreamRes!.write('id: 7\nevent: order.update\ndata: {"n":2}\n\n');
        await stream.waitFor('event: order.update');
        expect(bff.gateway.open.size, 'the upstream is still open after the second frame').toBe(1);
        const seen = bff.gateway.requests.find((r) => r.url.startsWith('/orders/stream'))!;
        expect(seen.url).toBe(`/orders/stream?orderId=${ORDER_ID}`);
        expect(seen.headers['last-event-id']).toBe('1755511234901-18');
        expect(seen.headers['authorization']).toBe(`Bearer ${TEST_JWT}`);
        expect(stream.chunks.join('')).not.toContain(TEST_JWT);
      } finally {
        stream.close();
      }
    });

    it('R-stream: no Last-Event-ID header is sent upstream when the client sent none', async () => {
      const cookie = await signIn(bff);
      bff.gateway.on('GET', '/orders/stream', (_req, res) => {
        res.writeHead(200, { 'Content-Type': 'text/event-stream' });
        res.write('event: stream.ready\ndata: {}\n\n');
      });
      const stream = await openStream(`${bff.baseUrl}/api/orders/stream`, { cookie });
      try {
        await stream.waitFor('stream.ready');
        const seen = bff.gateway.requests.find((r) => r.url.startsWith('/orders/stream'))!;
        expect(seen.url).toBe('/orders/stream');
        expect('last-event-id' in seen.headers).toBe(false);
      } finally {
        stream.close();
      }
    });

    it('R-stream: each frame reaches the client before the next one is written upstream, with compression offered (nothing is held back by the proxy)', async () => {
      const cookie = await signIn(bff);
      let upstreamRes: import('node:http').ServerResponse | undefined;
      bff.gateway.on('GET', '/orders/stream', (_req, res) => {
        upstreamRes = res;
        res.writeHead(200, { 'Content-Type': 'text/event-stream' });
        res.write(': open\n\n');
      });
      const stream = await openStream(`${bff.baseUrl}/api/orders/stream`, { cookie, 'Accept-Encoding': 'gzip, deflate, br' });
      try {
        await stream.waitFor(': open');
        expect(stream.headers['content-encoding'], 'the event stream must not be compressed (a compressor buffers)').toBeUndefined();
        for (let i = 1; i <= 5; i += 1) {
          upstreamRes!.write(`id: c${i}\nevent: order.updated\ndata: {"n":${i}}\n\n`);
          await stream.waitFor(`id: c${i}\n`, 3000); // the next frame is not written until this one has arrived
        }
      } finally {
        stream.close();
      }
    });

    it('R-stream: a real EventSource dropped by the Gateway reconnects THROUGH the proxy and resumes with the last id it saw', async () => {
      const cookie = await signIn(bff);
      const upstreamIds: Array<string | undefined> = [];
      bff.gateway.on('GET', '/orders/stream', (req, res) => {
        upstreamIds.push(req.headers['last-event-id'] as string | undefined);
        res.writeHead(200, { 'Content-Type': 'text/event-stream' });
        res.write(`retry: 50\nid: c${upstreamIds.length}\nevent: order.updated\ndata: {}\n\n`);
        if (upstreamIds.length === 1) res.end(); // the Gateway drops the first connection; the second stays open
      });
      const source = new EventSource(`${bff.baseUrl}/api/orders/stream`, { fetch: (input, init) => fetch(input, { ...init, headers: { ...Object.fromEntries(new Headers(init?.headers)), cookie } }) });
      try {
        await eventually(() => upstreamIds.length >= 2, 5000, 'the EventSource never reconnected through the proxy');
        expect(upstreamIds, 'first connection carries no cursor; the reconnect resumes from the last id the client saw').toEqual([undefined, 'c1']);
      } finally {
        source.close();
      }
    });

    it('R-stream: closing the client connection aborts the upstream within a bounded time', async () => {
      const cookie = await signIn(bff);
      bff.gateway.on('GET', '/orders/stream', (_req, res) => {
        res.writeHead(200, { 'Content-Type': 'text/event-stream' });
        res.write('event: stream.ready\ndata: {}\n\n');
      });
      const stream = await openStream(`${bff.baseUrl}/api/orders/stream`, { cookie });
      await stream.waitFor('stream.ready');
      expect(bff.gateway.open.size).toBe(1);
      stream.close();
      const took = await eventually(() => bff.gateway.open.size === 0, 3000, 'the upstream connection stayed open after the client left');
      expect(took).toBeLessThan(3000);
    });

    it('R-stream: a client that leaves before the Gateway answers the stream\'s headers still has the upstream aborted within a bounded time', async () => {
      const cookie = await signIn(bff);
      bff.gateway.on('GET', '/orders/stream', () => undefined); // the Gateway accepts the request and never answers its headers
      const req = httpRequest(`${bff.baseUrl}/api/orders/stream`, { headers: { cookie } });
      req.on('error', () => undefined);
      req.end();
      try {
        await eventually(() => bff.gateway.requests.some((r) => r.url.startsWith('/orders/stream')) && bff.gateway.open.size === 1, 3000, 'the upstream request never arrived');
        req.destroy(); // the client leaves while the BFF is still waiting for the upstream's headers
        const took = await eventually(() => bff.gateway.open.size === 0, 3000, 'the upstream connection stayed open after the client left before the upstream answered its headers');
        expect(took).toBeLessThan(3000);
      } finally {
        req.destroy();
      }
    });

    it('R-stream: a client that disconnects in the same tick it sends the request opens no upstream connection', async () => {
      const cookie = await signIn(bff);
      bff.gateway.on('GET', '/orders/stream', () => undefined); // were it ever reached, the Gateway would accept and never answer its headers
      const { port } = new URL(bff.baseUrl);
      const before = bff.gateway.requests.filter((r) => r.url.startsWith('/orders/stream')).length;
      const enteredBefore = bff.streamRouteEntries();
      const CLIENTS = 3;
      for (let i = 0; i < CLIENTS; i++) {
        const socket = connect(Number(port), '127.0.0.1');
        socket.on('error', () => undefined);
        socket.on('connect', () => {
          socket.write(`GET /api/orders/stream HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nCookie: ${cookie}\r\n\r\n`);
          socket.destroy(); // gone before the BFF has read the session
        });
      }
      await new Promise((done) => setTimeout(done, 1500));
      // The premise: every one of those requests REACHED the stream route (which logs its entry before it reads the session). Without it, the two
      // assertions below pass just as well for a request that never got there (a typo in the path, a route that moved, a socket closed before it was read).
      expect(bff.streamRouteEntries() - enteredBefore, 'the premise: the same-tick requests did not reach the stream route, so nothing below says anything about it').toBe(CLIENTS);
      expect(bff.gateway.open.size, 'the upstream connection stayed open for a client that had already left').toBe(0);
      expect(bff.gateway.requests.filter((r) => r.url.startsWith('/orders/stream')).length - before, 'an upstream stream request was opened for a client that had already left').toBe(0);
    });

    it('R-stream: a stream with no session answers the BFF\'s own 401 problem and opens no upstream connection', async () => {
      installAllSuccess(bff.gateway);
      const response = await bff.fetch('/api/orders/stream');
      expect(response.status).toBe(401);
      expect(((await response.json()) as { code: string }).code).toBe('UNAUTHENTICATED');
      expect(bff.gateway.requests).toHaveLength(0);
    });

    it('R-stream: an unreachable Gateway answers the BFF\'s own 502 problem for the stream, not a dead connection', async () => {
      const cookie = await signIn(bff);
      await bff.gateway.stop();
      const response = await bff.fetch('/api/orders/stream', { headers: { cookie } });
      expect(response.status).toBe(502);
      expect(((await response.json()) as { code: string }).code).toBe('GATEWAY_UNREACHABLE');
    });

    it('R-stream: a Gateway refusal of the stream is relayed as the Gateway\'s problem document', async () => {
      const cookie = await signIn(bff);
      const body = problem(401, 'Token expired.', 'Unauthorized', 'TOKEN_EXPIRED');
      bff.gateway.on('GET', '/orders/stream', (_req, res) => {
        res.writeHead(401, { 'Content-Type': 'application/problem+json' });
        res.end(JSON.stringify(body));
      });
      const response = await bff.fetch('/api/orders/stream', { headers: { cookie } });
      expect(response.status).toBe(401);
      expect(await response.json()).toEqual(body);
    });
  });
}
