import { defineEventHandler } from 'h3';
import { clearSession } from '../../../lib/session';

/** `POST /api/auth/logout`: forgets the sealed session. The Gateway JWT is stateless; dropping it is the logout. No upstream call. */
export default defineEventHandler((event) => {
  clearSession(event);
  return { authenticated: false };
});
