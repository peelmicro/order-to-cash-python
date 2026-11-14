import { expect, test } from '@playwright/test';

/**
 * #7's D1/D2/D7 on the live app (`../order-to-cash-nestjs/progress/review_e2e_playwright.md`): an order page whose event stream delivers NOTHING must
 * not stay stale under a badge that says "Live". #7's page did exactly that after a lost frame, and its e2e flaked because `toHaveText('completed')`
 * polled a DOM that never changed. The fix is the BACKSTOP re-read: the non-terminal branch of `RefetchPlan.interval` (`src/app/lib/order-detail.ts`,
 * `STALE_STATUS_BACKSTOP_MS`), wired as the order page's `refetchInterval` (`orders/[id].page.ts`); the rule itself is unit-tested in
 * `src/app/lib/order-detail.spec.ts`. THIS test proves that branch end to end, and is built so that nothing else can satisfy it:
 *
 * - The order is placed and brought to `invoiced` on a SECOND page. The page under test is opened afterwards, so its FIRST read is a plain `200 invoiced`:
 *   never a `202 projection_pending`, hence R55's pending retry (the `pending` branch of the same method) has nothing to retry and cannot rescue it
 *   (the reviewer measured that retry returning the new status at ~2.5 s in the earlier version of this test, which made the backstop, first firing at
 *   ~7.5 s, unnecessary: deleting only the backstop branch left it green).
 * - Its stream request is held open and never answered (no frame, no error, no reconnect, no "gave-up" re-check), so the page can only hear nothing.
 * - The payment is registered through the billing UI on the second page. Afterwards the ONLY way the first page can learn `completed` is a re-read of
 *   `GET /orders/{id}` on its own timer, and a `200` whose status is non-terminal is answered by exactly one branch: the backstop.
 *
 * The premise is asserted, not assumed: the page under test shows `invoiced` before the payment, and its own connection badge must NOT read "connected"
 * at the end, or the stream was not really silent.
 */
test('a silent event stream cannot keep an invoiced order page stale: the backstop re-read brings it to completed', async ({ page, context }) => {
  // A handler that never fulfils, aborts or continues: the browser's EventSource stays "connecting" forever. (Aborting instead would let the page's other
  // recovery, the one-off re-check after it gives up, bring the status in after ~15 s and hide a missing interval: measured with the interval removed.)
  // Registered on THIS page only: the second page below keeps its live stream.
  await page.route('**/api/orders/stream**', () => undefined);

  // The second page places the order and waits for the saga's resting point, so the order is projected before the page under test ever reads it.
  const operator = await context.newPage();
  await operator.goto('/orders/place');
  await operator.getByRole('combobox', { name: 'Retailer' }).selectOption('CarrefourEs');
  await operator.getByRole('combobox', { name: 'Company' }).selectOption('ALBIONFOODS');
  await operator.getByLabel('Product', { exact: true }).selectOption('PRD-0006');
  await operator.getByRole('button', { name: 'Place order', exact: true }).click();
  await expect(operator).toHaveURL(/\/orders\/[0-9a-f-]{36}$/);
  const orderUrl = operator.url();
  await expect(operator.getByTestId('order-detail-status')).toHaveText('invoiced', { timeout: 30_000 });
  const reference = (await operator.getByTestId('order-detail-reference').innerText()).trim();
  expect(reference).toMatch(/^ORD-\d{6}$/);

  // The page under test: its first read is a 200 `invoiced` (non-terminal), and from here it hears nothing from the stream.
  await page.goto(orderUrl);
  await expect(page.getByTestId('order-detail-status')).toHaveText('invoiced');
  await expect(page.getByTestId('stream-status')).not.toHaveAttribute('data-status', 'connected');

  // The payment, through the billing UI, on the second page.
  await operator.goto('/billing');
  const orderFilter = operator.getByLabel('Invoice order reference');
  await orderFilter.fill(reference);
  await orderFilter.press('Enter');
  const invoiceRow = operator.getByTestId('invoice-row').filter({ hasText: reference });
  await expect(invoiceRow).toHaveCount(1);
  await invoiceRow.getByTestId('register-payment-button').click();
  const paymentForm = operator.getByTestId('payment-form');
  await paymentForm.getByRole('button', { name: 'Submit payment' }).click();
  await expect(paymentForm.getByTestId('payment-outcome-accepted')).toBeVisible();
  await expect(invoiceRow.getByTestId('invoice-status')).toHaveText('paid');

  // `completed` is terminal, so waiting for it is waiting for a monotonic fact. The silent page was never reloaded and never navigated: only its own
  // interval can have brought it here (the backstop fires every 5 s, well inside the 30 s assertion timeout).
  await expect(
    page.getByTestId('order-detail-status'),
    'the backstop: a silent page showing a NON-TERMINAL status (invoiced) must re-read the order on its own timer and reach completed',
  ).toHaveText('completed', { timeout: 30_000 });
  await expect(page.getByTestId('stream-status')).not.toHaveAttribute('data-status', 'connected');
  expect(page.url()).toBe(orderUrl);
});
