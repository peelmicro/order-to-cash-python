import { randomBytes } from 'node:crypto';

/**
 * Server-side configuration, read from the environment at REQUEST time and never from a public
 * runtime value: nothing here is reachable from the client bundle (only src/server/** imports it,
 * and src/server/server-only.spec.ts fails if src/app/** ever imports anything from src/server).
 * `pnpm dev` / `pnpm start` load the repository root `.env` with node's `--env-file-if-exists`.
 *
 * Settings: GATEWAY_BASE_URL (else http://localhost:${GATEWAY_PORT:-3001}), WEB_SESSION_PASSWORD
 * (>= 32 characters), WEB_COOKIE_SECURE (default on), WEB_GATEWAY_TIMEOUT_MS (default 15000),
 * WEB_PORT (default 3010, read by scripts/serve.mjs).
 */
type Env = Record<string, string | undefined>;

export function gatewayBaseUrl(env: Env = process.env): string {
  const explicit = env['GATEWAY_BASE_URL']?.trim();
  if (explicit) return explicit.replace(/\/+$/, '');
  const port = env['GATEWAY_PORT']?.trim() || '3001';
  return `http://localhost:${port}`;
}

export const MIN_SESSION_PASSWORD_LENGTH = 32;

/**
 * The generated fallback key lives on `globalThis`, not in a module variable: a bundled server can
 * hold one module instance per entry (#8 found this live: login sealed with one random key and the
 * next request unsealed with another, so every sign-in bounced). One symbol-keyed slot is shared.
 */
const GENERATED_KEY = Symbol.for('otc.web.generatedSessionPassword');
type KeyHolder = { [GENERATED_KEY]?: string };

/**
 * The password the session cookie is sealed with. `WEB_SESSION_PASSWORD` (>= 32 characters) in any
 * real deployment. Set but shorter: throw (fail closed). Unset: a random per-process key, with a
 * warning, which only means sessions end when this server restarts (#8's choice, server/config.ts;
 * #7 instead shipped a hard-coded dev password as the fallback, apps/web/nuxt.config.ts:34, which
 * would make every unconfigured deployment's cookies forgeable, so it is not repeated).
 */
export function sessionPassword(env: Env = process.env): string {
  const configured = env['WEB_SESSION_PASSWORD'];
  if (configured && configured.length >= MIN_SESSION_PASSWORD_LENGTH) return configured;
  if (configured) {
    throw new Error(`WEB_SESSION_PASSWORD must be at least ${MIN_SESSION_PASSWORD_LENGTH} characters long.`);
  }
  const holder = globalThis as KeyHolder;
  if (!holder[GENERATED_KEY]) {
    holder[GENERATED_KEY] = randomBytes(32).toString('hex');
    console.warn('WEB_SESSION_PASSWORD is not set: sealing sessions with a random per-process key (sessions end when this server restarts).');
  }
  return holder[GENERATED_KEY];
}

/** `Secure` on the session cookie. On unless WEB_COOKIE_SECURE is exactly `false`; browsers treat http://localhost as a secure context. */
export function cookieSecure(env: Env = process.env): boolean {
  return env['WEB_COOKIE_SECURE'] !== 'false';
}

export const DEFAULT_GATEWAY_TIMEOUT_MS = 15_000;

export function gatewayTimeoutMs(env: Env = process.env): number {
  const raw = Number(env['WEB_GATEWAY_TIMEOUT_MS']);
  return Number.isInteger(raw) && raw > 0 ? raw : DEFAULT_GATEWAY_TIMEOUT_MS;
}
