import { getHeader, getRequestURL, readRawBody, sendNoContent, setResponseHeader, setResponseStatus, type H3Event } from 'h3';
import { gatewayBaseUrl, gatewayTimeoutMs } from './config';
import { localProblem } from './problem';
import { clearSession, readSession } from './session';

/**
 * The ONLY module that calls the Gateway. Every `/api/*` route goes through it; the browser never
 * does. It attaches the bearer token from the sealed session and relays the Gateway's answer
 * UNCHANGED: status, body bytes and the headers a client acts on. An RFC 9457 problem document
 * therefore reaches the browser exactly as the Gateway wrote it, with no envelope around it.
 *
 * (#7's routes re-threw the Gateway's body through h3's `createError`; Nitro's error handler then
 * wrapped it a level deeper and every page read `error.data.detail` from the wrong level for the
 * app's whole life. Here nothing is ever thrown at the framework: the body is written as it is.)
 */

/** Response headers of the Gateway that the browser needs, relayed as they are. */
export const RELAYED_RESPONSE_HEADERS = ['content-type', 'retry-after', 'idempotent-replay', 'x-correlation-id'] as const;

export interface GatewayCall {
  method?: 'GET' | 'POST';
  /** Raw query string INCLUDING the leading `?`, or empty. */
  search?: string;
  /** Raw request body text, sent unchanged. */
  body?: string;
  token?: string;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Overall deadline; defaults to WEB_GATEWAY_TIMEOUT_MS. Not applied to the SSE stream (long-lived by design). */
  timeoutMs?: number | false;
}

export async function callGateway(path: string, call: GatewayCall = {}): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json', ...call.headers };
  if (call.token) headers['Authorization'] = `Bearer ${call.token}`;
  if (call.body !== undefined) headers['Content-Type'] = 'application/json';
  const signals: AbortSignal[] = [];
  if (call.signal) signals.push(call.signal);
  if (call.timeoutMs !== false) signals.push(AbortSignal.timeout(call.timeoutMs ?? gatewayTimeoutMs()));
  return fetch(`${gatewayBaseUrl()}${path}${call.search ?? ''}`, {
    method: call.method ?? 'GET',
    headers,
    body: call.body,
    signal: signals.length ? AbortSignal.any(signals) : undefined,
    redirect: 'manual',
  });
}

export function notSignedIn(event: H3Event): string {
  clearSession(event);
  return localProblem(event, 401, 'UNAUTHENTICATED', 'Not signed in', 'You are not signed in, or your session has expired. Sign in again.');
}

/**
 * BFF-local answer when the Gateway could not be called at all: its own words, never the Gateway's. The browser-facing
 * detail names no address (the Gateway's URL is an internal detail); the URL goes to a server log line instead.
 */
export function gatewayFailed(event: H3Event, error: unknown): string {
  if (error instanceof Error && error.name === 'TimeoutError') {
    console.error(`gateway did not answer within ${gatewayTimeoutMs()} ms: ${gatewayBaseUrl()}`);
    return localProblem(event, 504, 'GATEWAY_TIMEOUT', 'The Gateway did not answer in time', `The Gateway did not answer within ${gatewayTimeoutMs()} ms.`);
  }
  const reason = error instanceof Error ? error.message : String(error);
  console.error(`gateway could not be reached: ${gatewayBaseUrl()} (${reason})`);
  return localProblem(event, 502, 'GATEWAY_UNREACHABLE', 'The Gateway could not be reached', `The Gateway could not be reached (${reason}).`);
}

/**
 * Writes an upstream Gateway response through h3 byte for byte. A 401 expires this app's session
 * cookie, and ONLY a 401: a 403/409/5xx must not sign the user out (#8 RR4: its reviewer killed a
 * mutant that cleared on every 4xx/5xx).
 */
export async function relay(event: H3Event, upstream: Response): Promise<Uint8Array | undefined> {
  const body = new Uint8Array(await upstream.arrayBuffer());
  setResponseStatus(event, upstream.status);
  for (const name of RELAYED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) setResponseHeader(event, name, value);
  }
  setResponseHeader(event, 'Cache-Control', 'no-store');
  if (upstream.status === 401) clearSession(event);
  if (upstream.status === 204 || upstream.status === 304) {
    await sendNoContent(event, upstream.status);
    return undefined;
  }
  return body;
}

export interface ProxyOptions {
  method?: 'GET' | 'POST';
  /** The Gateway path; defaults to the incoming path minus the `/api` prefix. */
  gatewayPath: string;
  /** Incoming request headers to forward to the Gateway, by name. */
  forwardRequestHeaders?: readonly string[];
}

/** The whole of an authenticated proxied call: session, Gateway, unchanged relay. */
export async function proxyToGateway(event: H3Event, options: ProxyOptions): Promise<unknown> {
  const session = await readSession(event);
  if (!session) return notSignedIn(event);

  const method = options.method ?? 'GET';
  const headers: Record<string, string> = {};
  for (const name of options.forwardRequestHeaders ?? []) {
    const value = getHeader(event, name);
    if (value) headers[name] = value;
  }
  const raw = method === 'POST' ? await readRawBody(event, 'utf8') : undefined;

  let upstream: Response;
  try {
    upstream = await callGateway(options.gatewayPath, {
      method,
      search: method === 'GET' ? getRequestURL(event).search : '',
      body: raw ? raw : undefined,
      token: session.accessToken,
      headers,
    });
  } catch (error) {
    return gatewayFailed(event, error);
  }
  return relay(event, upstream);
}

