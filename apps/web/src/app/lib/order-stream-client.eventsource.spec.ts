// @vitest-environment node
// The reconnect with Last-Event-ID, against a REAL EventSource (the `eventsource` package, as #8's tests used) over a real local HTTP server: the
// resume is the EventSource's own behaviour, so it is only proven by letting one reconnect (R55, openapi.yaml "Reconnection").
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { EventSource } from 'eventsource';
import { afterEach, describe, expect, it } from 'vitest';
import { E1, E2, ORDER_ID, timelineFrame, updateFrame } from '../testing/orders-fixtures';
import { OrderStreamClient, type EventSourceLike, type StreamConnectionStatus } from './order-stream-client';
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

// Real-server cases that check the premises of the fake: FakeEventSource.drop() leaves CONNECTING (the EventSource retries) and refuse() leaves CLOSED (it does not).
const C1 = 'c-update-1';
const C1T = 'c-timeline-1';
const C2 = 'c-update-2';
const C2T = 'c-timeline-2';

async function listen(handler: (request: IncomingMessage, response: ServerResponse) => void): Promise<string> {
  server = createServer(handler);
  await new Promise<void>((resolve) => server!.listen(0, '127.0.0.1', resolve));
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}/stream?orderId=${ORDER_ID}`;
}

const realEventSource = (target: string) => new EventSource(target, { fetch: (input, init) => fetch(input, init) }) as unknown as EventSourceLike;

async function waitUntil(condition: () => boolean, message: () => string, timeoutMs = 10_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!condition() && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 20));
  expect(condition(), message()).toBe(true);
}

function recorder() {
  const updates: Schemas['OrderStreamUpdate'][] = [];
  const entries: Schemas['TimelineStreamEntry'][] = [];
  const statuses: StreamConnectionStatus[] = [];
  let resyncs = 0;
  return {
    updates,
    entries,
    statuses,
    resyncs: () => resyncs,
    callbacks: { onOrderUpdated: (u: Schemas['OrderStreamUpdate']) => updates.push(u), onTimelineAppended: (e: Schemas['TimelineStreamEntry']) => entries.push(e), onResync: () => (resyncs += 1), onStatusChange: (s: StreamConnectionStatus) => statuses.push(s) },
  };
}

describe('R-resume (id 30): a FORCED mid-stream disconnect on a real server', () => {
  it('socket destroyed after a content frame, a timeline frame and a ping: the reconnect carries the last CONTENT frame id; the missed frames arrive once, nothing is duplicated', async () => {
    const lastEventIds: Array<string | undefined> = [];
    const url = await listen((request, response) => {
      lastEventIds.push(request.headers['last-event-id'] as string | undefined);
      response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      // A short reconnection delay for this local server only: the Gateway sends no `retry:` field.
      response.write('retry: 20\n\n');
      if (lastEventIds.length === 1) {
        response.write(frame('stream.ready', { cursor: 'c0', resumed: false }));
        response.write(frame('order.updated', updateFrame(E1, 'confirmed'), C1));
        response.write(frame('timeline.appended', timelineFrame(E1, 'order.confirmed.v1', 'Order confirmed'), C1T));
        response.write(frame('ping', { at: '2026-10-15T10:00:00.000Z' })); // no id: the resume point must stay the last CONTENT frame
        setTimeout(() => response.destroy(), 50); // an abrupt drop, not a clean end
        return;
      }
      response.write(frame('stream.ready', { cursor: C1T, resumed: true }));
      response.write(frame('timeline.appended', timelineFrame(E1, 'order.confirmed.v1', 'Order confirmed'), C1T)); // at-least-once: already applied
      response.write(frame('order.updated', updateFrame(E2, 'despatched'), C2));
      response.write(frame('timeline.appended', timelineFrame(E2, 'order.despatched.v1', 'Despatch created'), C2T));
    });
    const r = recorder();
    const client = new OrderStreamClient(url, r.callbacks, realEventSource);
    client.connect();
    try {
      await waitUntil(() => r.entries.length >= 2, () => `both timeline frames should arrive across the reconnect; requests=${JSON.stringify(lastEventIds)} statuses=${JSON.stringify(r.statuses)}`);
      await new Promise((resolve) => setTimeout(resolve, 150)); // a late duplicate would land here
    } finally {
      client.disconnect();
    }
    expect(lastEventIds, 'fresh connection sends none; the reconnect sends the last content frame id (the ping carries none)').toEqual([undefined, C1T]);
    expect(r.updates.map((u) => u.eventId)).toEqual([E1, E2]);
    expect(r.entries.map((e) => e.eventId)).toEqual([E1, E2]);
    expect(r.resyncs(), 'only the first stream.ready said resumed:false').toBe(1);
    expect(r.statuses, 'the drop was reported').toContain('reconnecting');
    expect(r.statuses.at(-1)).toBe('connected');
  }, 30_000);

  it('repeated forced drops reach gave-up after N=3 errors and NO further connection is made afterwards', async () => {
    let connections = 0;
    const url = await listen((_request, response) => {
      connections += 1;
      response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      response.write('retry: 10\n\n'); // a retry directive only; no frame, so the error counter is never reset
      setTimeout(() => response.destroy(), 5);
    });
    const r = recorder();
    const client = new OrderStreamClient(url, r.callbacks, realEventSource, 3);
    client.connect();
    try {
      await waitUntil(() => r.statuses.includes('gave-up'), () => `should give up after 3 errors; connections=${connections} statuses=${JSON.stringify(r.statuses)}`);
      const atGiveUp = connections;
      await new Promise((resolve) => setTimeout(resolve, 200));
      expect(connections, 'no connection after give-up').toBe(atGiveUp);
      expect(atGiveUp, 'one initial connection plus one per reconnecting error').toBe(3);
      expect(r.statuses.filter((s) => s === 'reconnecting'), 'N-1 reconnecting statuses, the Nth error gives up').toHaveLength(2);
      expect(r.statuses.at(-1)).toBe('gave-up');
    } finally {
      client.disconnect();
    }
  }, 30_000);

  it('a 401 application/problem+json answer ends at gave-up with exactly one connection, never a retry loop', async () => {
    let connections = 0;
    const url = await listen((_request, response) => {
      connections += 1;
      response.writeHead(401, { 'Content-Type': 'application/problem+json' });
      response.end('{"title":"Not signed in","code":"UNAUTHENTICATED"}');
    });
    const r = recorder();
    const client = new OrderStreamClient(url, r.callbacks, realEventSource);
    client.connect();
    try {
      await waitUntil(() => r.statuses.at(-1) === 'gave-up', () => `a refusal should end at gave-up; statuses=${JSON.stringify(r.statuses)}`);
      await new Promise((resolve) => setTimeout(resolve, 200));
      expect(connections, 'exactly one connection, no retry').toBe(1);
      expect(r.statuses).not.toContain('reconnecting');
    } finally {
      client.disconnect();
    }
  }, 30_000);
});
