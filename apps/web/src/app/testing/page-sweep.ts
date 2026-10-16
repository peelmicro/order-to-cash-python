/// <reference types="vite/client" />
import { randomUUID } from 'node:crypto';
import { readdirSync } from 'node:fs';
import path from 'node:path';
import { TestBed } from '@angular/core/testing';
import { fireEvent, screen } from '@testing-library/dom';
import { vi } from 'vitest';
import { declaredOperations, operationFor } from '../../server/testing/openapi-statuses';
import { QUERY_RETRY_DELAY_MS } from '../session/signed-out';
import { json, mount, problemResponse, sleep, type Mounted } from './browser-harness';
import { COMPANIES, orderDetail, orderPage, PENDING, placeOrderResponse, PRODUCTS, RETAILERS } from './orders-fixtures';
import { creditPage, invoicePage, paymentAccepted, replenishResponse, stockPage } from './stock-billing-fixtures';

/**
 * The harness behind src/app/error-text.sweep.spec.ts (acceptance item 4): render every page the file
 * router has as the browser does, observe every request, fail each one in turn with a problem document
 * whose text is a unique sentinel, and read what the USER sees, the rendered text. Nothing here knows how a
 * page shows an error; it only knows what a page is. (A syntax guard over error sites was defeated by the
 * plainest shapes in #8's round 2 and replaced by exactly this; it is built first here, not after.)
 */

// ── The page population: the FILESYSTEM, twice ─────────────────────────────

export const WEB_ROOT = path.resolve(import.meta.dirname, '..', '..', '..');
export const PAGES_DIR = path.join(WEB_ROOT, 'src', 'app', 'pages');

const GLOB = import.meta.glob('/src/app/pages/**/*.page.ts');

export type PageKind = 'page' | 'layout' | 'redirect';

export interface PageFile {
  /** Relative to src/app/pages, e.g. `(app)/orders.page.ts`. */
  rel: string;
  /** The URL a browser opens it at, dynamic segments filled from PARAM_VALUES. */
  url: string;
  load: () => Promise<{ routeMeta?: { redirectTo?: string } }>;
}

/** A value for every dynamic segment a page may have. A segment with no value fails the sweep by name. */
export const PARAM_VALUES: Record<string, string> = { id: '9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f' };

/** Analog's file-name convention: `(group)` segments vanish, `index` is the folder itself, a dot is a slash, `[x]` is a parameter. */
export function urlOf(rel: string): string {
  const stem = rel.replace(/\.page\.ts$/, '');
  const segments = stem
    .split('/')
    .filter((segment) => !/^\(.*\)$/.test(segment))
    .flatMap((segment) => segment.split('.'))
    .filter((segment) => segment !== 'index' && segment !== '')
    .map((segment) => {
      const match = /^\[([^\].]+)\]$/.exec(segment);
      if (!match) return segment;
      const value = PARAM_VALUES[match[1]!];
      if (value === undefined) throw new Error(`sweep: no PARAM_VALUES entry for the dynamic segment "${segment}" in ${rel}: add one`);
      return value;
    });
  return `/${segments.join('/')}`;
}

export const PAGE_FILES: PageFile[] = Object.entries(GLOB)
  .map(([key, load]) => {
    const rel = key.replace(/^\/src\/app\/pages\//, '');
    return { rel, url: urlOf(rel), load: load as PageFile['load'] };
  })
  .sort((a, b) => a.rel.localeCompare(b.rel));

/** The same population read straight off the disk, to check the glob against. */
export function pageFilesOnDisk(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else out.push(path.relative(PAGES_DIR, full).split(path.sep).join('/'));
    }
  };
  walk(PAGES_DIR);
  return out.sort();
}

/** A page file is a layout when a folder of the same name sits beside it (`(app).page.ts` and `(app)/`). */
export function isLayout(rel: string): boolean {
  const folder = rel.replace(/\.page\.ts$/, '');
  return pageFilesOnDisk().some((other) => other.startsWith(`${folder}/`));
}

export async function kindOf(file: PageFile): Promise<PageKind> {
  if (isLayout(file.rel)) return 'layout';
  const module = await file.load();
  return module.routeMeta?.redirectTo ? 'redirect' : 'page';
}

// ── Sentinels ──────────────────────────────────────────────────────────────

/** Random per run, so no string in the app, a fallback or a label, can ever equal a sentinel. */
export const NONCE = randomUUID().replace(/-/g, '').slice(0, 12);
export const issuedSentinels: string[] = [];
let sentinelCount = 0;

export type Variant = 'detail' | 'title';

export function sentinel(variant: Variant): string {
  sentinelCount += 1;
  const value = `sweep-${NONCE}-${sentinelCount}-${variant}`;
  issuedSentinels.push(value);
  return value;
}

/**
 * A problem document shaped like a real Gateway one (same keys), with the sentinel as its `detail`
 * (variant `detail`) or, with `detail` ABSENT, as its `title` (variant `title`). The `detail` variant's
 * title is a decoy: a page that shows the title while a detail exists does not show the sentinel.
 */
export function problemBody(variant: Variant, text: string, status: number): Record<string, unknown> {
  const base = { type: 'about:blank', status, code: 'DOMAIN_ERROR', correlationId: '3f7b2f0e-6a52-4a4e-9d57-2f1d6a0f6a11', occurredAt: '2026-10-15T10:00:00.000Z' };
  return variant === 'detail' ? { ...base, title: `decoy-title-${NONCE}`, detail: text } : { ...base, title: text };
}

// ── Failure statuses ───────────────────────────────────────────────────────

/** Routes of THIS app with no Gateway operation behind them, and the failures each can answer. */
export const WEB_ONLY_STATUSES: Record<string, { statuses: number[]; reason: string }> = {
  'GET /api/auth/session': { statuses: [500], reason: 'the session probe makes no Gateway call (server/routes/api/auth/session.get.ts); it can only fail by an unhandled throw, which Nitro answers with 500' },
  'POST /api/auth/logout': { statuses: [500], reason: 'the logout route makes no Gateway call (server/routes/api/auth/logout.post.ts); it can only fail by an unhandled throw' },
};

/**
 * Failures the BFF itself answers for ANY proxied request, whatever the Gateway would have said: it could not reach the
 * Gateway (502) or the Gateway did not answer in time (504) (server/lib/gateway.ts `gatewayFailed`).
 */
export const BFF_LOCAL_STATUSES = [502, 504];

/**
 * The statuses a failing request is drawn as: every 4xx/5xx `openapi.yaml` declares for the Gateway operation
 * behind it (`default` drawn as 500), plus the BFF-local ones for a proxied route. 401 is left out except for the sign-in
 * request itself (a page the sign-in action merely navigates to is not `/login`): everywhere else the app's answer to a 401 is to leave for the sign-in page (session/signed-out.ts),
 * not to render text.
 */
export function failureStatuses(key: string, route: string): number[] {
  const [method, target] = key.split(' ') as [string, string];
  const apiPath = target.split('?')[0]!;
  const webOnly = WEB_ONLY_STATUSES[`${method} ${apiPath}`];
  let declared: number[];
  if (webOnly) declared = webOnly.statuses;
  else {
    const operation = operationFor(method, apiPath.replace(/^\/api/, ''));
    if (!operation) throw new Error(`sweep: ${key} matches no operation in openapi.yaml and is not in WEB_ONLY_STATUSES`);
    declared = [...operation.statuses, ...BFF_LOCAL_STATUSES];
  }
  const failing = [...new Set(declared)].filter((status) => status >= 400 && (status !== 401 || (route === '/login' && key === 'POST /api/auth/login'))).sort();
  if (failing.length === 0) throw new Error(`sweep: ${key} declares no failure status the sweep can serve on ${route}`);
  return failing;
}

export { declaredOperations };

/**
 * How long a baseline keeps watching after it has settled, for requests that start late. The longest NON-poll
 * timer the app sets is the query retry delay (session/signed-out.ts QUERY_RETRY_DELAY_MS); src/app/error-text.sweep.spec.ts
 * lists every timer in the source and fails if it finds one this window does not outlast. Polls only repeat
 * keys already observed, so they do not bound this.
 */
export const LATE_WATCH_MS = QUERY_RETRY_DELAY_MS + 500;

// ── Success answers ────────────────────────────────────────────────────────

const SESSION = { authenticated: true, username: 'operator', displayName: 'Order-To-Cash Operator', roles: ['operator'] };

export type Answer = (key: string, init: RequestInit | undefined) => Response;
type Success = [method: string, path: RegExp, answer: Answer];

/** The `page` the key asked for (`GET /api/orders?page=2&pageSize=20`), so a next-page action is answered with that page. */
const pageOf = (key: string) => Number(new URLSearchParams(key.split('?')[1] ?? '').get('page') ?? '1');

export const SUCCESS: Success[] = [
  ['GET', /^\/api\/auth\/session$/, () => json(SESSION)],
  ['POST', /^\/api\/auth\/login$/, () => json(SESSION)],
  ['POST', /^\/api\/auth\/logout$/, () => json({ authenticated: false })],
  // 45 orders at 20 per page: three pages, so "next page" exists on page 1 and the pager has a count to claim.
  ['GET', /^\/api\/orders$/, (key) => json(orderPage(pageOf(key), 20, 45, pageOf(key) === 3 ? 5 : 20))],
  ['POST', /^\/api\/orders$/, () => json(placeOrderResponse(), 201)],
  ['GET', /^\/api\/orders\/[^/]+$/, () => json(orderDetail())],
  ['GET', /^\/api\/catalog\/retailers$/, () => json({ items: RETAILERS })],
  ['GET', /^\/api\/catalog\/companies$/, () => json({ items: COMPANIES })],
  ['GET', /^\/api\/catalog\/products$/, () => json({ items: PRODUCTS })],
  // 45 rows at 20 per page for each of the three lists, as the orders list has: "next page" exists on page 1.
  ['GET', /^\/api\/stock$/, (key) => json(stockPage(pageOf(key)))],
  ['POST', /^\/api\/stock\/replenish$/, () => json(replenishResponse())],
  ['GET', /^\/api\/invoices$/, (key) => json(invoicePage(pageOf(key)))],
  ['POST', /^\/api\/invoices\/[^/]+\/payments$/, () => json(paymentAccepted(), 201)],
  ['GET', /^\/api\/credits$/, (key) => json(creditPage(pageOf(key)))],
];

/** Answers a script may substitute for a run, by request key (for example the detail page answering `202 ProjectionPending`). */
export const PENDING_DETAIL: Record<string, Answer> = { [`GET /api/orders/${PARAM_VALUES['id']}`]: () => json(PENDING, 202, { 'Retry-After': '1' }) };


// ── Timers, measured ────────────────────────────────────────────────────────

/** Where a timer was asked for, from the stack at the call. The harness's own sleeps (src/app/testing) are not the app's timers. */
function describeTimer(kind: TimerRequest['kind'], delay: unknown): TimerRequest | undefined {
  const frames = (new Error().stack ?? '').split('\n').slice(1).filter((frame) => !/\/src\/app\/testing\/page-sweep\.ts/.test(frame));
  // The harness's own waits (`sleep`, in browser-harness.ts) call setTimeout directly: the first frame OUTSIDE this probe is the harness. A timer a
  // library schedules while the harness merely drives change detection has a library frame first, and is the app's.
  if (/\/src\/app\/testing\//.test(frames[0] ?? '')) return undefined;
  // The ASKER is the first frame: a page that wraps or aliases `setTimeout` is still the frame that called it. (Any-frame-in-the-stack made every TanStack timer started from a page's `injectQuery` "app".)
  const origin = /\/src\/app\/(?!testing\/|ui\/)/.test(frames[0] ?? '') ? 'app' : 'library';
  const askedBy = /\(?([^()\s]+?)(?::\d+){2}\)?$/.exec(frames[0] ?? '')?.[1] ?? '(unknown)';
  const creator = frames.map((frame) => /at (?:new )?([\w.#$<>]+) /.exec(frame)?.[1]).find((name): name is string => name !== undefined) ?? '(anonymous)';
  return { kind, delay: Number.isFinite(Number(delay)) ? Number(delay) : 0, origin, creator, askedBy };
}

function installTimerProbes(sink: TimerRequest[]): void {
  const realSetTimeout = globalThis.setTimeout;
  const realSetInterval = globalThis.setInterval;
  const realAbortTimeout = AbortSignal.timeout.bind(AbortSignal);
  const note = (kind: TimerRequest['kind'], delay: unknown) => {
    const request = describeTimer(kind, delay);
    if (request) sink.push(request);
  };
  vi.stubGlobal('setTimeout', (handler: TimerHandler, delay?: number, ...args: unknown[]) => (note('setTimeout', delay), realSetTimeout(handler, delay, ...args)));
  vi.stubGlobal('setInterval', (handler: TimerHandler, delay?: number, ...args: unknown[]) => (note('setInterval', delay), realSetInterval(handler, delay, ...args)));
  AbortSignal.timeout = (delay: number) => (note('AbortSignal.timeout', delay), realAbortTimeout(delay));
}

// ── One run ────────────────────────────────────────────────────────────────

export interface ActionScript {
  /** The page URL the action runs on, e.g. `/login`. */
  route: string;
  name: string;
  run: (m: Mounted) => Promise<void>;
  /** Success answers this action's runs use instead of the defaults (the load AND the action phase). */
  answers?: Record<string, Answer>;
  /**
   * Requests the action is EXPECTED to repeat although the page's load also made them (a retry re-reads the order). Listed so that
   * the sweep fails them in the action phase too; a repeat the action does not make is then a failure of the EXPECTED_ACTION premise.
   */
  repeats?: string[];
}

export interface FailOne {
  phase: 'load' | 'action';
  key: string;
  variant: Variant;
  text: string;
  status: number;
}

export interface TimerRequest {
  kind: 'setTimeout' | 'setInterval' | 'AbortSignal.timeout';
  /** The delay asked for, in milliseconds (a missing delay is 0). */
  delay: number;
  /** `app`: the frame that called the timer function is a file of src/app (outside testing and ui); `library`: it is a dependency's. */
  origin: 'app' | 'library';
  /** The file of the first stack frame, the code that called the timer function (the asker). */
  askedBy: string;
  /** The first stack frame that names a function, for the reviewed table of long library timers. */
  creator: string;
}

export interface Run {
  renderError?: string;
  /** The router's URL after the page loaded, and after the action. */
  finalUrl: string;
  finalUrlAfterAction?: string;
  load: string[];
  action: string[];
  /** Keys first requested AFTER a phase settled (during the late watch), that the phase had not already requested. */
  late: string[];
  /** Requests that did NOT go through the API seam (global fetch, XHR, sendBeacon, WebSocket, EventSource). */
  bypasses: string[];
  /** Every timer the page's own code and its libraries asked for during the run (the harness's own sleeps excluded), measured at run time. */
  timers: TimerRequest[];
  /** Every interactive element on screen when the run ended, as `tag:accessible name` (links by their normalised href). */
  controls: string[];
  /** Event streams the page opened through the API seam (`EVENT_SOURCE`), as their URLs. */
  streams: string[];
  /** The `data-testid` of every element whose live `.type` was `number` at ANY moment of the run (the render half of the number-box guard, src/app/number-boxes.spec.ts); `(no data-testid)` for an unnamed one. */
  numberBoxes: string[];
  /** Requests with no success body in {@link SUCCESS}. */
  unrouted: string[];
  text: string;
  /** Every non-empty text node, trimmed. */
  texts: string[];
  /** Every text node that was on screen at ANY moment of the run (a form before submit, a pending label, the outcome). */
  everShown: string[];
  title: string;
}

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;

/** Every control a user can operate: buttons, fields, links. Named as the user would name it (label, aria-label, text), links by href with ids normalised. */
export function controlsOf(root: ParentNode = document.body): string[] {
  const out = new Set<string>();
  for (const element of root.querySelectorAll('button, select, input, textarea, a[href]')) {
    const tag = element.tagName.toLowerCase();
    if (element instanceof HTMLInputElement && element.type === 'hidden') continue;
    const labelled = element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement ? element.labels?.[0]?.textContent : undefined;
    const name = tag === 'a' ? (element.getAttribute('href') ?? '').replace(UUID, ':id') : (element.getAttribute('aria-label') ?? labelled ?? element.textContent ?? '').trim();
    out.add(`${tag}:${name}`);
  }
  return [...out].sort();
}

function textNodes(): string[] {
  const out: string[] = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent?.trim();
    if (text) out.push(text);
  }
  return out;
}

const REAL_ABORT_TIMEOUT = AbortSignal.timeout;

export async function runPage(url: string, options: { action?: ActionScript; fail?: FailOne; watchLate?: boolean } = {}): Promise<Run> {
  const run: Run = { numberBoxes: [], finalUrl: '', load: [], action: [], late: [], everShown: [], bypasses: [], unrouted: [], streams: [], timers: [], controls: [], text: '', texts: [], title: '' };
  const state = { phase: 'load' as 'load' | 'action', watching: false };
  const seen = { load: new Set<string>(), action: new Set<string>() };
  const late = new Set<string>();

  // One run is one application: a fresh test bed, so a sweep can run many of them inside one test.
  TestBed.resetTestingModule();
  const bypass = (what: string) => run.bypasses.push(what);
  vi.stubGlobal('fetch', (input: unknown) => {
    bypass(`fetch ${String(input instanceof Request ? input.url : input)}`);
    return Promise.reject(new TypeError('sweep: a request bypassed the API seam'));
  });
  vi.stubGlobal('XMLHttpRequest', class { open(method: string, target: string) { bypass(`XMLHttpRequest ${method} ${target}`); } send() {} setRequestHeader() {} addEventListener() {} });
  vi.stubGlobal('WebSocket', class { constructor(target: string) { bypass(`WebSocket ${target}`); } addEventListener() {} close() {} });
  vi.stubGlobal('EventSource', class { constructor(target: string) { bypass(`EventSource ${target}`); } addEventListener() {} close() {} });
  Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: (target: string) => (bypass(`sendBeacon ${target}`), true) });

  installTimerProbes(run.timers);

  const everShown = new Set<string>();
  const everNumberBoxes = new Set<string>();
  const sample = () => {
    for (const text of textNodes()) everShown.add(text);
    for (const input of document.querySelectorAll('input')) if (input.type === 'number') everNumberBoxes.add(input.getAttribute('data-testid') ?? '(no data-testid)');
  };
  const observer = new MutationObserver(sample);
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });

  let mounted: Mounted | undefined;
  try {
    mounted = await mount(url, (key, init) => {
      if (state.watching && !seen[state.phase].has(key) && !seen.load.has(key)) late.add(`${state.phase}: ${key}`);
      seen[state.phase].add(key);
      if (options.fail && options.fail.phase === state.phase && options.fail.key === key) return problemResponse(options.fail.status, problemBody(options.fail.variant, options.fail.text, options.fail.status));
      const override = options.action?.answers?.[key];
      if (override) return override(key, init);
      const [method, target] = key.split(' ') as [string, string];
      const success = SUCCESS.find(([m, pattern]) => m === method && pattern.test(target.split('?')[0]!));
      if (!success) {
        run.unrouted.push(key);
        return new Response('', { status: 599 });
      }
      return success[2](key, init);
    });
    const watch = async () => {
      if (!options.watchLate) return;
      state.watching = true;
      await sleep(LATE_WATCH_MS);
      await mounted!.settle();
      state.watching = false;
    };
    await watch();
    run.finalUrl = mounted.router.url;
    if (options.action) {
      state.phase = 'action';
      await options.action.run(mounted);
      await mounted.settle();
      await watch();
      run.finalUrlAfterAction = mounted.router.url;
    }
    run.text = document.body.textContent ?? '';
    run.texts = textNodes();
    run.controls = controlsOf();
    run.title = document.title;
    return run;
  } catch (error) {
    run.renderError = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    return run;
  } finally {
    run.load = [...seen.load].sort();
    run.action = [...seen.action].sort();
    run.late = [...late].sort();
    run.streams = mounted?.streams.map((stream) => stream.url) ?? [];
    sample();
    observer.disconnect();
    run.everShown = [...everShown];
    run.numberBoxes = [...everNumberBoxes].sort();
    mounted?.client.clear();
    TestBed.resetTestingModule();
    vi.unstubAllGlobals();
    AbortSignal.timeout = REAL_ABORT_TIMEOUT;
    delete (navigator as { sendBeacon?: unknown }).sendBeacon;
  }
}

/** Every text node a failing run ends with that its all-success baseline never showed at any moment. */
export function addedTexts(run: Run, baseline: Run): string[] {
  const before = new Set(baseline.everShown);
  return run.texts.filter((text) => !before.has(text));
}

export function newTexts(run: Run, baseline: Run): string {
  const added = addedTexts(run, baseline);
  return added.length ? added.join(' ⏎ ') : '(no new text at all)';
}

// ── Interaction helpers for scripts (Testing Library's DOM queries: by label and by role, as a user finds things) ──

export function byLabel(label: string): HTMLInputElement {
  return screen.getByLabelText<HTMLInputElement>(label);
}

export function typeInto(input: HTMLInputElement, value: string): void {
  fireEvent.input(input, { target: { value } });
}

/** Chooses an option of a `<select>` found by its label, as a user does (the change event the page listens to). */
export function choose(select: HTMLElement, value: string): void {
  fireEvent.change(select, { target: { value } });
}

export function buttonNamed(name: string): HTMLButtonElement {
  return screen.getByRole<HTMLButtonElement>('button', { name });
}
