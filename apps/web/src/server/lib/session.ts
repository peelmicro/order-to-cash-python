import { deleteCookie, getCookie, unsealSession, useSession, type H3Event, type SessionConfig } from 'h3';
import type { SessionInfo } from '../../shared/api-types';
import { cookieSecure, sessionPassword } from './config';

/**
 * The session this server holds ON BEHALF OF the browser. `accessToken` is the real Gateway-issued
 * JWT; it exists only inside the sealed (AES-CTR + HMAC, iron-webcrypto) value of an `httpOnly`
 * cookie, so no client-side script can read it and the raw cookie never carries it in the clear.
 * No response BODY this app returns ever includes it: `toSessionInfo` is the only shape the
 * browser is given.
 */
export interface OtcSession {
  accessToken: string;
  /** Epoch milliseconds after which the token is treated as expired without asking the Gateway. */
  expiresAt: number;
  username: string;
  displayName?: string;
  roles: string[];
}

export const SESSION_COOKIE = 'otc_session';
export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 12;

/** The attributes of the cookie, set by THIS file on purpose and not left to library defaults. */
export function cookieAttributes() {
  return { httpOnly: true, secure: cookieSecure(), sameSite: 'lax' as const, path: '/' };
}

function sessionConfig(): SessionConfig {
  return {
    name: SESSION_COOKIE,
    password: sessionPassword(),
    maxAge: SESSION_MAX_AGE_SECONDS,
    // h3 would ALSO accept the sealed session from an `x-<name>-session` request header by default;
    // the session is a cookie and nothing else.
    sessionHeader: false,
    // h3 would otherwise express the lifetime only as an `Expires` derived from the session's creation time.
    cookie: { ...cookieAttributes(), maxAge: SESSION_MAX_AGE_SECONDS },
  };
}

/**
 * The session, or `undefined` when there is none, it is malformed, or it is expired. Never throws for a bad cookie.
 * A cookie that cannot be read (tampered, sealed with another key, past its lifetime) is CLEARED, never replaced:
 * h3's `useSession` would answer it by minting and `Set-Cookie`-ing a fresh empty session, so the cookie is unsealed
 * directly here (which also keeps the `x-<name>-session` request header, a path of `useSession`, out of the read).
 */
export async function readSession(event: H3Event, now: number = Date.now()): Promise<OtcSession | undefined> {
  const sealed = getCookie(event, SESSION_COOKIE);
  if (!sealed) return undefined;
  let data: Partial<OtcSession>;
  try {
    data = ((await unsealSession(event, sessionConfig(), sealed)) as { data: Partial<OtcSession> }).data;
  } catch {
    clearSession(event);
    return undefined;
  }
  const { accessToken, expiresAt, username, displayName, roles } = data;
  if (!accessToken || typeof expiresAt !== 'number' || expiresAt <= now || !username) return undefined;
  return { accessToken, expiresAt, username, displayName, roles: Array.isArray(roles) ? roles : [] };
}

export async function writeSession(event: H3Event, session: OtcSession): Promise<void> {
  const sealed = await useSession<Partial<OtcSession>>(event, sessionConfig());
  await sealed.update({ ...session });
}

/** Expires the cookie now (`Max-Age=0`), on the same path and with the same attributes it was set with. */
export function clearSession(event: H3Event): void {
  deleteCookie(event, SESSION_COOKIE, cookieAttributes());
}

/** The ONLY session shape any response body carries: identity, never the token. */
export function toSessionInfo(session: OtcSession | undefined): SessionInfo {
  if (!session) return { authenticated: false };
  return { authenticated: true, username: session.username, displayName: session.displayName, roles: session.roles };
}
