// The login page: what a user sees and what the BFF is sent. The error TEXT is proven for every status by the
// behavioural sweep (error-text.sweep.spec.ts); these cases pin the flow around it.
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { json, mount, problemResponse, sleep } from './testing/browser-harness';
import { buttonNamed, byLabel, typeInto } from './testing/page-sweep';
import { realProblem } from '../server/testing/gateway-script';
import { orderPage } from './testing/orders-fixtures';

const SESSION = { authenticated: true, username: 'operator', displayName: 'Order-To-Cash Operator', roles: ['operator'] };

describe('the login page', () => {
  it('shows the stack label, the username prefilled with the operator account, and an empty password', async () => {
    const m = await mount('/login', () => json({}));
    expect(m.text()).toContain('#9 · Python / Angular');
    expect(byLabel('Username').value).toBe('operator');
    expect(byLabel('Password').value).toBe('');
    expect(m.requests, 'the login page must not call the BFF before the user acts').toEqual([]);
  });

  it('sends the credentials as JSON to POST /api/auth/login and, on success, lands on /orders with no further session request', async () => {
    const bodies: string[] = [];
    const m = await mount('/login', (key, init) => {
      if (key === 'POST /api/auth/login') {
        bodies.push(String(init?.body));
        return json(SESSION);
      }
      return key.startsWith('GET /api/orders') ? json(orderPage(1, 20, 0, 0)) : json({ items: [] }); // the order list the sign-in lands on
    });
    typeInto(byLabel('Password'), 'secret');
    buttonNamed('Sign in').click();
    await m.settle();
    expect(bodies).toEqual(['{"username":"operator","password":"secret"}']);
    expect(m.router.url).toBe('/orders');
    expect(m.requests.filter((key) => key.includes('/api/auth/')), 'the session returned by login primes the cache: the guard asks nothing more').toEqual(['POST /api/auth/login']);
    expect(m.text()).toContain('Order-To-Cash Operator');
  });

  it('does not send a request while the password is empty', async () => {
    const m = await mount('/login', () => json(SESSION));
    buttonNamed('Sign in').click();
    await m.settle();
    expect(m.requests).toEqual([]);
  });

  it('a refusal stays on the page in the Gateway\'s own words, the button works again, and a second attempt can succeed', async () => {
    let attempt = 0;
    const m = await mount('/login', () => {
      attempt += 1;
      return attempt === 1 ? problemResponse(401, { title: 'Unauthorized', detail: 'The username or password is wrong.', code: 'INVALID_CREDENTIALS', status: 401 }) : json(SESSION);
    });
    typeInto(byLabel('Password'), 'nope');
    buttonNamed('Sign in').click();
    await m.settle();
    expect(m.router.url, 'a 401 on the login page must not loop back to /login or leave it').toBe('/login');
    expect(document.querySelector('[data-testid="login-error"]')?.textContent?.trim()).toBe('The username or password is wrong.');
    expect(buttonNamed('Sign in').disabled).toBe(false);
    typeInto(byLabel('Password'), 'right');
    buttonNamed('Sign in').click();
    await m.settle();
    expect(m.router.url).toBe('/orders');
  });

  it('shows the title when the refusal has no detail, and never the title while a detail exists', async () => {
    const m = await mount('/login', () => problemResponse(429, { title: 'Too many sign-in attempts', status: 429, code: 'TOO_MANY_REQUESTS' }));
    typeInto(byLabel('Password'), 'x');
    buttonNamed('Sign in').click();
    await m.settle();
    expect(document.querySelector('[data-testid="login-error"]')?.textContent?.trim()).toBe('Too many sign-in attempts');
  });

  it('the fixed fallback appears only when no problem document came back at all (an HTML 502, or a request that never got an answer)', async () => {
    for (const answer of [() => new Response('<html>Bad gateway</html>', { status: 502, headers: { 'Content-Type': 'text/html' } }), () => Promise.reject(new TypeError('Failed to fetch'))]) {
      TestBed.resetTestingModule();
      const m = await mount('/login', answer);
      typeInto(byLabel('Password'), 'x');
      buttonNamed('Sign in').click();
      await m.settle();
      expect(document.querySelector('[data-testid="login-error"]')?.textContent?.trim()).toBe('Sign-in failed.');
    }
  });

  it('disables the button while the request is in flight, so a double click sends one request', async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const m = await mount('/login', async () => {
      await gate;
      return json(SESSION);
    });
    typeInto(byLabel('Password'), 'x');
    buttonNamed('Sign in').click();
    await sleep(30);
    m.harness.detectChanges();
    expect(buttonNamed('Sign in').disabled).toBe(true);
    buttonNamed('Sign in').click();
    release();
    await m.settle();
    expect(m.requests.filter((key) => key.includes('/api/auth/')), 'a double click sends one sign-in').toEqual(['POST /api/auth/login']);
  });

  it('shows the detail of the REAL Gateway\'s refusal (captured from a running Gateway), not its title', async () => {
    const real = JSON.parse(realProblem('login-401')) as { title: string; detail: string };
    expect(real.detail, 'the fixture must have a detail that differs from its title, or this test proves nothing').not.toBe(real.title);
    const m = await mount('/login', () => new Response(realProblem('login-401'), { status: 401, headers: { 'Content-Type': 'application/problem+json' } }));
    typeInto(byLabel('Password'), 'wrong');
    buttonNamed('Sign in').click();
    await m.settle();
    expect(document.querySelector('[data-testid="login-error"]')?.textContent?.trim()).toBe(real.detail);
  });
});
