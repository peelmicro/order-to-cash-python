import { defineEventHandler, getRequestURL } from 'h3';
import { localProblem } from '../../lib/problem';

/**
 * Anything under /api that no route above answers is a 404 problem document in the BFF's own words, never
 * the single-page shell (Nitro's client renderer would otherwise answer an unknown /api path with index.html
 * and status 200, which the browser client would try to parse as JSON).
 */
export default defineEventHandler((event) => localProblem(event, 404, 'NOT_FOUND', 'No such API route', `${event.method} ${getRequestURL(event).pathname} is not a route of this site.`));
