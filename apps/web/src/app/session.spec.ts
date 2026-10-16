// The session: the route guard, the signed-in shell, sign-out, and what a 401 from ANY BFF call does
// (#8 id 98's precondition: a 401 anywhere sends the user to /login, from queries and mutations alike).
import { describe, expect, it } from 'vitest';
import { ApiClient } from './api/api-client';
import { QUERY_CLIENT } from './session/signed-out';
import { json, mount, problemResponse } from './testing/browser-harness';
import { buttonNamed } from './testing/page-sweep';
import { TestBed } from '@angular/core/testing';
import { ApiError } from './lib/problem';

const SESSION = { authenticated: true, username: 'operator', displayName: 'Order-To-Cash Operator', roles: ['operator'] };
const signedIn = () => json(SESSION);

describe('the route guard', () => {
  it('sends a signed-out visitor from /orders to /login after exactly one session probe', async () => {
    const m = await mount('/orders', () => json({ authenticated: false }));
    expect(m.router.url).toBe('/login');
    expect(m.requests).toEqual(['GET /api/auth/session']);
  });

  it('lets a signed-in user in: the shell shows the user, the stack label and the navigation that exists', async () => {
    const m = await mount('/orders', signedIn);
    expect(m.router.url).toBe('/orders');
    const header = document.querySelector('header')!;
    expect(header.textContent).toContain('Order-To-Cash Operator');
    expect(header.textContent).toContain('#9 · Python / Angular');
    expect([...header.querySelectorAll('nav a')].map((a) => a.getAttribute('href'))).toEqual(['/orders', '/stock', '/billing']);
  });

  it('/ goes to /orders when signed in and on to /login when not', async () => {
    expect((await mount('/', signedIn)).router.url).toBe('/orders');
    TestBed.resetTestingModule();
    expect((await mount('/', () => json({ authenticated: false }))).router.url).toBe('/login');
  });

  it('a failing session probe does not hide itself behind a redirect: the shell is entered and shows the server\'s words', async () => {
    const m = await mount('/orders', () => problemResponse(503, { title: 'BFF down', detail: 'Session store unavailable.', status: 503 }));
    expect(m.router.url).toBe('/orders');
    expect(document.querySelector('[data-testid="session-error"]')?.textContent?.trim()).toBe('Session store unavailable.');
  });
});

describe('a 401 from any BFF call sends the user to /login, and nothing else does', () => {
  it('a query answered 401 (any page\'s read) leaves the page and drops the cached data', async () => {
    const m = await mount('/orders', (key) => (key === 'GET /api/orders' ? problemResponse(401, { title: 'Not signed in', status: 401 }) : signedIn()));
    expect(m.router.url).toBe('/orders');
    const api = TestBed.inject(ApiClient);
    await m.client.fetchQuery({ queryKey: ['orders'], queryFn: () => api.listOrders() }).catch((e: unknown) => e);
    await m.settle();
    expect(m.router.url).toBe('/login');
    expect(m.client.getQueryCache().findAll().length, 'the cache of the old session survived').toBe(0);
  });

  it('a mutation answered 401 leaves the page too', async () => {
    const m = await mount('/orders', (key) => (key === 'POST /api/auth/logout' ? problemResponse(401, { title: 'Not signed in', status: 401 }) : signedIn()));
    buttonNamed('Log out').click();
    await m.settle();
    expect(m.router.url).toBe('/login');
  });

  it.each([400, 403, 404, 409, 422, 500, 503])('a %i leaves the user where they are', async (status) => {
    const m = await mount('/orders', (key) => (key === 'GET /api/orders' ? problemResponse(status, { title: 'T', detail: 'D', status }) : signedIn()));
    const api = TestBed.inject(ApiClient);
    const error = await m.client.fetchQuery({ queryKey: ['orders', status], queryFn: () => api.listOrders() }).catch((e: unknown) => e);
    await m.settle();
    expect((error as ApiError).status).toBe(status);
    expect(m.router.url).toBe('/orders');
  });

  it('a 401 while on /login (a refused sign-in) does not navigate and does not clear what the page has cached', async () => {
    const m = await mount('/login', () => problemResponse(401, { title: 'Unauthorized', detail: 'Wrong.', status: 401 }));
    const api = TestBed.inject(ApiClient);
    m.client.setQueryData(['marker'], 'still here');
    await TestBed.inject(QUERY_CLIENT).fetchQuery({ queryKey: ['x'], queryFn: () => api.login({ username: 'a', password: 'b' }) }).catch(() => undefined);
    await m.settle();
    expect(m.router.url).toBe('/login');
    expect(m.client.getQueryData(['marker']), 'a refused sign-in dropped the cache as if a session had ended').toBe('still here');
  });
});

describe('signing out', () => {
  it('posts the logout, clears everything the old session cached, and lands on /login, whose guard-free page makes no request', async () => {
    const m = await mount('/orders', (key) => (key === 'POST /api/auth/logout' ? json({ authenticated: false }) : signedIn()));
    buttonNamed('Log out').click();
    await m.settle();
    expect(m.router.url).toBe('/login');
    expect(m.requests.filter((key) => key.includes('/api/auth/'))).toEqual(['GET /api/auth/session', 'POST /api/auth/logout']);
    const session = m.client.getQueryData(['session']);
    expect(session, 'after sign-out the cached session must say signed out').toEqual({ authenticated: false });
    expect(document.body.textContent).not.toContain('Order-To-Cash Operator');
  });
});
