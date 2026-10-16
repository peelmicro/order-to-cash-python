import { defineEventHandler, getHeader, getQuery } from 'h3';
import { gatewayFailed, notSignedIn, relay } from '../../../lib/gateway';
import { readSession } from '../../../lib/session';
import { openUpstreamOrderStream, pumpStream, STREAM_RESPONSE_HEADERS, STREAM_ROUTE_ENTERED } from '../../../lib/stream-proxy';

/**
 * `GET /api/orders/stream[?orderId=]`: the browser's `EventSource` connects HERE, never to the Gateway; the bearer
 * token is attached server-side. The browser's `Last-Event-ID` (sent automatically on reconnect) is forwarded verbatim,
 * the upstream bytes are handed on as they arrive, and a client disconnect aborts the upstream request.
 */
export default defineEventHandler(async (event) => {
  const session = await readSession(event);
  if (!session) return notSignedIn(event);
  // The test premise ("the request reached the stream route") is read from this line: it is logged only for a request the BFF ACCEPTED (signed in), so a refused cookie cannot satisfy it.
  console.debug(STREAM_ROUTE_ENTERED);

  const orderIdParam = getQuery(event)['orderId'];
  const res = event.node.res;
  // Wired BEFORE the upstream is opened: a client that leaves while the Gateway has not yet answered its headers would
  // otherwise have closed already when a later listener is attached, and the upstream would stay open for the server's life.
  const upstreamAbort = new AbortController();
  const onClientGone = () => upstreamAbort.abort();
  res.on('close', onClientGone);
  // The client may have left during `readSession` above: its `close` was emitted before this listener existed and never will be again.
  if (res.destroyed) {
    res.off('close', onClientGone);
    return undefined;
  }
  let upstream: Response;
  try {
    upstream = await openUpstreamOrderStream({
      token: session.accessToken,
      orderId: typeof orderIdParam === 'string' ? orderIdParam : undefined,
      lastEventId: getHeader(event, 'last-event-id') || undefined,
      signal: upstreamAbort.signal,
    });
  } catch (error) {
    res.off('close', onClientGone);
    if (upstreamAbort.signal.aborted) return undefined; // the client left before the Gateway answered: nobody to tell
    return gatewayFailed(event, error);
  }
  if (res.destroyed || upstreamAbort.signal.aborted) {
    // The client left while the headers were arriving: release the upstream now.
    upstreamAbort.abort();
    res.off('close', onClientGone);
    await upstream.body?.cancel().catch(() => undefined);
    return undefined;
  }
  if (!upstream.ok || !upstream.body) {
    res.off('close', onClientGone);
    return relay(event, upstream);
  }

  res.writeHead(200, STREAM_RESPONSE_HEADERS);
  res.flushHeaders();
  try {
    await pumpStream(upstream.body, res);
  } finally {
    res.off('close', onClientGone);
  }
  return undefined;
});
