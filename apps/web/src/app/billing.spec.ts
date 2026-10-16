// The billing page (feature 29, stage 3): invoices, credits and Register payment (R47, R48, R49). Ported by content from #8's billing-view.test.tsx and #7's billing/index.spec.ts,
// with a loading state proven only while a request is held (#7 Pass 7) and the money parsed digit-wise with the INVOICE's exponent (#7 review pass 5's float bug).
import { fireEvent, screen, within } from '@testing-library/dom';
import { afterEach, describe, expect, it } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { QueryClient } from '@tanstack/angular-query-experimental';
import { json, problemResponse } from './testing/browser-harness';
import { gate, mountPage, type Stub } from './testing/page-test';
import { buttonNamed, byLabel, choose, typeInto } from './testing/page-sweep';
import { typeParseable, typeUnparseable, writesWhileTyping } from './testing/number-input';
import { CREDITS, creditPage, INV_BHD, INV_EUR, INV_JPY, INV_TRAP, INVOICES, invoicePage, paymentAccepted, paymentDuplicate } from './testing/stock-billing-fixtures';

afterEach(() => TestBed.resetTestingModule());

const INVOICES_LIST = /^GET \/api\/invoices\?/;
const CREDITS_LIST = /^GET \/api\/credits\?/;
const pay = (invoiceId: string) => `POST /api/invoices/${invoiceId}/payments`;
const PAY_ANY = /^POST \/api\/invoices\/[^/]+\/payments$/;
const problem = (status: number, detail: string, code = 'DOMAIN_ERROR') => problemResponse(status, { type: 'about:blank', title: 'decoy-title', status, detail, code });
const flat = (node: Element | null) => (node?.textContent ?? '').replace(/\s+/g, ' ').trim();
const queryOf = (key: string) => Object.fromEntries(new URLSearchParams(key.split('?')[1]));
const lastOf = (s: Stub, list: RegExp) => s.calls.filter((call) => list.test(call.key)).at(-1)!.key;
const pager = (testId: string) => screen.getByTestId(testId);
const pagerText = (testId: string) => within(pager(testId)).getByTestId('pager-count').textContent;
const LANDMARK: Record<string, string> = { 'credits-pager': 'Credits pagination', 'invoices-pager': 'Invoices pagination' };
const next = (testId: string) => within(pager(testId)).getByRole<HTMLButtonElement>('button', { name: `Next (${LANDMARK[testId]})` });
const previous = (testId: string) => within(pager(testId)).getByRole<HTMLButtonElement>('button', { name: `Previous (${LANDMARK[testId]})` });
const registerFor = (reference: string) => screen.getByRole<HTMLButtonElement>('button', { name: `Register payment ${reference}` });
const amountBox = () => screen.getByLabelText<HTMLInputElement>('Amount');
const referenceBox = () => screen.getByLabelText<HTMLInputElement>('Payment reference');
const bodyOf = (s: Stub) => s.matching(PAY_ANY).at(-1)!.init!.body as string;
const form = () => screen.getByTestId('payment-form').querySelector('form')!;
const invoiceStates = () => ({ loading: screen.queryByTestId('invoices-loading') !== null, empty: screen.queryByTestId('invoices-empty') !== null, error: screen.queryByTestId('invoices-error') !== null, table: screen.queryByTestId('invoices-table') !== null });
const creditStates = () => ({ loading: screen.queryByTestId('credits-loading') !== null, empty: screen.queryByTestId('credits-empty') !== null, error: screen.queryByTestId('credits-error') !== null, table: screen.queryByTestId('credits-table') !== null });

/** The exact bytes of a registered payment, with the one field that is the clock (`valueDate`) taken from the body itself and checked to be a real instant of the last minute, in the wire's form. */
function expectBytes(body: string, reference: string, amount: number, currency: string): void {
  const { valueDate } = JSON.parse(body) as { valueDate: string };
  expect(valueDate, 'valueDate is the wire instant form YYYY-MM-DDTHH:MM:SS.mmmZ').toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  expect(Math.abs(Date.now() - Date.parse(valueDate)), 'valueDate is now, not a literal').toBeLessThan(60_000);
  expect(body).toBe(`{"paymentReference":"${reference}","amount":{"amount":${amount},"currency":"${currency}"},"valueDate":"${valueDate}","source":"operator"}`);
}

describe('R-billing-states: each list has distinct loading, empty and error states, independent of the other, proven while a request is held', () => {
  it('invoices in flight: only "Loading invoices…", no table, no empty text, no error, NO count; the credits list is unaffected', async () => {
    const held = gate();
    const { m } = await mountPage('/billing', [[INVOICES_LIST, held.answer]], { settle: false });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(held.started(), 'the request must be in flight for this to prove anything').toBe(true);
    expect(invoiceStates()).toEqual({ loading: true, empty: false, error: false, table: false });
    expect(pagerText('invoices-pager')).toBe('');
    expect(next('invoices-pager').disabled && previous('invoices-pager').disabled).toBe(true);
    expect(creditStates()).toEqual({ loading: false, empty: false, error: false, table: true });
    held.release(json(invoicePage(1)));
    await m.settle();
    expect(invoiceStates()).toEqual({ loading: false, empty: false, error: false, table: true });
    expect(pagerText('invoices-pager')).toBe('Page 1 of 3 · 45 invoices');
  });

  it('credits in flight: only "Loading credit limits…", NO count; the invoices list is unaffected', async () => {
    const held = gate();
    const { m } = await mountPage('/billing', [[CREDITS_LIST, held.answer]], { settle: false });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(held.started()).toBe(true);
    expect(creditStates()).toEqual({ loading: true, empty: false, error: false, table: false });
    expect(screen.getByTestId('credits-loading').textContent).toContain('Loading credit limits');
    expect(pagerText('credits-pager')).toBe('');
    expect(invoiceStates().table).toBe(true);
    held.release(json(creditPage(1)));
    await m.settle();
    expect(creditStates()).toEqual({ loading: false, empty: false, error: false, table: true });
    expect(pagerText('credits-pager')).toBe('Page 1 of 3 · 45 credit lines');
  });

  it('an empty answer shows the empty state for that list only, and its pager reads Page 1 of 1 · 0', async () => {
    await mountPage('/billing', [
      [INVOICES_LIST, () => json(invoicePage(1, [], 0))],
      [CREDITS_LIST, () => json(creditPage(1, [], 0))],
    ]);
    expect(invoiceStates()).toEqual({ loading: false, empty: true, error: false, table: false });
    expect(creditStates()).toEqual({ loading: false, empty: true, error: false, table: false });
    expect(pagerText('invoices-pager')).toBe('Page 1 of 1 · 0 invoices');
    expect(pagerText('credits-pager')).toBe('Page 1 of 1 · 0 credit lines');
  });

  it("a failed invoice read shows its own detail and no count, and the credit list does not go with it; and the other way round", async () => {
    await mountPage('/billing', [[INVOICES_LIST, () => problem(503, 'Billing did not answer for the invoices.')]]);
    expect(invoiceStates()).toEqual({ loading: false, empty: false, error: true, table: false });
    expect(screen.getByTestId('invoices-error').textContent).toContain('Billing did not answer for the invoices.');
    expect(pagerText('invoices-pager')).toBe('');
    expect(creditStates().table).toBe(true);
    TestBed.resetTestingModule();
    await mountPage('/billing', [[CREDITS_LIST, () => problem(500, 'The credit read is down.')]]);
    expect(creditStates()).toEqual({ loading: false, empty: false, error: true, table: false });
    expect(screen.getByTestId('credits-error').textContent).toContain('The credit read is down.');
    expect(screen.queryByText('decoy-title')).toBeNull();
    expect(pagerText('credits-pager')).toBe('');
    expect(invoiceStates().table).toBe(true);
  });

  it.each([
    ['invoices', INVOICES_LIST, 'invoices-pager', ['invoices', 'invoices-pager'] as const, () => json(invoicePage(1)), 'Page 1 of 3 · 45 invoices'],
    ['credits', CREDITS_LIST, 'credits-pager', ['credits', 'credits-pager'] as const, () => json(creditPage(1)), 'Page 1 of 3 · 45 credit lines'],
  ])('%s: the first read answers 45, the next read fails: the error shows and the pager no longer claims "%s" (stage 2 review A2, applied)', async (_name, list, pagerId, [queryKey], answer, claim) => {
    let reads = 0;
    const { m } = await mountPage('/billing', [[list, () => (++reads === 1 ? answer() : problem(500, 'The read is down.'))]]);
    expect(pagerText(pagerId)).toBe(claim);
    await TestBed.inject(QueryClient).refetchQueries({ queryKey: [queryKey] });
    await m.settle();
    expect(reads, 'a second read must have happened for this to prove anything').toBeGreaterThanOrEqual(2);
    expect(pagerText(pagerId), 'TanStack keeps the last data after a failed refetch; the pager must not keep claiming its count').toBe('');
    expect(next(pagerId).disabled && previous(pagerId).disabled).toBe(true);
  });
});

describe('R-billing-money: amounts are the ISO 4217 text of integer minor units, never the raw integer', () => {
  it('invoice totals use their own currency exponent (EUR 2, BHD 3, JPY 0) and group by three', async () => {
    await mountPage('/billing');
    expect(screen.getAllByTestId('invoice-total').map(flat)).toEqual(['1 242.50 EUR', '33.33 EUR', '2.005 BHD', '5 000 JPY', '50.00 EUR']);
    expect(screen.getByTestId('invoices-table').textContent, 'the raw integer must not be on screen').not.toContain('124250');
  });

  it('credit limits, holds, exposure and availability are decimals; an exhausted line is flagged', async () => {
    await mountPage('/billing');
    const rows = screen.getAllByTestId('credit-row');
    expect(rows.map((row) => ['credit-limit', 'credit-held', 'credit-exposure', 'credit-available'].map((id) => flat(within(row).getByTestId(id))))).toEqual([
      ['10 000.00 EUR', '1 242.50 EUR', '500.00 EUR', '8 257.50 EUR'],
      ['5 000 000 JPY', '2 000 000 JPY', '3 000 000 JPY', '0 JPY'],
    ]);
    expect(within(rows[1]!).getByTestId('credit-available').className).toContain('text-destructive');
    expect(within(rows[0]!).getByTestId('credit-available').className).not.toContain('text-destructive');
    expect(CREDITS).toHaveLength(2);
  });

  it('an invoice row shows its reference, order, retailer, company, issue instant and status; only an ISSUED invoice has a Register payment button', async () => {
    await mountPage('/billing');
    const rows = screen.getAllByTestId('invoice-row');
    expect(flat(rows[0]!)).toContain('INV-000027');
    expect(flat(rows[0]!)).toContain('ORD-000042');
    expect(flat(rows[0]!)).toContain('2026-10-15 10:00:00 UTC');
    expect(rows.map((row) => flat(within(row).getByTestId('invoice-status')))).toEqual(['issued', 'issued', 'issued', 'issued', 'paid']);
    expect(rows.map((row) => within(row).queryByTestId('register-payment-button') !== null)).toEqual([true, true, true, true, false]);
    expect(INVOICES).toHaveLength(5);
  });
});

describe('R-billing-filters: the filters openapi.yaml declares for /invoices and /credits, and paging, are requests that start from page 1', () => {
  it('invoices: the sent keys are exactly status, retailerCode, companyCode, orderReference, issuedBeforeMinutes, page, pageSize', async () => {
    const { m, s } = await mountPage('/billing');
    expect(lastOf(s, INVOICES_LIST)).toBe('GET /api/invoices?page=1&pageSize=20');
    choose(byLabel('Invoice status'), 'issued');
    await m.settle();
    typeInto(byLabel('Invoice retailer'), 'CarrefourEs');
    fireEvent.change(byLabel('Invoice retailer'));
    await m.settle();
    typeInto(byLabel('Invoice company'), 'IBERFOODS');
    fireEvent.change(byLabel('Invoice company'));
    await m.settle();
    typeInto(byLabel('Invoice order reference'), ' ORD-000042 ');
    fireEvent.change(byLabel('Invoice order reference'));
    await m.settle();
    typeParseable(byLabel('Issued at least (minutes) ago') as HTMLInputElement, '90');
    fireEvent.change(byLabel('Issued at least (minutes) ago'));
    await m.settle();
    expect(queryOf(lastOf(s, INVOICES_LIST))).toEqual({ companyCode: 'IBERFOODS', issuedBeforeMinutes: '90', orderReference: 'ORD-000042', page: '1', pageSize: '20', retailerCode: 'CarrefourEs', status: 'issued' });
  });

  it('invoices: the status filter offers exactly the two invoice statuses of openapi.yaml plus "All statuses"', async () => {
    await mountPage('/billing');
    expect(within(byLabel('Invoice status')).getAllByRole('option').map((option) => option.textContent)).toEqual(['All statuses', 'issued', 'paid']);
  });

  it('credits: the sent keys are exactly retailerCode, companyCode, page, pageSize, and the invoices are not re-read', async () => {
    const { m, s } = await mountPage('/billing');
    expect(lastOf(s, CREDITS_LIST)).toBe('GET /api/credits?page=1&pageSize=20');
    const invoiceReads = s.count(INVOICES_LIST);
    typeInto(byLabel('Credit retailer'), 'TokyoMart');
    fireEvent.change(byLabel('Credit retailer'));
    await m.settle();
    typeInto(byLabel('Credit company'), ' IBERFOODS ');
    fireEvent.change(byLabel('Credit company'));
    await m.settle();
    expect(queryOf(lastOf(s, CREDITS_LIST))).toEqual({ companyCode: 'IBERFOODS', page: '1', pageSize: '20', retailerCode: 'TokyoMart' });
    expect(s.count(INVOICES_LIST)).toBe(invoiceReads);
  });

  it.each([
    ['invoices-pager', INVOICES_LIST, invoicePage, 'Invoice status', 'issued', 'GET /api/invoices?page=1&pageSize=20&status=issued'],
    ['credits-pager', CREDITS_LIST, creditPage, 'Credit retailer', 'TokyoMart', 'GET /api/credits?page=1&pageSize=20&retailerCode=TokyoMart'],
  ])('%s: Next asks for page 2, Previous for page 1, Previous is off on page 1 and Next on the last page; a filter returns to page 1', async (testId, list, makePage, filterLabel, value, filtered) => {
    const { m, s } = await mountPage('/billing', [[list, (key) => json(makePage(Number(queryOf(key)['page'])))]]);
    expect(previous(testId).disabled).toBe(true);
    next(testId).click();
    await m.settle();
    expect(lastOf(s, list)).toBe(list === INVOICES_LIST ? 'GET /api/invoices?page=2&pageSize=20' : 'GET /api/credits?page=2&pageSize=20');
    next(testId).click();
    await m.settle();
    expect(next(testId).disabled).toBe(true);
    if (filterLabel === 'Invoice status') choose(byLabel(filterLabel), value);
    else {
      typeInto(byLabel(filterLabel), value);
      fireEvent.change(byLabel(filterLabel));
    }
    await m.settle();
    expect(lastOf(s, list)).toBe(filtered);
  });

  it('the two pagers are two landmarks with their own names, and their buttons are named per pager (a census cannot merge them)', async () => {
    await mountPage('/billing');
    expect(screen.getAllByRole('button').map((button) => button.getAttribute('aria-label')).filter((name) => /^(Next|Previous)/.test(name ?? ''))).toEqual(['Previous (Credits pagination)', 'Next (Credits pagination)', 'Previous (Invoices pagination)', 'Next (Invoices pagination)']);
    expect(screen.getByRole('navigation', { name: 'Credits pagination' })).toBe(pager('credits-pager'));
    expect(screen.getByRole('navigation', { name: 'Invoices pagination' })).toBe(pager('invoices-pager'));
  });
});

describe('R-billing-age-bad-input: the age filter is a number box that follows the place-order pattern', () => {
  const age = () => byLabel('Issued at least (minutes) ago') as HTMLInputElement;

  it('a text the browser cannot parse is refused in words naming the field, the filter is NOT changed and nothing is sent; a parseable retype applies', async () => {
    const { m, s } = await mountPage('/billing');
    const reads = s.count(INVOICES_LIST);
    // Only the events Chromium fires: from an EMPTY box an unreadable text ("1-2", "12e") produces `input` events and, on Tab or Enter, NO `change` (live: .arm/web29r4/s3/live/age.out, 0 change events).
    typeUnparseable(age());
    fireEvent.blur(age());
    await m.settle();
    expect(screen.getByTestId('invoice-age-problem').textContent).toBe('Issued at least (minutes) ago: enter a whole number of minutes, 0 or more.');
    expect(age().getAttribute('aria-invalid')).toBe('true');
    expect(s.count(INVOICES_LIST), 'nothing may be sent for an unparseable age').toBe(reads);
    typeParseable(age(), '15');
    fireEvent.change(age());
    await m.settle();
    expect(queryOf(lastOf(s, INVOICES_LIST))['issuedBeforeMinutes']).toBe('15');
    expect(screen.queryByTestId('invoice-age-problem')).toBeNull();
  });

  it.each(['-5', '1.5', '1e2'])('"%s" is refused and the previous filter stays', async (typed) => {
    const { m, s } = await mountPage('/billing');
    typeParseable(age(), '30');
    fireEvent.change(age());
    await m.settle();
    const reads = s.count(INVOICES_LIST);
    typeParseable(age(), typed);
    fireEvent.change(age());
    await m.settle();
    expect(screen.getByTestId('invoice-age-problem')).toBeTruthy();
    expect(s.count(INVOICES_LIST)).toBe(reads);
    expect(queryOf(lastOf(s, INVOICES_LIST))['issuedBeforeMinutes']).toBe('30');
  });

  it('an emptied box clears the filter', async () => {
    const { m, s } = await mountPage('/billing');
    typeParseable(age(), '30');
    fireEvent.change(age());
    await m.settle();
    expect(queryOf(lastOf(s, INVOICES_LIST))['issuedBeforeMinutes']).toBe('30');
    typeParseable(age(), '');
    fireEvent.change(age());
    await m.settle();
    // The unfiltered answer is still cached (fresh), so no new request is owed: the active query's own key is what shows the filter is gone.
    const active = TestBed.inject(QueryClient).getQueryCache().findAll({ queryKey: ['invoices'], type: 'active' });
    expect(active.map((query) => (query.queryKey[1] as { issuedBeforeMinutes?: number }).issuedBeforeMinutes)).toEqual([undefined]);
    expect(s.count(INVOICES_LIST)).toBeGreaterThanOrEqual(2);
  });
});

describe('R-payment-bytes: the BFF receives the typed amount as integer minor units of the INVOICE\'s currency, exactly', () => {
  it.each([
    ['INV-000028', 'EUR', '0.29', 29], // 0.29 * 100 = 28.999999999999996 in IEEE 754: the float trap
    ['INV-000027', 'EUR', '19.99', 1999],
    ['INV-000027', 'EUR', '4.35', 435],
    ['INV-000027', 'EUR', '1.10', 110],
    ['INV-000027', 'EUR', '.5', 50],
    ['INV-000029', 'BHD', '1.005', 1005], // three decimals
    ['INV-000030', 'JPY', '1999', 1999], // none
  ])('%s (%s): "%s" is sent as %i, in the request body\'s bytes', async (invoiceReference, currency, typed, minor) => {
    const { m, s } = await mountPage('/billing');
    registerFor(invoiceReference).click();
    await m.settle();
    typeParseable(amountBox(), typed);
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(s.count(PAY_ANY), `"${typed}" for ${currency} must be accepted and sent`).toBe(1);
    expectBytes(bodyOf(s), `PAY-${new Date().toISOString().slice(0, 10)}-${invoiceReference.replace('INV-', '')}`, minor, currency);
  });

  it('the request goes to THIS invoice\'s payments route, once', async () => {
    const { m, s } = await mountPage('/billing');
    registerFor('INV-000029').click();
    await m.settle();
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(s.count(PAY_ANY)).toBe(1);
    expect(s.count(pay(INV_BHD.invoiceId))).toBe(1);
  });

  it("the box is prefilled with the invoice's exact total, in its own decimals, and its step follows the invoice's currency exponent", async () => {
    const { m } = await mountPage('/billing');
    for (const [reference, total, step] of [
      ['INV-000027', '1242.50', '0.01'],
      ['INV-000028', '33.33', '0.01'],
      ['INV-000029', '2.005', '0.001'],
      ['INV-000030', '5000', '1'],
    ] as const) {
      registerFor(reference).click();
      await m.settle();
      expect(amountBox().value, `${reference}'s prefilled amount`).toBe(total);
      expect(amountBox().getAttribute('step'), `${reference}'s step`).toBe(step);
    }
  });

  it('the prefilled total, submitted untouched, is the invoice total in minor units', async () => {
    const { m, s } = await mountPage('/billing');
    for (const invoice of [INV_EUR, INV_TRAP, INV_BHD, INV_JPY]) {
      registerFor(invoice.invoiceReference).click();
      await m.settle();
      buttonNamed('Submit payment').click();
      await m.settle();
      expect(JSON.parse(bodyOf(s)).amount, invoice.invoiceReference).toEqual({ amount: invoice.totalAmount, currency: invoice.currency });
    }
  });
});

describe('R-payment-bad-input: a malformed amount or reference is refused in words that name the field, and nothing is sent', () => {
  it.each([
    ['INV-000027', '1.005', 'Amount: enter an amount with at most 2 decimals (EUR).'], // never rounded to 100 or 101
    ['INV-000030', '19.99', 'Amount: enter a whole amount (JPY).'],
    ['INV-000027', '', 'Amount: enter an amount with at most 2 decimals (EUR).'],
    ['INV-000027', '1e2', 'Amount: enter an amount with at most 2 decimals (EUR).'],
    ['INV-000027', '-1', 'Amount: enter an amount with at most 2 decimals (EUR).'],
    ['INV-000029', '1.0055', 'Amount: enter an amount with at most 3 decimals (BHD).'],
    ['INV-000027', '90071992547409.92', 'Amount: enter an amount of at most 90071992547409.91 (EUR).'], // 2 decimals, too large: refused for its size (review A2)
    ['INV-000030', '9007199254740992', 'Amount: enter an amount of at most 9007199254740991 (JPY).'],
  ])('%s: "%s" is refused (%s)', async (invoiceReference, typed, words) => {
    const { m, s } = await mountPage('/billing');
    registerFor(invoiceReference).click();
    await m.settle();
    typeParseable(amountBox(), typed);
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(s.count(PAY_ANY)).toBe(0);
    expect(screen.getByTestId('payment-amount-problem').textContent).toBe(words);
    expect(amountBox().getAttribute('aria-invalid')).toBe('true');
  });

  it('a text the browser could not parse (reported as "" with badInput) is refused, never read as a default; a parseable retype then sends the typed amount', async () => {
    const { m, s } = await mountPage('/billing');
    registerFor('INV-000028').click();
    await m.settle();
    typeUnparseable(amountBox());
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(s.count(PAY_ANY), 'nothing may be sent').toBe(0);
    expect(screen.getByTestId('payment-amount-problem').textContent, 'an unreadable text is told apart from an empty one').toBe('Amount: the browser could not read what was typed. Enter an amount with at most 2 decimals (EUR).');
    typeParseable(amountBox(), '0.29');
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(s.count(PAY_ANY)).toBe(1);
    expect(bodyOf(s)).toContain('"amount":{"amount":29,');
  });

  it('an empty or too-long payment reference is refused in words naming the field', async () => {
    const { m, s } = await mountPage('/billing');
    registerFor('INV-000027').click();
    await m.settle();
    for (const typed of ['', '   ', 'P'.repeat(31)]) {
      typeInto(referenceBox(), typed);
      buttonNamed('Submit payment').click();
      await m.settle();
      expect(screen.getByTestId('payment-reference-problem').textContent).toBe('Payment reference: enter the remittance reference, 1 to 30 characters.');
    }
    expect(s.count(PAY_ANY)).toBe(0);
    typeInto(referenceBox(), 'BANK-REF-7');
    buttonNamed('Submit payment').click();
    await m.settle();
    expectBytes(bodyOf(s), 'BANK-REF-7', 124250, 'EUR');
    typeInto(referenceBox(), 'Bank-Ref-7a');
    buttonNamed('Submit payment').click();
    await m.settle();
    expectBytes(bodyOf(s), 'Bank-Ref-7a', 124250, 'EUR');
  });

  it('the suggested reference is shaped like the spec example and within the wire limit', async () => {
    const { m } = await mountPage('/billing');
    registerFor('INV-000027').click();
    await m.settle();
    expect(referenceBox().value).toBe(`PAY-${new Date().toISOString().slice(0, 10)}-000027`);
    expect(referenceBox().value.length).toBeLessThanOrEqual(30);
    expect(referenceBox().getAttribute('maxlength')).toBe('30');
  });
});

describe('R-payment-outcome: 201 and 200 are both success, and each is rendered as what it says happened', () => {
  it('201 accepted: "recorded (HTTP 201)", the invoice status the server answered, and BOTH lists are read again', async () => {
    const { m, s } = await mountPage('/billing', [[PAY_ANY, () => json(paymentAccepted('PAY-X'), 201)]]);
    registerFor('INV-000027').click();
    await m.settle();
    const invoiceReads = s.count(INVOICES_LIST);
    const creditReads = s.count(CREDITS_LIST);
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(flat(screen.getByTestId('payment-outcome-accepted'))).toBe('Payment PAY-X recorded (HTTP 201). Invoice INV-000027 is now paid.');
    expect(screen.getByTestId('payment-outcome-accepted').getAttribute('data-http-status')).toBe('201');
    expect(screen.queryByTestId('payment-outcome-duplicate')).toBeNull();
    expect(s.count(INVOICES_LIST), 'the invoice list was read again').toBe(invoiceReads + 1);
    expect(s.count(CREDITS_LIST), 'the payment releases credit: the credit list was read again').toBe(creditReads + 1);
  });

  it('200 duplicate: an idempotent replay is rendered DIFFERENTLY (nothing new was created), not as a second success', async () => {
    const { m } = await mountPage('/billing', [[PAY_ANY, () => json(paymentDuplicate('PAY-X'), 200, { 'Idempotent-Replay': 'true' })]]);
    registerFor('INV-000027').click();
    await m.settle();
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(flat(screen.getByTestId('payment-outcome-duplicate'))).toBe('Payment PAY-X was already recorded (HTTP 200). Nothing new was created: this was an idempotent replay.');
    expect(screen.getByTestId('payment-outcome-duplicate').getAttribute('data-http-status')).toBe('200');
    expect(screen.queryByTestId('payment-outcome-accepted')).toBeNull();
    expect(flat(screen.getByTestId('payment-form'))).not.toMatch(/PAY-X recorded/);
  });

  it('submitting the SAME remittance twice sends the same paymentReference both times (the replay key) and renders 201 then 200', async () => {
    let answered = 0;
    const { m, s } = await mountPage('/billing', [[PAY_ANY, () => (++answered === 1 ? json(paymentAccepted('PAY-X'), 201) : json(paymentDuplicate('PAY-X'), 200, { 'Idempotent-Replay': 'true' }))]]);
    registerFor('INV-000027').click();
    await m.settle();
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(screen.queryByTestId('payment-outcome-accepted')).not.toBeNull();
    buttonNamed('Submit payment').click();
    await m.settle();
    const sent = s.matching(PAY_ANY).map((call) => JSON.parse(call.init!.body as string) as { paymentReference: string; amount: unknown });
    expect(sent).toHaveLength(2);
    expect(sent[1]!.paymentReference).toBe(sent[0]!.paymentReference);
    expect(sent[1]!.amount).toEqual(sent[0]!.amount);
    expect(screen.queryByTestId('payment-outcome-duplicate')).not.toBeNull();
    expect(screen.queryByTestId('payment-outcome-accepted'), 'the first success is replaced, not stacked').toBeNull();
  });

  it.each([
    [400, 'paymentReference: must not be empty.', 'BAD_REQUEST'],
    [404, 'Invoice 10000000-0000-4000-8000-000000000027 does not exist.', 'NOT_FOUND'],
    [409, 'Payment reference PAY-X is already used for a different remittance.', 'PAYMENT_REFERENCE_REUSED'],
    [409, 'Invoice INV-000027 is already paid.', 'INVOICE_ALREADY_PAID'],
    [422, 'The remittance of 1.00 EUR does not equal the invoice total of 1 242.50 EUR.', 'PAYMENT_MISMATCH'],
    [503, 'The Billing context did not answer in time.', 'UPSTREAM_UNAVAILABLE'],
    [500, 'An unexpected error occurred.', 'INTERNAL'],
  ])("a %i shows the problem's own detail (not the decoy title), no success outcome, and re-reads nothing", async (status, detail, code) => {
    const { m, s } = await mountPage('/billing', [[PAY_ANY, () => problem(status, detail, code)]]);
    registerFor('INV-000027').click();
    await m.settle();
    const reads = s.count(INVOICES_LIST) + s.count(CREDITS_LIST);
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(screen.getByTestId('payment-error').textContent).toContain(detail);
    expect(screen.queryByText('decoy-title')).toBeNull();
    expect(screen.queryByTestId('payment-outcome-accepted')).toBeNull();
    expect(screen.queryByTestId('payment-outcome-duplicate')).toBeNull();
    expect(s.count(INVOICES_LIST) + s.count(CREDITS_LIST), 'a refused payment changed nothing').toBe(reads);
  });

  it("a rejected remittance's error, and the previous outcome, do not follow the panel to another invoice", async () => {
    const { m } = await mountPage('/billing', [[PAY_ANY, () => problem(422, 'The remittance does not equal the invoice total.', 'PAYMENT_MISMATCH')]]);
    registerFor('INV-000027').click();
    await m.settle();
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(screen.queryByTestId('payment-error')).not.toBeNull();
    registerFor('INV-000028').click();
    await m.settle();
    expect(screen.queryByTestId('payment-error'), 'the other invoice starts clean').toBeNull();
  });

  it('the outcome stays on screen when the paid invoice drops out of an "issued" list on the next read', async () => {
    let paid = false;
    const { m } = await mountPage('/billing', [
      [INVOICES_LIST, () => json(invoicePage(1, paid ? INVOICES.slice(1) : INVOICES))],
      [PAY_ANY, () => ((paid = true), json(paymentAccepted('PAY-X'), 201))],
    ]);
    registerFor('INV-000027').click();
    await m.settle();
    buttonNamed('Submit payment').click();
    await m.settle();
    expect(screen.getAllByTestId('invoice-row').map((row) => flat(row).slice(0, 10))).not.toContain('INV-000027');
    expect(screen.queryByTestId('payment-outcome-accepted')).not.toBeNull();
  });
});

describe('R-payment-single: a payment submit cannot double-fire', () => {
  it('two submit events in the same task, and a click on the disabled button, send ONE request; the button reads "Registering…" while it is in flight', async () => {
    const held = gate();
    const { m, s } = await mountPage('/billing', [[PAY_ANY, held.answer]]);
    registerFor('INV-000027').click();
    await m.settle();
    fireEvent.submit(form());
    fireEvent.submit(form());
    fireEvent.click(buttonNamed('Submit payment'));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(s.count(PAY_ANY)).toBe(1);
    expect(buttonNamed('Registering…').disabled).toBe(true);
    held.release(json(paymentAccepted(), 201));
    await m.settle();
    expect(s.count(PAY_ANY)).toBe(1);
  });
});

describe('R-payment-draft (stage 2 re-review H01): the panel\'s boxes take their drafts from outside when it moves to another invoice', () => {
  it('"5" typed for INV-000027, then Register payment on INV-000030: the SAME amount box shows 5000 with step 1, and the reference follows the invoice', async () => {
    const { m } = await mountPage('/billing');
    registerFor('INV-000027').click();
    await m.settle();
    const box = amountBox();
    typeParseable(box, '5');
    await m.settle();
    expect(box.value).toBe('5');
    registerFor('INV-000030').click();
    await m.settle();
    expect(amountBox(), 'the panel persists across the two invoices: this is an existing box, not a new one').toBe(box);
    expect(box.value, 'the draft was reset from outside and the box shows it').toBe('5000');
    expect(box.getAttribute('step')).toBe('1');
    expect(referenceBox().value).toBe(`PAY-${new Date().toISOString().slice(0, 10)}-000030`);
  });
});

describe('R-billing-labels: filters and headers are found by their visible label', () => {
  it('every filter resolves by label, and both tables have real column headers', async () => {
    await mountPage('/billing');
    for (const label of ['Credit retailer', 'Credit company', 'Invoice status', 'Invoice retailer', 'Invoice company', 'Invoice order reference', 'Issued at least (minutes) ago']) expect(byLabel(label), label).toBeTruthy();
    expect(screen.getAllByRole('columnheader').map(flat)).toEqual([
      'Retailer', 'Company', 'Limit', 'Held', 'Open exposure', 'Available',
      'Invoice', 'Order', 'Retailer', 'Company', 'Issued', 'Total', 'Status', 'Actions',
    ]);
  });
});

describe('R-typing (stage 3): keystrokes typed into the amount box while a request is in flight end up as exactly the typed text', () => {
  it('"1", "19", "19.9", "19.99" typed while the credit list is held and released mid-typing: the text is the typed text, the page makes no assignment to the box, and the bytes are exact', async () => {
    const held = gate();
    const { m, s } = await mountPage('/billing', [[CREDITS_LIST, held.answer]], { settle: false });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(held.started(), 'the credit read must be in flight for this to prove anything').toBe(true);
    registerFor('INV-000027').click();
    await new Promise((resolve) => setTimeout(resolve, 30));
    const box = amountBox();
    const writes = writesWhileTyping(box);
    for (const [index, typed] of ['1', '19', '19.9', '19.99'].entries()) {
      typeParseable(box, typed);
      if (index === 1) held.release(json(creditPage(1)));
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(box.value, `after typing "${typed}"`).toBe(typed);
    }
    await m.settle();
    expect(box.value).toBe('19.99');
    expect(writes, 'any assignment by the page while typing').toEqual([]);
    buttonNamed('Submit payment').click();
    await m.settle();
    expectBytes(bodyOf(s), `PAY-${new Date().toISOString().slice(0, 10)}-000027`, 1999, 'EUR');
  });
});
