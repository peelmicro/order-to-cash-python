import { sessionPassword } from '../lib/config';

/**
 * Runs once when the server boots: a WEB_SESSION_PASSWORD that is set but too short stops the server
 * here, with the setting named, instead of failing the first login (a missing binding raises at boot,
 * never on the first request: CLAUDE.md, one composition root). Unset is allowed (random per-process key).
 */
export default function validateConfig(): void {
  sessionPassword();
}
