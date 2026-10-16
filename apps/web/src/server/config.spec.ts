// Server configuration (src/server/lib/config.ts), ported from #8's server/config.test.ts. Pure functions of an env object.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cookieSecure, DEFAULT_GATEWAY_TIMEOUT_MS, gatewayBaseUrl, gatewayTimeoutMs, MIN_SESSION_PASSWORD_LENGTH, sessionPassword } from './lib/config';

describe('gatewayBaseUrl', () => {
  it('reaches the Gateway on GATEWAY_PORT, and not on a sibling *_PORT (substitution)', () => {
    expect(gatewayBaseUrl({ GATEWAY_PORT: '4321', ORDERS_PORT: '1111', WEB_PORT: '2222', GATEWAY_HOST: '9999' })).toBe('http://localhost:4321');
  });

  it('defaults to port 3001, the Gateway port in .env.example, and an explicit GATEWAY_BASE_URL wins (trailing slashes dropped)', () => {
    expect(gatewayBaseUrl({})).toBe('http://localhost:3001');
    expect(gatewayBaseUrl({ GATEWAY_BASE_URL: 'http://gateway.internal:8080//', GATEWAY_PORT: '4321' })).toBe('http://gateway.internal:8080');
    expect(gatewayBaseUrl({ GATEWAY_BASE_URL: '   ', GATEWAY_PORT: '4321' }), 'a blank GATEWAY_BASE_URL is unset').toBe('http://localhost:4321');
  });
});

describe('sessionPassword', () => {
  afterEach(() => vi.restoreAllMocks());

  it('uses WEB_SESSION_PASSWORD when it is at least 32 characters, refuses a shorter one naming the setting', () => {
    const good = 'x'.repeat(MIN_SESSION_PASSWORD_LENGTH);
    expect(sessionPassword({ WEB_SESSION_PASSWORD: good })).toBe(good);
    expect(() => sessionPassword({ WEB_SESSION_PASSWORD: 'x'.repeat(MIN_SESSION_PASSWORD_LENGTH - 1) })).toThrow(/WEB_SESSION_PASSWORD must be at least 32 characters/);
  });

  it('with none set, uses ONE stable random per-process key (never a constant in the source), and warns once', () => {
    (globalThis as Record<symbol, unknown>)[Symbol.for('otc.web.generatedSessionPassword')] = undefined;
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const first = sessionPassword({});
    expect(sessionPassword({})).toBe(first);
    expect(first).toMatch(/^[0-9a-f]{64}$/);
    expect(warn).toHaveBeenCalledTimes(1);
    (globalThis as Record<symbol, unknown>)[Symbol.for('otc.web.generatedSessionPassword')] = undefined;
    expect(sessionPassword({}), 'a fresh process must not reuse a previous key').not.toBe(first);
  });
});

describe('cookieSecure and gatewayTimeoutMs', () => {
  it('the session cookie is Secure unless WEB_COOKIE_SECURE is exactly "false"', () => {
    expect([cookieSecure({}), cookieSecure({ WEB_COOKIE_SECURE: 'true' }), cookieSecure({ WEB_COOKIE_SECURE: '' }), cookieSecure({ WEB_COOKIE_SECURE: 'false' }), cookieSecure({ WEB_COOKIE_SECURE: 'False' })]).toEqual([true, true, true, false, true]);
  });

  it('the Gateway deadline defaults to 15 s and takes a positive integer from WEB_GATEWAY_TIMEOUT_MS', () => {
    expect(DEFAULT_GATEWAY_TIMEOUT_MS).toBe(15_000);
    expect([gatewayTimeoutMs({}), gatewayTimeoutMs({ WEB_GATEWAY_TIMEOUT_MS: '250' }), gatewayTimeoutMs({ WEB_GATEWAY_TIMEOUT_MS: '-1' }), gatewayTimeoutMs({ WEB_GATEWAY_TIMEOUT_MS: 'soon' })]).toEqual([15_000, 250, 15_000, 15_000]);
  });
});
