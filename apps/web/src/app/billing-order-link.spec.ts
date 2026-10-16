// The order link after a Register payment (feature 29, stage 4). An invoice carries only its order's business reference, so a successful payment (201 or the 200 replay) resolves that reference to
// the order's id through GET /api/orders?orderReference=… and links to /orders/<id>. Ported by content from #8's billing-view.tsx `useOrderIdByReference` and #7's `useOrderByReferenceQuery`,
// with #8's three answers (resolving / found / asked-and-empty / failed) kept and the failed one shown in the problem's own words (acceptance item 4).
// Fixtures: the order id, the order reference and the invoice reference are three distinct values and none contains another; a second row of the answer is a decoy with its own id.
import { screen } from '@testing-library/dom';
import { afterEach, describe, expect, it } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { json, problemResponse } from './testing/browser-harness';
import { gate, mountPage } from './testing/page-test';
import { buttonNamed, byLabel, typeInto } from './testing/page-sweep';
import { orderSummary } from './testing/orders-fixtures';
import { paymentAccepted, paymentDuplicate } from './testing/stock-billing-fixtures';

afterEach(() => TestBed.resetTestingModule());

const PAID_ORDER_REFERENCE = 'ORD-000042'; // what paymentAccepted() answers as the paid invoice's orderReference
const PAID_ORDER_ID = 'a1b2c3d4-0000-4000-8000-00000000f042';
const DECOY_ORDER_ID = 'd3c0de00-0000-4000-8000-00000000f099';
const PAY_ANY = /^POST \/api\/invoices\/[^/]+\/payments$/;
const LOOKUP = /^GET \/api\/orders\?orderReference=/;
/** ANY orders read: the billing page makes no other, so an ungated lookup (sent with no reference) is caught by this and not by LOOKUP. */
const ANY_ORDERS_READ = /^GET \/api\/orders(\?|$)/;
const LOOKUP_KEY = `GET /api/orders?orderReference=${PAID_ORDER_REFERENCE}&page=1&pageSize=1`;
const found = () => ({ items: [{ ...orderSummary(42), orderId: PAID_ORDER_ID, orderReference: PAID_ORDER_REFERENCE }, { ...orderSummary(99), orderId: DECOY_ORDER_ID, orderReference: 'ORD-000099' }], page: { page: 1, pageSize: 1, total: 2 } });
const problem = (status: number, detail: string, code = 'DOMAIN_ERROR') => problemResponse(status, { type: 'about:blank', title: 'decoy-title', status, detail, code });
const flat = (node: Element | null) => (node?.textContent ?? '').replace(/\s+/g, ' ').trim();
const registerFor = (reference: string) => screen.getByRole<HTMLButtonElement>('button', { name: `Register payment ${reference}` });

async function pay(m: { settle: () => Promise<void> }) {
  registerFor('INV-000027').click();
  await m.settle();
  buttonNamed('Submit payment').click();
  await m.settle();
}

describe('R-order-link: a successful payment links to the paid invoice\'s order, found by its reference', () => {
  it.each([
    ['201 accepted', () => json(paymentAccepted('PAY-X'), 201)],
    ['200 duplicate (an idempotent replay)', () => json(paymentDuplicate('PAY-X'), 200, { 'Idempotent-Replay': 'true' })],
  ])('%s: the link\'s href is /orders/<the matching order\'s id>, not its reference, not the invoice\'s reference, not another row\'s id', async (_name, answer) => {
    const { m } = await mountPage('/billing', [
      [PAY_ANY, answer],
      [LOOKUP, () => json(found())],
    ]);
    await pay(m);
    const link = screen.getByTestId('view-order-link');
    expect(link.getAttribute('href')).toBe(`/orders/${PAID_ORDER_ID}`);
    expect(flat(link)).toBe("Watch it on the order's live timeline");
    expect(screen.queryByTestId('view-order-link-not-found')).toBeNull();
    expect(screen.queryByTestId('view-order-link-error')).toBeNull();
    expect(screen.queryByTestId('view-order-link-resolving')).toBeNull();
  });

  it('the request is GET /api/orders with the PAID invoice\'s orderReference (from the response, not from the filter box), once, and nothing else filtered', async () => {
    const { m, s } = await mountPage('/billing', [
      [PAY_ANY, () => json(paymentAccepted('PAY-X'), 201)],
      [LOOKUP, () => json(found())],
    ]);
    // A different reference sits in the "Invoice order reference" filter box: the lookup must not read it.
    const box = byLabel('Invoice order reference') as HTMLInputElement;
    typeInto(box, 'ORD-000777');
    box.dispatchEvent(new Event('change', { bubbles: true }));
    await m.settle();
    await pay(m);
    expect(s.matching(LOOKUP).map((call) => call.key)).toEqual([LOOKUP_KEY]);
  });

  it('no lookup is sent while the panel is merely open, none after a payment that FAILED, and one only after a success', async () => {
    let answered = 0;
    const { m, s } = await mountPage('/billing', [
      [PAY_ANY, () => (++answered === 1 ? problem(409, 'Invoice INV-000027 is already paid.', 'INVOICE_ALREADY_PAID') : json(paymentAccepted('PAY-X'), 201))],
      [LOOKUP, () => json(found())],
    ]);
    expect(s.count(ANY_ORDERS_READ), 'a page that has paid nothing asks nothing').toBe(0);
    registerFor('INV-000027').click();
    await m.settle();
    expect(s.count(ANY_ORDERS_READ), 'an open panel asks nothing').toBe(0);
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(screen.queryByTestId('payment-error')).not.toBeNull();
    expect(s.count(ANY_ORDERS_READ), 'a refused payment asks nothing').toBe(0);
    expect(screen.queryByTestId('view-order-link')).toBeNull();
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(s.count(ANY_ORDERS_READ), 'the success asks once').toBe(1);
  });

  it('while the lookup is in flight only "Resolving the order link…" shows, then the link replaces it', async () => {
    const held = gate();
    const { m } = await mountPage('/billing', [
      [PAY_ANY, () => json(paymentAccepted('PAY-X'), 201)],
      [LOOKUP, held.answer],
    ]);
    registerFor('INV-000027').click();
    await m.settle();
    buttonNamed('Submit payment').click();
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(held.started(), 'the lookup must be in flight for this to prove anything').toBe(true);
    expect(flat(screen.getByTestId('view-order-link-resolving'))).toBe('Resolving the order link…');
    expect(screen.queryByTestId('view-order-link')).toBeNull();
    held.release(json(found()));
    await m.settle();
    expect(screen.queryByTestId('view-order-link-resolving')).toBeNull();
    expect(screen.queryByTestId('view-order-link')).not.toBeNull();
  });

  it('the lookup ANSWERED and found no order: it says so, names the reference, and neither a link nor "Resolving" stays', async () => {
    const { m } = await mountPage('/billing', [
      [PAY_ANY, () => json(paymentAccepted('PAY-X'), 201)],
      [LOOKUP, () => json({ items: [], page: { page: 1, pageSize: 1, total: 0 } })],
    ]);
    await pay(m);
    expect(flat(screen.getByTestId('view-order-link-not-found'))).toBe(`No order was found for ${PAID_ORDER_REFERENCE}, so there is no timeline to link to.`);
    expect(screen.queryByTestId('view-order-link')).toBeNull();
    expect(screen.queryByTestId('view-order-link-resolving')).toBeNull();
    expect(screen.queryByTestId('view-order-link-error')).toBeNull();
  });

  it.each([
    [404, 'No order matches that reference.', 'NOT_FOUND'],
    [403, 'The operator may not read orders.', 'FORBIDDEN'],
  ])("the lookup FAILED with %i: the problem's own detail shows (not the decoy title, not a generic line), the payment outcome stays, and there is no link", async (status, detail, code) => {
    const { m } = await mountPage('/billing', [
      [PAY_ANY, () => json(paymentAccepted('PAY-X'), 201)],
      [LOOKUP, () => problem(status, detail, code)],
    ]);
    await pay(m);
    expect(flat(screen.getByTestId('view-order-link-error'))).toBe(`The order link could not be resolved: ${detail}`);
    expect(screen.queryByText('decoy-title')).toBeNull();
    expect(screen.queryByTestId('view-order-link')).toBeNull();
    expect(screen.queryByTestId('view-order-link-not-found'), 'a failed lookup is not an empty answer').toBeNull();
    expect(screen.queryByTestId('view-order-link-resolving')).toBeNull();
    expect(screen.queryByTestId('payment-outcome-accepted'), 'the payment itself succeeded and still says so').not.toBeNull();
  });

  it('a failed lookup with no problem document says it failed in its fallback words, and still no link', async () => {
    const { m } = await mountPage('/billing', [
      [PAY_ANY, () => json(paymentAccepted('PAY-X'), 201)],
      [LOOKUP, () => new Response('<html>bad gateway</html>', { status: 404, headers: { 'Content-Type': 'text/html' } })],
    ]);
    await pay(m);
    expect(flat(screen.getByTestId('view-order-link-error'))).toBe('The order link could not be resolved: the request failed');
  });

  it('a response that carries no orderReference asks nothing and shows no link state at all', async () => {
    const { orderReference: _dropped, ...withoutReference } = paymentAccepted('PAY-X');
    const { m, s } = await mountPage('/billing', [[PAY_ANY, () => json(withoutReference, 201)]]);
    await pay(m);
    expect(s.count(ANY_ORDERS_READ)).toBe(0);
    for (const id of ['view-order-link', 'view-order-link-not-found', 'view-order-link-error', 'view-order-link-resolving']) expect(screen.queryByTestId(id), id).toBeNull();
  });

  it('closing the panel and opening another invoice drops the link of the previous payment', async () => {
    const { m } = await mountPage('/billing', [
      [PAY_ANY, () => json(paymentAccepted('PAY-X'), 201)],
      [LOOKUP, () => json(found())],
    ]);
    await pay(m);
    expect(screen.queryByTestId('view-order-link')).not.toBeNull();
    registerFor('INV-000028').click();
    await m.settle();
    expect(screen.queryByTestId('view-order-link')).toBeNull();
  });
});
