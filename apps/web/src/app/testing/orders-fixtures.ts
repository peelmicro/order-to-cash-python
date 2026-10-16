import type { Schemas } from '../../shared/api-types';

/** The order id the sweep's dynamic route is rendered with (page-sweep.ts PARAM_VALUES.id). */
export const ORDER_ID = '9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f';

/** Event ids that collide ACROSS frame types on purpose: the projector gives `order.updated` and `timeline.appended` of one fact the same `eventId`. */
export const E1 = '11111111-1111-4111-8111-111111111111';
export const E2 = '22222222-2222-4222-8222-222222222222';
export const E3 = '33333333-3333-4333-8333-333333333333';
export const E4 = '44444444-4444-4444-8444-444444444444';
/** The id of a COMMAND (SA-6: a responder fact's `causationId` names the command, never a timeline entry). */
export const COMMAND_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

export const RETAILERS: Schemas['Party'][] = [
  { code: 'CarrefourEs', name: 'Carrefour España', country: 'ES', gln: '8431234000011', currency: 'EUR', enabled: true },
  { code: 'TokyoMart', name: 'Tokyo Mart', country: 'JP', gln: '4912345000012', currency: 'JPY', enabled: true },
];
export const COMPANIES: Schemas['Party'][] = [{ code: 'IBERFOODS', name: 'Iber Foods', country: 'ES', gln: '8430000000017', currency: 'EUR', enabled: true }];
export const PRODUCTS: Schemas['Product'][] = [
  { code: 'PRD-0001', name: 'Olive oil 1 L', price: 1999, currency: 'EUR', enabled: true },
  { code: 'PRD-0007', name: 'Rice 5 kg', price: 29, currency: 'EUR', enabled: true },
];

export function orderSummary(index: number, status: Schemas['OrderStatus'] = 'confirmed'): Schemas['OrderSummary'] {
  return {
    orderId: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
    orderReference: `ORD-${String(index).padStart(6, '0')}`,
    orderDate: '2026-10-15T10:00:00.000Z',
    retailer: { code: 'CarrefourEs', name: 'Carrefour España', gln: '8431234000011' },
    company: { code: 'IBERFOODS', name: 'Iber Foods', gln: '8430000000017' },
    status,
    currency: 'EUR',
    totals: { initialAmount: 124250, initialDiscount: 0, totalAmount: 124250 },
    updatedAt: '2026-10-15T10:00:05.000Z',
  };
}

export function orderPage(page: number, pageSize: number, total: number, rows: number): Schemas['OrderSummaryPage'] {
  return { items: Array.from({ length: rows }, (_, i) => orderSummary((page - 1) * pageSize + i + 1)), page: { page, pageSize, total } };
}

export function timelineEntry(eventId: string, eventType: string, summary: string, occurredAt: string, causationId?: string): Schemas['TimelineEntry'] {
  return causationId ? { eventId, causationId, eventType, occurredAt, summary } : { eventId, eventType, occurredAt, summary };
}

/** E1 placed (no cause); E2 reserved, caused by E1 (a fact: linkable); E3 credit approved, caused by a COMMAND (not an entry: no link). */
export function orderDetail(overrides: Partial<Schemas['OrderDetail']> = {}): Schemas['OrderDetail'] {
  return {
    orderId: ORDER_ID,
    orderReference: 'ORD-000042',
    orderDate: '2026-10-15T10:00:00.000Z',
    retailer: { code: 'CarrefourEs', name: 'Carrefour España', gln: '8431234000011' },
    company: { code: 'IBERFOODS', name: 'Iber Foods', gln: '8430000000017' },
    status: 'confirmed',
    cancellationReason: null,
    currency: 'EUR',
    totals: { initialAmount: 124250, initialDiscount: 0, totalAmount: 124250 },
    items: [{ productCode: 'PRD-0001', name: 'Olive oil 1 L', quantity: 5, unitPrice: 24850, lineDiscount: 0 }],
    references: { despatchReference: null, invoiceReference: null, paymentReference: null },
    events: [
      timelineEntry(E1, 'order.placed.v1', 'Order ORD-000042 placed for CarrefourEs', '2026-10-15T10:00:00.000Z'),
      timelineEntry(E2, 'stock.reserved.v1', 'Stock reserved for 1 line(s)', '2026-10-15T10:00:01.000Z', E1),
      timelineEntry(E3, 'credit.approved.v1', 'Credit hold of 1 242.50 EUR approved', '2026-10-15T10:00:02.000Z', COMMAND_ID),
    ],
    headerComplete: true,
    updatedAt: '2026-10-15T10:00:02.000Z',
    ...overrides,
  };
}

export const PENDING: Schemas['ProjectionPending'] = { orderId: ORDER_ID, status: 'projection_pending', message: 'The order was accepted and is not projected yet. Subscribe to /orders/stream or retry.', retryAfterMs: 500 };

export function placeOrderResponse(): Schemas['PlaceOrderResponse'] {
  return { orderId: ORDER_ID, orderReference: 'ORD-000042', status: 'placed', currency: 'EUR', initialAmount: 124250, initialDiscount: 0, totalAmount: 124250, orderDate: '2026-10-15T10:00:00.000Z', projectionPending: true };
}

export const updateFrame = (eventId: string, status: Schemas['OrderStatus'], occurredAt = '2026-10-15T10:00:03.000Z'): Schemas['OrderStreamUpdate'] => ({ eventId, orderId: ORDER_ID, status, occurredAt });
export const timelineFrame = (eventId: string, eventType: string, summary: string, occurredAt = '2026-10-15T10:00:03.000Z', causationId?: string): Schemas['TimelineStreamEntry'] =>
  causationId ? { eventId, causationId, orderId: ORDER_ID, eventType, occurredAt, summary } : { eventId, orderId: ORDER_ID, eventType, occurredAt, summary };
