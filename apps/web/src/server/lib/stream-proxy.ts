import { once } from 'node:events';
import type { ServerResponse } from 'node:http';
import { gatewayBaseUrl } from './config';

/**
 * Written (at debug level, no data) the moment a request reaches the stream route, before the session is read. The same-tick contract case
 * ("a client that disconnects in the same tick it sends the request opens no upstream connection") reads it as its PREMISE: without it the case
 * would pass just as well if the request never reached the route at all.
 */
export const STREAM_ROUTE_ENTERED = '[bff] stream route entered';

export interface UpstreamStreamOptions {
  token: string;
  orderId?: string;
  lastEventId?: string;
  signal: AbortSignal;
  baseUrl?: string;
}

/**
 * Opens the Gateway's `GET /orders/stream` with the bearer token attached server-side and the
 * browser's `Last-Event-ID` forwarded VERBATIM, so the Gateway's bounded replay buffer can resume a
 * reconnecting EventSource from its own cursor (openapi.yaml, "Reconnection"). No deadline is set:
 * the connection is long-lived by design.
 */
export function openUpstreamOrderStream(options: UpstreamStreamOptions): Promise<Response> {
  const url = new URL('/orders/stream', options.baseUrl ?? gatewayBaseUrl());
  if (options.orderId) url.searchParams.set('orderId', options.orderId);
  const headers: Record<string, string> = { Accept: 'text/event-stream', Authorization: `Bearer ${options.token}` };
  if (options.lastEventId) headers['Last-Event-ID'] = options.lastEventId;
  return fetch(url, { headers, signal: options.signal, redirect: 'manual' });
}

/** Response headers of the proxied stream. `no-transform` and `X-Accel-Buffering: no` are for intermediaries that compress or buffer. */
export const STREAM_RESPONSE_HEADERS: Readonly<Record<string, string>> = {
  'Content-Type': 'text/event-stream; charset=utf-8',
  'Cache-Control': 'no-cache, no-transform',
  Connection: 'keep-alive',
  'X-Accel-Buffering': 'no',
};

/**
 * Pumps the upstream body to the client as the chunks arrive (nothing is collected). The route owns the abort:
 * it wires the client's disconnect to the upstream request BEFORE the upstream is opened (stream.get.ts), because
 * a listener attached here would miss a client that left while the Gateway had not yet answered its headers.
 *
 * Hand-built on purpose: h3 1.x `sendStream` on a web ReadableStream pipes with `pipeTo` and registers
 * no cleanup at all on the response's `close`, so a closed tab would leave the Gateway connection (and
 * its StreamHub subscription) open. The route wires the signal to the RESPONSE's `close`, the lifecycle of what is
 * being streamed. (Probed on Node 24.19 for a body-less GET: the request's `close` fires at the same
 * moment, 5 ms after the client destroys the socket, so #7's `req.on('close')` was sound for this route.)
 * Writes honour back-pressure (`drain`).
 */
export async function pumpStream(upstreamBody: ReadableStream<Uint8Array>, res: ServerResponse): Promise<void> {
  const reader = upstreamBody.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!res.write(value)) {
        // A client that closes while the buffer is full never emits 'drain': wait for whichever comes first.
        const settled = new AbortController();
        await Promise.race([once(res, 'drain', { signal: settled.signal }), once(res, 'close', { signal: settled.signal })]).finally(() => settled.abort()).catch(() => undefined);
      }
    }
  } catch {
    // The upstream ended abnormally or was aborted because the client left: either way the response ends here.
  } finally {
    reader.cancel().catch(() => undefined);
    if (!res.writableEnded) res.end();
  }
}
