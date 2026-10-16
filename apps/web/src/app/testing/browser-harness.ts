import { ApplicationRef, provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideLocationMocks } from '@angular/common/testing';
import { Router, TitleStrategy } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { provideFileRouter } from '@analogjs/router';
import { provideTanStackQuery, QueryClient } from '@tanstack/angular-query-experimental';
import { API_FETCH, EVENT_SOURCE } from '../api/api-client';
import { AppTitleStrategy } from '../lib/title-strategy';
import { QUERY_CLIENT } from '../session/signed-out';
import { FakeEventSource } from './fake-event-source';

/** `METHOD /path?sorted-query`: a request as the sweep names it. */
export function requestKey(method: string, input: string): string {
  const url = new URL(input, 'http://web.test');
  const query = new URLSearchParams([...url.searchParams].sort(([a], [b]) => a.localeCompare(b))).toString();
  return `${method.toUpperCase()} ${url.pathname}${query ? `?${query}` : ''}`;
}

export type Answer = (key: string, init: RequestInit | undefined) => Response | Promise<Response>;

export interface Mounted {
  harness: RouterTestingHarness;
  router: Router;
  client: QueryClient;
  /** Every request made through the API seam, in order, as `METHOD /path?query`. */
  requests: string[];
  /** Every event stream the page opened through the API seam, in order (closed ones stay in the list). */
  streams: FakeEventSource[];
  /** Requests started but not yet answered. */
  inflight: () => number;
  root: HTMLElement;
  /** Everything on screen as one string. */
  text: () => string;
  /** Waits until nothing is in flight, nothing is fetching or mutating, and the view has been checked, for `quiet` consecutive polls. */
  settle: (quiet?: number) => Promise<void>;
}

export const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Mounts the app's REAL file router (provideFileRouter: every page and layout under src/app/pages, with
 * their guards) in the Angular test bed, zoneless, with the same providers as src/app/app.config.ts except
 * the network seam, which is `answer`. This renders a page as the browser does: layout chain, guard, query
 * client, title strategy.
 */
export async function mount(url: string, answer: Answer, options: { settle?: boolean } = {}): Promise<Mounted> {
  const requests: string[] = [];
  const streams: FakeEventSource[] = [];
  let inflight = 0;
  const seam: typeof fetch = async (input, init) => {
    const key = requestKey(init?.method ?? 'GET', String(input instanceof Request ? input.url : input));
    requests.push(key);
    inflight += 1;
    try {
      await sleep(0);
      return await answer(key, init);
    } finally {
      inflight -= 1;
    }
  };
  TestBed.configureTestingModule({
    providers: [
      provideZonelessChangeDetection(),
      provideLocationMocks(),
      provideFileRouter(),
      { provide: TitleStrategy, useClass: AppTitleStrategy },
      provideTanStackQuery(QUERY_CLIENT),
      { provide: API_FETCH, useValue: seam },
      {
        provide: EVENT_SOURCE,
        useValue: (url: string) => {
          const stream = new FakeEventSource(url);
          streams.push(stream);
          return stream;
        },
      },
    ],
  });
  const client = TestBed.inject(QUERY_CLIENT);
  const harness = await RouterTestingHarness.create();
  const router = TestBed.inject(Router);
  const appRef = TestBed.inject(ApplicationRef);
  const root = harness.routeNativeElement?.ownerDocument.body ?? document.body;

  const settle = async (quiet = 5) => {
    let calm = 0;
    const deadline = Date.now() + 20_000;
    while (Date.now() < deadline) {
      await sleep(20);
      await appRef.whenStable();
      harness.detectChanges();
      const busy = inflight > 0 || client.isFetching() > 0 || client.isMutating() > 0;
      calm = busy ? 0 : calm + 1;
      if (calm >= quiet) return;
    }
    throw new Error(`browser harness: ${url} never settled (inflight ${inflight}, fetching ${client.isFetching()}, mutating ${client.isMutating()})`);
  };

  await harness.navigateByUrl(url);
  // A test that HOLDS a request (to look at the loading state while it is unanswered) mounts with `settle: false`; it settles after releasing it.
  if (options.settle !== false) await settle();
  return { harness, router, client, requests, streams, inflight: () => inflight, root, text: () => root.textContent ?? '', settle };
}

/** A JSON response. */
export const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

/** A problem+json response. */
export const problemResponse = (status: number, body: Record<string, unknown>) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/problem+json' } });
