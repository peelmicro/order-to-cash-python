import { defineEventHandler } from 'h3';
import { proxyToGateway } from '../../../lib/gateway';

/** `GET /api/invoices` -> Gateway `GET /invoices`. Query string forwarded as it is. */
export default defineEventHandler((event) => proxyToGateway(event, { gatewayPath: '/invoices' }));
