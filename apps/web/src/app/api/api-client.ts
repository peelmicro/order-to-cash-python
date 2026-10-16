import { inject, Injectable, InjectionToken } from '@angular/core';
import type { LoginRequest, Schemas, SessionInfo } from '../../shared/api-types';
import { OrderStreamClient, type EventSourceFactory, type EventSourceLike, type OrderStreamCallbacks } from '../lib/order-stream-client';
import { ApiError, readProblem } from '../lib/problem';

/**
 * The browser's ONLY way to make a request: `ApiClient`, which calls THIS site's `/api/*` (the BFF),
 * never the Gateway. This token is the one thing that touches the network primitive, so a test (the
 * error-text sweep) can observe and fail every request a page makes. Its default reads `fetch` at call
 * time, so a stubbed global is honoured. src/app/seam.spec.ts fails if any other browser file uses
 * `fetch`, `XMLHttpRequest`, `WebSocket`, `sendBeacon` or `HttpClient`.
 */
export const API_FETCH = new InjectionToken<typeof fetch>('API_FETCH', {
  providedIn: 'root',
  factory: () => (input, init) => globalThis.fetch(input, init),
});

/**
 * The browser's ONLY way to open a server-sent-event stream, the twin of {@link API_FETCH}: the live timeline's `EventSource` is created here
 * (aimed at THIS origin's `/api/orders/stream`, never the Gateway) so a test can supply a transport it controls, and src/app/seam.spec.ts
 * can allow the `EventSource` primitive in this file alone.
 */
export const EVENT_SOURCE = new InjectionToken<EventSourceFactory>('EVENT_SOURCE', {
  providedIn: 'root',
  factory: () => (url) => new EventSource(url) as unknown as EventSourceLike,
});

export interface ApiResponse<T> {
  /** The HTTP status: 200/201, or 202 for an order not projected yet. */
  status: number;
  data: T;
  /** `Retry-After` in seconds, when the BFF relayed one. */
  retryAfterSeconds?: number;
}

export interface RequestOptions {
  /** An array repeats the parameter (`?status=placed&status=paid`), as openapi.yaml's exploded `status` filter says. */
  query?: Record<string, string | number | readonly string[] | undefined>;
  body?: unknown;
  headers?: Record<string, string>;
}

type Method = 'GET' | 'POST';

@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly send = inject(API_FETCH);
  private readonly openEventSource = inject(EVENT_SOURCE);

  async request<T>(method: Method, path: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (typeof value === 'object') for (const each of value) params.append(key, each);
      else if (value !== undefined && value !== '') params.set(key, String(value));
    }
    const query = params.toString();
    const headers: Record<string, string> = { Accept: 'application/json', ...options.headers };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await this.send(`/api${path}${query ? `?${query}` : ''}`, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: 'same-origin',
    });
    if (!response.ok) throw new ApiError(response.status, await readProblem(response));
    const retryAfter = Number(response.headers.get('retry-after'));
    const text = await response.text();
    return { status: response.status, data: (text ? JSON.parse(text) : undefined) as T, retryAfterSeconds: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined };
  }

  // ── Session (BFF-local routes) ───────────────────────────────────────────
  async session(): Promise<SessionInfo> {
    return (await this.request<SessionInfo>('GET', '/auth/session')).data;
  }
  async login(credentials: LoginRequest): Promise<SessionInfo> {
    return (await this.request<SessionInfo>('POST', '/auth/login', { body: credentials })).data;
  }
  async logout(): Promise<SessionInfo> {
    return (await this.request<SessionInfo>('POST', '/auth/logout')).data;
  }

  // ── Gateway operations the BFF proxies (typed from openapi.yaml). Pages arrive in stages 2 and 3. ──
  listOrders(query?: RequestOptions['query']) {
    return this.request<Schemas['OrderSummaryPage']>('GET', '/orders', { query });
  }
  getOrder(id: string) {
    return this.request<Schemas['OrderDetail'] | Schemas['ProjectionPending']>('GET', `/orders/${encodeURIComponent(id)}`);
  }
  placeOrder(order: Schemas['PlaceOrderRequest'], idempotencyKey?: string) {
    return this.request<Schemas['PlaceOrderResponse']>('POST', '/orders', { body: order, headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined });
  }
  listStock(query?: RequestOptions['query']) {
    return this.request<Schemas['StockPage']>('GET', '/stock', { query });
  }
  replenishStock(request: Schemas['ReplenishStockRequest']) {
    return this.request<Schemas['ReplenishStockResponse']>('POST', '/stock/replenish', { body: request });
  }
  listInvoices(query?: RequestOptions['query']) {
    return this.request<Schemas['InvoicePage']>('GET', '/invoices', { query });
  }
  registerPayment(invoiceId: string, payment: Schemas['RegisterPaymentRequest']) {
    return this.request<Schemas['RegisterPaymentResponse']>('POST', `/invoices/${encodeURIComponent(invoiceId)}/payments`, { body: payment });
  }
  listCredits(query?: RequestOptions['query']) {
    return this.request<Schemas['CreditPage']>('GET', '/credits', { query });
  }
  catalogProducts() {
    return this.request<{ items: Schemas['Product'][] }>('GET', '/catalog/products');
  }
  catalogRetailers() {
    return this.request<{ items: Schemas['Party'][] }>('GET', '/catalog/retailers');
  }
  catalogCompanies() {
    return this.request<{ items: Schemas['Party'][] }>('GET', '/catalog/companies');
  }

  // ── The live stream of one order (R55). Not a request/response: frames arrive until the client closes it. ──
  /** A stream client for `GET /api/orders/stream?orderId=`; the caller connects it and disconnects it (closing it is what makes the BFF abort its upstream). */
  orderStream(orderId: string, callbacks: OrderStreamCallbacks): OrderStreamClient {
    return new OrderStreamClient(`/api/orders/stream?orderId=${encodeURIComponent(orderId)}`, callbacks, (url) => this.openEventSource(url));
  }
}
