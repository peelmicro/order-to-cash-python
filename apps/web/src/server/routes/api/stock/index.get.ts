import { defineEventHandler } from 'h3';
import { proxyToGateway } from '../../../lib/gateway';

/** `GET /api/stock` -> Gateway `GET /stock`. Query string forwarded as it is. */
export default defineEventHandler((event) => proxyToGateway(event, { gatewayPath: '/stock' }));
