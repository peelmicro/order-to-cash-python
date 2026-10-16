import { defineEventHandler, setResponseHeader } from 'h3';
import { readSession, toSessionInfo } from '../../../lib/session';

/** `GET /api/auth/session`: what the browser may know about its own session: identity, never the token. */
export default defineEventHandler(async (event) => {
  setResponseHeader(event, 'Cache-Control', 'no-store');
  return toSessionInfo(await readSession(event));
});
