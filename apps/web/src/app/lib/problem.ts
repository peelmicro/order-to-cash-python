import type { Problem } from '../../shared/api-types';

/**
 * Every error the browser sees from the BFF is the Gateway's RFC 9457 problem document, relayed
 * UNCHANGED (src/server/lib/gateway.ts `relay`), or one the BFF wrote itself in the same shape
 * (src/server/lib/problem.ts). There is no framework envelope around it, so the problem is the parsed
 * body itself and not a field of it.
 *
 * That sentence is the whole of #7's most expensive web defect in reverse: #7's pages read
 * `error.data.detail` while Nitro had wrapped the problem one level deeper, so every error rendered
 * generic text from the day the app was built and four review passes walked past it. The guard is not
 * this comment. It is src/app/error-text.sweep.spec.ts, which fails every request every page makes and
 * requires the server's own words on screen.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: Partial<Problem> | undefined,
  ) {
    super(problem?.detail ?? problem?.title ?? `Request failed with status ${status}`);
    this.name = 'ApiError';
  }
}

function isProblemLike(value: unknown): value is Partial<Problem> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) && ('detail' in value || 'title' in value || 'code' in value);
}

/** Parses a non-2xx response body into a problem document, or `undefined` when it is not one (an HTML error page, an empty body, an intermediary's text). */
export async function readProblem(response: Response): Promise<Partial<Problem> | undefined> {
  const text = await response.text().catch(() => '');
  if (!text) return undefined;
  try {
    const parsed: unknown = JSON.parse(text);
    return isProblemLike(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

/**
 * The one line an error-rendering component shows: the problem's own `detail`, else its `title`, else
 * `fallback`. The fallback is for a body that carries NEITHER (no problem document at all, or a request
 * that never got an answer); it is never shown while the server said something specific.
 */
export function describeError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    const detail = error.problem?.detail?.trim();
    if (detail) return detail;
    const title = error.problem?.title?.trim();
    if (title) return title;
  }
  return fallback;
}
