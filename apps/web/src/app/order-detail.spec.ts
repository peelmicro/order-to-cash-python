// The order page (R50, R54, R55): the document, the honest 202, the ONE live stream with its two frame types, the "caused by" links (backlog 201,
// SA-6), the connection states and what a refused stream does (#8 id 98). Ported by content from #8's order-detail-view.test.tsx and #7's [id].spec.ts;
// every state that depends on a request or a stream is held deterministically (a gate, a fake transport), never by timing.
import { fireEvent, screen, within } from '@testing-library/dom';
import { afterEach, describe, expect, it } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { json, problemResponse } from './testing/browser-harness';
import { COMMAND_ID, E1, E2, E3, E4, ORDER_ID, orderDetail, PENDING, timelineFrame, updateFrame } from './testing/orders-fixtures';
import { gate, mountPage } from './testing/page-test';
import { buttonNamed } from './testing/page-sweep';
import type { Schemas } from '../shared/api-types';

afterEach(() => TestBed.resetTestingModule());

const URL = `/orders/${ORDER_ID}`;
const GET = `GET /api/orders/${ORDER_ID}`;
const STREAM = `/api/orders/stream?orderId=${ORDER_ID}`;
const entries = () => screen.queryAllByTestId('timeline-entry').map((li) => li.getAttribute('data-event-id'));
const status = () => screen.getByTestId('order-detail-status').getAttribute('data-status') ?? screen.getByTestId('order-detail-status').querySelector('[data-status]')?.getAttribute('data-status');
const connection = () => screen.getByTestId('stream-status').textContent?.trim();
const unauthorized = () => problemResponse(401, { type: 'about:blank', title: 'Unauthorized', status: 401, detail: 'Authentication is required.' });

/** A mutable document the stub serves: tests change what the next read answers. */
function serving(initial: Schemas['OrderDetail']) {
  const state = { detail: initial };
  return { state, route: [GET, () => json(state.detail)] as [string, () => Response] };
}

describe('R-detail: the document', () => {
  it('shows the reference, parties, status, total and items in the currency\'s own text, and the timeline in order with its times', async () => {
    await mountPage(URL);
    expect(screen.getByTestId('order-detail-reference').textContent).toBe('ORD-000042');
    expect(screen.getByText('Carrefour España · Iber Foods')).toBeTruthy();
    expect(status()).toBe('confirmed');
    expect(screen.getByTestId('order-detail-total').textContent).toBe('1 242.50 EUR');
    expect(screen.getByTestId('order-detail-items').textContent).toContain('5 × Olive oil 1 L at 248.50 EUR');
    expect(entries()).toEqual([E1, E2, E3]);
    expect(screen.getAllByTestId('timeline-entry')[0]!.textContent).toContain('2026-10-15 10:00:00 UTC');
    // #8 id 100: the human money text of a timeline entry is written by the server (ISO 4217 exponent) and shown AS WRITTEN, never reformatted or re-parsed here.
    expect(screen.getAllByTestId('timeline-entry').map((li) => li.querySelector('p.font-medium')?.textContent)).toEqual(['Order ORD-000042 placed for CarrefourEs', 'Stock reserved for 1 line(s)', 'Credit hold of 1 242.50 EUR approved']);
  });

  it('a JPY order shows its whole amounts; a cancelled order shows its reason', async () => {
    await mountPage(URL, [[GET, () => json(orderDetail({ currency: 'JPY', totals: { initialAmount: 1234567, initialDiscount: 0, totalAmount: 1234567 }, status: 'cancelled', cancellationReason: 'credit_rejected' }))]]);
    expect(screen.getByTestId('order-detail-total').textContent).toBe('1 234 567 JPY');
    expect(screen.getByTestId('order-detail-cancellation').textContent).toBe('credit_rejected');
  });

  it('a placeholder document says its header is still filling in', async () => {
    await mountPage(URL, [[GET, () => json(orderDetail({ headerComplete: false }))]]);
    expect(screen.getByTestId('order-detail-header-incomplete')).toBeTruthy();
  });

  it('while the read is in flight: only "Loading order…" (held on an unresolved promise, not assumed)', async () => {
    const held = gate();
    const { m } = await mountPage(URL, [[GET, held.answer]], { settle: false });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(held.started()).toBe(true);
    expect(screen.getByTestId('order-detail-loading').textContent).toContain('Loading order');
    expect([screen.queryByTestId('order-detail-error'), screen.queryByTestId('order-detail-pending'), screen.queryByTestId('order-timeline')]).toEqual([null, null, null]);
    held.release(json(orderDetail()));
    await m.settle();
    expect(screen.queryByTestId('order-detail-loading')).toBeNull();
  });

  it('a 404 shows the problem\'s own detail, not the waiting state and not an empty order', async () => {
    await mountPage(URL, [[GET, () => problemResponse(404, { type: 'about:blank', title: 'No such resource', status: 404, detail: `Order ${ORDER_ID} is unknown to the system.` })]]);
    expect(screen.getByTestId('order-detail-error').textContent).toContain(`Order ${ORDER_ID} is unknown to the system.`);
    expect([screen.queryByTestId('order-detail-pending'), screen.queryByTestId('order-detail-reference')]).toEqual([null, null]);
  });
});

describe('R55 (web half): the honest 202', () => {
  const pending = () => new Response(JSON.stringify({ ...PENDING, retryAfterMs: 60_000 }), { status: 202, headers: { 'Content-Type': 'application/json', 'Retry-After': '60' } });

  it('renders the waiting state on a projection-pending answer and fills in from the update stream', async () => {
    // Retry-After is a minute, so the poll cannot be what fills the page in: only the stream can.
    const live = serving(orderDetail());
    let answered = 0;
    const { m, s } = await mountPage(URL, [[GET, () => (++answered === 1 ? pending() : json(live.state.detail))]]);
    // The named waiting state: not a spinner, not an error, not a 404.
    const waiting = screen.getByTestId('order-detail-pending');
    expect(within(waiting).getByText('Waiting for this order to appear')).toBeTruthy();
    expect(screen.getByTestId('order-detail-pending-message').textContent).toBe(PENDING.message);
    expect(screen.getByTestId('order-detail-pending-schedule').textContent).toContain('Checking again every 60 s');
    expect([screen.queryByTestId('order-detail-loading'), screen.queryByTestId('order-detail-error'), screen.queryByTestId('order-detail-reference')]).toEqual([null, null, null]);
    expect(s.count(GET)).toBe(1);
    // The stream is open while the answer is pending (one per page), and a fact arriving on it fills the page in.
    expect(m.streams.map((stream) => stream.url)).toEqual([STREAM]);
    m.streams[0]!.emit('timeline.appended', timelineFrame(E1, 'order.placed.v1', 'Order ORD-000042 placed for CarrefourEs'));
    await m.settle();
    expect(s.count(GET), 'the frame made the page read the order again').toBe(2);
    expect(screen.queryByTestId('order-detail-pending')).toBeNull();
    expect(screen.getByTestId('order-detail-reference').textContent).toBe('ORD-000042');
    expect(entries()).toEqual([E1, E2, E3]);
  });

  it('the stream\'s first stream.ready (a fresh connection is never "resumed") also reads the order again, and "Check now" does too', async () => {
    let answered = 0;
    const { m, s } = await mountPage(URL, [[GET, () => (++answered < 3 ? pending() : json(orderDetail()))]]);
    m.streams[0]!.emit('stream.ready', { cursor: 'c0', resumed: false, orderId: ORDER_ID });
    await m.settle();
    expect(s.count(GET)).toBe(2);
    expect(screen.getByTestId('order-detail-pending')).toBeTruthy();
    buttonNamed('Check now').click();
    await m.settle();
    expect(s.count(GET)).toBe(3);
    expect(screen.getByTestId('order-detail-reference')).toBeTruthy();
  });
});

describe('R-stream-live: one stream per page, two frame types de-duplicated separately', () => {
  it('opens exactly one stream aimed at this origin\'s proxy, however many frames and re-reads follow, and closes it when the page is left', async () => {
    const { m, s } = await mountPage(URL);
    expect(m.streams.map((stream) => stream.url)).toEqual([STREAM]);
    for (let i = 0; i < 5; i++) {
      m.streams[0]!.emit('ping', { at: 'x' });
      m.streams[0]!.emit('stream.ready', { cursor: 'c', resumed: false });
      await m.settle();
    }
    expect(m.streams, 'frames and re-reads must not reopen the stream').toHaveLength(1);
    expect(s.count(GET)).toBe(6);
    expect(m.streams[0]!.closed).toBe(false);
    await m.router.navigateByUrl('/orders');
    await m.settle();
    expect(m.streams[0]!.closed, 'leaving the page closes the stream (which is what makes the BFF abort its upstream)').toBe(true);
    expect(m.streams).toHaveLength(1);
  });

  it('the two frames of one fact share an eventId (here E4, colliding across types): both are applied, once each', async () => {
    const { m } = await mountPage(URL);
    const stream = m.streams[0]!;
    stream.emit('order.updated', updateFrame(E4, 'despatched'));
    stream.emit('timeline.appended', timelineFrame(E4, 'order.despatched.v1', 'Despatch DES-000001 created'));
    await m.settle();
    expect(status()).toBe('despatched');
    expect(entries()).toEqual([E1, E2, E3, E4]);
    for (let i = 0; i < 3; i++) {
      stream.emit('order.updated', updateFrame(E4, 'despatched'));
      stream.emit('timeline.appended', timelineFrame(E4, 'order.despatched.v1', 'Despatch DES-000001 created'));
    }
    await m.settle();
    expect(entries(), 'at-least-once delivery: a redelivery changes nothing').toEqual([E1, E2, E3, E4]);
  });

  it('facts the fetched snapshot already holds are dropped when replayed: a stale order.updated cannot regress the status', async () => {
    const { m } = await mountPage(URL, [[GET, () => json(orderDetail({ status: 'completed' }))]]);
    m.streams[0]!.emit('order.updated', updateFrame(E1, 'placed'));
    m.streams[0]!.emit('timeline.appended', timelineFrame(E1, 'order.placed.v1', 'again'));
    await m.settle();
    expect(status()).toBe('completed');
    expect(entries()).toEqual([E1, E2, E3]);
  });

  it('stream.ready resumed:false re-reads the order, resumed:true does not', async () => {
    const { m, s } = await mountPage(URL);
    m.streams[0]!.emit('stream.ready', { cursor: 'c1', resumed: true });
    await m.settle();
    expect(s.count(GET)).toBe(1);
    m.streams[0]!.emit('stream.ready', { cursor: 'c2', resumed: false });
    await m.settle();
    expect(s.count(GET)).toBe(2);
  });
});

describe('backlog 201 / SA-6: "caused by" links only to an entry that is on the timeline, and says nothing otherwise', () => {
  const causation = () => screen.queryAllByTestId('timeline-causation').map((node) => node.closest('[data-testid="timeline-entry"]')?.getAttribute('data-event-id'));

  it('only E2 (caused by the fact E1) has one; E1 (no cause) and E3 (cause is a COMMAND, which is no entry) have none', async () => {
    await mountPage(URL);
    expect(causation()).toEqual([E2]);
    const e3 = screen.getAllByTestId('timeline-entry')[2]!;
    expect(e3.textContent).not.toMatch(/caused by/i);
    expect(e3.textContent, 'the unresolved command id must not surface anywhere').not.toContain(COMMAND_ID);
  });

  it('every link on the page points at an element that exists, and is a timeline entry; clicking it highlights that entry and keeps the page', async () => {
    const { m } = await mountPage(URL);
    const links = screen.getAllByTestId('timeline-causation-link');
    expect(links.length, 'the population must not be empty').toBeGreaterThan(0);
    for (const link of links) {
      const target = document.getElementById(link.getAttribute('href')!.slice(1));
      expect(target, `${link.getAttribute('href')} must exist`).not.toBeNull();
      expect(target!.getAttribute('data-testid')).toBe('timeline-entry');
    }
    expect(links[0]!.textContent).toBe('order.placed.v1');
    fireEvent.click(links[0]!);
    await m.settle();
    expect(document.getElementById(`timeline-entry-${E1}`)!.className).toContain('bg-muted');
    expect(m.router.url).toBe(URL);
  });

  it('a live frame follows the same rule: a cause that is an entry links, a command does not', async () => {
    const { m } = await mountPage(URL);
    m.streams[0]!.emit('timeline.appended', timelineFrame(E4, 'order.confirmed.v1', 'Order confirmed (ORDRSP)', '2026-10-15T10:00:04.000Z', E3));
    m.streams[0]!.emit('timeline.appended', timelineFrame('55555555-5555-4555-8555-555555555555', 'stock.released.v1', '5 unit(s) released', '2026-10-15T10:00:05.000Z', COMMAND_ID));
    await m.settle();
    expect(causation()).toEqual([E2, E4]);
    expect(screen.getAllByTestId('timeline-entry')).toHaveLength(5);
  });
});

describe('R-conn: the connection states', () => {
  it('Connecting…, then Live on a frame, Reconnecting… on a drop, Live again, Connection lost with Retry after a refusal', async () => {
    const { m } = await mountPage(URL);
    expect(connection()).toBe('Connecting…');
    m.streams[0]!.emit('ping', { at: 'x' });
    await m.settle();
    expect(connection()).toBe('Live');
    m.streams[0]!.drop();
    await m.settle();
    expect(connection()).toBe('Reconnecting…');
    m.streams[0]!.emit('ping', { at: 'x' });
    await m.settle();
    expect(connection()).toBe('Live');
    expect(screen.queryByTestId('stream-retry')).toBeNull();
    m.streams[0]!.refuse();
    await m.settle();
    expect(connection()).toBe('Connection lost');
    expect(screen.getByTestId('stream-retry').textContent).toBe('Retry connection');
  });
});

describe('#8 id 98: a refused stream is asked about through a query that can say why', () => {
  const COMPLETED = orderDetail({ status: 'completed' });

  it('an expired session on a TERMINAL order ends at /login, not at "Connection lost" (the refusal is held, not timed)', async () => {
    let reads = 0;
    const second = gate();
    const { m, s } = await mountPage(URL, [[GET, () => (++reads === 1 ? json(COMPLETED) : second.answer())]]);
    expect(status()).toBe('completed');
    m.streams[0]!.refuse();
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(second.started(), 'giving up asked the order again, through a query').toBe(true);
    expect(connection(), 'while the answer is held the page honestly says the connection is lost').toBe('Connection lost');
    second.release(unauthorized());
    await m.settle();
    expect(m.router.url, 'the 401 reached the sign-out redirect').toBe('/login');
    expect(document.body.textContent).not.toContain('Connection lost');
    expect(s.count(GET)).toBe(2);
  });

  it('Retry re-checks first: a 500 shows its own words and opens NO new stream, however often it is pressed; a 401 ends at /login; only a success reopens', async () => {
    let reads = 0;
    const answers = [json(orderDetail()), problemResponse(500, { type: 'about:blank', title: 'x', status: 500, detail: 'The read model is down.' }), problemResponse(500, { type: 'about:blank', title: 'x', status: 500, detail: 'The read model is down.' })];
    const { m, s } = await mountPage(URL, [[GET, () => (reads < answers.length ? answers[reads++]!.clone() : reads++ === answers.length ? unauthorized() : json(orderDetail()))]]);
    m.streams[0]!.refuse();
    await m.settle();
    expect(s.count(GET), 'initial read + the one read giving up asks for (a 500 is retried once by the query client, which is a second attempt of the SAME read)').toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId('order-detail-error').textContent).toContain('The read model is down.');
    const streamsBefore = m.streams.length;
    for (let i = 0; i < 3; i++) {
      buttonNamed('Retry connection').click();
      await m.settle();
      if (m.router.url === '/login') break;
    }
    expect(m.streams.length, 'a refusal must never reopen a stream').toBe(streamsBefore);
    expect(m.router.url, 'the 401 on a Retry ends at /login').toBe('/login');
  });

  it('Retry with a healthy read reopens the stream once, and it starts Connecting…', async () => {
    const { m } = await mountPage(URL);
    m.streams[0]!.refuse();
    await m.settle();
    expect(connection()).toBe('Connection lost');
    buttonNamed('Retry connection').click();
    await m.settle();
    expect(m.streams).toHaveLength(2);
    expect(m.streams[0]!.closed).toBe(true);
    expect(m.streams[1]!.closed).toBe(false);
    expect(connection()).toBe('Connecting…');
  });
});
