import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineBffContract, setCookieLine, sessionCookie, signIn } from './testing/bff-contract';
import { SESSION_PASSWORD, TEST_JWT, TEST_PASSWORD, installAllSuccess, problem, realProblem, ORDER_ID } from './testing/gateway-script';
import { startBff, type Bff } from './testing/harness';
import { sendJson } from './testing/fake-gateway';
import { renderLogCalls } from './testing/log-capture';

function stubDefaults() {
  vi.stubEnv('WEB_SESSION_PASSWORD', SESSION_PASSWORD);
  vi.stubEnv('WEB_COOKIE_SECURE', '');
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// The contract (src/server/testing/bff-contract.ts) holds of the BFF assembled in-process over h3 ...
defineBffContract('BFF in-process (h3 app over a real socket)', async () => {
  stubDefaults();
  return startBff((name, value) => vi.stubEnv(name, value));
});

// ... and of the PRODUCTION build: src/build/production-bff.spec.ts runs the same contract against `node dist/analog/server/index.mjs`.

describe('BFF configuration and session variants (in-process)', () => {
  let bff: Bff;
  afterEach(async () => {
    await bff?.stop();
  });

  it('R-session: WEB_COOKIE_SECURE=false drops Secure (and only Secure) from the session cookie', async () => {
    stubDefaults();
    vi.stubEnv('WEB_COOKIE_SECURE', 'false');
    bff = await startBff((n, v) => vi.stubEnv(n, v));
    installAllSuccess(bff.gateway);
    const response = await bff.fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'operator', password: TEST_PASSWORD }) });
    const line = setCookieLine(response)!;
    expect(line).not.toMatch(/;\s*Secure/i);
    expect(line).toMatch(/;\s*HttpOnly/i);
    expect(line).toMatch(/;\s*SameSite=Lax/i);
  });

  it('R-session: a WEB_SESSION_PASSWORD shorter than 32 characters fails closed, naming the setting', async () => {
    stubDefaults();
    vi.stubEnv('WEB_SESSION_PASSWORD', 'too-short');
    bff = await startBff((n, v) => vi.stubEnv(n, v));
    installAllSuccess(bff.gateway);
    const response = await bff.fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'operator', password: TEST_PASSWORD }) });
    expect(response.status).toBe(500);
    expect(sessionCookie(response), 'no session may be issued with a weak password').toBeUndefined();
    expect(await response.text()).not.toContain(TEST_JWT);
  });

  it('R-session: with WEB_SESSION_PASSWORD unset a random per-process key is used, with a warning, and sessions still round-trip', async () => {
    stubDefaults();
    vi.stubEnv('WEB_SESSION_PASSWORD', '');
    delete process.env['WEB_SESSION_PASSWORD'];
    (globalThis as Record<symbol, unknown>)[Symbol.for('otc.web.generatedSessionPassword')] = undefined;
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    bff = await startBff((n, v) => vi.stubEnv(n, v));
    const cookie = await signIn(bff);
    const response = await bff.fetch('/api/auth/session', { headers: { cookie } });
    expect(((await response.json()) as { authenticated: boolean }).authenticated).toBe(true);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0]![0])).toContain('WEB_SESSION_PASSWORD is not set');
    expect(renderLogCalls([warn])).not.toContain(TEST_JWT);
  });

  it('R-session: an expired session is no session, and a proxied call with it answers the BFF\'s 401 and never reaches the Gateway', async () => {
    stubDefaults();
    bff = await startBff((n, v) => vi.stubEnv(n, v));
    installAllSuccess(bff.gateway);
    bff.gateway.on('POST', '/auth/login', (_req, res) => sendJson(res, 200, { accessToken: TEST_JWT, tokenType: 'Bearer', expiresIn: -5 }));
    const login = await bff.fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'operator', password: TEST_PASSWORD }) });
    const cookie = sessionCookie(login)!;
    bff.gateway.requests.length = 0;
    expect(await (await bff.fetch('/api/auth/session', { headers: { cookie } })).json()).toEqual({ authenticated: false });
    const proxied = await bff.fetch('/api/orders', { headers: { cookie } });
    expect(proxied.status).toBe(401);
    expect(bff.gateway.requests).toHaveLength(0);
  });

  it('R-local: a Gateway that does not answer within WEB_GATEWAY_TIMEOUT_MS gets the BFF\'s own 504 problem', async () => {
    stubDefaults();
    vi.stubEnv('WEB_GATEWAY_TIMEOUT_MS', '150');
    bff = await startBff((n, v) => vi.stubEnv(n, v));
    const cookie = await signIn(bff);
    const logged = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    bff.gateway.on('GET', '/orders', () => undefined); // never answers
    const response = await bff.fetch('/api/orders', { headers: { cookie } });
    expect(response.status).toBe(504);
    const body = (await response.json()) as { code: string; detail: string };
    expect(body.code).toBe('GATEWAY_TIMEOUT');
    expect(body.detail).toContain('150 ms');
    expect(body.detail, 'the browser-facing detail names the internal Gateway address').not.toContain(new URL(bff.gateway.baseUrl).host);
    expect(renderLogCalls([logged]), 'the Gateway address belongs in a server log line').toContain(bff.gateway.baseUrl);
  });

  it('R-local: an unreachable Gateway is answered without its address, and the address is logged on the server', async () => {
    stubDefaults();
    bff = await startBff((n, v) => vi.stubEnv(n, v));
    const cookie = await signIn(bff);
    const logged = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    await bff.gateway.stop();
    const response = await bff.fetch('/api/orders', { headers: { cookie } });
    expect(response.status).toBe(502);
    const body = (await response.json()) as { detail: string };
    expect(body.detail, 'the browser-facing detail names the internal Gateway address').not.toContain(new URL(bff.gateway.baseUrl).host);
    expect(body.detail).not.toContain('http://');
    expect(renderLogCalls([logged]), 'the Gateway address belongs in a server log line').toContain(bff.gateway.baseUrl);
  });

  it('R-session: the JWT is in no log line (console.log/info/warn/error/debug) across login, a proxied call, a refusal and a stream', async () => {
    stubDefaults();
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((level) => vi.spyOn(console, level).mockImplementation(() => undefined));
    bff = await startBff((n, v) => vi.stubEnv(n, v));
    const cookie = await signIn(bff);
    await bff.fetch('/api/orders', { headers: { cookie } });
    bff.gateway.on('GET', '/stock', (_req, res) => {
      res.writeHead(500, { 'Content-Type': 'application/problem+json' });
      res.end(JSON.stringify(problem(500, 'boom', 'Internal')));
    });
    await bff.fetch('/api/stock', { headers: { cookie } });
    await bff.fetch(`/api/orders/${ORDER_ID}`, { headers: { cookie } });
    const logged = renderLogCalls(spies);
    expect(logged, 'a log line carries the JWT').not.toContain(TEST_JWT);
    expect(logged, 'a log line carries the JWT signature').not.toContain(TEST_JWT.split('.')[2]!);
  });

  it('R-relay: problem documents captured from the REAL Gateway are relayed byte for byte, with their status and content type (login 401, no-token 401, validation 400 with errors[])', async () => {
    stubDefaults();
    bff = await startBff((n, v) => vi.stubEnv(n, v));
    const cookie = await signIn(bff);
    const cases: Array<[string, string, string, number, 'login-401' | 'orders-no-token-401' | 'order-bad-id-400']> = [
      ['POST', '/auth/login', '/api/auth/login', 401, 'login-401'],
      ['GET', '/orders', '/api/orders', 401, 'orders-no-token-401'],
      ['GET', '/orders/not-a-uuid', '/api/orders/not-a-uuid', 400, 'order-bad-id-400'],
    ];
    for (const [method, upstream, browserPath, status, fixture] of cases) {
      const body = realProblem(fixture);
      bff.gateway.on(method, upstream, (_req, res) => {
        res.writeHead(status, { 'Content-Type': 'application/problem+json' });
        res.end(body);
      });
      const response = await bff.fetch(browserPath, { method, headers: { cookie, 'Content-Type': 'application/json' }, body: method === 'POST' ? '{"username":"operator","password":"x"}' : undefined });
      expect(response.status, fixture).toBe(status);
      expect(await response.text(), `${fixture}: the relayed body is not the captured one`).toBe(body);
    }
  });
});
