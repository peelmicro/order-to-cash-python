import { setResponseHeader, setResponseStatus, type H3Event } from 'h3';
import type { Problem } from '../../shared/api-types';

/**
 * A problem document minted by THIS app (not the Gateway), only for failures that never reached it:
 * no session, Gateway unreachable, timeout, a blocked cross-site request. Every other error the
 * browser sees is the Gateway's own document relayed unchanged (gateway.ts `relay`).
 */
export function localProblem(event: H3Event, status: number, code: string, title: string, detail: string): string {
  const body: Problem = { type: 'about:blank', title, status, detail, code };
  setResponseStatus(event, status);
  setResponseHeader(event, 'Content-Type', 'application/problem+json');
  setResponseHeader(event, 'Cache-Control', 'no-store');
  return JSON.stringify(body);
}
