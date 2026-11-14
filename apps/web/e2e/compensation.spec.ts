import { expect, test } from '@playwright/test';

/**
 * Item 2 of feature 32, and R28's end-to-end half (`specs/shared/test-matrix.md`): the `.99` compensation path. `fillCompensationDemo()` in
 * `place.page.ts` builds one line with an explicit unit price of 24 999 minor units: a total ending in `.99`, which the credit simulator refuses
 * (`simulated_cents_rule`), so the saga releases the stock and cancels the order.
 *
 * The demo fill takes the FIRST retailer, company and product of the catalogue (the Gateway sorts by code), so on the seeded data this is AldiDe, ALBIONFOODS
 * and PRD-0001. The test does not assert which they are: the running total is what it depends on, and 24 999 reads "249.99" whatever the retailer's currency
 * (every seeded currency has exponent 2).
 *
 * Synchronisation: waits only for `cancelled`, the terminal state, never a mid-compensation state.
 *
 * **On the ordering assertion** (ported from #7's `compensation.spec.ts` D4, and #8's). The `.99` refusal is deterministic, but amendment A1's original
 * defect in #7 was a random `eventId` tie-break, so an end-to-end ordering check is a probabilistic guard against that class: it catches a full inversion,
 * not every instance of a random tie-break. The deterministic guard for the class is the black-box `assertCausalOrder` over every timeline entry of the
 * API suite (feature 31); this is the real-browser confirmation on top, not a replacement.
 */
test('a .99 order is cancelled with credit_rejected, and the timeline shows both compensation steps in order with the causal link rendered', async ({ page }) => {
  await page.goto('/orders/place');

  // Wait for the REAL catalogue before the fill: the fill takes `retailers.data()?.[0]`, and before the answer lands it falls back to literals
  // (CarrefourEs / IBERFOODS / PRD-0001) that never reach a <select>. The combobox only exists once all three lists are usable.
  await expect(page.getByRole('combobox', { name: 'Retailer' })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Company' })).toBeVisible();
  await expect(page.getByLabel('Product', { exact: true })).toHaveJSProperty('tagName', 'SELECT');

  await page.getByRole('button', { name: 'Fill demo order (.99 → compensation)' }).click();
  // Sanity: the demo order's total really ends in .99 (the premise of the whole scenario).
  await expect(page.getByTestId('running-total')).toContainText('249.99');

  const submit = page.getByRole('button', { name: 'Place order', exact: true });
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]{36}$/);

  // Terminal wait: `cancelled`, where this saga rests for good.
  await expect(page.getByTestId('order-detail-status')).toHaveText('cancelled', { timeout: 30_000 });
  await expect(page.getByTestId('order-detail-cancellation')).toHaveText('credit_rejected');

  // Each entry's second <p> is its event type (the first is the human summary): see the `<li>` in `[id].page.ts`. A text-filtered locator would match
  // BOTH entries for "stock.released.v1", because the cancellation entry's own "caused by stock.released.v1" line contains that text.
  const entries = page.getByTestId('timeline-entry');
  const readEventTypes = () => entries.evaluateAll((nodes) => nodes.map((node) => node.querySelectorAll('p')[1]?.textContent?.trim() ?? ''));

  // The relationship, not an exact count (a legitimate new fact on this path must not break this test): both compensation facts are rendered.
  await expect
    .poll(readEventTypes, { message: 'expected the timeline to render both stock.released.v1 and order.cancelled.v1' })
    .toEqual(expect.arrayContaining(['stock.released.v1', 'order.cancelled.v1']));

  const types = await readEventTypes();
  const releasedAt = types.indexOf('stock.released.v1');
  const cancelledAt = types.indexOf('order.cancelled.v1');
  expect(releasedAt, `stock.released.v1 rendered among ${JSON.stringify(types)}`).toBeGreaterThanOrEqual(0);
  expect(cancelledAt, `order.cancelled.v1 rendered among ${JSON.stringify(types)}`).toBeGreaterThanOrEqual(0);
  // The index must point at the entry of EXACTLY that type: `indexOf` of a sibling type (`stock.reserved.v1` also precedes the cancellation) would leave the
  // ordering below true for the wrong entry (the reviewer's R3 substitution passed it; only the `href` check further down caught it).
  expect(types[releasedAt], 'the ordering index must point at the stock.released.v1 entry').toBe('stock.released.v1');
  expect(types[cancelledAt], 'the ordering index must point at the order.cancelled.v1 entry').toBe('order.cancelled.v1');
  expect(releasedAt, `stock.released.v1 must be rendered BEFORE order.cancelled.v1, got ${JSON.stringify(types)}`).toBeLessThan(cancelledAt);

  // The causal edge, rendered: the cancellation entry reads "caused by stock.released.v1", and the link points at THE stock.released.v1 entry of this
  // timeline (its `data-event-id`), not merely at text that happens to read the same.
  const cancelled = entries.nth(cancelledAt);
  const causation = cancelled.getByTestId('timeline-causation');
  await expect(causation).toBeVisible();
  await expect(causation).toContainText('caused by');
  const link = cancelled.getByTestId('timeline-causation-link');
  await expect(link).toHaveText('stock.released.v1');
  const releasedEventId = await entries.nth(releasedAt).getAttribute('data-event-id');
  expect(releasedEventId, 'the stock.released.v1 entry carries its event id').toBeTruthy();
  await expect(link).toHaveAttribute('href', `#timeline-entry-${releasedEventId}`);
});
