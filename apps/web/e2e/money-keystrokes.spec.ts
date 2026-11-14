import { expect, test, type Page } from '@playwright/test';

/**
 * Item 4 of feature 32, carried from feature 29 stage 2 item 8: typing "19.99" into the unit price and "0.29" into the line discount of a COLD
 * `/orders/place`, with the page's render deferred, SHOWS and SENDS exactly 1999 and 29 minor units.
 *
 * The defect it guards: on `<input type="number">` Chromium keeps the typed text ("19.") on screen while `value` reports its parse ("19"); a `[value]`
 * binding that re-assigns the draft a render after the keystroke replaces the screen text and moves the caret to the start, so the next keys land in
 * front ("19.99" -> "9919", sent as 991900; "0.29" -> "290", sent as 29000). The render has to land BETWEEN two keys, so the failure needs a render that
 * is slow relative to the key gap. Two lag configurations reproduce it deterministically on the pre-fix build (progress/review_web_app.md, "Stage 2
 * re-review (fix round 1)": 5/5 and 5/5 cold runs), and the mechanism below is that review's `keys.mjs` probe, ported:
 *
 *   - an init script that adds `lag` ms to every `setTimeout` and `requestAnimationFrame` (what makes a render late);
 *   - `keyboard.type` with a per-key `delay`, typing as soon as the box is attached, with no settling wait (a cold page).
 *
 * "Sends" is the request body Playwright observes on the wire (`page.route`), not the DOM value: the POST to `/api/orders` is captured and answered
 * with a 503, so the guard places no real order and consumes no stock. The catalogue, the session and every other call are the real stack's.
 * A DOM value is read as well, before and after the submit.
 *
 * Armed by restoring `[value]` on the three number inputs of `place.page.ts` (record, section "Arms").
 */
const CONFIGURATIONS = [
  { name: 'render lag 150 ms, key gap 60 ms', lagMs: 150, keyDelayMs: 60 },
  { name: 'render lag 60 ms, key gap 40 ms', lagMs: 60, keyDelayMs: 40 },
];

/** Sets the Place-order form's three fields from the real catalogue, submits, and returns the body the browser sent. */
async function submitAndCaptureBody(page: Page): Promise<{ lines: Array<Record<string, unknown>> }> {
  await page.getByRole('combobox', { name: 'Retailer' }).selectOption('CarrefourEs');
  await page.getByRole('combobox', { name: 'Company' }).selectOption('ALBIONFOODS');
  await page.getByLabel('Product', { exact: true }).selectOption('PRD-0006');
  const sent = page.waitForRequest((request) => request.method() === 'POST' && new URL(request.url()).pathname === '/api/orders');
  await page.getByRole('button', { name: 'Place order', exact: true }).click();
  const request = await sent;
  return JSON.parse(request.postData() ?? 'null') as { lines: Array<Record<string, unknown>> };
}

for (const { name, lagMs, keyDelayMs } of CONFIGURATIONS) {
  test(`typing 19.99 and 0.29 on a cold place-order page under ${name} shows and sends 1999 and 29`, async ({ page }) => {
    // Never place a real order from this guard: capture the POST, answer 503. Everything else falls through to the real stack.
    await page.route('**/api/orders', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      return route.fulfill({ status: 503, contentType: 'application/problem+json', body: JSON.stringify({ type: 'about:blank', title: 'e2e guard', status: 503, detail: 'e2e keystroke guard: not placed' }) });
    });

    await page.addInitScript((lag) => {
      const originalSetTimeout = window.setTimeout.bind(window);
      window.setTimeout = ((handler: TimerHandler, delay = 0, ...args: unknown[]) => originalSetTimeout(handler, delay + lag, ...args)) as typeof window.setTimeout;
      window.requestAnimationFrame = ((callback: FrameRequestCallback) => originalSetTimeout(() => callback(performance.now()), lag)) as typeof window.requestAnimationFrame;
    }, lagMs);

    // Cold: a new page, navigation committed, typing begins the moment the box is attached.
    await page.goto('/orders/place', { waitUntil: 'commit' });
    const unitPrice = page.getByTestId('unit-price-input');
    const lineDiscount = page.getByTestId('line-discount-input');
    await unitPrice.waitFor({ state: 'attached' });
    await unitPrice.click();
    await page.keyboard.type('19.99', { delay: keyDelayMs });
    await lineDiscount.click();
    await page.keyboard.type('0.29', { delay: keyDelayMs });

    // A bounded settle, deliberately fixed: this waits for a NEGATIVE ("no late render rewrites what was typed"), which no condition can signal. It is
    // several times the largest lag, so a deferred render has landed by now.
    await page.waitForTimeout(600);
    await expect(unitPrice).toHaveValue('19.99');
    await expect(lineDiscount).toHaveValue('0.29');

    const body = await submitAndCaptureBody(page);
    expect(body.lines, 'one line was sent').toHaveLength(1);
    expect(body.lines[0]?.['unitPrice'], 'unitPrice on the wire is 1999 minor units').toBe(1999);
    expect(body.lines[0]?.['lineDiscount'], 'lineDiscount on the wire is 29 minor units').toBe(29);

    // The failed submit re-renders the form; what is on screen must still be what was typed.
    await expect(unitPrice).toHaveValue('19.99');
    await expect(lineDiscount).toHaveValue('0.29');
  });
}
