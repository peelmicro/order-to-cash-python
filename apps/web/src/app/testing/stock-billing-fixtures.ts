import type { Schemas } from '../../shared/api-types';

/**
 * Fixtures for the stock and billing pages. Chosen so that no assertion passes by accident (CLAUDE.md "fixtures must not satisfy the assertion's
 * relation by accident"): no product name contains a product code and no code contains a name, so "the code appears once" cannot be satisfied by a
 * name that happens to carry it; every amount is distinct from every other in the same table.
 */

/** In the catalogue (PRODUCTS in orders-fixtures.ts) as "Olive oil 1 L"; the stock line carries no name of its own. */
export const STOCK_CATALOGUE_NAMED: Schemas['StockItem'] = { companyCode: 'IBERFOODS', productCode: 'PRD-0001', units: 120, reservedUnits: 20, availableUnits: 100, lowStockThreshold: 10 };
/** In the catalogue as "Rice 5 kg", AND carries its own `productName`: the stock line's name wins. Low on stock (available 5 < threshold 10). */
export const STOCK_OWN_NAME: Schemas['StockItem'] = { companyCode: 'IBERFOODS', productCode: 'PRD-0007', productName: 'Arroz bomba', units: 8, reservedUnits: 3, availableUnits: 5, lowStockThreshold: 10 };
/** Not in the catalogue and carrying no name: only its code can be shown, once. */
export const STOCK_UNKNOWN: Schemas['StockItem'] = { companyCode: 'IBERFOODS', productCode: 'PRD-0999', units: 50, reservedUnits: 0, availableUnits: 50, lowStockThreshold: 5 };

export const STOCK_ITEMS = [STOCK_CATALOGUE_NAMED, STOCK_OWN_NAME, STOCK_UNKNOWN];

/** 45 stock lines at 20 per page: three pages, so Next exists on page 1 and the pager has a count to claim. */
export function stockPage(page: number, items: Schemas['StockItem'][] = STOCK_ITEMS, total = 45): Schemas['StockPage'] {
  return { items, page: { page, pageSize: 20, total } };
}

export function replenishResponse(items: Schemas['StockItem'][] = [{ ...STOCK_CATALOGUE_NAMED, units: 220, availableUnits: 200 }]): Schemas['ReplenishStockResponse'] {
  return { items };
}

const invoice = (n: number, overrides: Partial<Schemas['Invoice']>): Schemas['Invoice'] => ({
  invoiceId: `10000000-0000-4000-8000-${String(n).padStart(12, '0')}`,
  invoiceReference: `INV-${String(n).padStart(6, '0')}`,
  invoiceDate: '2026-10-15T10:00:00.000Z',
  orderReference: `ORD-${String(n + 15).padStart(6, '0')}`,
  retailerCode: 'CarrefourEs',
  companyCode: 'IBERFOODS',
  currency: 'EUR',
  amount: 124250,
  discount: 0,
  totalAmount: 124250,
  status: 'issued',
  paidAt: null,
  ...overrides,
});

/** EUR 1 242.50; EUR 33.33; BHD 2.005 (three decimals); JPY 5000 (none); and a paid EUR 50.00. No total equals an amount a test types (0.29, 19.99, 1.005, 1999), so a row that passes with the typing ignored would have to pass by the prefill alone (stage 3 review B-S3-3). */
export const INV_EUR = invoice(27, {});
export const INV_TRAP = invoice(28, { amount: 3333, totalAmount: 3333 });
export const INV_BHD = invoice(29, { currency: 'BHD', amount: 2005, totalAmount: 2005, retailerCode: 'GulfMart' });
export const INV_JPY = invoice(30, { currency: 'JPY', amount: 5000, totalAmount: 5000, retailerCode: 'TokyoMart' });
export const INV_PAID = invoice(31, { amount: 5000, totalAmount: 5000, status: 'paid', paidAt: '2026-10-15T11:00:00.000Z' });
export const INVOICES = [INV_EUR, INV_TRAP, INV_BHD, INV_JPY, INV_PAID];

export function invoicePage(page: number, items: Schemas['Invoice'][] = INVOICES, total = 45): Schemas['InvoicePage'] {
  return { items, page: { page, pageSize: 20, total } };
}

export const CREDIT_OPEN: Schemas['Credit'] = { creditCode: 'CR-000001', retailerCode: 'CarrefourEs', companyCode: 'IBERFOODS', currency: 'EUR', creditLimit: 1_000_000, activeHolds: 124250, openExposure: 50_000, availableCredit: 825_750 };
export const CREDIT_EXHAUSTED: Schemas['Credit'] = { creditCode: 'CR-000002', retailerCode: 'TokyoMart', companyCode: 'IBERFOODS', currency: 'JPY', creditLimit: 5_000_000, activeHolds: 2_000_000, openExposure: 3_000_000, availableCredit: 0 };
export const CREDITS = [CREDIT_OPEN, CREDIT_EXHAUSTED];

export function creditPage(page: number, items: Schemas['Credit'][] = CREDITS, total = 45): Schemas['CreditPage'] {
  return { items, page: { page, pageSize: 20, total } };
}

export function paymentAccepted(reference = 'PAY-2026-10-15-000027'): Schemas['RegisterPaymentResponse'] {
  return { outcome: 'accepted', paymentReference: reference, invoiceReference: 'INV-000027', orderReference: 'ORD-000042', invoiceStatus: 'paid', paidAt: '2026-10-15T10:05:00.000Z' };
}
export function paymentDuplicate(reference = 'PAY-2026-10-15-000027'): Schemas['RegisterPaymentResponse'] {
  return { ...paymentAccepted(reference), outcome: 'duplicate' };
}
