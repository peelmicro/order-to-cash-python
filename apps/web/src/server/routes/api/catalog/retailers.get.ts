import { defineEventHandler } from 'h3';
import { proxyToGateway } from '../../../lib/gateway';

/** `GET /api/catalog/retailers` -> Gateway `GET /catalog/retailers`. */
export default defineEventHandler((event) => proxyToGateway(event, { gatewayPath: '/catalog/retailers' }));
