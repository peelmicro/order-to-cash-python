import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { ROUTE_FILES } from '../../server/testing/harness';
import { ApiError } from '../lib/problem';
import { API_FETCH, ApiClient } from './api-client';

interface Sent {
  method: string;
  url: string;
  headers: Record<string, string>;
  body?: string;
}

function client(answer: (sent: Sent) => Response) {
  const sent: Sent[] = [];
  const seam: typeof fetch = async (input, init) => {
    const record = { method: init?.method ?? 'GET', url: String(input), headers: (init?.headers ?? {}) as Record<string, string>, body: init?.body as string | undefined };
    sent.push(record);
    return answer(record);
  };
  TestBed.configureTestingModule({ providers: [{ provide: API_FETCH, useValue: seam }] });
  return { api: TestBed.inject(ApiClient), sent };
}

const ok = (body: unknown = {}, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

describe('ApiClient is the single seam to the BFF', () => {
  it('every request it can make is a route of the BFF (derived from src/server/routes, matched by method and path)', async () => {
    const { api, sent } = client(() => ok());
    await api.session();
    await api.login({ username: 'u', password: 'p' });
    await api.logout();
    await api.listOrders({ page: 1 });
    await api.getOrder('abc');
    await api.placeOrder({} as never);
    await api.listStock();
    await api.replenishStock({} as never);
    await api.listInvoices();
    await api.registerPayment('inv-1', {} as never);
    await api.listCredits();
    await api.catalogProducts();
    await api.catalogRetailers();
    await api.catalogCompanies();
    const routes = ROUTE_FILES.filter((file) => !file.name.includes('**')).map((file) => ({ method: (file.method ?? 'get').toUpperCase(), pattern: new RegExp(`^${file.name.replace(/\{[^}]+\}/g, '[^/]+')}$`) }));
    const unmatched = sent.filter((s) => !routes.some((r) => r.method === s.method && r.pattern.test(s.url.split('?')[0]!)));
    expect(unmatched, 'requests the client can make that no BFF route answers').toEqual([]);
    expect(sent.length).toBe(14);
  });

  it('sends JSON with a Content-Type only when there is a body, never an Authorization header, same-origin credentials', async () => {
    const { api, sent } = client(() => ok());
    await api.listOrders();
    await api.login({ username: 'u', password: 'p' });
    expect(sent[0]!.headers['Content-Type']).toBeUndefined();
    expect(sent[1]!.headers['Content-Type']).toBe('application/json');
    expect(sent[1]!.body).toBe('{"username":"u","password":"p"}');
    for (const s of sent) expect(Object.keys(s.headers).map((h) => h.toLowerCase())).not.toContain('authorization');
  });

  it('builds the query string from defined values only', async () => {
    const { api, sent } = client(() => ok());
    await api.listOrders({ page: 2, pageSize: 20, orderReference: undefined, retailerCode: '' });
    expect(sent[0]!.url).toBe('/api/orders?page=2&pageSize=20');
  });

  it('repeats a parameter for an array value (openapi.yaml: the status filter is exploded)', async () => {
    const { api, sent } = client(() => ok());
    await api.listOrders({ status: ['placed', 'cancelled'], page: 1 });
    expect(sent[0]!.url).toBe('/api/orders?status=placed&status=cancelled&page=1');
  });

  it('forwards the Idempotency-Key header on place order, and encodes path parameters', async () => {
    const { api, sent } = client(() => ok());
    await api.placeOrder({} as never, 'key-1');
    await api.getOrder('a/b');
    expect(sent[0]!.headers['Idempotency-Key']).toBe('key-1');
    expect(sent[1]!.url).toBe('/api/orders/a%2Fb');
  });

  it('keeps the status and Retry-After of a 202 (an order not projected yet)', async () => {
    const { api } = client(() => ok({ status: 'pending' }, 202, { 'Retry-After': '3' }));
    const response = await api.getOrder('id');
    expect([response.status, response.retryAfterSeconds]).toEqual([202, 3]);
  });

  it('throws ApiError carrying the problem document of a refusal as its parsed body', async () => {
    const { api } = client(() => new Response('{"title":"Conflict","detail":"Already paid.","code":"INVOICE_ALREADY_PAID"}', { status: 409, headers: { 'Content-Type': 'application/problem+json' } }));
    const error = await api.registerPayment('i', {} as never).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).problem).toEqual({ title: 'Conflict', detail: 'Already paid.', code: 'INVOICE_ALREADY_PAID' });
  });

  it('an empty success body is undefined, not a parse error', async () => {
    const { api } = client(() => new Response(null, { status: 204 }));
    expect((await api.listOrders()).data).toBeUndefined();
  });
});
