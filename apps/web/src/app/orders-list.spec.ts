// The order list (R54): paging, filters, and three distinct states. Ported by content from #8's orders-list.test.tsx and #7's orders/index.spec.ts,
// with #7's Pass 7 lesson built in: a loading state is only proven while a request is genuinely held in flight.
import { screen, within, fireEvent } from '@testing-library/dom';
import { afterEach, describe, expect, it } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { QueryClient } from '@tanstack/angular-query-experimental';
import { json, problemResponse } from './testing/browser-harness';
import { orderPage, orderSummary } from './testing/orders-fixtures';
import { gate, mountPage } from './testing/page-test';
import { byLabel, choose, buttonNamed } from './testing/page-sweep';

afterEach(() => TestBed.resetTestingModule());

const LIST = /^GET \/api\/orders\?/;
const ids = () => screen.queryAllByTestId('order-row').map((row) => within(row).getAllByRole('link')[0]!.textContent);
const states = () => ({
  loading: screen.queryByTestId('orders-loading') !== null,
  empty: screen.queryByTestId('orders-empty') !== null,
  error: screen.queryByTestId('orders-error') !== null,
  table: screen.queryByTestId('orders-table') !== null,
});
const pagerText = () => screen.getByTestId('pager-count').textContent;

describe('R-list-states: loading, empty and error are distinct, and loading is proven while a request is held', () => {
  it('while the orders request is in flight: only "Loading orders…", no table, no empty text, no error, and the pager claims NO count', async () => {
    const held = gate();
    const { m } = await mountPage('/orders', [[LIST, held.answer]], { settle: false });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(held.started(), 'the request must be in flight for this to prove anything').toBe(true);
    expect(states()).toEqual({ loading: true, empty: false, error: false, table: false });
    expect(screen.getByTestId('orders-loading').textContent).toContain('Loading orders');
    expect(pagerText(), 'a pager that says "Page 1 of 1" while loading is the lie #8 review S4 found').toBe('');
    expect(buttonNamed('Next').disabled && buttonNamed('Previous').disabled).toBe(true);
    held.release(json(orderPage(1, 20, 45, 20)));
    await m.settle();
    expect(states()).toEqual({ loading: false, empty: false, error: false, table: true });
    expect(pagerText()).toBe('Page 1 of 3 · 45 orders');
  });

  it('an empty answer shows the empty state (not an empty table, not an error), and the pager reads Page 1 of 1 · 0 orders', async () => {
    await mountPage('/orders', [[LIST, () => json(orderPage(1, 20, 0, 0))]]);
    expect(states()).toEqual({ loading: false, empty: true, error: false, table: false });
    expect(pagerText()).toBe('Page 1 of 1 · 0 orders');
  });

  it('a failed read shows the problem\'s own detail, with no table, no empty text and no count', async () => {
    await mountPage('/orders', [[LIST, () => problemResponse(400, { type: 'about:blank', title: 'decoy', status: 400, detail: 'status: must be one of the nine order statuses' })]]);
    expect(states()).toEqual({ loading: false, empty: false, error: true, table: false });
    expect(screen.getByTestId('orders-error').textContent).toContain('status: must be one of the nine order statuses');
    expect(pagerText()).toBe('');
  });
});

describe('R-list-states (stage 2 review A2): after a later read fails the pager claims no count', () => {
  it('the first read answers 45 orders, the next read fails: the error shows, and the pager no longer says "Page 1 of 3 · 45 orders"', async () => {
    let reads = 0;
    const { m } = await mountPage('/orders', [[LIST, () => (++reads === 1 ? json(orderPage(1, 20, 45, 20)) : problemResponse(500, { type: 'about:blank', title: 'down', status: 500, detail: 'The read model is down.' }))]]);
    expect(pagerText()).toBe('Page 1 of 3 · 45 orders');
    await TestBed.inject(QueryClient).refetchQueries({ queryKey: ['orders'] });
    await m.settle();
    expect(reads, 'a second read must have happened for this to prove anything').toBeGreaterThanOrEqual(2);
    expect(states().error).toBe(true);
    expect(pagerText(), 'TanStack keeps the last data after a failed refetch; the pager must not keep claiming its count').toBe('');
    expect(buttonNamed('Next').disabled && buttonNamed('Previous').disabled).toBe(true);
  });
});

describe('R-list-rows: what a row shows', () => {
  it('reference (a link to the order), date, retailer, company, status and the total in the currency\'s own decimals', async () => {
    const page = orderPage(1, 20, 3, 3);
    page.items[1] = { ...orderSummary(2, 'cancelled'), currency: 'JPY', totals: { initialAmount: 1234567, initialDiscount: 0, totalAmount: 1234567 } };
    page.items[2] = { ...orderSummary(3, 'completed'), currency: 'BHD', totals: { initialAmount: 1005, initialDiscount: 0, totalAmount: 1005 } };
    await mountPage('/orders', [[LIST, () => json(page)]]);
    const rows = screen.getAllByTestId('order-row');
    expect(within(rows[0]!).getByRole('link').getAttribute('href')).toBe('/orders/00000000-0000-4000-8000-000000000001');
    expect(rows.map((row) => within(row).getByTestId('order-total').textContent)).toEqual(['1 242.50 EUR', '1 234 567 JPY', '1.005 BHD']);
    expect(rows[0]!.textContent).toContain('2026-10-15 10:00:00 UTC');
    expect(rows[0]!.textContent).toContain('Carrefour España');
    expect(rows.map((row) => row.querySelector('[data-status]')?.getAttribute('data-status'))).toEqual(['confirmed', 'cancelled', 'completed']);
  });
});

describe('R-list-filters: filters and paging are requests, and they start from page 1', () => {
  it('the status filter offers exactly the nine order statuses of openapi.yaml plus "All statuses"', async () => {
    await mountPage('/orders');
    const options = within(byLabel('Status')).getAllByRole('option').map((option) => option.textContent);
    expect(options).toEqual(['All statuses', 'placed', 'stock_reserved', 'credit_approved', 'confirmed', 'despatched', 'invoiced', 'paid', 'completed', 'cancelled']);
  });

  it('each filter sends its own query parameter, and the sent keys are exactly the openapi.yaml ones', async () => {
    const { m, s } = await mountPage('/orders');
    choose(byLabel('Status'), 'placed');
    await m.settle();
    choose(byLabel('Retailer'), 'CarrefourEs');
    await m.settle();
    choose(byLabel('Company'), 'IBERFOODS');
    await m.settle();
    choose(byLabel('Reference'), ' ORD-000042 ');
    await m.settle();
    const last = s.calls.filter((call) => LIST.test(call.key)).at(-1)!.key;
    expect(new URLSearchParams(last.split('?')[1]).getAll('status')).toEqual(['placed']);
    expect(Object.fromEntries(new URLSearchParams(last.split('?')[1]))).toEqual({ companyCode: 'IBERFOODS', orderReference: 'ORD-000042', page: '1', pageSize: '20', retailerCode: 'CarrefourEs', status: 'placed' });
  });

  it('Next asks for page 2, Previous for page 1, Previous is off on page 1 and Next on the last page; a filter returns to page 1', async () => {
    const { m, s } = await mountPage('/orders', [[LIST, (key) => json(orderPage(Number(new URLSearchParams(key.split('?')[1]).get('page')), 20, 45, 20))]]);
    expect(buttonNamed('Previous').disabled).toBe(true);
    buttonNamed('Next').click();
    await m.settle();
    expect(s.calls.at(-1)!.key).toBe('GET /api/orders?page=2&pageSize=20');
    expect(pagerText()).toBe('Page 2 of 3 · 45 orders');
    buttonNamed('Next').click();
    await m.settle();
    expect(buttonNamed('Next').disabled).toBe(true);
    choose(byLabel('Status'), 'paid');
    await m.settle();
    expect(s.calls.at(-1)!.key).toBe('GET /api/orders?page=1&pageSize=20&status=paid');
    expect(pagerText()).toBe('Page 1 of 3 · 45 orders');
    fireEvent.click(buttonNamed('Next'));
    await m.settle();
    buttonNamed('Previous').click();
    await m.settle();
    expect(pagerText(), 'back on page 1 (its answer is still fresh, so no new request is owed)').toBe('Page 1 of 3 · 45 orders');
  });

  it('a failing retailer list shows its own text beside the filter and the orders still load', async () => {
    await mountPage('/orders', [['GET /api/catalog/retailers', () => problemResponse(503, { type: 'about:blank', title: 'Service Unavailable', status: 503, detail: 'The catalogue responder did not answer in time.' })]]);
    expect(screen.getByTestId('order-retailer-filter-error').textContent).toContain('The catalogue responder did not answer in time.');
    expect(ids()).toHaveLength(20);
  });
});
