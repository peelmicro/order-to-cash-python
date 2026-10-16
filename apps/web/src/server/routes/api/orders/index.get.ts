import { defineEventHandler } from 'h3';
import { proxyToGateway } from '../../../lib/gateway';

/** `GET /api/orders` -> Gateway `GET /orders` (read model, R54). Query string forwarded as it is. */
export default defineEventHandler((event) => proxyToGateway(event, { gatewayPath: '/orders' }));
