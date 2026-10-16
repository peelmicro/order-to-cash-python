import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { Problem } from '../../shared/api-types';
import { sendJson, sendProblem, type FakeGateway } from './fake-gateway';

/** A JWT-shaped token with a distinctive middle, so a search for it finds only this value. */
export const TEST_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvcGVyYXRvci10ZXN0LWp3dCJ9.SIGNATURE_SENTINEL_9f3a7c1e';
export const TEST_PASSWORD = 'correct horse battery staple';
export const SESSION_PASSWORD = 'a-session-password-that-is-at-least-32-chars';

export const ME = { username: 'operator', displayName: 'Order-To-Cash Operator', roles: ['operator'] };

export function problem(status: number, detail: string | undefined, title: string, code = 'DOMAIN_ERROR'): Problem {
  const body: Problem = { type: 'about:blank', title, status, code, correlationId: '3f7b2f0e-6a52-4a4e-9d57-2f1d6a0f6a11', occurredAt: '2026-10-15T10:00:00.000Z' };
  if (detail !== undefined) body.detail = detail;
  return body;
}

/** A body for every Gateway operation the BFF proxies, shaped like the real ones. */
const OK_BODIES: Record<string, { status: number; body: unknown }> = {
  'GET /catalog/products': { status: 200, body: { items: [] } },
  'GET /catalog/retailers': { status: 200, body: { items: [] } },
  'GET /catalog/companies': { status: 200, body: { items: [] } },
  'GET /credits': { status: 200, body: { items: [], page: { page: 1, pageSize: 20, total: 0 } } },
  'GET /invoices': { status: 200, body: { items: [], page: { page: 1, pageSize: 20, total: 0 } } },
  'GET /orders': { status: 200, body: { items: [], page: { page: 1, pageSize: 20, total: 0 } } },
  'GET /stock': { status: 200, body: { items: [], page: { page: 1, pageSize: 20, total: 0 } } },
  'POST /orders': { status: 201, body: { orderId: '9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f', orderReference: 'ORD-000001' } },
  'POST /stock/replenish': { status: 200, body: { items: [] } },
};

export const ORDER_ID = '9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f';
export const INVOICE_ID = '2a8f3d4e-5b6c-4d7e-8f90-a1b2c3d4e5f6';

/** Installs an all-success Gateway: every operation the BFF can call answers a success. */
export function installAllSuccess(gateway: FakeGateway): void {
  gateway.on('POST', '/auth/login', (_req, res) => sendJson(res, 200, { accessToken: TEST_JWT, tokenType: 'Bearer', expiresIn: 3600 }));
  gateway.on('GET', '/auth/me', (_req, res) => sendJson(res, 200, ME));
  for (const [key, answer] of Object.entries(OK_BODIES)) {
    const [method, path] = key.split(' ') as [string, string];
    gateway.on(method, path, (_req, res) => sendJson(res, answer.status, answer.body));
  }
  gateway.on('GET', `/orders/${ORDER_ID}`, (_req, res) => sendJson(res, 200, { orderId: ORDER_ID, orderReference: 'ORD-000001', status: 'placed' }));
  gateway.on('POST', `/invoices/${INVOICE_ID}/payments`, (_req, res) => sendJson(res, 201, { outcome: 'accepted' }));
  // A stream that sends one frame and ends, so a route test can read it to completion.
  gateway.on('GET', '/orders/stream', (_req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.end('event: stream.ready\ndata: {"cursor":"0"}\n\n');
  });
}

/** Makes ONE Gateway operation answer a problem document instead of its success. */
export function failOne(gateway: FakeGateway, method: string, path: string, status: number, body: Problem, headers?: Record<string, string>): void {
  gateway.on(method, path, (_req, res) => {
    if (headers) {
      res.writeHead(status, { 'Content-Type': 'application/problem+json', ...headers });
      res.end(JSON.stringify(body));
    } else sendProblem(res, status, body);
  });
}

/** The body of a problem document captured from a running Gateway (fixtures/gateway-problems/README.md), byte for byte. */
export function realProblem(name: 'login-401' | 'orders-no-token-401' | 'order-bad-id-400'): string {
  return readFileSync(path.join(import.meta.dirname, 'fixtures', 'gateway-problems', `${name}.json`), 'utf8');
}
