import { getHeader, getRequestHost, getRequestProtocol, type H3Event } from 'h3';

/**
 * The CSRF stance for this cookie-authenticated BFF (both #7 and #8 relied on the `SameSite=Lax`
 * cookie alone: #7 server/utils/session.ts:41, #8 server/session.ts:49; neither checked the origin of a
 * mutation). #9 keeps `SameSite=Lax` AND refuses, for every non-read method on EVERY path (the check runs on
 * every request: h3 routes on the DECODED path, so a test of the raw path such as `/%61pi/...` would be bypassed),
 * a request a browser marks as cross-origin:
 *   - `Sec-Fetch-Site: cross-site | same-site` (anything but `same-origin` / `none`), or
 *   - an `Origin` header whose ORIGIN (scheme, host and port) is not the one this server was addressed by.
 * A request carrying neither header is not a browser acting for an attacker (browsers always send
 * `Origin` on a cross-origin POST), so it passes: curl, the tests, a server-to-server caller.
 * Behind a TLS-terminating proxy the scheme is `https` only when the proxy sends `X-Forwarded-Proto: https`.
 *
 * `readBody` does NOT make a JSON content type a precondition (h3 parses `application/x-www-form-urlencoded` too),
 * and the proxy forwards any body with a forced `Content-Type: application/json`; so a cross-site `<form>` or a
 * `text/plain` request (both CORS-simple, no preflight) could carry credentials or an order. `unsupportedMediaType`
 * therefore refuses every mutation whose body is not declared `application/json`.
 */
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

export function isSafeMethod(event: H3Event): boolean {
  return SAFE_METHODS.has(event.method.toUpperCase());
}

export function csrfViolation(event: H3Event): string | undefined {
  if (isSafeMethod(event)) return undefined;
  const fetchSite = getHeader(event, 'sec-fetch-site');
  if (fetchSite && fetchSite !== 'same-origin' && fetchSite !== 'none') {
    return `Sec-Fetch-Site is "${fetchSite}"`;
  }
  const origin = getHeader(event, 'origin');
  if (origin) {
    let claimed: string;
    try {
      claimed = new URL(origin).origin;
    } catch {
      return `Origin "${origin}" is not a valid origin`;
    }
    const own = `${getRequestProtocol(event)}://${getRequestHost(event)}`;
    if (claimed !== own) return `Origin "${origin}" is not this server`;
  }
  return undefined;
}

/**
 * The declared media type of a mutation's body when it is not `application/json`, or `undefined` when it is acceptable.
 * A mutation with no body and no Content-Type (logout, a bodiless POST) is acceptable.
 */
export function unsupportedMediaType(event: H3Event): string | undefined {
  if (isSafeMethod(event)) return undefined;
  const declared = getHeader(event, 'content-type');
  if (declared === undefined || declared.trim() === '') {
    const hasBody = (getHeader(event, 'content-length') ?? '0') !== '0' || getHeader(event, 'transfer-encoding') !== undefined;
    return hasBody ? '(none)' : undefined;
  }
  const mediaType = declared.split(';')[0]!.trim().toLowerCase();
  return mediaType === 'application/json' ? undefined : mediaType;
}
