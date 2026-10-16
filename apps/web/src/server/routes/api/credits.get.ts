import { defineEventHandler } from 'h3';
import { proxyToGateway } from '../../lib/gateway';

/** `GET /api/credits` -> Gateway `GET /credits`. Query string forwarded as it is. */
export default defineEventHandler((event) => proxyToGateway(event, { gatewayPath: '/credits' }));
