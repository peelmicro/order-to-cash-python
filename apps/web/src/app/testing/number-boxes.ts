/**
 * The number boxes of the app, as last reviewed: a NEW one fails BOTH halves of the guard until it is added here, with `[appDraftValue]` and a `validity.badInput` handler.
 * The syntax half (src/app/number-boxes.spec.ts) reads the templates; the render half (src/app/error-text.sweep.spec.ts) reads the live DOM of every state the sweep reaches.
 */
export const EXPECTED_NUMBER_BOXES = [
  'pages/(app)/billing/index.page.ts | invoice-age-input',
  'pages/(app)/billing/index.page.ts | payment-amount-input',
  'pages/(app)/orders/place.page.ts | line-discount-input',
  'pages/(app)/orders/place.page.ts | quantity-input',
  'pages/(app)/orders/place.page.ts | unit-price-input',
  'pages/(app)/stock/index.page.ts | replenish-units-input',
];

/** The same boxes by `data-testid` alone, which is all a rendered element can say about itself. */
export const EXPECTED_NUMBER_BOX_IDS = EXPECTED_NUMBER_BOXES.map((key) => key.split(' | ')[1]!).sort();
