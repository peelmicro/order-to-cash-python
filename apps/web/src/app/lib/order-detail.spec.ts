// The pure rules behind the order page: the pending retry hint, when the page re-reads on its own, how live frames patch a document, timeline order,
// and which entry a "caused by" may name. Ported by content from #8's order-detail.test.ts and #7's useOrderDetail.spec.ts.
import { describe, expect, it } from 'vitest';
import { COMMAND_ID, E1, E2, E3, E4, orderDetail, PENDING, timelineEntry, timelineFrame, updateFrame } from '../testing/orders-fixtures';
import { applyOrderUpdate, applyTimelineAppended, causingEntry, DEFAULT_PENDING_RETRY_MS, isTerminalStatus, MIN_PENDING_RETRY_MS, orderTimeline, pendingRetryDelayMs, RefetchPlan, STALE_STATUS_BACKSTOP_MS, type OrderDetailResult } from './order-detail';

const ready = (overrides = {}): OrderDetailResult => ({ kind: 'ready', detail: orderDetail(overrides) });
const pending: OrderDetailResult = { kind: 'pending', pending: PENDING, retryAfterMs: 500 };

describe('R-pending: the retry hint of a 202', () => {
  it('Retry-After (seconds) wins over the body, the body over the default, and none is ever below the floor', () => {
    expect(pendingRetryDelayMs(3, { retryAfterMs: 900 })).toBe(3000);
    expect(pendingRetryDelayMs(undefined, { retryAfterMs: 900 })).toBe(900);
    expect(pendingRetryDelayMs(undefined, {})).toBe(DEFAULT_PENDING_RETRY_MS);
    expect(pendingRetryDelayMs(0, { retryAfterMs: 0 }), 'a hint of 0 must not become a tight loop').toBe(MIN_PENDING_RETRY_MS);
    expect(pendingRetryDelayMs(undefined, { retryAfterMs: 0 })).toBe(MIN_PENDING_RETRY_MS);
  });
});

describe('R-poll: when the page re-reads on its own', () => {
  it('terminal statuses are completed and cancelled, nothing else', () => {
    expect((['placed', 'stock_reserved', 'credit_approved', 'confirmed', 'despatched', 'invoiced', 'paid', 'completed', 'cancelled'] as const).filter(isTerminalStatus)).toEqual(['completed', 'cancelled']);
  });

  it('a pending answer: at the Gateway\'s own interval; a live order: on the backstop; no data: never', () => {
    const plan = new RefetchPlan();
    expect(plan.interval(undefined)).toBe(false);
    expect(plan.interval(pending)).toBe(500);
    expect(plan.interval(ready())).toBe(STALE_STATUS_BACKSTOP_MS);
  });

  it('an order that BECOMES terminal while watched is read once more, then never', () => {
    const plan = new RefetchPlan();
    plan.noteRead();
    expect(plan.interval(ready())).toBe(STALE_STATUS_BACKSTOP_MS);
    expect(plan.interval(ready({ status: 'completed' })), 'no read completed since the terminal status was first seen: one more is owed').toBe(STALE_STATUS_BACKSTOP_MS);
    plan.noteRead();
    expect(plan.interval(ready({ status: 'completed' })), 'that read happened').toBe(false);
  });

  it('an order the page opened already terminal is never re-read', () => {
    const plan = new RefetchPlan();
    plan.noteRead();
    expect(plan.interval(ready({ status: 'cancelled' }))).toBe(false);
    plan.noteRead();
    expect(plan.interval(ready({ status: 'cancelled' }))).toBe(false);
  });

  it('reset() forgets the previous order (a new id on the same page)', () => {
    const plan = new RefetchPlan();
    plan.interval(ready());
    plan.reset();
    expect(plan.interval(ready({ status: 'completed' }))).toBe(false);
  });
});

describe('R-patch: live frames patch a projected document', () => {
  it('order.updated replaces status, reason, references, totals, reference and updatedAt; a pending answer is left alone', () => {
    const frame = { ...updateFrame(E4, 'despatched', '2026-10-15T10:00:09.000Z'), orderReference: 'ORD-000043', references: { despatchReference: 'DES-000001' }, totals: { initialAmount: 1, initialDiscount: 0, totalAmount: 1 } };
    const patched = applyOrderUpdate(ready(), frame);
    expect(patched?.kind === 'ready' && [patched.detail.status, patched.detail.orderReference, patched.detail.references?.despatchReference, patched.detail.totals?.totalAmount, patched.detail.updatedAt]).toEqual(['despatched', 'ORD-000043', 'DES-000001', 1, '2026-10-15T10:00:09.000Z']);
    expect(applyOrderUpdate(pending, frame)).toBe(pending);
    expect(applyOrderUpdate(undefined, frame)).toBeUndefined();
  });

  it('timeline.appended appends in occurredAt order, carries causationId, and a known eventId changes nothing (second de-duplication layer)', () => {
    const appended = applyTimelineAppended(ready(), timelineFrame(E4, 'order.confirmed.v1', 'Order confirmed (ORDRSP)', '2026-10-15T10:00:04.000Z', E3));
    expect(appended?.kind === 'ready' && appended.detail.events.map((e) => e.eventId)).toEqual([E1, E2, E3, E4]);
    expect(appended?.kind === 'ready' && appended.detail.events.at(-1)?.causationId).toBe(E3);
    const again = applyTimelineAppended(appended, timelineFrame(E4, 'order.confirmed.v1', 'x'));
    expect(again).toBe(appended);
    expect(applyTimelineAppended(pending, timelineFrame(E4, 't', 's'))).toBe(pending);
  });

  it('a frame whose occurredAt is earlier lands earlier: the page shows the order a reload would', () => {
    const late = applyTimelineAppended(ready(), timelineFrame(E4, 'x', 'y', '2026-10-15T10:00:00.500Z'));
    expect(late?.kind === 'ready' && late.detail.events.map((e) => e.eventId)).toEqual([E1, E4, E2, E3]);
  });
});

describe('R50/A1: timeline order', () => {
  it('within one identical occurredAt a fact follows the fact that caused it, even against eventId order', () => {
    const at = '2026-10-15T10:00:00.000Z';
    // E1 sorts before E2, but E1 is caused by E2: the cause comes first.
    const out = orderTimeline([timelineEntry(E1, 'b', 'effect', at, E2), timelineEntry(E2, 'a', 'cause', at)]);
    expect(out.map((e) => e.eventId)).toEqual([E2, E1]);
  });
  it('with no recorded edge, tied entries fall back to eventId ascending; a cycle does not hang', () => {
    const at = '2026-10-15T10:00:00.000Z';
    expect(orderTimeline([timelineEntry(E2, 'b', 'x', at), timelineEntry(E1, 'a', 'y', at)]).map((e) => e.eventId)).toEqual([E1, E2]);
    expect(orderTimeline([timelineEntry(E1, 'a', 'x', at, E2), timelineEntry(E2, 'b', 'y', at, E1)]).map((e) => e.eventId)).toEqual([E1, E2]);
  });
});

describe('backlog 201 / SA-6: which entry a "caused by" may name', () => {
  const events = orderDetail().events;
  it('an entry caused by another ENTRY resolves to it', () => {
    expect(causingEntry(events[1]!, events)?.eventId).toBe(E1);
  });
  it('an entry whose causationId names a COMMAND (a responder fact) resolves to nothing', () => {
    expect(events[2]!.causationId).toBe(COMMAND_ID);
    expect(causingEntry(events[2]!, events)).toBeUndefined();
  });
  it('an entry with no causationId (projected before the field existed) resolves to nothing', () => {
    expect(causingEntry(events[0]!, events)).toBeUndefined();
  });
});
