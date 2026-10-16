// The client half of GET /orders/stream (R51, R55): per-frame-type de-duplication, the two outcomes of stream.ready, the connection states.
// Ported by content from #8's order-stream-client.test.ts and #7's order-stream-client.spec.ts; the id collision across frame types is #7's bug
// (#7 review pass 3, finding 1: one shared set dropped whichever frame of a fact arrived second).
import { describe, expect, it } from 'vitest';
import { E1, E2, ORDER_ID, timelineFrame, updateFrame } from '../testing/orders-fixtures';
import { FakeEventSource } from '../testing/fake-event-source';
import { OrderStreamClient, type StreamConnectionStatus } from './order-stream-client';
import type { Schemas } from '../../shared/api-types';

function setup(giveUpAfter?: number) {
  const sources: FakeEventSource[] = [];
  const updates: Schemas['OrderStreamUpdate'][] = [];
  const entries: Schemas['TimelineStreamEntry'][] = [];
  const statuses: StreamConnectionStatus[] = [];
  let resyncs = 0;
  const client = new OrderStreamClient(
    '/api/orders/stream?orderId=x',
    { onOrderUpdated: (u) => updates.push(u), onTimelineAppended: (e) => entries.push(e), onResync: () => (resyncs += 1), onStatusChange: (s) => statuses.push(s) },
    (url) => {
      const source = new FakeEventSource(url);
      sources.push(source);
      return source;
    },
    giveUpAfter,
  );
  return { client, sources, updates, entries, statuses, resyncs: () => resyncs };
}

const ready = (resumed: boolean) => ({ cursor: 'c0', resumed, orderId: ORDER_ID });

describe('R-dedup: de-duplication is per frame type', () => {
  it('the two frames of one fact share an eventId: both are applied, once each', () => {
    const { client, sources, updates, entries } = setup();
    client.connect();
    sources[0]!.emit('order.updated', updateFrame(E1, 'confirmed'));
    sources[0]!.emit('timeline.appended', timelineFrame(E1, 'order.confirmed.v1', 'Order confirmed (ORDRSP)'));
    expect([updates.map((u) => u.eventId), entries.map((e) => e.eventId)]).toEqual([[E1], [E1]]);
  });

  it('the reverse arrival order too: the timeline frame first, the update second', () => {
    const { client, sources, updates, entries } = setup();
    client.connect();
    sources[0]!.emit('timeline.appended', timelineFrame(E1, 'order.confirmed.v1', 'x'));
    sources[0]!.emit('order.updated', updateFrame(E1, 'confirmed'));
    expect([updates.length, entries.length]).toEqual([1, 1]);
  });

  it('a redelivery of the SAME type with the same eventId is dropped (R51: at-least-once), for each type', () => {
    const { client, sources, updates, entries } = setup();
    client.connect();
    for (let i = 0; i < 3; i++) {
      sources[0]!.emit('order.updated', updateFrame(E1, 'confirmed'));
      sources[0]!.emit('timeline.appended', timelineFrame(E1, 't', 's'));
    }
    sources[0]!.emit('order.updated', updateFrame(E2, 'despatched'));
    expect([updates.map((u) => u.eventId), entries.map((e) => e.eventId)]).toEqual([[E1, E2], [E1]]);
  });

  it('facts a fetched snapshot already holds are seeded for BOTH types: a replayed frame of either is dropped', () => {
    const { client, sources, updates, entries } = setup();
    client.seedSeenEventIds([E1]);
    client.connect();
    sources[0]!.emit('order.updated', updateFrame(E1, 'confirmed'));
    sources[0]!.emit('timeline.appended', timelineFrame(E1, 't', 's'));
    sources[0]!.emit('timeline.appended', timelineFrame(E2, 't', 's'));
    expect([updates.length, entries.map((e) => e.eventId)]).toEqual([0, [E2]]);
  });

  it('a malformed frame is ignored, not applied and not fatal', () => {
    const { client, sources, updates } = setup();
    client.connect();
    sources[0]!.emit('order.updated', '{not json');
    sources[0]!.emit('order.updated', updateFrame(E1, 'confirmed'));
    expect(updates.length).toBe(1);
  });
});

describe('R-resync: stream.ready', () => {
  it('resumed:false re-reads (a fresh connection always gets it); resumed:true does not', () => {
    const { client, sources, resyncs } = setup();
    client.connect();
    sources[0]!.emit('stream.ready', ready(false));
    expect(resyncs()).toBe(1);
    sources[0]!.emit('stream.ready', ready(true));
    expect(resyncs()).toBe(1);
  });
});

describe('R-status: the connection states', () => {
  it('connecting, then connected on any frame (a ping too), reconnecting on a drop, connected again, and the counter restarts', () => {
    const { client, sources, statuses } = setup(3);
    client.connect();
    sources[0]!.emit('ping', { at: 'x' });
    sources[0]!.drop();
    sources[0]!.drop();
    sources[0]!.emit('ping', { at: 'x' });
    sources[0]!.drop();
    sources[0]!.drop();
    expect(statuses).toEqual(['connecting', 'connected', 'reconnecting', 'reconnecting', 'connected', 'reconnecting', 'reconnecting']);
  });

  it('gives up after N consecutive errors, closing the source', () => {
    const { client, sources, statuses } = setup(3);
    client.connect();
    sources[0]!.drop();
    sources[0]!.drop();
    sources[0]!.drop();
    expect(statuses.at(-1)).toBe('gave-up');
    expect(sources[0]!.closed).toBe(true);
  });

  it('gives up at once when the browser has closed the stream for good (a refusal)', () => {
    const { client, sources, statuses } = setup();
    client.connect();
    sources[0]!.refuse();
    expect(statuses).toEqual(['connecting', 'gave-up']);
    expect(sources[0]!.closed).toBe(true);
  });

  it('connect() closes the previous source, and a frame from it is ignored afterwards', () => {
    const { client, sources, updates } = setup();
    client.connect();
    client.connect();
    expect([sources.length, sources[0]!.closed, sources[1]!.closed]).toEqual([2, true, false]);
    // the old source is closed, so even a late event it still holds is not delivered
    sources[0]!.emit('order.updated', updateFrame(E1, 'confirmed'));
    expect(updates.length).toBe(0);
  });

  it('disconnect() closes the source', () => {
    const { client, sources } = setup();
    client.connect();
    client.disconnect();
    expect(sources[0]!.closed).toBe(true);
  });
});
