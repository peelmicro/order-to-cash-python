import { inject, Injectable, InjectionToken } from '@angular/core';
import { MutationCache, QueryCache, QueryClient } from '@tanstack/angular-query-experimental';
import { Router } from '@angular/router';
import { ApiError } from '../lib/problem';

/**
 * A 401 from ANY BFF call means the session is gone (expired, revoked, or never there): the user goes to
 * `/login`, from every page and every kind of request, queries and mutations alike (#8 id 98's
 * precondition; #8 src/app/providers.tsx `redirectOnSignedOut`). The navigation is the router's, so the
 * page the user was on is left and the cached data of the old session is dropped.
 */
@Injectable({ providedIn: 'root' })
export class SignedOutNavigator {
  private readonly router = inject(Router);

  handle(error: unknown, client: QueryClient): void {
    if (!(error instanceof ApiError) || error.status !== 401) return;
    if (this.router.url.split('?')[0] === '/login') return;
    client.clear();
    void this.router.navigateByUrl('/login');
  }
}

/** The delay before the single retry of a failed query (TanStack's default for the first retry, written down so the sweep can bound its settle window by it). */
export const QUERY_RETRY_DELAY_MS = 1_000;

export const QUERY_CLIENT = new InjectionToken<QueryClient>('QUERY_CLIENT', {
  providedIn: 'root',
  factory: () => {
    const navigator = inject(SignedOutNavigator);
    const client: QueryClient = new QueryClient({
      queryCache: new QueryCache({ onError: (error) => navigator.handle(error, client) }),
      mutationCache: new MutationCache({ onError: (error) => navigator.handle(error, client) }),
      defaultOptions: {
        queries: {
          // A 4xx will not change by asking again; a 5xx or a network failure gets one retry before the error is shown.
          retry: (failureCount, error) => !(error instanceof ApiError && error.status < 500) && failureCount < 1,
          retryDelay: QUERY_RETRY_DELAY_MS,
          staleTime: 2_000,
        },
      },
    });
    return client;
  },
});
