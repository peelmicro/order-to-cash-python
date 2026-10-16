import { inject } from '@angular/core';
import { QueryClient, queryOptions } from '@tanstack/angular-query-experimental';
import { Router, type CanActivateFn } from '@angular/router';
import { ApiClient } from '../api/api-client';

export const SESSION_KEY = ['session'] as const;

/** The browser's only knowledge of "am I signed in": identity from `GET /api/auth/session`, never the token. */
export function sessionQuery(api: ApiClient) {
  return queryOptions({ queryKey: SESSION_KEY, queryFn: () => api.session(), staleTime: 30_000 });
}

/**
 * The route guard of every signed-in page: no live session sends the user to `/login`. A failure of the
 * session probe itself (the BFF is down) is NOT answered with a redirect, which would hide it: the page
 * is entered and the shell shows the error in the server's own words (src/app/pages/(app).page.ts).
 */
export const requireSession: CanActivateFn = async () => {
  const client = inject(QueryClient);
  const router = inject(Router);
  const api = inject(ApiClient);
  try {
    const session = await client.fetchQuery(sessionQuery(api));
    return session.authenticated ? true : router.parseUrl('/login');
  } catch {
    return true;
  }
};
