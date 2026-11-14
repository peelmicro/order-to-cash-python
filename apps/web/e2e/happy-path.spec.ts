import { expect, test } from '@playwright/test';

/**
 * Items 1 of feature 32: scenario 1 (an order reaches `completed`) and scenario 3 (a payment flips the invoice to `paid`), in ONE order, as #7's and
 * #8's `happy-path.spec.ts` did: place a non-.99 order, wait for `invoiced`, register the payment through the billing UI, the invoice row flips to
 * `paid`, the order reaches `completed`. One order is placed, not two, and each fact is still asserted explicitly.
 *
 * Synchronisation rule (binding): every wait below is for a TERMINAL or MONOTONIC fact. `invoiced` is where the automatic part of the saga rests until
 * a human registers a payment; `paid` on an invoice never reverts; `completed` is the order's terminal state. Nothing polls a transient mid-saga status
 * (`stock_reserved`, `credit_approved`, `confirmed`, `despatched`), which the saga leaves within one poll by construction.
 *
 * `completed` is asserted twice on purpose: by the timeline holding `order.completed.v1`, and by the badge on a RELOADED page. A live badge passes through
 * `paid` on its way to `completed` (#8's reviewer substituted `paid` for `completed` and the test still passed), so a polling assertion on the live badge
 * cannot tell the two apart; a read after a reload, of a terminal order, can.
 *
 * Data: CarrefourEs (EUR) buying from ALBIONFOODS: PRD-0006, quantity 2, no price override, 2 x 645 = 12.90 (not .99). ALBIONFOODS is one of the 22 seeded
 * companies with the full baseline stock (500 units of each seeded product) and a 500 000 credit line with every retailer, so neither STOCK_UNAVAILABLE
 * nor a credit refusal can fail this test for a reason it does not exist to cover. Consumption: 2 units of PRD-0006 per run (see the record, N1).
 */
test('an order with a non-.99 total reaches completed, and the invoice explicitly flips to paid', async ({ page }) => {
  await page.goto('/orders/place');

  // Role `combobox`, not `getByLabel`: until the catalogue resolves the form renders a plain text <input> under the SAME label and id, which getByLabel
  // would match at once, and `selectOption` on it fails outright (#8 found this live). Only the real <select> carries role=combobox, so Playwright's
  // auto-wait holds for it.
  await page.getByRole('combobox', { name: 'Retailer' }).selectOption('CarrefourEs');
  await page.getByRole('combobox', { name: 'Company' }).selectOption('ALBIONFOODS');
  // These two go through the LABELS (`for` -> `id`), so they fail if a label and its control ever disagree (#8 id 106; place-order-labels.spec.ts holds the
  // dedicated proof). #8 routed around the defect with a structural locator; #9 has no reason to.
  await page.getByLabel('Product', { exact: true }).selectOption('PRD-0006');
  await page.getByLabel('Quantity', { exact: true }).fill('2');

  const submit = page.getByRole('button', { name: 'Place order', exact: true });
  await expect(submit).toBeEnabled();
  await submit.click();

  // #9 has no success banner (#7's and #8's had one): a 201 navigates straight to the order's page (place.page.ts, `onSuccess`).
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]{36}$/);
  const orderUrl = page.url();

  // Terminal wait #1: `invoiced`, the saga's resting point until a payment arrives.
  await expect(page.getByTestId('order-detail-status')).toHaveText('invoiced', { timeout: 30_000 });
  const reference = (await page.getByTestId('order-detail-reference').innerText()).trim();
  expect(reference, 'the order page names an ORD-nnnnnn reference once projected').toMatch(/^ORD-\d{6}$/);

  await page.goto('/billing');
  // Filter to this order's reference (the field commits on `change`), so the row is found however many invoices earlier runs left behind.
  const orderFilter = page.getByLabel('Invoice order reference');
  await orderFilter.fill(reference);
  await orderFilter.press('Enter');
  const invoiceRow = page.getByTestId('invoice-row').filter({ hasText: reference });
  await expect(invoiceRow).toHaveCount(1);
  await expect(invoiceRow.getByTestId('invoice-status')).toHaveText('issued');

  await invoiceRow.getByTestId('register-payment-button').click();
  const paymentForm = page.getByTestId('payment-form');
  await expect(paymentForm).toBeVisible();
  await expect(paymentForm).toContainText(reference);

  // The form opens pre-filled (a suggested payment reference, the invoice's exact total), submitted as it stands: the "register a payment through the billing UI" step.
  await paymentForm.getByRole('button', { name: 'Submit payment' }).click();
  await expect(paymentForm.getByTestId('payment-outcome-accepted')).toBeVisible();

  // Scenario 3, explicit: the invoice row's own badge flips to `paid` (terminal for an invoice, so monotonic evidence).
  await expect(invoiceRow.getByTestId('invoice-status')).toHaveText('paid');

  const viewOrder = paymentForm.getByTestId('view-order-link');
  await expect(viewOrder).toBeVisible();
  await viewOrder.click();
  await expect(page).toHaveURL(orderUrl);

  // Terminal wait #2: the terminal FACT, `order.completed.v1`, rendered on the timeline (monotonic: nothing follows it).
  await expect(page.getByTestId('timeline-entry').filter({ hasText: 'order.completed.v1' })).toHaveCount(1, { timeout: 30_000 });

  // Then a fresh read of the order: after a reload the page is a plain `GET /orders/{id}` of a terminal order, with no event still on its way, so the badge
  // here is the persisted status and cannot be the transient `paid` that a live badge passes through on its way to `completed`.
  await page.reload();
  await expect(page.getByTestId('order-detail-status')).toHaveText('completed');
  await expect(page.getByTestId('order-detail-cancellation')).toHaveCount(0);
});
