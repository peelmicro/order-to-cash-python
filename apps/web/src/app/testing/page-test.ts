import { SUCCESS } from './page-sweep';
import { json, mount, type Answer, type Mounted } from './browser-harness';

export type Route = [match: string | RegExp, answer: Answer];

export interface Stub {
  answer: Answer;
  /** Every request, in order, with the init the seam received (method, headers, body bytes). */
  calls: Array<{ key: string; init: RequestInit | undefined }>;
  /** How many requests matched `match` (an exact key or a pattern). */
  count: (match: string | RegExp) => number;
  /** The requests that matched, in order. */
  matching: (match: string | RegExp) => Array<{ key: string; init: RequestInit | undefined }>;
}

const matches = (match: string | RegExp, key: string) => (typeof match === 'string' ? match === key : match.test(key));

/** A stand-in for the BFF: the first route that matches answers, else the all-success defaults of the sweep. Records every request. */
export function stub(routes: Route[] = []): Stub {
  const calls: Stub['calls'] = [];
  const answer: Answer = (key, init) => {
    calls.push({ key, init });
    for (const [match, handler] of routes) if (matches(match, key)) return handler(key, init);
    const [method, target] = key.split(' ') as [string, string];
    const success = SUCCESS.find(([m, pattern]) => m === method && pattern.test(target.split('?')[0]!));
    return success ? success[2](key, init) : json({ unrouted: key }, 599);
  };
  return { answer, calls, count: (match) => calls.filter((call) => matches(match, call.key)).length, matching: (match) => calls.filter((call) => matches(match, call.key)) };
}

/** A request held on an unresolved promise until the test releases it with the response (or fails it): the loading state is looked at while the request is genuinely in flight. */
export function gate(): { answer: () => Promise<Response>; release: (response: Response) => void; started: () => boolean } {
  let release!: (response: Response) => void;
  let started = false;
  const promise = new Promise<Response>((resolve) => (release = resolve));
  return {
    answer: () => {
      started = true;
      return promise;
    },
    release: (response) => release(response),
    started: () => started,
  };
}

export const mountPage = (url: string, routes: Route[] = [], options: { settle?: boolean } = {}): Promise<{ m: Mounted; s: Stub }> => {
  const s = stub(routes);
  return mount(url, s.answer, options).then((m) => ({ m, s }));
};
