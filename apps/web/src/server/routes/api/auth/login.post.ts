import { defineEventHandler, readBody } from 'h3';
import type { CurrentUser, LoginRequest, LoginResponse } from '../../../../shared/api-types';
import { callGateway, gatewayFailed, relay } from '../../../lib/gateway';
import { localProblem } from '../../../lib/problem';
import { toSessionInfo, writeSession, type OtcSession } from '../../../lib/session';

/**
 * `POST /api/auth/login`: exchanges operator credentials for a Gateway JWT and seals it into this
 * server's httpOnly session cookie. The response BODY is `SessionInfo` (identity only); the token
 * never appears in it.
 *
 * TWO upstream calls (`POST /auth/login`, then `GET /auth/me`). A refusal of EITHER is relayed with
 * the Gateway's own problem document (#8 RR3 D1: the second call's body was dropped on one path).
 * The sweep's unit is every upstream call this route makes (src/server/routes.sweep.spec.ts).
 */
export default defineEventHandler(async (event) => {
  let credentials: LoginRequest;
  try {
    const parsed = (await readBody(event)) as Partial<LoginRequest> | undefined;
    credentials = { username: String(parsed?.username ?? ''), password: String(parsed?.password ?? '') };
  } catch {
    return localProblem(event, 400, 'VALIDATION_FAILED', 'The request was malformed', 'The login request body could not be read.');
  }

  let issuedResponse: Response;
  try {
    issuedResponse = await callGateway('/auth/login', { method: 'POST', body: JSON.stringify(credentials) });
  } catch (error) {
    return gatewayFailed(event, error);
  }
  if (!issuedResponse.ok) return relay(event, issuedResponse);
  const issued = (await issuedResponse.json()) as LoginResponse;

  let meResponse: Response;
  try {
    meResponse = await callGateway('/auth/me', { token: issued.accessToken });
  } catch (error) {
    return gatewayFailed(event, error);
  }
  if (!meResponse.ok) return relay(event, meResponse);
  const me = (await meResponse.json()) as CurrentUser;

  const session: OtcSession = {
    accessToken: issued.accessToken,
    expiresAt: Date.now() + issued.expiresIn * 1000,
    username: me.username,
    displayName: me.displayName,
    roles: me.roles,
  };
  await writeSession(event, session);
  return toSessionInfo(session);
});
