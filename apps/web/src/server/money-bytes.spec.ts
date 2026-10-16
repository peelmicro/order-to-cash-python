// Stage 3, acceptance item 3: the BFF relays a payment's and a replenish's body to the Gateway as the exact bytes the browser sent, and money stays an integer.
// The browser side of the same claim is src/app/billing.spec.ts R-payment-bytes (what the page puts on the wire for "0.29", BHD "1.005", JPY "1999");
// this file is the half that follows: nothing between the browser and the Gateway parses, rounds or re-serialises an amount.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { signIn } from './testing/bff-contract';
import { INVOICE_ID, SESSION_PASSWORD } from './testing/gateway-script';
import { sendJson } from './testing/fake-gateway';
import { startBff, type Bff } from './testing/harness';

let bff: Bff | undefined;
afterEach(async () => {
  await bff?.stop();
  bff = undefined;
  vi.unstubAllEnvs();
});

async function start(): Promise<{ bff: Bff; cookie: string }> {
  vi.stubEnv('WEB_SESSION_PASSWORD', SESSION_PASSWORD);
  vi.stubEnv('WEB_COOKIE_SECURE', '');
  bff = await startBff((name, value) => vi.stubEnv(name, value));
  const cookie = await signIn(bff);
  bff.gateway.requests.length = 0;
  return { bff, cookie };
}

const payment = (amount: number, currency: string) => `{"paymentReference":"PAY-2026-10-15-000027","amount":{"amount":${amount},"currency":"${currency}"},"valueDate":"2026-10-15T10:00:00.000Z","source":"operator"}`;

describe('R-bytes (BFF): a body reaches the Gateway as the exact bytes the browser sent', () => {
  it.each([
    ['EUR 0.29, the float trap (0.29 * 100 is 28.999999999999996)', 29, 'EUR'],
    ['BHD 1.005, three decimals', 1005, 'BHD'],
    ['JPY 1999, none', 1999, 'JPY'],
    ['EUR 19.99', 1999, 'EUR'],
    ['the largest safe integer', 9007199254740991, 'EUR'],
  ])('a payment of %s: the Gateway receives byte-identical JSON, the amount an integer', async (_name, minor, currency) => {
    const started = await start();
    started.bff.gateway.on('POST', `/invoices/${INVOICE_ID}/payments`, (_req, res) => sendJson(res, 201, { outcome: 'accepted' }));
    const sent = payment(minor, currency);
    const response = await started.bff.fetch(`/api/invoices/${INVOICE_ID}/payments`, { method: 'POST', headers: { cookie: started.cookie, 'Content-Type': 'application/json' }, body: sent });
    expect(response.status).toBe(201);
    const received = started.bff.gateway.requests.filter((request) => request.url === `/invoices/${INVOICE_ID}/payments`);
    expect(received, 'one request reached the Gateway').toHaveLength(1);
    expect(received[0]!.body, 'the bytes the Gateway received').toBe(sent);
    const amount = (JSON.parse(received[0]!.body) as { amount: { amount: number } }).amount.amount;
    expect(Number.isInteger(amount) && amount === minor, 'an integer count of minor units, exactly').toBe(true);
  });

  it('NON-canonical bytes reach the Gateway untouched: whitespace, a key order the browser never writes, and an integer above 2^53 (which a JSON round trip would change to ...992) (review A3)', async () => {
    const started = await start();
    started.bff.gateway.on('POST', `/invoices/${INVOICE_ID}/payments`, (_req, res) => sendJson(res, 201, { outcome: 'accepted' }));
    const sent = '{ "source": "operator",\n  "amount": { "currency": "EUR", "amount": 9007199254740993 }, "valueDate": "2026-10-15T10:00:00.000Z", "paymentReference": "PAY-1" }';
    expect(JSON.stringify(JSON.parse(sent)), 'the premise: a parse and re-serialise would NOT give these bytes back').not.toBe(sent);
    const response = await started.bff.fetch(`/api/invoices/${INVOICE_ID}/payments`, { method: 'POST', headers: { cookie: started.cookie, 'Content-Type': 'application/json' }, body: sent });
    expect(response.status).toBe(201);
    expect(started.bff.gateway.requests.at(-1)!.body, 'the bytes the Gateway received').toBe(sent);
  });

  it('a replenish of 7 units reaches the Gateway as the same bytes, `units` an integer', async () => {
    const started = await start();
    started.bff.gateway.on('POST', '/stock/replenish', (_req, res) => sendJson(res, 200, { items: [] }));
    const sent = '{"companyCode":"IBERFOODS","lines":[{"productCode":"PRD-0001","units":7}]}';
    const response = await started.bff.fetch('/api/stock/replenish', { method: 'POST', headers: { cookie: started.cookie, 'Content-Type': 'application/json' }, body: sent });
    expect(response.status).toBe(200);
    expect(started.bff.gateway.requests.at(-1)!.body).toBe(sent);
  });

  it('a 201 and a 200 (the idempotent replay, with its Idempotent-Replay header) are relayed with their own status and body', async () => {
    const started = await start();
    started.bff.gateway.on('POST', `/invoices/${INVOICE_ID}/payments`, (req, res) => {
      const replay = started.bff.gateway.requests.filter((request) => request.url === req.url).length > 1;
      sendJson(res, replay ? 200 : 201, { outcome: replay ? 'duplicate' : 'accepted' }, replay ? { 'Idempotent-Replay': 'true' } : {});
    });
    const post = () => started.bff.fetch(`/api/invoices/${INVOICE_ID}/payments`, { method: 'POST', headers: { cookie: started.cookie, 'Content-Type': 'application/json' }, body: payment(29, 'EUR') });
    const first = await post();
    const second = await post();
    expect([first.status, await first.json(), first.headers.get('idempotent-replay')]).toEqual([201, { outcome: 'accepted' }, null]);
    expect([second.status, await second.json(), second.headers.get('idempotent-replay')]).toEqual([200, { outcome: 'duplicate' }, 'true']);
  });
});
