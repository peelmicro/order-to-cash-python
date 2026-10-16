import { defineEventHandler } from 'h3';
import { proxyToGateway } from '../../../lib/gateway';
import { pathId } from '../../../lib/path-id';

/**
 * `GET /api/orders/{id}` -> Gateway `GET /orders/{id}` (R54/R55). The Gateway's `202` + `Retry-After` for an order
 * not projected yet is relayed with that status and header intact, so the page can show its waiting state.
 * An id that could reach another Gateway path (`..`, a separator) is the BFF's own 400 (lib/path-id.ts).
 */
export default defineEventHandler((event) => {
  const id = pathId(event);
  if (typeof id !== 'string') return id.problem;
  return proxyToGateway(event, { gatewayPath: `/orders/${encodeURIComponent(id)}` });
});
