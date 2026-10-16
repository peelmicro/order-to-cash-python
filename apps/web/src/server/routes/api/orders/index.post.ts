import { defineEventHandler } from 'h3';
import { proxyToGateway } from '../../../lib/gateway';

/** `POST /api/orders` -> Gateway `POST /orders`. `201` means accepted, not completed; `Idempotency-Key` is forwarded. */
export default defineEventHandler((event) => proxyToGateway(event, { method: 'POST', gatewayPath: '/orders', forwardRequestHeaders: ['idempotency-key'] }));
