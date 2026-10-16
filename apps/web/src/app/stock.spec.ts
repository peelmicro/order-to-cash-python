// The stock page (feature 29, stage 3): the list, #8 id 101 (names), the replenish delta. Ported by content from #8's stock-view.test.tsx and #7's stock/index.spec.ts,
// with #7 Pass 7's lesson built in (a loading state is only proven while a request is held in flight) and stage 2's A2 (the pager claims no count while loading or after a failed read).
import { fireEvent, screen, within } from '@testing-library/dom';
import { afterEach, describe, expect, it } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { QueryClient } from '@tanstack/angular-query-experimental';
import { json, problemResponse } from './testing/browser-harness';
import { gate, mountPage, type Stub } from './testing/page-test';
import { buttonNamed, byLabel, typeInto } from './testing/page-sweep';
import { typeParseable, typeUnparseable, writesWhileTyping } from './testing/number-input';
import { replenishResponse, STOCK_CATALOGUE_NAMED, STOCK_ITEMS, STOCK_OWN_NAME, STOCK_UNKNOWN, stockPage } from './testing/stock-billing-fixtures';

afterEach(() => TestBed.resetTestingModule());

const LIST = /^GET \/api\/stock\?/;
const PRODUCTS = 'GET /api/catalog/products';
const REPLENISH = 'POST /api/stock/replenish';
const problem = (status: number, detail: string) => problemResponse(status, { type: 'about:blank', title: 'decoy-title', status, detail });
const flat = (node: Element | null) => (node?.textContent ?? '').replace(/\s+/g, ' ').trim();
const productCells = () => screen.queryAllByTestId('stock-product').map(flat);
const states = () => ({
  loading: screen.queryByTestId('stock-loading') !== null,
  empty: screen.queryByTestId('stock-empty') !== null,
  error: screen.queryByTestId('stock-error') !== null,
  table: screen.queryByTestId('stock-table') !== null,
});
const pagerText = () => screen.getByTestId('pager-count').textContent;
const queryOf = (key: string) => Object.fromEntries(new URLSearchParams(key.split('?')[1]));
const bodyOf = (s: Stub) => s.matching(REPLENISH).at(-1)!.init!.body as string;
/** One button per (company, product) row: its name carries both, because the same product is held by several companies (found live: 215 lines of 5 companies). */
const open = (code: string, company = 'IBERFOODS') => buttonNamed(`Replenish ${code} for ${company}`).click();
const unitsBox = () => screen.getByLabelText<HTMLInputElement>('Units to add');
const form = () => screen.getByTestId('replenish-form').querySelector('form')!;

describe('R-stock-states: loading, empty and error are distinct, and loading is proven while a request is held', () => {
  it('while the stock request is in flight: only "Loading stock…", no table, no empty text, no error, and the pager claims NO count', async () => {
    const held = gate();
    const { m } = await mountPage('/stock', [[LIST, held.answer]], { settle: false });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(held.started(), 'the request must be in flight for this to prove anything').toBe(true);
    expect(states()).toEqual({ loading: true, empty: false, error: false, table: false });
    expect(pagerText()).toBe('');
    expect(buttonNamed('Next').disabled && buttonNamed('Previous').disabled).toBe(true);
    held.release(json(stockPage(1)));
    await m.settle();
    expect(states()).toEqual({ loading: false, empty: false, error: false, table: true });
    expect(pagerText()).toBe('Page 1 of 3 · 45 stock lines');
  });

  it('an empty answer shows the empty state (not an empty table, not an error), and the pager reads Page 1 of 1 · 0 stock lines', async () => {
    await mountPage('/stock', [[LIST, () => json(stockPage(1, [], 0))]]);
    expect(states()).toEqual({ loading: false, empty: true, error: false, table: false });
    expect(pagerText()).toBe('Page 1 of 1 · 0 stock lines');
  });

  it("a failed read shows the problem's own detail (not the decoy title), with no table, no empty text and no count", async () => {
    await mountPage('/stock', [[LIST, () => problem(503, 'Fulfillment did not answer in time.')]]);
    expect(states()).toEqual({ loading: false, empty: false, error: true, table: false });
    expect(screen.getByTestId('stock-error').textContent).toContain('Fulfillment did not answer in time.');
    expect(screen.queryByText('decoy-title')).toBeNull();
    expect(pagerText()).toBe('');
  });

  it('the first read answers 45 lines, the next read fails: the error shows, and the pager no longer says "Page 1 of 3 · 45 stock lines" (stage 2 review A2, applied)', async () => {
    let reads = 0;
    const { m } = await mountPage('/stock', [[LIST, () => (++reads === 1 ? json(stockPage(1)) : problem(500, 'The stock read is down.'))]]);
    expect(pagerText()).toBe('Page 1 of 3 · 45 stock lines');
    await TestBed.inject(QueryClient).refetchQueries({ queryKey: ['stock'] });
    await m.settle();
    expect(reads, 'a second read must have happened for this to prove anything').toBeGreaterThanOrEqual(2);
    expect(states().error).toBe(true);
    expect(pagerText()).toBe('');
    expect(buttonNamed('Next').disabled && buttonNamed('Previous').disabled).toBe(true);
  });
});

describe('R-stock-rows: what a row shows', () => {
  it('on hand, reserved and available (units - reserved, F1) per line, with a low line flagged', async () => {
    await mountPage('/stock');
    const rows = screen.getAllByTestId('stock-row');
    expect(rows.map((row) => [within(row).getByTestId('stock-units').textContent, within(row).getByTestId('stock-reserved').textContent, flat(within(row).getByTestId('stock-available'))])).toEqual([
      ['120', '20', '100'],
      ['8', '3', '5'],
      ['50', '0', '50'],
    ]);
    const badge = (row: HTMLElement) => within(row).getByTestId('stock-available').querySelector('span')!.className;
    expect(badge(rows[1]!), 'available 5 < threshold 10 is flagged; available 100 and 50 are not').not.toBe(badge(rows[0]!));
    expect(badge(rows[2]!)).toBe(badge(rows[0]!));
  });
});

describe('R-stock-name (#8 id 101): the product name with its code beside it, the code once when no name is known', () => {
  it('the name comes from the catalogue when the stock line carries none; the line\'s own productName wins over the catalogue; an unknown product shows its code alone', async () => {
    await mountPage('/stock');
    expect(productCells()).toEqual(['Olive oil 1 L (PRD-0001)', 'Arroz bomba (PRD-0007)', 'PRD-0999']);
  });

  it('the code appears exactly once in every row, whether a name is known or not (the duplicate "PRD-0999 (PRD-0999)" is what returning would look like)', async () => {
    await mountPage('/stock');
    for (const [index, item] of STOCK_ITEMS.entries()) {
      const cell = productCells()[index]!;
      expect(cell.split(item.productCode).length - 1, `${item.productCode} in "${cell}"`).toBe(1);
    }
  });

  it("productName wins: the catalogue's own name for that code (\"Rice 5 kg\") is not shown, and neither name contains a code", async () => {
    await mountPage('/stock');
    expect(screen.queryByText(/Rice 5 kg/)).toBeNull();
    expect(flat(screen.getAllByTestId('stock-row')[1]!)).toContain('Arroz bomba');
  });

  it('the catalogue request is part of the page (it is what the sweep fails, and it is asked once)', async () => {
    const { s } = await mountPage('/stock');
    expect(s.count(PRODUCTS)).toBe(1);
  });

  it('while the catalogue is held the rows show their codes; when it arrives the names appear (and the code is still once)', async () => {
    const held = gate();
    const { m } = await mountPage('/stock', [[PRODUCTS, held.answer]], { settle: false });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(held.started()).toBe(true);
    expect(states().table, 'the table does not wait for the catalogue').toBe(true);
    expect(productCells()).toEqual(['PRD-0001', 'Arroz bomba (PRD-0007)', 'PRD-0999']);
    held.release(json({ items: [{ code: 'PRD-0001', name: 'Olive oil 1 L', price: 1999, currency: 'EUR', enabled: true }] }));
    await m.settle();
    expect(productCells()).toEqual(['Olive oil 1 L (PRD-0001)', 'Arroz bomba (PRD-0007)', 'PRD-0999']);
  });

  it("a failed catalogue read does not hide the table: rows fall back to their codes, and the catalogue's own words are shown once beside it", async () => {
    await mountPage('/stock', [[PRODUCTS, () => problem(503, 'The catalogue responder did not answer in time.')]]);
    expect(states()).toEqual({ loading: false, empty: false, error: false, table: true });
    expect(productCells()).toEqual(['PRD-0001', 'Arroz bomba (PRD-0007)', 'PRD-0999']);
    expect(screen.getAllByTestId('stock-products-error').map(flat)).toEqual(['Product names unavailable: The catalogue responder did not answer in time.']);
    expect(screen.queryByTestId('stock-error'), 'the stock error is for the stock read only').toBeNull();
  });
});

describe('R-stock-filters: the filters openapi.yaml declares for /stock, and paging, are requests that start from page 1', () => {
  it('the sent keys are exactly companyCode, productCode, belowThreshold, page, pageSize; belowThreshold is absent until it is on', async () => {
    const { m, s } = await mountPage('/stock');
    expect(s.calls.filter((call) => LIST.test(call.key)).at(-1)!.key).toBe('GET /api/stock?page=1&pageSize=20');
    typeInto(byLabel('Company'), 'IBERFOODS');
    fireEvent.change(byLabel('Company'));
    await m.settle();
    typeInto(byLabel('Product'), ' PRD-0001 ');
    fireEvent.change(byLabel('Product'));
    await m.settle();
    expect(queryOf(s.calls.filter((call) => LIST.test(call.key)).at(-1)!.key), 'switched off, the parameter is not sent at all').toEqual({ companyCode: 'IBERFOODS', page: '1', pageSize: '20', productCode: 'PRD-0001' });
    fireEvent.click(byLabel('Low stock only'));
    await m.settle();
    expect(queryOf(s.calls.filter((call) => LIST.test(call.key)).at(-1)!.key)).toEqual({ belowThreshold: 'true', companyCode: 'IBERFOODS', page: '1', pageSize: '20', productCode: 'PRD-0001' });
  });

  it('Next asks for page 2 and Previous for page 1, Previous is off on page 1 and Next on the last page; a filter returns to page 1', async () => {
    const { m, s } = await mountPage('/stock', [[LIST, (key) => json(stockPage(Number(queryOf(key)['page'])))]]);
    expect(buttonNamed('Previous').disabled).toBe(true);
    buttonNamed('Next').click();
    await m.settle();
    expect(s.calls.at(-1)!.key).toBe('GET /api/stock?page=2&pageSize=20');
    expect(pagerText()).toBe('Page 2 of 3 · 45 stock lines');
    buttonNamed('Next').click();
    await m.settle();
    expect(buttonNamed('Next').disabled).toBe(true);
    fireEvent.click(byLabel('Low stock only'));
    await m.settle();
    expect(s.calls.at(-1)!.key).toBe('GET /api/stock?belowThreshold=true&page=1&pageSize=20');
  });
});

describe('R-replenish-body: the request is exactly ReplenishStockRequest, `units` is an integer, a delta', () => {
  it.each([
    ['100', 100],
    ['7', 7],
    ['1', 1],
  ])('"%s" units for PRD-0001 is sent as the bytes {"companyCode":"IBERFOODS","lines":[{"productCode":"PRD-0001","units":%i}]}', async (typed, units) => {
    const { m, s } = await mountPage('/stock');
    open('PRD-0001');
    await m.settle();
    typeParseable(unitsBox(), typed);
    buttonNamed('Add units').click();
    await m.settle();
    expect(bodyOf(s)).toBe(`{"companyCode":"IBERFOODS","lines":[{"productCode":"PRD-0001","units":${units}}]}`);
    expect(JSON.parse(bodyOf(s)).lines[0].units, 'an integer, not the text').toBe(units);
  });

  it('the form says it ADDS (a delta, not a target level) and that a repeat adds again', async () => {
    const { m } = await mountPage('/stock');
    open('PRD-0001');
    await m.settle();
    const text = flat(screen.getByTestId('replenish-form'));
    expect(text).toContain('adds to on-hand stock');
    expect(text).toContain('a delta, not a target level');
    expect(text).toContain('Submitting the same amount twice adds it twice');
  });

  it('the row that was opened is the row replenished: PRD-0007\'s button sends PRD-0007', async () => {
    const { m, s } = await mountPage('/stock');
    open('PRD-0007');
    await m.settle();
    typeParseable(unitsBox(), '40');
    buttonNamed('Add units').click();
    await m.settle();
    expect(bodyOf(s)).toBe('{"companyCode":"IBERFOODS","lines":[{"productCode":"PRD-0007","units":40}]}');
  });
});

describe('R-replenish-bad-input: a units text that is not a whole number of at least 1 is refused in words that name the field, and nothing is sent', () => {
  it.each(['0', '1.5', '-2', '', '1e2', 'abc', '9007199254740993'])('"%s" is refused; a parseable retype then sends the typed number', async (typed) => {
    const { m, s } = await mountPage('/stock');
    open('PRD-0001');
    await m.settle();
    typeParseable(unitsBox(), typed);
    buttonNamed('Add units').click();
    await m.settle();
    expect(s.count(REPLENISH), 'nothing may be sent').toBe(0);
    expect(screen.getByTestId('replenish-units-problem').textContent).toBe('Units to add: enter a whole number of at least 1.');
    expect(unitsBox().getAttribute('aria-invalid')).toBe('true');
    typeParseable(unitsBox(), '12');
    buttonNamed('Add units').click();
    await m.settle();
    expect(s.count(REPLENISH)).toBe(1);
    expect(bodyOf(s)).toContain('"units":12');
  });

  it('a text the browser could not parse (reported as "" with badInput) is refused, never read as an empty or a default amount', async () => {
    const { m, s } = await mountPage('/stock');
    open('PRD-0001');
    await m.settle();
    typeParseable(unitsBox(), '5');
    typeUnparseable(unitsBox());
    buttonNamed('Add units').click();
    await m.settle();
    expect(s.count(REPLENISH)).toBe(0);
    expect(screen.getByTestId('replenish-units-problem').textContent, 'an unreadable text is told apart from an empty one').toBe('Units to add: the browser could not read what was typed. Enter a whole number of at least 1.');
  });
});

describe('R-replenish-result: the list is read again after success, and every answer is shown honestly', () => {
  it('after a 200 the list re-reads and the row shows the new on-hand level; the outcome says what was added and the new level', async () => {
    let replenished = false;
    const { m, s } = await mountPage('/stock', [
      [LIST, () => json(stockPage(1, replenished ? [{ ...STOCK_CATALOGUE_NAMED, units: 220, availableUnits: 200 }, STOCK_OWN_NAME, STOCK_UNKNOWN] : STOCK_ITEMS))],
      [REPLENISH, () => ((replenished = true), json(replenishResponse()))],
    ]);
    expect(screen.getAllByTestId('stock-units')[0]!.textContent).toBe('120');
    const reads = s.count(LIST);
    open('PRD-0001');
    await m.settle();
    typeParseable(unitsBox(), '100');
    buttonNamed('Add units').click();
    await m.settle();
    expect(s.count(LIST), 'the list was read again').toBe(reads + 1);
    expect(screen.getAllByTestId('stock-units')[0]!.textContent).toBe('220');
    expect(screen.getByTestId('replenish-outcome').textContent).toBe('Added 100 units to PRD-0001 for IBERFOODS. On hand is now 220.');
  });

  it('an answer that omits the line says so, and never reads as still working', async () => {
    const { m } = await mountPage('/stock', [[REPLENISH, () => json(replenishResponse([]))]]);
    open('PRD-0001');
    await m.settle();
    typeParseable(unitsBox(), '3');
    buttonNamed('Add units').click();
    await m.settle();
    expect(screen.getByTestId('replenish-outcome').textContent).toBe('Added 3 units to PRD-0001 for IBERFOODS. The answer did not include this line’s new on-hand level.');
  });

  it.each([
    [400, 'lines[0].units: must be at least 1.'],
    [404, 'Stock line PRD-0001 of IBERFOODS does not exist.'],
    [500, 'An unexpected error occurred.'],
    [503, 'The Fulfillment context did not answer in time.'],
  ])("a %i shows the problem's own detail (not the decoy title), keeps the form, and re-reads nothing", async (status, detail) => {
    const { m, s } = await mountPage('/stock', [[REPLENISH, () => problem(status, detail)]]);
    open('PRD-0001');
    await m.settle();
    const reads = s.count(LIST);
    typeParseable(unitsBox(), '5');
    buttonNamed('Add units').click();
    await m.settle();
    expect(screen.getByTestId('replenish-error').textContent).toContain(detail);
    expect(screen.queryByText('decoy-title')).toBeNull();
    expect(screen.queryByTestId('replenish-outcome')).toBeNull();
    expect(s.count(LIST), 'a refused top-up changed nothing: no re-read is owed').toBe(reads);
    expect(s.count(REPLENISH)).toBe(1);
  });

  it("a rejected replenish's error does not follow the panel to another line", async () => {
    const { m } = await mountPage('/stock', [[REPLENISH, () => problem(404, 'Stock line PRD-0001 of IBERFOODS does not exist.')]]);
    open('PRD-0001');
    await m.settle();
    typeParseable(unitsBox(), '5');
    buttonNamed('Add units').click();
    await m.settle();
    expect(screen.queryByTestId('replenish-error')).not.toBeNull();
    open('PRD-0007');
    await m.settle();
    expect(screen.queryByTestId('replenish-error'), 'the other line starts clean').toBeNull();
  });
});

describe('R-replenish-single: a top-up is a delta, so a submit cannot double-fire', () => {
  it('two submit events in the same task, and a click on the disabled button, send ONE request; the button reads "Adding…" while it is in flight', async () => {
    const held = gate();
    const { m, s } = await mountPage('/stock', [[REPLENISH, held.answer]]);
    open('PRD-0001');
    await m.settle();
    typeParseable(unitsBox(), '5');
    fireEvent.submit(form());
    fireEvent.submit(form());
    fireEvent.click(buttonNamed('Add units'));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(s.count(REPLENISH)).toBe(1);
    expect(buttonNamed('Adding…').disabled).toBe(true);
    held.release(json(replenishResponse()));
    await m.settle();
    expect(s.count(REPLENISH)).toBe(1);
  });
});

describe('R-replenish-company (found live): the same product held by several companies has one button per row, named by both, and the company replenished is the row\'s', () => {
  const TWO_COMPANIES = [STOCK_CATALOGUE_NAMED, { ...STOCK_CATALOGUE_NAMED, companyCode: 'BAUWERK', units: 70, reservedUnits: 5, availableUnits: 65 }];

  it('two rows of PRD-0001 (IBERFOODS and BAUWERK): two distinct accessible names, and each button opens its own row', async () => {
    const { m } = await mountPage('/stock', [[LIST, () => json(stockPage(1, TWO_COMPANIES, 2))]]);
    const names = screen.getAllByTestId('replenish-button').map((button) => button.getAttribute('aria-label'));
    expect(names).toEqual(['Replenish PRD-0001 for IBERFOODS', 'Replenish PRD-0001 for BAUWERK']);
    expect(new Set(names).size, 'every button of the page has its own name').toBe(2);
    open('PRD-0001', 'BAUWERK');
    await m.settle();
    expect(flat(screen.getByTestId('replenish-form'))).toContain('(BAUWERK)');
  });

  it("the replenish for the second row sends BAUWERK, the row's company, and that row's units are what the outcome reports", async () => {
    const { m, s } = await mountPage('/stock', [
      [LIST, () => json(stockPage(1, TWO_COMPANIES, 2))],
      [REPLENISH, () => json(replenishResponse([{ ...STOCK_CATALOGUE_NAMED, units: 999 }, { ...STOCK_CATALOGUE_NAMED, companyCode: 'BAUWERK', units: 77, reservedUnits: 5, availableUnits: 72 }]))],
    ]);
    open('PRD-0001', 'BAUWERK');
    await m.settle();
    typeParseable(unitsBox(), '7');
    buttonNamed('Add units').click();
    await m.settle();
    expect(bodyOf(s)).toBe('{"companyCode":"BAUWERK","lines":[{"productCode":"PRD-0001","units":7}]}');
    expect(screen.getByTestId('replenish-outcome').textContent, "the other company's line of the same product is not mistaken for this one").toBe('Added 7 units to PRD-0001 for BAUWERK. On hand is now 77.');
  });
});

describe('R-replenish-draft (stage 2 re-review H01): the units box takes its draft from outside when the panel moves to another line', () => {
  it('"5" typed for PRD-0001, then Replenish on PRD-0007: the SAME box now shows nothing, and submitting sends nothing until a number is typed', async () => {
    const { m, s } = await mountPage('/stock');
    open('PRD-0001');
    await m.settle();
    const box = unitsBox();
    typeParseable(box, '5');
    await m.settle();
    expect(box.value).toBe('5');
    open('PRD-0007');
    await m.settle();
    expect(unitsBox(), 'the panel persists across the two rows: this is an existing box, not a new one').toBe(box);
    expect(box.value, 'the draft was reset from outside and the box shows it').toBe('');
    buttonNamed('Add units').click();
    await m.settle();
    expect(s.count(REPLENISH)).toBe(0);
  });
});

describe('R-replenish-draft (review A1): an UNREADABLE text in the units box is cleared when the panel moves to another row', () => {
  it('"1-2" (value "", badInput) is in the box; Replenish on PRD-0007: the page writes "" into that same box (a draft that is "" already would otherwise write nothing)', async () => {
    const { m } = await mountPage('/stock');
    open('PRD-0001');
    await m.settle();
    const box = unitsBox();
    typeUnparseable(box);
    await m.settle();
    const writes = writesWhileTyping(box);
    open('PRD-0007');
    await m.settle();
    expect(unitsBox(), 'the same element').toBe(box);
    expect(writes, 'one write of "": the text on screen is cleared, not left under the other row\'s heading').toEqual(['']);
  });

  it('typing unreadable text never writes (the reset counter moves only when the page resets the draft)', async () => {
    const { m } = await mountPage('/stock');
    open('PRD-0001');
    await m.settle();
    const writes = writesWhileTyping(unitsBox());
    typeParseable(unitsBox(), '5');
    typeUnparseable(unitsBox());
    await m.settle();
    expect(writes).toEqual([]);
  });
});

describe('R-stock-labels: filters and headers are found by their visible label', () => {
  it('Company, Product and Low stock only resolve by label; the table has real column headers', async () => {
    await mountPage('/stock');
    expect([byLabel('Company'), byLabel('Product'), byLabel('Low stock only')].every((control) => control instanceof HTMLInputElement)).toBe(true);
    expect(screen.getAllByRole('columnheader').map((header) => flat(header))).toEqual(['Company', 'Product', 'On hand', 'Reserved', 'Available', 'Threshold', 'Actions']);
  });
});

describe('R-typing (stage 3): keystrokes typed into the units box while a request is in flight end up as exactly the typed text', () => {
  it('"1", "10", "100" typed while the catalogue is held and released mid-typing: the text is the typed text, the page makes no assignment to the box, and the bytes are exact', async () => {
    const held = gate();
    const { m, s } = await mountPage('/stock', [[PRODUCTS, held.answer]], { settle: false });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(held.started(), 'the catalogue must be in flight for this to prove anything').toBe(true);
    open('PRD-0001');
    await new Promise((resolve) => setTimeout(resolve, 30));
    const box = unitsBox();
    const writes = writesWhileTyping(box);
    for (const [index, typed] of ['1', '10', '100'].entries()) {
      typeParseable(box, typed);
      if (index === 1) held.release(json({ items: [] }));
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(box.value, `after typing "${typed}"`).toBe(typed);
    }
    await m.settle();
    expect(box.value).toBe('100');
    expect(writes, 'any assignment by the page while typing').toEqual([]);
    buttonNamed('Add units').click();
    await m.settle();
    expect(bodyOf(s)).toBe('{"companyCode":"IBERFOODS","lines":[{"productCode":"PRD-0001","units":100}]}');
  });
});
