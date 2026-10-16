import { defineEventHandler } from 'h3';
import { proxyToGateway } from '../../../lib/gateway';

/** `POST /api/stock/replenish` -> Gateway `POST /stock/replenish`. `units` is a delta; deliberately not idempotent (openapi.yaml). */
export default defineEventHandler((event) => proxyToGateway(event, { method: 'POST', gatewayPath: '/stock/replenish' }));
