import { RouteMeta } from '@analogjs/router';

/** `/` has no content of its own: it redirects to the orders page, whose guard sends a signed-out user on to `/login`. A redirect page exports `routeMeta` and no component. */
export const routeMeta: RouteMeta = { redirectTo: '/orders', pathMatch: 'full' };
