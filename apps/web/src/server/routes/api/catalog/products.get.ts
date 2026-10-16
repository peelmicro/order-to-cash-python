import { defineEventHandler } from 'h3';
import { proxyToGateway } from '../../../lib/gateway';

/** `GET /api/catalog/products` -> Gateway `GET /catalog/products`. */
export default defineEventHandler((event) => proxyToGateway(event, { gatewayPath: '/catalog/products' }));
