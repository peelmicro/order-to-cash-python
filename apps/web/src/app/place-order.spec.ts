// Place order (R13, R42): typed amounts become integer minor units exactly (#7 review pass 5's float bug), the input step follows the currency's
// exponent, a submit cannot double-fire, the result navigates to the order, a refusal shows the problem's own words, a failed catalogue read shows that
// read's own text, and a label's `for` is its control's `id` on every render (#8 id 106).
import { fireEvent, screen } from '@testing-library/dom';
import { afterEach, describe, expect, it } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { json, problemResponse } from './testing/browser-harness';
import { ORDER_ID, placeOrderResponse } from './testing/orders-fixtures';
import { gate, mountPage, type Stub } from './testing/page-test';
import { writesWhileTyping } from './testing/number-input';
import { buttonNamed, byLabel, choose, SUCCESS, typeInto } from './testing/page-sweep';
import type { Mounted } from './testing/browser-harness';

afterEach(() => TestBed.resetTestingModule());

const POST = 'POST /api/orders';
const posts = (s: Stub) => s.matching(POST);
const bodyOf = (s: Stub) => (posts(s).at(-1)!.init!.body as string);
const form = () => screen.getByTestId('place-order-form') as HTMLFormElement;

async function fillBasics(m: Mounted, product = 'PRD-0001') {
  choose(byLabel('Retailer'), 'CarrefourEs');
  choose(byLabel('Company'), 'IBERFOODS');
  choose(byLabel('Product'), product);
  await m.settle();
}
const fieldIn = (label: string) => screen.getByLabelText<HTMLInputElement>(label);

describe('R-bytes: the BFF receives integer minor units, exactly', () => {
  it.each([
    ['19.99', 1999],
    ['0.29', 29], // 0.29 * 100 = 28.999999999999996 in IEEE 754: the float trap
    ['4.35', 435],
    ['249.99', 24999],
    ['1.10', 110],
    ['.5', 50],
  ])('a unit price typed "%s" is sent as %i, in the request body\'s bytes', async (typed, minor) => {
    const { m, s } = await mountPage('/orders/place');
    await fillBasics(m);
    typeInto(fieldIn('Unit price override'), typed);
    typeInto(fieldIn('Quantity'), '2');
    buttonNamed('Place order').click();
    await m.settle();
    expect(bodyOf(s), 'the exact bytes the BFF receives').toBe(`{"retailerCode":"CarrefourEs","companyCode":"IBERFOODS","currency":"EUR","lines":[{"productCode":"PRD-0001","quantity":2,"unitPrice":${minor}}]}`);
  });

  it('a line discount is minor units too; a zero discount is not sent; an untouched price is not sent (the catalogue price applies)', async () => {
    const { m, s } = await mountPage('/orders/place');
    await fillBasics(m);
    typeInto(fieldIn('Line discount'), '0.29');
    buttonNamed('Place order').click();
    await m.settle();
    expect(bodyOf(s)).toBe('{"retailerCode":"CarrefourEs","companyCode":"IBERFOODS","currency":"EUR","lines":[{"productCode":"PRD-0001","quantity":1,"lineDiscount":29}]}');
  });

  it('JPY takes whole amounts only: "1999" is sent as 1999, "19.99" is refused in words and nothing is sent', async () => {
    const { m, s } = await mountPage('/orders/place');
    choose(byLabel('Retailer'), 'TokyoMart');
    choose(byLabel('Company'), 'IBERFOODS');
    choose(byLabel('Product'), 'PRD-0001');
    await m.settle();
    expect(fieldIn('Currency').value).toBe('JPY');
    typeInto(fieldIn('Unit price override'), '19.99');
    buttonNamed('Place order').click();
    await m.settle();
    expect(posts(s)).toHaveLength(0);
    expect(screen.getByText(/Enter a whole amount \(JPY\)\./)).toBeTruthy();
    typeInto(fieldIn('Unit price override'), '1999');
    buttonNamed('Place order').click();
    await m.settle();
    expect(bodyOf(s)).toContain('"currency":"JPY"');
    expect(bodyOf(s)).toContain('"unitPrice":1999');
  });

  it('BHD takes three decimals ("1.005" -> 1005), EUR refuses "1.005" (never rounded to 100 or 101)', async () => {
    const { m, s } = await mountPage('/orders/place');
    await fillBasics(m);
    typeInto(fieldIn('Unit price override'), '1.005');
    buttonNamed('Place order').click();
    await m.settle();
    expect(posts(s)).toHaveLength(0);
    expect(screen.getByText(/Enter an amount with at most 2 decimals \(EUR\)\./)).toBeTruthy();
    typeInto(fieldIn('Currency'), 'BHD');
    await m.settle();
    buttonNamed('Place order').click();
    await m.settle();
    expect(bodyOf(s)).toContain('"currency":"BHD"');
    expect(bodyOf(s)).toContain('"unitPrice":1005');
  });

  it('a quantity that is not a whole number of at least 1 is refused in words and nothing is sent', async () => {
    const { m, s } = await mountPage('/orders/place');
    await fillBasics(m);
    for (const typed of ['0', '1.5', '-2', '', 'abc']) {
      typeInto(fieldIn('Quantity'), typed);
      buttonNamed('Place order').click();
      await m.settle();
    }
    expect(posts(s)).toHaveLength(0);
    expect(screen.getAllByText('Quantity: enter a whole number of at least 1.').length).toBeGreaterThan(0);
  });
});

/** What Chromium does with "1-2" in a `type="number"` box: the text stays on screen, `value` is "" and `validity.badInput` is true. jsdom sanitises the value the same way but has no such validity, so it is defined here. */
function typeUnparseable(input: HTMLInputElement): void {
  Object.defineProperty(input, 'validity', { configurable: true, value: { badInput: true } });
  fireEvent.input(input, { target: { value: '' } });
}
function typeParseable(input: HTMLInputElement, value: string): void {
  Object.defineProperty(input, 'validity', { configurable: true, value: { badInput: false } });
  typeInto(input, value);
}

describe('R-bad-input (stage 2 review B1): a money box whose text the browser cannot parse is refused in words, never read as "not overridden"', () => {
  it.each([
    ['Unit price override', 'unit price'],
    ['Line discount', 'line discount'],
  ])('%s: an unparseable text sends nothing, shows the problem, and a parseable retype sends the typed amount', async (label, _name) => {
    const { m, s } = await mountPage('/orders/place');
    await fillBasics(m);
    typeUnparseable(fieldIn(label));
    buttonNamed('Place order').click();
    await m.settle();
    expect(posts(s), 'nothing may be sent: no catalogue-price fallback, no "no discount"').toHaveLength(0);
    expect(screen.getByText(/Enter an amount with at most 2 decimals \(EUR\)\./)).toBeTruthy();
    expect(fieldIn(label).getAttribute('aria-invalid')).toBe('true');
    typeParseable(fieldIn(label), '0.29');
    buttonNamed('Place order').click();
    await m.settle();
    expect(posts(s)).toHaveLength(1);
    expect(bodyOf(s)).toContain(label === 'Line discount' ? '"lineDiscount":29' : '"unitPrice":29');
  });

  it.each([
    ['Unit price override', '90071992547409.92'],
    ['Line discount', '90071992547409.92'],
  ])('%s: a well-formed amount that is too large is refused for its size, naming the largest amount (review A2), and nothing is sent', async (label, typed) => {
    const { m, s } = await mountPage('/orders/place');
    await fillBasics(m);
    typeParseable(fieldIn(label), typed);
    buttonNamed('Place order').click();
    await m.settle();
    expect(posts(s)).toHaveLength(0);
    expect(screen.getByText('Enter an amount of at most 90071992547409.91 (EUR).')).toBeTruthy();
  });

  it('Quantity: an unparseable text is refused in words that say the browser could not read it, and nothing is sent (an EMPTY value is refused too, with the plain sentence)', async () => {
    const { m, s } = await mountPage('/orders/place');
    await fillBasics(m);
    typeUnparseable(fieldIn('Quantity'));
    buttonNamed('Place order').click();
    await m.settle();
    expect(posts(s)).toHaveLength(0);
    expect(screen.getByText('Quantity: the browser could not read what was typed. Enter a whole number of at least 1.'), 'an unreadable text is told apart from an empty one').toBeTruthy();
    // An EMPTY value (what a cleared box reports, `badInput` false) is refused with the plain sentence, and is never read as "1": nothing is sent.
    typeParseable(fieldIn('Quantity'), '');
    buttonNamed('Place order').click();
    await m.settle();
    expect(posts(s), 'an empty quantity is not a quantity of 1').toHaveLength(0);
    expect(screen.getByText('Quantity: enter a whole number of at least 1.')).toBeTruthy();
    expect(screen.queryByText('Quantity: the browser could not read what was typed. Enter a whole number of at least 1.'), 'the unreadable sentence is gone: the box is readable (empty) now').toBeNull();
  });

  it('the running total does not pretend a price when an override is unparseable', async () => {
    const { m } = await mountPage('/orders/place');
    await fillBasics(m);
    typeUnparseable(fieldIn('Unit price override'));
    await m.settle();
    expect(screen.getByTestId('running-total').textContent).toContain('—');
  });
});

describe('R-typing (stage 2 fix round 1, item 8): keystrokes typed while the page is still loading end up as exactly the typed text', () => {
  it.each([
    ['Quantity', ['2', '25'], '"quantity":25'],
    ['Unit price override', ['1', '19', '19.9', '19.99'], '"unitPrice":1999'],
    ['Line discount', ['0', '0.2', '0.29'], '"lineDiscount":29'],
  ])('%s: typed character by character while the catalogue is held, released mid-typing: the text is the typed text, the page makes no assignment to the box while typing, and the bytes are exact', async (label, keystrokes, bytes) => {
    // The three catalogue reads wait on ONE unresolved promise; on release each answers with the sweep's default success body.
    let release!: () => void;
    const opened = new Promise<void>((resolve) => (release = resolve));
    let started = 0;
    const held = async (key: string) => {
      started += 1;
      await opened;
      const target = key.split(' ')[1]!.split('?')[0]!;
      return SUCCESS.find(([method, pattern]) => method === 'GET' && pattern.test(target))![2](key, undefined);
    };
    const { m, s } = await mountPage('/orders/place', [[/^GET \/api\/catalog\//, held]], { settle: false });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(started, 'the three catalogue requests must be in flight for this to prove anything').toBe(3);
    const field = fieldIn(label);
    const writes = writesWhileTyping(field);
    for (const [index, typed] of keystrokes.entries()) {
      typeInto(field, typed);
      if (index === 1) release();
      await new Promise((resolve) => setTimeout(resolve, 30)); // renders interleave with the keystrokes, as on a real page
      expect(field.value, `after typing "${typed}"`).toBe(typed);
    }
    await m.settle();
    expect(field.value, 'the text survives the catalogue arriving').toBe(keystrokes.at(-1));
    expect(writes, 'any assignment by the page while typing (the text the box holds moves the caret of a number input; any other text replaces what was typed)').toEqual([]);
    await fillBasics(m);
    buttonNamed('Place order').click();
    await m.settle();
    expect(bodyOf(s), 'the bytes the BFF receives are the typed amount').toContain(bytes);
  });

  it('a NEW box is given its draft: the demo button replaces the line (a new key, so a new element), and the new box shows the demo price (an existing box changed from outside is proved in stock.spec.ts and billing.spec.ts, R-replenish-draft and R-payment-draft)', async () => {
    const { m } = await mountPage('/orders/place');
    typeInto(fieldIn('Unit price override'), '1');
    await m.settle();
    buttonNamed('Fill demo order (.99 → compensation)').click();
    await m.settle();
    expect(fieldIn('Unit price override').value).toBe('249.99');
  });
});

describe('R-step: the money inputs\' step follows the currency\'s exponent', () => {
  it.each([
    ['EUR', '0.01'],
    ['HUF', '0.01'],
    ['JPY', '1'],
    ['BHD', '0.001'],
    ['IQD', '0.001'],
    ['CLF', '0.0001'],
  ])('with the currency %s, unit price and line discount have step %s (and a placeholder with that many decimals)', async (currency, step) => {
    const { m } = await mountPage('/orders/place');
    typeInto(fieldIn('Currency'), currency);
    await m.settle();
    expect(fieldIn('Unit price override').getAttribute('step')).toBe(step);
    expect(fieldIn('Line discount').getAttribute('step')).toBe(step);
    expect(fieldIn('Line discount').getAttribute('placeholder')).toBe(step === '1' ? '0' : `0.${'0'.repeat(step.length - 2)}`);
    expect(fieldIn('Quantity').getAttribute('step'), 'a quantity is a count, whatever the currency').toBe('1');
  });
});

describe('R-total: the running total is an estimate in the currency\'s own text', () => {
  it('catalogue price x quantity, an override over the catalogue price, minus the discount; the figures are exact', async () => {
    const { m } = await mountPage('/orders/place');
    expect(screen.getByTestId('running-total').textContent).toBe('0.00 EUR');
    choose(byLabel('Product'), 'PRD-0007'); // 0.29 EUR: a float trap at x 3
    typeInto(fieldIn('Quantity'), '3');
    await m.settle();
    expect(screen.getByTestId('running-total').textContent).toBe('0.87 EUR');
    typeInto(fieldIn('Unit price override'), '19.99');
    typeInto(fieldIn('Line discount'), '0.10');
    await m.settle();
    expect(screen.getByTestId('running-total').textContent).toBe('59.87 EUR');
  });

  it('a total beyond the safe-integer range is shown as a dash, never as an inexact number', async () => {
    const { m } = await mountPage('/orders/place');
    choose(byLabel('Product'), 'PRD-0001');
    typeInto(fieldIn('Unit price override'), '90071992547409.91');
    typeInto(fieldIn('Quantity'), '2');
    await m.settle();
    expect(screen.getByTestId('running-total').textContent).toBe('—');
  });
});

describe('R-single: a submit cannot double-fire', () => {
  it('two submit events in the same task send ONE request', async () => {
    const held = gate();
    const { m, s } = await mountPage('/orders/place', [[POST, held.answer]]);
    await fillBasics(m);
    fireEvent.submit(form());
    fireEvent.submit(form());
    fireEvent.click(buttonNamed('Place order'));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(s.count(POST), 'two submits in one task, a click on the disabled button: one request').toBe(1);
    expect(buttonNamed('Placing…').disabled).toBe(true);
    held.release(json(placeOrderResponse(), 201));
    await m.settle();
  });

  it('after a refusal the form can be submitted again; the SAME draft retries with the SAME Idempotency-Key, an edited one with a new key', async () => {
    let call = 0;
    const { m, s } = await mountPage('/orders/place', [[POST, () => (++call < 3 ? problemResponse(503, { type: 'about:blank', title: 'Service Unavailable', status: 503, detail: 'Orders is not answering.' }) : json(placeOrderResponse(), 201))]]);
    await fillBasics(m);
    buttonNamed('Place order').click();
    await m.settle();
    buttonNamed('Place order').click();
    await m.settle();
    const keys = posts(s).map((call) => (call.init!.headers as Record<string, string>)['Idempotency-Key']);
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(keys[1], 'a retry of the same draft is the same order to the server').toBe(keys[0]);
    typeInto(fieldIn('Notes'), 'changed');
    buttonNamed('Place order').click();
    await m.settle();
    expect(s.count(POST)).toBe(3);
    expect(posts(s)[2]!.init!.headers as Record<string, string>, 'an edited draft is a different order').not.toHaveProperty('Idempotency-Key', keys[0]);
  });

  it('an edited draft after a refusal is a new order with a new key', async () => {
    const { m, s } = await mountPage('/orders/place', [[POST, () => problemResponse(409, { type: 'about:blank', title: 'Conflict', status: 409, detail: 'PRD-0001: requested 5, only 2 available.' })]]);
    await fillBasics(m);
    buttonNamed('Place order').click();
    await m.settle();
    typeInto(fieldIn('Quantity'), '2');
    buttonNamed('Place order').click();
    await m.settle();
    const keys = posts(s).map((call) => (call.init!.headers as Record<string, string>)['Idempotency-Key']);
    expect(keys).toHaveLength(2);
    expect(keys[1]).not.toBe(keys[0]);
  });
});

describe('R-result: the answer', () => {
  it.each([201, 200])('a %i answer navigates to the order page, which shows the order', async (status) => {
    const { m } = await mountPage('/orders/place', [[POST, () => json(placeOrderResponse(), status, status === 200 ? { 'Idempotent-Replay': 'true' } : {})]]);
    await fillBasics(m);
    buttonNamed('Place order').click();
    await m.settle();
    expect(m.router.url).toBe(`/orders/${ORDER_ID}`);
    expect(screen.getByTestId('order-detail-reference').textContent).toBe('ORD-000042');
  });

  it.each([
    [400, 'unitPrice: must be a non-negative integer.'],
    [409, 'Stock check reports 1 short line(s): PRD-0001 requested 5, available 2'],
    [422, 'orderDiscount 5.00 EUR was supplied, but the Order cannot take one yet.'],
    [503, 'The Orders context did not answer in time.'],
    [500, 'An unexpected error occurred.'],
  ])('a %i refusal shows the problem\'s own detail, stays on the form, and sends nothing else', async (status, detail) => {
    const { m, s } = await mountPage('/orders/place', [[POST, () => problemResponse(status, { type: 'about:blank', title: 'decoy-title', status, detail })]]);
    await fillBasics(m);
    buttonNamed('Place order').click();
    await m.settle();
    expect(screen.getByTestId('place-order-error').textContent).toContain(detail);
    expect(screen.queryByText('decoy-title')).toBeNull();
    expect(m.router.url).toBe('/orders/place');
    expect(s.count(POST)).toBe(1);
  });

  it('nothing is sent while the retailer, company or product is missing, and the form says so', async () => {
    const { m, s } = await mountPage('/orders/place');
    buttonNamed('Place order').click();
    await m.settle();
    expect(s.count(POST)).toBe(0);
    expect(screen.getByTestId('place-order-incomplete').textContent).toBe('Choose a retailer, a company and at least one product.');
  });

  it('the demo button fills the .99 order of the compensation path (unit price 249.99, quantity 1)', async () => {
    const { m, s } = await mountPage('/orders/place');
    buttonNamed('Fill demo order (.99 → compensation)').click();
    await m.settle();
    buttonNamed('Place order').click();
    await m.settle();
    expect(bodyOf(s)).toBe('{"retailerCode":"CarrefourEs","companyCode":"IBERFOODS","currency":"EUR","lines":[{"productCode":"PRD-0001","quantity":1,"unitPrice":24999}],"notes":"demo — compensation path (.99)"}');
  });
});

describe('R-catalog-notice: a failed catalogue read shows that read\'s own words (#8 review B1)', () => {
  const unavailable = (detail: string) => () => problemResponse(503, { type: 'about:blank', title: 'Service Unavailable', status: 503, detail });

  it('each failing read\'s own text is shown once, the manual-entry help follows, and typing the codes by hand still places the order', async () => {
    const { m, s } = await mountPage('/orders/place', [
      ['GET /api/catalog/retailers', unavailable('The retailer catalogue did not answer.')],
      ['GET /api/catalog/companies', unavailable('The retailer catalogue did not answer.')],
      ['GET /api/catalog/products', unavailable('The product catalogue is rebuilding.')],
    ]);
    const texts = screen.getAllByTestId('catalog-error').map((node) => node.textContent?.trim());
    expect(texts, 'two distinct texts, the repeated one only once').toEqual(['The retailer catalogue did not answer.', 'The product catalogue is rebuilding.']);
    expect(screen.getByTestId('catalog-manual-entry').textContent).toBe('You can still type the codes by hand.');
    typeInto(fieldIn('Retailer'), 'CarrefourEs');
    typeInto(fieldIn('Company'), 'IBERFOODS');
    typeInto(fieldIn('Product'), 'PRD-0001');
    buttonNamed('Place order').click();
    await m.settle();
    expect(bodyOf(s)).toContain('"retailerCode":"CarrefourEs","companyCode":"IBERFOODS"');
  });

  it('a failure with no problem document at all falls back to the fixed sentence, and only then', async () => {
    await mountPage('/orders/place', [['GET /api/catalog/products', () => new Response('<html>bad gateway</html>', { status: 502, headers: { 'Content-Type': 'text/html' } })]]);
    expect(screen.getByTestId('catalog-error').textContent).toContain('The catalogue could not be loaded.');
  });
});

describe('R-label-id (#8 id 106): a label\'s `for` is its control\'s `id`, on every render in the same process', () => {
  const pairs = () =>
    [...document.querySelectorAll('label')]
      .map((label) => ({ text: label.textContent?.trim(), target: label.getAttribute('for') }))
      .map(({ text, target }) => ({ text, target, control: target ? document.getElementById(target) : null }));

  it('renders the form ten times in one module instance: every label points at exactly one existing control, and the ids are the same on every render', async () => {
    let first: Array<string | null> | undefined;
    for (let render = 0; render < 10; render++) {
      TestBed.resetTestingModule();
      const { m } = await mountPage('/orders/place');
      const found = pairs();
      expect(found.length, `render ${render}: the labels`).toBeGreaterThanOrEqual(8);
      for (const { text, target, control } of found) {
        expect(target, `render ${render}: the label "${text}" has no for`).toBeTruthy();
        expect(control, `render ${render}: the label "${text}" points at #${target}, which does not exist`).not.toBeNull();
        expect(document.querySelectorAll(`[id="${target}"]`).length, `render ${render}: #${target} is not unique`).toBe(1);
        expect(['INPUT', 'SELECT', 'TEXTAREA'], `render ${render}: #${target} is not a form control`).toContain(control!.tagName);
      }
      const targets = found.map((pair) => pair.target);
      first ??= targets;
      expect(targets, `render ${render}: the ids differ from the first render's (a module-level counter keeps counting)`).toEqual(first);
      await m.settle();
    }
  });

  it('lines added and removed keep every pair intact and unique', async () => {
    const { m } = await mountPage('/orders/place');
    buttonNamed('Add line').click();
    buttonNamed('Add line').click();
    await m.settle();
    expect(screen.getAllByTestId('order-line')).toHaveLength(3);
    screen.getByRole('button', { name: 'Remove line 2' }).click();
    await m.settle();
    const found = pairs();
    expect(found.every(({ control }) => control !== null)).toBe(true);
    const targets = found.map((pair) => pair.target);
    expect(new Set(targets).size).toBe(targets.length);
  });
});
