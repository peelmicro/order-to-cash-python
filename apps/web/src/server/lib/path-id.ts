import { getRequestURL, getRouterParam, type H3Event } from 'h3';
import { localProblem } from './problem';

/**
 * The identifier of a `{id}` route, or the BFF's own 400 problem for one that could reach another Gateway path.
 *
 * h3 routes on the DECODED path (`_decodePath`): `%2E%2E` arrives as the router param `..`, and
 * `encodeURIComponent('..')` is `..`, which `fetch` would normalise away as a dot segment (the Gateway's `/` or
 * `/payments`). A decoded `?` also ends the router's path, so `x%3Fy=1` arrives as the id `x`. Both are refused here,
 * on the param AND on the raw path: an id is empty, `.`, `..`, or contains `/` or `?` once decoded (a second
 * time, because h3 leaves `%2F` and `%25` encoded in the param).
 */
export function pathId(event: H3Event, name = 'id'): string | { problem: string } {
  const id = getRouterParam(event, name) ?? '';
  const decodedTwice = safeDecode(id);
  const rawPath = getRequestURL(event).pathname;
  const invalid = id === '' || [id, decodedTwice].some((candidate) => candidate === '.' || candidate === '..' || /[/?]/.test(candidate)) || /%3f/i.test(rawPath);
  if (invalid) return { problem: localProblem(event, 400, 'VALIDATION_FAILED', 'The identifier is not valid', 'The identifier in the path is empty, a dot segment, or contains a path or query separator.') };
  return id;
}

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
