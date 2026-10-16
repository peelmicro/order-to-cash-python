// Acceptance item 4 — "every error shown is that error's own problem-document text" — tested as BEHAVIOUR.
//
// This file knows nothing about how a page renders an error:
//   1. the pages come from the FILESYSTEM (src/app/testing/page-sweep.ts), globbed and walked;
//   2. each page is rendered through the real file router (layout chain, guard) and every request it makes
//      is OBSERVED at the API seam;
//   3. each observed request is failed in turn with every status openapi.yaml declares for its operation
//      (plus the BFF-local ones), once with a problem whose `detail` is a unique sentinel and once with `detail`
//      ABSENT and the sentinel as `title`, and the rendered text must contain the sentinel;
//   4. requests that follow a user action are reached by the scripts in ACTIONS;
//   5. the text a failing run ADDS, minus the text containing the sentinel, must be a subset of the reviewed
//      LABELS (the claim's second half: never a generic message), checked both ways;
//   6. every expected set below is a literal; everything else is derived by subtraction.
// Stages add a page by adding entries to EXPECTED_PAGES / EXPECTED_LOAD (and to ACTIONS for a mutation or an interaction-gated read).
import { readdirSync, readFileSync } from 'node:fs';
import { fireEvent, screen, within } from '@testing-library/dom';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { QUERY_RETRY_DELAY_MS } from './session/signed-out';
import type { TimerRequest } from './testing/page-sweep';
import { EXPECTED_NUMBER_BOX_IDS } from './testing/number-boxes';
import {
  addedTexts, buttonNamed, byLabel, choose, failureStatuses, kindOf, LATE_WATCH_MS, NONCE, newTexts, PAGE_FILES, pageFilesOnDisk, PAGES_DIR, PARAM_VALUES, PENDING_DETAIL, runPage, sentinel, typeInto, urlOf, WEB_ONLY_STATUSES, WEB_ROOT,
  type ActionScript, type PageKind, type Run, type Variant, issuedSentinels,
} from './testing/page-sweep';

const SWEEP_TIMEOUT = 240_000;

// ── Literal, reviewed lists ────────────────────────────────────────────────

/** Every file under src/app/pages and what it is. A file not listed here (a new page) fails the sweep by name. */
const EXPECTED_PAGES: Record<string, PageKind> = {
  '(app).page.ts': 'layout',
  '(app)/billing/index.page.ts': 'page',
  '(app)/orders/[id].page.ts': 'page',
  '(app)/orders/index.page.ts': 'page',
  '(app)/orders/place.page.ts': 'page',
  '(app)/stock/index.page.ts': 'page',
  'index.page.ts': 'redirect',
  'login.page.ts': 'page',
};

/** Where a redirect page ends up (signed in). */
const EXPECTED_REDIRECT: Record<string, string> = { '/': '/orders' };

const ORDER_URL = `/orders/${PARAM_VALUES['id']}`;
const ORDER_GET = `GET /api/orders/${PARAM_VALUES['id']}`;

/**
 * The requests each page makes on load, as last reviewed. This is NOT where the sweep's population comes from
 * (that is observed); it is the check that observation still sees what it saw.
 */
const EXPECTED_LOAD: Record<string, string[]> = {
  '/login': [],
  '/billing': ['GET /api/auth/session', 'GET /api/credits?page=1&pageSize=20', 'GET /api/invoices?page=1&pageSize=20'],
  '/stock': ['GET /api/auth/session', 'GET /api/catalog/products', 'GET /api/stock?page=1&pageSize=20'],
  '/orders': ['GET /api/auth/session', 'GET /api/catalog/companies', 'GET /api/catalog/retailers', 'GET /api/orders?page=1&pageSize=20'],
  '/orders/place': ['GET /api/auth/session', 'GET /api/catalog/companies', 'GET /api/catalog/products', 'GET /api/catalog/retailers'],
  [ORDER_URL]: ['GET /api/auth/session', ORDER_GET],
};

/**
 * The event streams each page opens, as last reviewed (one per page, aimed at this origin's proxy). An `EventSource` has no response body to
 * read a problem from, so a stream is NOT swept like a request: see STREAM_EXCEPTIONS.
 */
const EXPECTED_STREAMS: Record<string, string[]> = {
  '/login': [],
  '/billing': [],
  '/stock': [],
  '/orders': [],
  '/orders/place': [],
  [ORDER_URL]: [`/api/orders/stream?orderId=${PARAM_VALUES['id']}`],
};

/**
 * A stream's failure cannot be served as a problem document (EventSource exposes no body, and a refusal is indistinguishable from a drop), so the
 * sweep does not fail it with a sentinel. What the user sees instead is a connection state in the page's fixed words (reviewed in LABELS-like
 * fashion by the page tests: order-detail.spec.ts "Connection lost" and the id 98 cases), and the question "why" is put to a request that can
 * answer it: the actions below refuse the stream and fail THAT request. (#8 RR3-3 listed its stream the same way.)
 */
const STREAM_EXCEPTIONS: Record<string, string> = {
  [`/api/orders/stream?orderId=${PARAM_VALUES['id']}`]:
    'EventSource has no response body: a refused stream shows the connection state, then re-asks through GET /api/orders/{id} (actions stream-refused and retry-connection), which is swept',
};

/** Types into a box and commits it, as a browser does on blur or Enter. */
const commit = (input: HTMLInputElement, value: string) => {
  typeInto(input, value);
  fireEvent.change(input);
};
const STOCK_GET = 'GET /api/stock?page=1&pageSize=20';
const CREDITS_GET = 'GET /api/credits?page=1&pageSize=20';
const INVOICES_GET = 'GET /api/invoices?page=1&pageSize=20';
const ORDER_LINK_GET = 'GET /api/orders?orderReference=ORD-000042&page=1&pageSize=1';
const PAYMENT_POST = `POST /api/invoices/10000000-0000-4000-8000-000000000027/payments`;

const refuseTheStream = async (m: { streams: Array<{ refuse(): void }> }) => m.streams[0]!.refuse();

/** One scripted user action per mutation the app can make, and per interaction-gated read. Every request an action causes is swept exactly like a load request. */
const ACTIONS: ActionScript[] = [
  {
    route: '/login',
    name: 'sign-in',
    run: async () => {
      typeInto(byLabel('Password'), 'secret');
      buttonNamed('Sign in').click();
    },
  },
  {
    route: '/orders',
    name: 'sign-out',
    run: async () => {
      buttonNamed('Log out').click();
    },
  },
  {
    route: '/orders',
    name: 'filter-by-status',
    run: async () => choose(byLabel('Status'), 'placed'),
  },
  {
    route: '/orders',
    name: 'filter-by-retailer',
    run: async () => choose(byLabel('Retailer'), 'CarrefourEs'),
  },
  {
    route: '/orders',
    name: 'filter-by-company',
    run: async () => choose(byLabel('Company'), 'IBERFOODS'),
  },
  {
    route: '/orders',
    name: 'filter-by-reference',
    run: async () => choose(byLabel('Reference'), 'ORD-000042'),
  },
  {
    route: '/orders',
    name: 'next-page',
    run: async () => buttonNamed('Next').click(),
  },
  {
    route: '/orders/place',
    name: 'place-order',
    run: async () => {
      choose(byLabel('Retailer'), 'CarrefourEs');
      choose(byLabel('Company'), 'IBERFOODS');
      choose(byLabel('Product'), 'PRD-0001');
      buttonNamed('Place order').click();
    },
  },
  // Stock (stage 3). A filter's text is committed by `change`, as a browser does on blur or Enter.
  { route: '/stock', name: 'filter-by-company', run: async () => commit(byLabel('Company'), 'IBERFOODS') },
  { route: '/stock', name: 'filter-by-product', run: async () => commit(byLabel('Product'), 'PRD-0001') },
  { route: '/stock', name: 'filter-low-stock', run: async () => void fireEvent.click(byLabel('Low stock only')) },
  { route: '/stock', name: 'next-page', run: async () => buttonNamed('Next').click() },
  // No request: it ends with the replenish form OPEN, so the control table samples the form's own controls (the `replenish` action ends on the outcome, where the form is gone).
  {
    route: '/stock',
    name: 'open-replenish',
    run: async (m) => {
      buttonNamed('Replenish PRD-0001 for IBERFOODS').click();
      await m.settle();
    },
  },
  {
    route: '/stock',
    name: 'replenish',
    run: async (m) => {
      buttonNamed('Replenish PRD-0001 for IBERFOODS').click();
      await m.settle();
      typeInto(byLabel('Units to add'), '100');
      buttonNamed('Add units').click();
    },
    // The success re-reads the list, which the load also read.
    repeats: [STOCK_GET],
  },
  // Billing (stage 3): two lists with a pager each, and Register payment.
  { route: '/billing', name: 'credits-filter-retailer', run: async () => commit(byLabel('Credit retailer'), 'CarrefourEs') },
  { route: '/billing', name: 'credits-filter-company', run: async () => commit(byLabel('Credit company'), 'IBERFOODS') },
  { route: '/billing', name: 'credits-next-page', run: async () => within(screen.getByTestId('credits-pager')).getByRole('button', { name: 'Next (Credits pagination)' }).click() },
  { route: '/billing', name: 'invoices-filter-status', run: async () => choose(byLabel('Invoice status'), 'issued') },
  { route: '/billing', name: 'invoices-filter-retailer', run: async () => commit(byLabel('Invoice retailer'), 'CarrefourEs') },
  { route: '/billing', name: 'invoices-filter-company', run: async () => commit(byLabel('Invoice company'), 'IBERFOODS') },
  { route: '/billing', name: 'invoices-filter-order', run: async () => commit(byLabel('Invoice order reference'), 'ORD-000042') },
  { route: '/billing', name: 'invoices-filter-age', run: async () => commit(byLabel('Issued at least (minutes) ago'), '90') },
  { route: '/billing', name: 'invoices-next-page', run: async () => within(screen.getByTestId('invoices-pager')).getByRole('button', { name: 'Next (Invoices pagination)' }).click() },
  {
    route: '/billing',
    name: 'register-payment',
    run: async (m) => {
      buttonNamed('Register payment INV-000027').click();
      await m.settle();
      buttonNamed('Submit payment').click();
    },
    // The success re-reads both lists (the payment releases credit), which the load also read; it also looks up the paid invoice's order by its reference (the order link, stage 4).
    repeats: [CREDITS_GET, INVOICES_GET],
  },
  { route: ORDER_URL, name: 'stream-refused', run: refuseTheStream, repeats: [ORDER_GET] },
  {
    route: ORDER_URL,
    name: 'retry-connection',
    run: async (m) => {
      m.streams[0]!.refuse();
      await m.settle();
      buttonNamed('Retry connection').click();
    },
    repeats: [ORDER_GET],
  },
  {
    route: ORDER_URL,
    name: 'check-now',
    answers: PENDING_DETAIL,
    run: async () => buttonNamed('Check now').click(),
    repeats: [ORDER_GET],
  },
];

/** The requests each action makes (beyond the page's own load, except the `repeats` it declares), as last reviewed. */
const EXPECTED_ACTION: Record<string, string[]> = {
  // Signing in lands on the order list, whose own reads join the action.
  '/login | sign-in': ['GET /api/catalog/companies', 'GET /api/catalog/retailers', 'GET /api/orders?page=1&pageSize=20', 'POST /api/auth/login'],
  '/orders | sign-out': ['POST /api/auth/logout'],
  '/orders | filter-by-status': ['GET /api/orders?page=1&pageSize=20&status=placed'],
  '/orders | filter-by-retailer': ['GET /api/orders?page=1&pageSize=20&retailerCode=CarrefourEs'],
  '/orders | filter-by-company': ['GET /api/orders?companyCode=IBERFOODS&page=1&pageSize=20'],
  '/orders | filter-by-reference': ['GET /api/orders?orderReference=ORD-000042&page=1&pageSize=20'],
  '/orders | next-page': ['GET /api/orders?page=2&pageSize=20'],
  '/orders/place | place-order': [ORDER_GET, 'POST /api/orders'],
  '/stock | filter-by-company': ['GET /api/stock?companyCode=IBERFOODS&page=1&pageSize=20'],
  '/stock | filter-by-product': ['GET /api/stock?page=1&pageSize=20&productCode=PRD-0001'],
  '/stock | filter-low-stock': ['GET /api/stock?belowThreshold=true&page=1&pageSize=20'],
  '/stock | next-page': ['GET /api/stock?page=2&pageSize=20'],
  '/stock | open-replenish': [],
  '/stock | replenish': [STOCK_GET, 'POST /api/stock/replenish'],
  '/billing | credits-filter-retailer': ['GET /api/credits?page=1&pageSize=20&retailerCode=CarrefourEs'],
  '/billing | credits-filter-company': ['GET /api/credits?companyCode=IBERFOODS&page=1&pageSize=20'],
  '/billing | credits-next-page': ['GET /api/credits?page=2&pageSize=20'],
  '/billing | invoices-filter-status': ['GET /api/invoices?page=1&pageSize=20&status=issued'],
  '/billing | invoices-filter-retailer': ['GET /api/invoices?page=1&pageSize=20&retailerCode=CarrefourEs'],
  '/billing | invoices-filter-company': ['GET /api/invoices?companyCode=IBERFOODS&page=1&pageSize=20'],
  '/billing | invoices-filter-order': ['GET /api/invoices?orderReference=ORD-000042&page=1&pageSize=20'],
  '/billing | invoices-filter-age': ['GET /api/invoices?issuedBeforeMinutes=90&page=1&pageSize=20'],
  '/billing | invoices-next-page': ['GET /api/invoices?page=2&pageSize=20'],
  '/billing | register-payment': [CREDITS_GET, INVOICES_GET, ORDER_LINK_GET, PAYMENT_POST],
  [`${ORDER_URL} | stream-refused`]: [ORDER_GET],
  [`${ORDER_URL} | retry-connection`]: [ORDER_GET],
  [`${ORDER_URL} | check-now`]: [ORDER_GET],
};

/** Where each action ends when it succeeds. */
const EXPECTED_AFTER_ACTION: Record<string, string> = {
  '/login | sign-in': '/orders',
  '/orders | sign-out': '/login',
  '/orders | filter-by-status': '/orders',
  '/orders | filter-by-retailer': '/orders',
  '/orders | filter-by-company': '/orders',
  '/orders | filter-by-reference': '/orders',
  '/orders | next-page': '/orders',
  '/orders/place | place-order': ORDER_URL,
  '/stock | filter-by-company': '/stock',
  '/stock | filter-by-product': '/stock',
  '/stock | filter-low-stock': '/stock',
  '/stock | next-page': '/stock',
  '/stock | open-replenish': '/stock',
  '/stock | replenish': '/stock',
  '/billing | credits-filter-retailer': '/billing',
  '/billing | credits-filter-company': '/billing',
  '/billing | credits-next-page': '/billing',
  '/billing | invoices-filter-status': '/billing',
  '/billing | invoices-filter-retailer': '/billing',
  '/billing | invoices-filter-company': '/billing',
  '/billing | invoices-filter-order': '/billing',
  '/billing | invoices-filter-age': '/billing',
  '/billing | invoices-next-page': '/billing',
  '/billing | register-payment': '/billing',
  [`${ORDER_URL} | stream-refused`]: ORDER_URL,
  [`${ORDER_URL} | retry-connection`]: ORDER_URL,
  [`${ORDER_URL} | check-now`]: ORDER_URL,
};

/**
 * The ONLY text a failure may add besides the problem's own words (the claim's other half: never a generic message). Each is a label that
 * frames the problem text, or help that stays true whatever the problem says. Checked both ways, and both ways behaviourally: a text a failing run
 * adds that is not here fails the run, and a label here that NO failing run produces fails "every reviewed label is produced" (stale).
 */
const LABELS: Record<string, string> = {
  'Retailer filter unavailable': 'frames the retailer filter\'s own failure text on the orders list',
  'Company filter unavailable': 'frames the company filter\'s own failure text on the orders list',
  'You can still type the codes by hand.': 'true whatever the catalogue problem says: the place-order form falls back to text inputs',
  'The order link could not be resolved': 'frames the order lookup\'s own failure text after a payment (the link to the paid invoice\'s order; stage 4)',
  'Product names unavailable': 'frames the catalogue read\'s own failure text on the stock page (#8 id 101: the table stays, its rows fall back to their codes)',
};

/**
 * Texts a failing run adds because of the FIXTURES, not because of any wording the app chose (stage 3 review A7): a stock row whose product the failed catalogue read cannot name shows its
 * code alone, once (id 101), and the code is fixture data. Kept apart from LABELS so that a label is always app wording; checked the same way (a text no failing run produces is stale).
 */
const FIXTURE_TEXTS: Record<string, string> = {
  'PRD-0001': 'the stock row of a product the failed catalogue read cannot name: its code alone, once (id 101); the fixture\'s name contains no code',
};
const REVIEWED_TEXTS: Record<string, string> = { ...LABELS, ...FIXTURE_TEXTS };

/**
 * `route | load-or-action | request` whose failure is legitimately NOT shown, with the reason. If one starts
 * showing its sentinel, the entry is stale and the sweep says so. None today.
 */
const NOT_SHOWN: Record<string, string> = {};

/**
 * Every Angular construct that makes a request or gates one, per source file, as last reviewed (counted by content,
 * non-test files outside src/app/ui and src/app/testing). A new consumer changes a line here, and must then be
 * scripted in ACTIONS (a mutation or an interaction-gated read) or reached by a page load (a query) before this list is updated.
 */
const REQUEST_UNITS: Record<string, Record<string, number>> = {
  'orders/catalog.ts': { queryOptions: 3 },
  'pages/(app).page.ts': { injectQuery: 1, injectMutation: 1 },
  'pages/(app)/orders/[id].page.ts': { injectQuery: 1 },
  'pages/(app)/orders/index.page.ts': { injectQuery: 3 },
  'pages/(app)/orders/place.page.ts': { injectQuery: 3, injectMutation: 1 },
  'pages/(app)/billing/index.page.ts': { injectQuery: 3, injectMutation: 1, 'enabled:': 1 },
  'pages/(app)/stock/index.page.ts': { injectQuery: 2, injectMutation: 1 },
  'pages/login.page.ts': { injectMutation: 1 },
  'session/session.ts': { fetchQuery: 1, queryOptions: 1 },
};

/**
 * Every call of an `ApiClient` method, per source file, as last reviewed (stage 4 audit; `REQUEST_UNITS` counts the query constructs, which cannot see a SECOND call inside one `queryFn`). Each method is
 * paired with the request it makes; the premise below requires that request to be observed by some baseline run (a page load or a scripted action), and so to have been failed with every status of
 * its operation. `orderStream` is not a request: it opens an `EventSource` (STREAM_EXCEPTIONS).
 */
const API_CALL_SITES: Record<string, Record<string, number>> = {
  'orders/catalog.ts': { catalogCompanies: 1, catalogProducts: 1, catalogRetailers: 1 },
  'pages/(app).page.ts': { logout: 1 },
  'pages/(app)/billing/index.page.ts': { listCredits: 1, listInvoices: 1, listOrders: 1, registerPayment: 1 },
  'pages/(app)/orders/[id].page.ts': { getOrder: 1, orderStream: 1 },
  'pages/(app)/orders/index.page.ts': { listOrders: 1 },
  'pages/(app)/orders/place.page.ts': { placeOrder: 1 },
  'pages/(app)/stock/index.page.ts': { listStock: 1, replenishStock: 1 },
  'pages/login.page.ts': { login: 1 },
  'session/session.ts': { session: 1 },
};
/** The request (method and path, as the seam sees it) each ApiClient method makes. */
const API_METHOD_REQUESTS: Record<string, RegExp | null> = {
  catalogCompanies: /^GET \/api\/catalog\/companies$/,
  catalogProducts: /^GET \/api\/catalog\/products$/,
  catalogRetailers: /^GET \/api\/catalog\/retailers$/,
  getOrder: /^GET \/api\/orders\/[^/?]+$/,
  listCredits: /^GET \/api\/credits$/,
  listInvoices: /^GET \/api\/invoices$/,
  listOrders: /^GET \/api\/orders$/,
  listStock: /^GET \/api\/stock$/,
  login: /^POST \/api\/auth\/login$/,
  logout: /^POST \/api\/auth\/logout$/,
  orderStream: null,
  placeOrder: /^POST \/api\/orders$/,
  registerPayment: /^POST \/api\/invoices\/[^/]+\/payments$/,
  replenishStock: /^POST \/api\/stock\/replenish$/,
  session: /^GET \/api\/auth\/session$/,
};

/** Every timer-like construct in the source (by content), as last reviewed. The measured timers of every baseline run are checked separately. */
const TIMERS: Record<string, string[]> = {
  'lib/order-detail.ts': ['interval'],
  'pages/(app)/orders/[id].page.ts': ['interval', 'refetchInterval'],
  'pages/(app)/orders/index.page.ts': ['refetchInterval'],
  'session/signed-out.ts': ['retryDelay'],
};

/**
 * The timers longer than the late watch that a page's run may legitimately request, each by what it is (the delay is a measured fact of the run,
 * the class is the reviewed reason). A timer longer than LATE_WATCH_MS that is in no class could fire a request the watch would never see.
 * A class explains the timers TanStack Query's core asks for, and no other (the harness records who asked): a timer the app's own code requests, longer than the watch, is in no class and fails until it has an entry of its own.
 * `staleTime` timers are `staleTime - age + 1`, hence the range; the reviewed staleTimes are the client default (2 s), the session probe (30 s) and the catalogue (60 s).
 */
const REVIEWED_STALE_TIMES_MS = [2_000, 30_000, 60_000];
/** A long timer is explained only when TanStack Query's own timeout manager asked for it (measured: every long timer of every baseline run). An app timer, or another library's, is in no class. */
const fromQueryCore = (t: TimerRequest) => t.origin === 'library' && /\/node_modules\/@tanstack\/query-core\//.test(t.askedBy);
const LONG_TIMER_CLASSES: Array<{ name: string; matches: (timer: TimerRequest) => boolean; reason: string }> = [
  { name: 'gcTime', matches: (t) => fromQueryCore(t) && t.kind === 'setTimeout' && t.delay === 300_000, reason: 'TanStack Query removes an unobserved cache entry after gcTime (5 min default): no request' },
  { name: 'staleTime', matches: (t) => fromQueryCore(t) && t.kind === 'setTimeout' && REVIEWED_STALE_TIMES_MS.some((stale) => t.delay >= stale - 2_000 && t.delay <= stale + 1), reason: 'the observer re-renders a query as stale when staleTime passes: no request by itself' },
  { name: 'poll', matches: (t) => fromQueryCore(t) && t.kind === 'setInterval' && t.delay === 5_000, reason: 'refetchInterval of the order list and the live order page: repeats a key already observed' },
];

/** Mutation sites and the scripted action that reaches each. */
const MUTATION_COVERAGE: Record<string, string> = {
  'pages/login.page.ts': '/login | sign-in',
  'pages/(app).page.ts': '/orders | sign-out',
  'pages/(app)/orders/place.page.ts': '/orders/place | place-order',
  'pages/(app)/billing/index.page.ts': '/billing | register-payment',
  'pages/(app)/stock/index.page.ts': '/stock | replenish',
};

// ── The reviewed table of controls ─────────────────────────────────────────

/**
 * Every control (button, field, link) a user can operate on each route, in ANY state the sweep reaches (the load, and the end of each scripted action),
 * as `tag:name`, each classified: `request: <action>` (the action in ACTIONS that causes the request) or `no request: <reason>`. A control derived from
 * the rendered page and absent here, an entry no page renders, or a `request:` naming no action, fails the sweep: an interaction-gated read (a filter,
 * a "load more") cannot be added without being scripted or explicitly reviewed. (#8 RR3 D3 a.)
 */
const CONTROLS: Record<string, Record<string, string>> = {
  '/login': {
    'button:Sign in': 'request: /login | sign-in',
    'input:Password': 'no request: a field; the sign-in action types it',
    'input:Username': 'no request: a field',
  },
  '/orders': {
    'a:/billing': 'no request: navigation to the billing page',
    'a:/stock': 'no request: navigation to the stock page',
    'a:/orders': 'no request: the navigation to the page already open',
    'a:/orders/:id': 'no request: a row link; the order page is swept as its own page',
    'a:/orders/place': 'no request: navigation to the place-order page',
    'button:Log out': 'request: /orders | sign-out',
    'button:Next': 'request: /orders | next-page',
    'button:Previous': 'request: /orders | next-page (same query kind; page 1 is the load key)',
    'input:Reference': 'request: /orders | filter-by-reference',
    'select:Company': 'request: /orders | filter-by-company',
    'select:Retailer': 'request: /orders | filter-by-retailer',
    'select:Status': 'request: /orders | filter-by-status',
  },
  '/orders/place': {
    'a:/billing': 'no request: navigation to the billing page',
    'a:/stock': 'no request: navigation to the stock page',
    'a:/orders': 'no request: navigation',
    'button:Add line': 'no request: local state',
    'button:Fill demo order (.99 → compensation)': 'no request: local state',
    'button:Log out': 'request: /orders | sign-out',
    'button:Place order': 'request: /orders/place | place-order',
    'button:Remove line 1': 'no request: local state',
    // The manual-entry fallback inputs (Retailer, Company, Product as text) exist only while a catalogue read is failing; failing runs are not control-sampled.
    'input:Currency': 'no request: a field',
    'input:Line discount': 'no request: a field',
    'input:Notes': 'no request: a field',
    'input:Quantity': 'no request: a field',
    'input:Unit price override': 'no request: a field',
    'select:Company': 'no request: a choice; the place-order action makes it',
    'select:Product': 'no request: a choice; the place-order action makes it',
    'select:Retailer': 'no request: a choice; the place-order action makes it',
  },
  '/billing': {
    'a:/billing': 'no request: the navigation to the page already open',
    'a:/orders': 'no request: navigation',
    'a:/orders/:id': 'no request: the link to the paid invoice\'s order; the order page is swept as its own page',
    'a:/stock': 'no request: navigation',
    'button:Log out': '/orders | sign-out is scripted on /orders; the same shell button',
    'button:Next (Credits pagination)': 'request: /billing | credits-next-page',
    'button:Next (Invoices pagination)': 'request: /billing | invoices-next-page',
    'button:Previous (Credits pagination)': 'request: /billing | credits-next-page (same query kind; page 1 is the load key)',
    'button:Previous (Invoices pagination)': 'request: /billing | invoices-next-page (same query kind; page 1 is the load key)',
    'button:Register payment INV-000027': 'request: /billing | register-payment',
    'button:Register payment INV-000028': 'request: /billing | register-payment (the same action on another row)',
    'button:Register payment INV-000029': 'request: /billing | register-payment (the same action on another row)',
    'button:Register payment INV-000030': 'request: /billing | register-payment (the same action on another row)',
    'button:Submit payment': 'request: /billing | register-payment',
    'button:Close': 'no request: closes the panel',
    'input:Amount': 'no request: a field; the register-payment action submits it',
    'input:Credit company': 'request: /billing | credits-filter-company',
    'input:Credit retailer': 'request: /billing | credits-filter-retailer',
    'input:Invoice company': 'request: /billing | invoices-filter-company',
    'input:Invoice order reference': 'request: /billing | invoices-filter-order',
    'input:Invoice retailer': 'request: /billing | invoices-filter-retailer',
    'input:Issued at least (minutes) ago': 'request: /billing | invoices-filter-age',
    'input:Payment reference': 'no request: a field; the register-payment action submits it',
    'select:Invoice status': 'request: /billing | invoices-filter-status',
  },
  '/stock': {
    'a:/billing': 'no request: navigation',
    'a:/orders': 'no request: navigation',
    'a:/stock': 'no request: the navigation to the page already open',
    'button:Add units': 'request: /stock | replenish',
    'button:Cancel': 'no request: closes the panel',
    'button:Close': 'no request: closes the panel',
    'button:Log out': '/orders | sign-out is scripted on /orders; the same shell button',
    'button:Next': 'request: /stock | next-page',
    'button:Previous': 'request: /stock | next-page (same query kind; page 1 is the load key)',
    'button:Replenish PRD-0001 for IBERFOODS': 'request: /stock | replenish',
    'button:Replenish PRD-0007 for IBERFOODS': 'request: /stock | replenish (the same action on another row)',
    'button:Replenish PRD-0999 for IBERFOODS': 'request: /stock | replenish (the same action on another row)',
    'input:Company': 'request: /stock | filter-by-company',
    'input:Low stock only': 'request: /stock | filter-low-stock',
    'input:Product': 'request: /stock | filter-by-product',
    'input:Units to add': 'no request: a field; the replenish action submits it',
  },
  [ORDER_URL]: {
    'a:/billing': 'no request: navigation to the billing page',
    'a:/stock': 'no request: navigation to the stock page',
    'a:#timeline-entry-:id': 'no request: scrolls to an entry of the same page',
    'a:/orders': 'no request: navigation',
    'button:Check now': `request: ${ORDER_URL} | check-now`,
    'button:Log out': '/orders | sign-out is scripted on /orders; the same shell button',
    'button:Retry connection': `request: ${ORDER_URL} | retry-connection`,
  },
};

// ── Helpers ────────────────────────────────────────────────────────────────

const pages = PAGE_FILES.filter((file) => file.rel in EXPECTED_PAGES && EXPECTED_PAGES[file.rel] === 'page');
const byUrl = (url: string) => pages.find((file) => file.url === url)!;
const actionKey = (action: ActionScript) => `${action.route} | ${action.name}`;
const notShownKey = (route: string, phase: string, request: string) => `${route} | ${phase} | ${request}`;
const baselines = new Map<string, Run>();

async function baseline(url: string, action?: ActionScript): Promise<Run> {
  const cacheKey = `${url}|${action?.name ?? ''}`;
  let run = baselines.get(cacheKey);
  if (!run) {
    run = await runPage(url, { action, watchLate: true });
    baselines.set(cacheKey, run);
  }
  return run;
}

/** The requests an action causes: those the load did not make, plus the ones it is declared to repeat (a retry re-reads the order). */
async function actionKeysOf(action: ActionScript): Promise<string[]> {
  const loadKeys = new Set((await baseline(action.route)).load);
  const run = await baseline(action.route, action);
  return run.action.filter((key) => !loadKeys.has(key) || (action.repeats ?? []).includes(key));
}

const trimmed = (text: string) => text.replace(/^[\s\p{P}]+|[\s\p{P}]+$/gu, '');

/**
 * The added texts that are neither the problem's own words nor a reviewed label, and the labels these texts used. Angular renders `Static {{ value }}` as
 * ONE text node, so a node that contains the sentinel is not exempt as a whole: the sentinel is removed and what remains (trimmed of whitespace and
 * punctuation) must be empty or a reviewed label. (A node without the sentinel must itself be a reviewed label.)
 */
function classify(texts: string[], sentinelText: string): { unreviewed: string[]; used: string[] } {
  const unreviewed: string[] = [];
  const used = new Set<string>();
  const reviewed = new Map(Object.keys(REVIEWED_TEXTS).map((label) => [trimmed(label), label] as const));
  for (const text of texts) {
    if (!text.includes(sentinelText)) {
      if (text in REVIEWED_TEXTS) used.add(text);
      else unreviewed.push(text);
      continue;
    }
    const remainder = trimmed(text.split(sentinelText).join(''));
    if (remainder === '') continue;
    const label = reviewed.get(remainder);
    if (label) used.add(label);
    else unreviewed.push(text);
  }
  return { unreviewed, used: [...used] };
}
const labelled = (texts: string[], sentinelText: string) => classify(texts, sentinelText).unreviewed;

/**
 * The reviewed fixture texts a failing run ends with that the baseline's FINAL page does not have. This is deliberately not `addedTexts`: that compares with every text the baseline ever showed, and a
 * baseline whose stock list lands a tick before its catalogue shows the bare code `PRD-0001` for a moment before the names arrive (the order of two answers, not a property of the page), which would
 * make the failing runs "add nothing" and the staleness check fail on timing alone (stage 4 follow-up 2, measured with a held catalogue answer). The "extra text" check keeps using the wider set: it can only be more lenient.
 */
function fixtureTextsShown(run: Run, base: Run): string[] {
  return run.texts.filter((text, index) => text in FIXTURE_TEXTS && !base.texts.includes(text) && run.texts.indexOf(text) === index);
}

interface Outcome {
  /** A description of what the user saw instead of the problem's words, or `undefined` when the sentinel was shown with only reviewed labels beside it. */
  failure?: string;
  /** The reviewed labels this failing run produced. */
  used: string[];
  /** The `data-testid` of every number box this failing run rendered at any moment (the render half of the number-box guard reads the failure states too). */
  boxes?: string[];
}
const outcomes = new Map<string, Outcome>();

/** What one failing run showed, judged against its baseline (pure, so the unit test below can feed it a baseline that was caught mid-render). */
function judge(where: string, run: Run, base: Run, text: string): Outcome {
  if (run.renderError) return { failure: `${where} | the page crashed: ${run.renderError}`, used: [] };
  if (!run.text.includes(text)) return { failure: `${where} | expected "${text}" | shown instead: ${newTexts(run, base)}`, used: [] };
  const classified = classify(addedTexts(run, base), text);
  const used = [...new Set([...classified.used, ...fixtureTextsShown(run, base)])];
  return classified.unreviewed.length ? { failure: `${where} | text beside the problem's words that is not a reviewed label: ${JSON.stringify(classified.unreviewed)}`, used } : { used };
}

/** One failing run: fail `key` at `status` in the given variant and phase. Memoised, so the label-staleness premise can ask for every run without repeating one. */
async function failOne(route: string, variant: Variant, phase: 'load' | 'action', key: string, status: number, base: Run, action?: ActionScript): Promise<Outcome> {
  const memo = `${route}|${action?.name ?? ''}|${phase}|${variant}|${key}|${status}`;
  const known = outcomes.get(memo);
  if (known) return known;
  const text = sentinel(variant);
  const run = await runPage(route, { action, fail: { phase, key, variant, text, status }, watchLate: false });
  const where = `${route} | ${phase}${action ? ` ${action.name}` : ''} | ${key} -> ${status} | ${variant}`;
  const outcome = judge(where, run, base, text);
  outcome.boxes = run.numberBoxes;
  outcomes.set(memo, outcome);
  return outcome;
}

/** One sweep: fail each key of `keys` at each declared status, in the given variant; returns the failures, described. */
async function sweep(route: string, variant: Variant, phase: 'load' | 'action', keys: string[], base: Run, action?: ActionScript): Promise<string[]> {
  const failures: string[] = [];
  for (const key of keys) {
    if (notShownKey(route, phase, key) in NOT_SHOWN) continue;
    for (const status of failureStatuses(key, route)) {
      const outcome = await failOne(route, variant, phase, key, status, base, action);
      if (outcome.failure) failures.push(outcome.failure);
    }
  }
  return failures;
}

// ── The page population ────────────────────────────────────────────────────

describe('the page population is the filesystem', () => {
  it('the router glob and a directory walk of src/app/pages see the same files', () => {
    const onDisk = pageFilesOnDisk();
    expect(onDisk.length, 'the disk walk found nothing: it is not reading src/app/pages').toBeGreaterThanOrEqual(6);
    const globbed = PAGE_FILES.map((file) => file.rel);
    expect({ onDiskNotGlobbed: onDisk.filter((rel) => !globbed.includes(rel)), globbedNotOnDisk: globbed.filter((rel) => !onDisk.includes(rel)) }).toEqual({ onDiskNotGlobbed: [], globbedNotOnDisk: [] });
  });

  it('every page file is a `.page.ts`: no error / not-found / template convention hides UI the sweep would not render', () => {
    expect(pageFilesOnDisk().filter((rel) => !rel.endsWith('.page.ts'))).toEqual([]);
  });

  it('every file is listed in EXPECTED_PAGES with the kind it really has, and every entry names a file', async () => {
    const actual: Record<string, string> = {};
    for (const file of PAGE_FILES) actual[file.rel] = await kindOf(file);
    expect(actual, 'a page file the sweep has not been told about (or one whose kind changed)').toEqual(EXPECTED_PAGES);
  });

  it('every page has a reviewed load list and stream list, and no reviewed list names a page that no longer exists', () => {
    const urls = pages.map((file) => file.url);
    expect(urls.filter((url) => !(url in EXPECTED_LOAD)), 'pages with no EXPECTED_LOAD entry').toEqual([]);
    expect(Object.keys(EXPECTED_LOAD).filter((url) => !urls.includes(url)), 'EXPECTED_LOAD entries with no page').toEqual([]);
    expect(Object.keys(EXPECTED_STREAMS).sort(), 'EXPECTED_STREAMS must name exactly the swept pages').toEqual([...urls].sort());
    expect(Object.keys(CONTROLS).sort(), 'CONTROLS must name exactly the swept pages').toEqual([...urls].sort());
  });

  it('URLs are derived from file names by Analog\'s convention (groups vanish, index is the folder, [x] is a parameter)', () => {
    expect([urlOf('(app)/orders/index.page.ts'), urlOf('index.page.ts'), urlOf('login.page.ts'), urlOf('(app)/orders/[id].page.ts'), urlOf('(app)/orders/place.page.ts'), urlOf('(app)/stock/index.page.ts')]).toEqual([
      '/orders',
      '/',
      '/login',
      '/orders/9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f',
      '/orders/place',
      '/stock',
    ]);
    expect(() => urlOf('(app)/orders/[nope].page.ts')).toThrow(/PARAM_VALUES/);
  });

  it.each(Object.entries(EXPECTED_REDIRECT))('the redirect page %s ends at %s', async (from, to) => {
    const run = await runPage(from);
    expect(run.renderError).toBeUndefined();
    expect(run.finalUrl).toBe(to);
  });
});

// ── Pages: load ────────────────────────────────────────────────────────────

describe.each(pages.map((file) => [file.url, file.rel] as const))('%s (%s)', (url) => {
  it(
    'renders; its observed requests are the reviewed ones, all through the seam, all answered',
    async () => {
      const run = await baseline(url);
      expect(run.renderError, `${url} crashed while rendering`).toBeUndefined();
      expect(run.unrouted, `${url}: requests with no success body in page-sweep.ts`).toEqual([]);
      expect(run.bypasses, `${url}: requests that bypassed the API seam`).toEqual([]);
      expect(run.late, `${url}: requests that first started only after load had settled (watched for ${LATE_WATCH_MS} ms): review them before adding them to EXPECTED_LOAD`).toEqual([]);
      expect(run.load, `${url}: the requests observed on load differ from EXPECTED_LOAD`).toEqual(EXPECTED_LOAD[url] ?? ['(no EXPECTED_LOAD entry)']);
      expect(run.streams, `${url}: the event streams opened on load differ from EXPECTED_STREAMS`).toEqual(EXPECTED_STREAMS[url] ?? ['(no EXPECTED_STREAMS entry)']);
      expect(run.text.includes(NONCE), `${url}: the sentinel nonce is on screen before any failure`).toBe(false);
      expect(run.text.trim().length, `${url} rendered nothing`).toBeGreaterThan(0);
    },
    SWEEP_TIMEOUT,
  );

  it.each(['detail', 'title'] as const)(
    "shows each load request's failure as that problem's own %s",
    async (variant) => {
      const base = await baseline(url);
      const failures = await sweep(url, variant, 'load', base.load, base);
      if (failures.length) expect.fail(`${url}: load failures the user does not see in the problem's own words (route | phase | request -> status | variant | expected | shown instead):\n${failures.join('\n')}`);
    },
    SWEEP_TIMEOUT,
  );
});

// ── Actions ────────────────────────────────────────────────────────────────

describe.each(ACTIONS.map((action) => [actionKey(action), action] as const))('%s', (label, action) => {
  it(
    'runs; the requests it makes are the reviewed ones, all through the seam, all answered, and it ends where it should',
    async () => {
      const run = await baseline(action.route, action);
      expect(run.renderError, `${label} crashed`).toBeUndefined();
      expect(run.unrouted, `${label}: requests with no success body`).toEqual([]);
      expect(run.bypasses, `${label}: requests that bypassed the API seam`).toEqual([]);
      expect(run.late, `${label}: requests that first started only after the action settled`).toEqual([]);
      expect(await actionKeysOf(action), `${label}: the requests the action made differ from EXPECTED_ACTION`).toEqual(EXPECTED_ACTION[label] ?? ['(no EXPECTED_ACTION entry)']);
      expect(run.finalUrlAfterAction, `${label}: where the action ended`).toBe(EXPECTED_AFTER_ACTION[label]);
    },
    SWEEP_TIMEOUT,
  );

  it.each(['detail', 'title'] as const)(
    "shows each action request's failure as that problem's own %s",
    async (variant) => {
      const base = await baseline(action.route, action);
      const failures = await sweep(action.route, variant, 'action', await actionKeysOf(action), base, action);
      if (failures.length) expect.fail(`${label}: action failures the user does not see in the problem's own words (route | phase | request -> status | variant | expected | shown instead):\n${failures.join('\n')}`);
    },
    SWEEP_TIMEOUT,
  );
});

// ── The sweep's own premises ───────────────────────────────────────────────

function appSources(): string[] {
  const out: string[] = [];
  const src = path.join(WEB_ROOT, 'src', 'app');
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      const rel = path.relative(src, full).split(path.sep).join('/');
      if (entry.isDirectory()) {
        if (rel !== 'ui' && rel !== 'testing') walk(full);
      } else if (rel.endsWith('.ts') && !rel.endsWith('.spec.ts')) out.push(rel);
    }
  };
  walk(src);
  return out;
}

/** Every baseline run (each page's, each action's), computed on demand and cached: the premises below read the same observations the sweeps used. */
async function allBaselines(): Promise<Array<{ label: string; route: string; run: Run }>> {
  const out: Array<{ label: string; route: string; run: Run }> = [];
  for (const file of pages) out.push({ label: file.url, route: file.url, run: await baseline(file.url) });
  for (const action of ACTIONS) out.push({ label: actionKey(action), route: action.route, run: await baseline(action.route, action) });
  return out;
}

/**
 * Fails every key of every page and action at every declared status, in both variants (memoised: nothing runs twice). Returns the reviewed labels the failing runs produced AND the number
 * boxes they rendered: a failure state is a state the sweep reaches, and a box that exists only while a read has failed is a box (stage 3 re-review X1).
 */
async function failureSweep(): Promise<{ labels: Set<string>; boxes: Set<string>; runs: number }> {
  const produced = new Set<string>();
  const boxes = new Set<string>();
  let runs = 0;
  const note = (outcome: Outcome) => {
    runs += 1;
    for (const box of outcome.boxes ?? []) boxes.add(box);
    return outcome;
  };
  for (const file of pages) {
    const base = await baseline(file.url);
    for (const variant of ['detail', 'title'] as const) {
      for (const key of base.load) for (const status of failureStatuses(key, file.url)) for (const label of note(await failOne(file.url, variant, 'load', key, status, base)).used) produced.add(label);
    }
  }
  for (const action of ACTIONS) {
    const base = await baseline(action.route, action);
    for (const variant of ['detail', 'title'] as const) {
      for (const key of await actionKeysOf(action)) for (const status of failureStatuses(key, action.route)) for (const label of note(await failOne(action.route, variant, 'action', key, status, base, action)).used) produced.add(label);
    }
  }
  return { labels: produced, boxes, runs };
}

async function labelsProduced(): Promise<Set<string>> {
  return (await failureSweep()).labels;
}

describe("the sweep's premises", () => {
  it('every action is on a page the sweep renders, and every action has reviewed requests and an end', () => {
    for (const action of ACTIONS) {
      expect(pages.map((file) => file.url), `${actionKey(action)} is on a route that is not a swept page`).toContain(action.route);
      expect(Object.keys(EXPECTED_ACTION), `${actionKey(action)} has no EXPECTED_ACTION`).toContain(actionKey(action));
      expect(Object.keys(EXPECTED_AFTER_ACTION), `${actionKey(action)} has no EXPECTED_AFTER_ACTION`).toContain(actionKey(action));
    }
    expect(Object.keys(EXPECTED_ACTION).filter((k) => !ACTIONS.some((a) => actionKey(a) === k)), 'EXPECTED_ACTION entries with no action').toEqual([]);
    expect(new Set(ACTIONS.map(actionKey)).size, 'two actions share a name').toBe(ACTIONS.length);
  });

  it('every way to make a request, or gate one, is the reviewed one (by content)', () => {
    const constructs = ['injectQuery', 'injectMutation', 'queryOptions', 'fetchQuery', 'prefetchQuery', 'ensureQueryData', 'enabled:'];
    const found: Record<string, Record<string, number>> = {};
    for (const rel of appSources()) {
      const source = readFileSync(path.join(WEB_ROOT, 'src', 'app', rel), 'utf8');
      for (const construct of constructs) {
        const count = source.split(construct === 'enabled:' ? construct : `${construct}(`).length - 1;
        if (count) (found[rel] ??= {})[construct] = count;
      }
    }
    expect(found, 'a new consumer of the query client: script it in ACTIONS (a mutation or an interaction-gated read) or reach it from a page load (a query), then update REQUEST_UNITS').toEqual(REQUEST_UNITS);
  });

  it('every call of an ApiClient method is a reviewed one, and the request it makes is one a page load or scripted action drives (stage 4 audit)', async () => {
    const methods = Object.keys(API_METHOD_REQUESTS);
    const found: Record<string, Record<string, number>> = {};
    const mentioning: string[] = [];
    for (const rel of appSources()) {
      if (rel === 'api/api-client.ts') continue;
      const source = readFileSync(path.join(WEB_ROOT, 'src', 'app', rel), 'utf8');
      // A client held under another name (`const http = inject(ApiClient)`) would hide its calls from the pattern below, so the files that name the class are counted too.
      if (/\bApiClient\b/.test(source)) mentioning.push(rel);
      for (const match of source.matchAll(/\bapi\.([A-Za-z]+)\(/g)) { const counts = (found[rel] ??= {}); counts[match[1]!] = (counts[match[1]!] ?? 0) + 1; }
    }
    expect(found, 'a call of an ApiClient method that the audit has not classified: drive it from a page load or a scripted action, then add it here').toEqual(API_CALL_SITES);
    expect(mentioning.sort(), 'a file that names ApiClient but has no reviewed call site (or the reverse): its client may be held under another name').toEqual(Object.keys(API_CALL_SITES).sort());
    expect(Object.values(found).flatMap((counts) => Object.keys(counts)).filter((name) => !methods.includes(name)), 'a method with no request pairing').toEqual([]);
    const observed = new Set<string>();
    for (const { run } of await allBaselines()) for (const key of [...run.load, ...run.action]) observed.add(key.split('?')[0]!);
    const unobserved = [...new Set(Object.values(found).flatMap((counts) => Object.keys(counts)))].filter((name) => {
      const request = API_METHOD_REQUESTS[name];
      return request !== null && request !== undefined && ![...observed].some((key) => request.test(key));
    });
    expect(unobserved, 'ApiClient methods whose request no baseline run observes: the sweep never failed them').toEqual([]);
  }, SWEEP_TIMEOUT);

  it('no `fetch(` or `new EventSource(` outside the ApiClient (stage 4 audit)', () => {
    const hits: string[] = [];
    for (const rel of appSources()) {
      if (rel === 'api/api-client.ts') continue;
      const source = readFileSync(path.join(WEB_ROOT, 'src', 'app', rel), 'utf8');
      if (/\bfetch\(|new EventSource\(/.test(source)) hits.push(rel);
    }
    expect(hits).toEqual([]);
  });

  it('every mutation site belongs to a page with a scripted action', () => {
    const mutationSites = Object.entries(REQUEST_UNITS).filter(([, constructs]) => 'injectMutation' in constructs).map(([rel]) => rel);
    expect(mutationSites.filter((rel) => !(rel in MUTATION_COVERAGE)), 'mutation sites with no scripted action').toEqual([]);
    expect(Object.keys(MUTATION_COVERAGE).filter((rel) => !mutationSites.includes(rel)), 'MUTATION_COVERAGE entries that are not mutation sites').toEqual([]);
    expect(Object.values(MUTATION_COVERAGE).filter((k) => !ACTIONS.some((a) => actionKey(a) === k))).toEqual([]);
  });

  it('every control a user can operate is reviewed: scripted when it makes a request, explained when it does not; derived from the rendered pages, in every state the sweep reaches', async () => {
    const seen: Record<string, Set<string>> = {};
    // A control belongs to the page the run ENDED on (signing in ends on the order list; placing an order ends on the order page).
    for (const { run } of await allBaselines()) for (const control of run.controls) (seen[run.finalUrlAfterAction ?? run.finalUrl] ??= new Set()).add(control);
    const observed = Object.fromEntries(Object.entries(seen).map(([route, controls]) => [route, [...controls].sort()]));
    expect(Object.keys(observed).sort()).toEqual(Object.keys(CONTROLS).sort());
    const problems: string[] = [];
    for (const [route, reviewed] of Object.entries(CONTROLS)) {
      const live = observed[route] ?? [];
      for (const control of live) if (!(control in reviewed)) problems.push(`${route}: a control the sweep has not been told about: ${control}`);
      for (const control of Object.keys(reviewed)) if (!live.includes(control) && !control.startsWith('button:Log out')) problems.push(`${route}: a reviewed control no page state renders: ${control}`);
      for (const [control, how] of Object.entries(reviewed)) {
        const scripted = /^request: (.+?)(?: \(.*)?$/.exec(how)?.[1];
        if (scripted && !ACTIONS.some((action) => actionKey(action) === scripted)) problems.push(`${route}: ${control} says "${how}" but no such action exists`);
        if (!scripted && !how.startsWith('no request: ') && !how.includes(' is scripted on ')) problems.push(`${route}: ${control} has an unclassified entry: ${how}`);
      }
    }
    if (problems.length) expect.fail(`CONTROLS and the rendered pages disagree:\n${problems.join('\n')}`);
  }, SWEEP_TIMEOUT);

  it('every rendered number box is a reviewed one, and every reviewed box is rendered (the RENDER half of the number-box guard, src/app/number-boxes.spec.ts)', async () => {
    const all = await allBaselines();
    // Premise 1: every swept page has a baseline run, and every run mounted. A page that did not mount shows no boxes, and "no unreviewed box" would be vacuous.
    expect(pages.map((file) => file.url).filter((url) => !all.some((entry) => entry.label === url)), 'a swept page with no baseline run: its boxes were never looked at').toEqual([]);
    expect(all.filter((entry) => entry.run.renderError).map((entry) => entry.label), 'a state that did not mount: its boxes were never looked at').toEqual([]);
    // The failure states too: every failing run the label machinery already makes (memoised, so inside the whole file this costs nothing extra).
    const failures = await failureSweep();
    expect(failures.runs, 'no failing run was read: the failure states were never looked at').toBeGreaterThan(0);
    const rendered = new Set([...all.flatMap((entry) => entry.run.numberBoxes), ...failures.boxes]);
    const unreviewed = [...rendered].filter((id) => !EXPECTED_NUMBER_BOX_IDS.includes(id)).sort();
    // Premise 2: every form is opened. A reviewed box that no driven state renders means a script stopped opening the form that holds it (or the box vanished).
    const unrendered = EXPECTED_NUMBER_BOX_IDS.filter((id) => !rendered.has(id));
    if (unreviewed.length || unrendered.length) {
      expect.fail(`the number boxes the sweep sees differ from the reviewed set. Rendered (in a baseline state or in any failing run) but not reviewed (add to testing/number-boxes.ts with [appDraftValue] and a validity.badInput handler): ${JSON.stringify(unreviewed)}. Reviewed but rendered in no state the sweep drives (a script must open the form that holds it): ${JSON.stringify(unrendered)}`);
    }
  }, SWEEP_TIMEOUT * 4);

  it('every event stream a page opens is one the sweep has an exception for, and every exception is a stream a page opened', async () => {
    const opened = new Set<string>();
    for (const { run } of await allBaselines()) for (const url of run.streams) opened.add(url);
    expect([...opened].sort(), 'a stream with no STREAM_EXCEPTIONS entry (an EventSource has no response body: say why and where its failure is exercised)').toEqual(Object.keys(STREAM_EXCEPTIONS).sort());
  }, SWEEP_TIMEOUT);

  it('the late watch outlasts every non-poll timer the app sets (and the timers are the reviewed ones)', () => {
    const timerWords = /\b(setTimeout|setInterval|timer|interval|refetchInterval|retryDelay|debounceTime|delay|throttleTime)\b\s*[(:]/g;
    const found: Record<string, string[]> = {};
    for (const rel of appSources()) {
      const hits = [...new Set([...readFileSync(path.join(WEB_ROOT, 'src', 'app', rel), 'utf8').matchAll(timerWords)].map((m) => m[1]!))].sort();
      if (hits.length) found[rel] = hits;
    }
    if (JSON.stringify(found) !== JSON.stringify(TIMERS)) expect.fail(`a timer the late watch has not been checked against. Found: ${JSON.stringify(found)}\nReviewed: ${JSON.stringify(TIMERS)}`);
    expect(LATE_WATCH_MS).toBeGreaterThan(QUERY_RETRY_DELAY_MS);
  });

  it('the late watch is measured against the timers the runs REQUESTED: no timer longer than the watch is outside the reviewed classes (and each class was seen)', async () => {
    const requested: TimerRequest[] = [];
    for (const { run } of await allBaselines()) requested.push(...run.timers);
    expect(requested.length, 'no timer was observed at all: the probes in runPage are not installed').toBeGreaterThan(0);
    expect(requested.filter((timer) => timer.delay > 0 && timer.delay <= LATE_WATCH_MS).length, 'short timers (Angular scheduling, retry delay) must be observed too').toBeGreaterThan(0);
    const unreviewed = requested.filter((timer) => timer.delay > LATE_WATCH_MS && !LONG_TIMER_CLASSES.some((entry) => entry.matches(timer)));
    const named = [...new Set(unreviewed.map((timer) => `${timer.kind}(${timer.delay}) from ${timer.origin} code (${timer.creator}, ${timer.askedBy})`))];
    // The timers are written INTO the message (a reporter prints a deep-equal's diff separately): the failure must name the timer.
    if (named.length > 0) expect.fail(`timers longer than the ${LATE_WATCH_MS} ms late watch that no reviewed class explains (a request they fire would never be seen): ${JSON.stringify(named)}`);
    const unseen = LONG_TIMER_CLASSES.filter((entry) => !requested.some((timer) => entry.matches(timer))).map((entry) => entry.name);
    expect(unseen, 'reviewed timer classes no run requests (stale)').toEqual([]);
  }, SWEEP_TIMEOUT);

  it('every failure status the sweep serves comes from openapi.yaml (or a listed web-only route), and the web-only list names routes that exist', () => {
    expect(failureStatuses('POST /api/auth/login', '/login')).toEqual(expect.arrayContaining([400, 401, 429, 500]));
    expect(failureStatuses('POST /api/auth/login', '/login'), 'a declared status is missing, or one is invented').toEqual([400, 401, 429, 500, 502, 504]);
    expect(failureStatuses('GET /api/stock', '/stock'), '401 is excluded off /login').toEqual([500, 502, 503, 504]);
    expect(failureStatuses('GET /api/orders/abc', '/orders/abc'), 'the order read declares 404').toContain(404);
    expect(failureStatuses('POST /api/orders', '/orders/place'), 'placing an order declares 409 and 422').toEqual(expect.arrayContaining([400, 409, 422, 503]));
    expect(() => failureStatuses('GET /api/not-an-operation', '/x')).toThrow(/matches no operation/);
    for (const key of Object.keys(WEB_ONLY_STATUSES)) {
      const [method, route] = key.split(' ') as [string, string];
      const rel = `${route.replace(/^\//, '')}.${method.toLowerCase()}.ts`;
      expect(readdirSync(path.join(WEB_ROOT, 'src', 'server', 'routes', path.dirname(rel))), `${key} names no route file`).toContain(path.basename(rel));
    }
  });

  it('text sharing the problem\'s own text node is not exempt: only the sentinel plus whitespace or punctuation passes', () => {
    expect(labelled(['Something went wrong. SENT', 'SENT', ' SENT. ', '"SENT"', 'Try again: SENT', 'SENT (retry)'], 'SENT')).toEqual(['Something went wrong. SENT', 'Try again: SENT', 'SENT (retry)']);
    expect(labelled(['Unrelated line'], 'SENT'), 'a node without the sentinel must itself be a reviewed label').toEqual(['Unrelated line']);
    expect(classify(['Retailer filter unavailable: SENT', 'You can still type the codes by hand.'], 'SENT'), 'a reviewed label is accepted and reported as used').toEqual({ unreviewed: [], used: ['Retailer filter unavailable', 'You can still type the codes by hand.'] });
  });

  it('a fixture text is counted from the baseline\'s FINAL page, not from what it showed for a moment (stage 4 follow-up 2)', () => {
    const run = (texts: string[], everShown: string[] = texts) => ({ texts, everShown }) as Run;
    const failing = run(['PRD-0001', 'Product names unavailable: SENT']);
    // A baseline that showed the bare code before the names arrived: the wide comparison loses the text, the final-page comparison keeps it.
    const transient = run(['Olive oil 1 L', '(PRD-0001)'], ['PRD-0001', 'Olive oil 1 L', '(PRD-0001)']);
    expect(addedTexts(failing, transient), 'the instrument this replaces for the fixture texts').not.toContain('PRD-0001');
    expect(fixtureTextsShown(failing, transient)).toEqual(['PRD-0001']);
    // A baseline whose final page already shows the bare code adds nothing; a text that is not a reviewed fixture text is never counted; a repeat counts once.
    expect(fixtureTextsShown(failing, run(['PRD-0001']))).toEqual([]);
    expect(fixtureTextsShown(run(['PRD-0999', 'PRD-0001', 'PRD-0001']), run([]))).toEqual(['PRD-0001']);
    // Through the judgement the premise reads: the fixture text is "used" although the baseline caught it for a moment, and it is not reported as an unreviewed text either.
    const judged = judge('/stock | load | catalogue -> 500', { ...failing, text: 'PRD-0001 Product names unavailable: SENT', renderError: undefined } as Run, transient, 'SENT');
    expect(judged).toEqual({ used: expect.arrayContaining(['PRD-0001', 'Product names unavailable']) });
  });

  it('every reviewed label is produced by some failing run (a label no run produces is stale), and every NOT_SHOWN entry names something observed', async () => {
    const produced = await labelsProduced();
    expect(Object.keys(LABELS).filter((label) => !produced.has(label)), 'reviewed labels that no failing run produces: delete them or fix the page that stopped showing them').toEqual([]);
    const missingFixtureTexts = Object.keys(FIXTURE_TEXTS).filter((text) => !produced.has(text));
    const stockBase = missingFixtureTexts.length > 0 ? await baseline('/stock') : undefined;
    const stockBaseline = stockBase ? `${stockBase.texts.join(' | ')} (ever shown at any moment, among the fixture texts: ${JSON.stringify(stockBase.everShown.filter((t) => t in FIXTURE_TEXTS))})` : '';
    expect(missingFixtureTexts, `reviewed fixture texts that no failing run produces: delete them, or check the /stock baseline, which showed: ${stockBaseline}`).toEqual([]);
    expect([...produced].filter((label) => !(label in REVIEWED_TEXTS)), 'a label produced but not reviewed').toEqual([]);
    expect(Object.keys(LABELS).filter((label) => label in FIXTURE_TEXTS), 'a text is either app wording (LABELS) or fixture data (FIXTURE_TEXTS), never both').toEqual([]);
    const observed = new Set<string>();
    for (const { route, run } of await allBaselines()) for (const key of [...run.load, ...run.action]) for (const phase of ['load', 'action']) observed.add(notShownKey(route, phase, key));
    expect(Object.keys(NOT_SHOWN).filter((entry) => !observed.has(entry)), 'NOT_SHOWN entries that name no observed request').toEqual([]);
  }, SWEEP_TIMEOUT * 2);

  it('sentinels are unique, random, and cannot equal any text in the app', async () => {
    expect(new Set(issuedSentinels).size).toBe(issuedSentinels.length);
    expect(NONCE).toMatch(/^[0-9a-f]{12}$/);
    const sources = appSources().map((rel) => readFileSync(path.join(WEB_ROOT, 'src', 'app', rel), 'utf8')).join('\n');
    expect(sources.includes('sweep-')).toBe(false);
    expect(path.relative(WEB_ROOT, PAGES_DIR)).toBe('src/app/pages');
  });
});
