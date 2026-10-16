import { defineEventHandler } from 'h3';
import { proxyToGateway } from '../../../../lib/gateway';
import { pathId } from '../../../../lib/path-id';

/**
 * `POST /api/invoices/{id}/payments` -> Gateway `POST /invoices/{id}/payments` (R47). `201` accepted and
 * `200` duplicate are both relayed with their own status; a rejection (409/422) is relayed as the Gateway's problem document.
 * An id that could reach another Gateway path (`..`, a separator) is the BFF's own 400 (lib/path-id.ts).
 */
export default defineEventHandler((event) => {
  const id = pathId(event);
  if (typeof id !== 'string') return id.problem;
  return proxyToGateway(event, { method: 'POST', gatewayPath: `/invoices/${encodeURIComponent(id)}/payments` });
});
