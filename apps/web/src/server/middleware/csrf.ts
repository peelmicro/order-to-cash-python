import { defineEventHandler } from 'h3';
import { csrfViolation, unsupportedMediaType } from '../lib/csrf';
import { localProblem } from '../lib/problem';

/**
 * Runs before every route, on EVERY path (h3 routes on the decoded path, so a test of the raw path would be bypassed by
 * `/%61pi/...`; there is no mutation outside /api to exempt): a cross-origin mutation is refused with this app's own
 * problem document, and so is a mutation whose body is not JSON, before any route (or Gateway call) happens.
 */
export default defineEventHandler((event) => {
  const reason = csrfViolation(event);
  if (reason) {
    return localProblem(event, 403, 'CROSS_ORIGIN_REQUEST', 'Cross-origin request refused', `A request that changes state must come from this site itself (${reason}).`);
  }
  const mediaType = unsupportedMediaType(event);
  if (mediaType) {
    return localProblem(event, 415, 'UNSUPPORTED_MEDIA_TYPE', 'Unsupported media type', `A request that changes state must send application/json (this one sent ${mediaType}).`);
  }
  return undefined;
});
