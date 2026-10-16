import { defineEventHandler } from 'h3';
import { proxyToGateway } from '../../../lib/gateway';

/** `GET /api/catalog/companies` -> Gateway `GET /catalog/companies`. */
export default defineEventHandler((event) => proxyToGateway(event, { gatewayPath: '/catalog/companies' }));
