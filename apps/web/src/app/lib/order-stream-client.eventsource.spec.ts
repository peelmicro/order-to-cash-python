// @vitest-environment node
// The reconnect with Last-Event-ID, against a REAL EventSource (the `eventsource` package, as #8's tests used) over a real local HTTP server: the
// resume is the EventSource's own behaviour, so it is only proven by letting one reconnect (R55, openapi.yaml "Reconnection").
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { EventSource } from 'eventsource';
import { afterEach, describe, expect, it } from 'vitest';
import { E1, E2, ORDER_ID, timelineFrame, updateFrame } from '../testing/orders-fixtures';
import { OrderStreamClient, type EventSourceLike } from './order-stream-client';
import type { Schemas } from '../../shared/api-types';

let server: Server | undefined;
afterEach(async () => {
  server?.closeAllConnections();
  await new Promise<void>((resolve) => (server ? server.close(() => resolve()) : resolve()));
  server = undefined;
});

const frame = (event: string, data: unknown, id?: string) => `${id ? `id: ${id}\n` : ''}event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

describe('R-resume: the real EventSource reconnects with Last-Event-ID and the client keeps its state', () => {
  it('the second request carries the id of the last frame; a replayed frame is not applied twice; a ping without an id leaves the cursor alone', async () => {
    const requests: Array<string | undefined> = [];
    server = createServer((request, response) => {
      requests.push(request.headers['last-event-id'] as string | undefined);
      response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      if (requests.length === 1) {
        response.write(frame('stream.ready', { cursor: 'c0', resumed: false }));
        response.write(frame('order.updated', updateFrame(E1, 'confirmed'), 'c1'));
        response.write(frame('ping', { at: '2026-10-15T10:00:00.000Z' }));
        setTimeout(() => response.end(), 50); // the connection drops; the browser reconnects by itself
      } else {
        response.write(frame('stream.ready', { cursor: 'c1', resumed: true }));
        response.write(frame('order.updated', updateFrame(E1, 'confirmed'), 'c1')); // at-least-once: the same frame again
        response.write(frame('timeline.appended', timelineFrame(E2, 'order.despatched.v1', 'Despatch created'), 'c2'));
      }
    });
    await new Promise<void>((resolve) => server!.listen(0, '127.0.0.1', resolve));
    const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/stream?orderId=${ORDER_ID}`;

    const updates: Schemas['OrderStreamUpdate'][] = [];
    const entries: Schemas['TimelineStreamEntry'][] = [];
    let resyncs = 0;
    const client = new OrderStreamClient(
      url,
      { onOrderUpdated: (u) => updates.push(u), onTimelineAppended: (e) => entries.push(e), onResync: () => (resyncs += 1), onStatusChange: () => undefined },
      (target) => new EventSource(target, { fetch: (input, init) => fetch(input, init) }) as unknown as EventSourceLike,
    );
    client.connect();
    const deadline = Date.now() + 10_000;
    while (entries.length < 1 && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 25));
    client.disconnect();

    expect(requests[0], 'a fresh connection sends no Last-Event-ID').toBeUndefined();
    expect(requests[1], 'the reconnect resumes after the last frame that carried an id (the ping carries none)').toBe('c1');
    expect(updates.map((u) => u.eventId), 'the replayed order.updated was applied once').toEqual([E1]);
    expect(entries.map((e) => e.eventId)).toEqual([E2]);
    expect(resyncs, 'only the first stream.ready said resumed:false').toBe(1);
  }, 30_000);
});
