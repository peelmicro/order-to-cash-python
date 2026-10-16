import { describe, expect, it } from 'vitest';
import { ApiError, describeError, readProblem } from './problem';

describe('describeError: the server\'s own words', () => {
  it('shows detail when there is one, ignoring the title', () => {
    expect(describeError(new ApiError(409, { title: 'Conflict', detail: 'Order ORD-000042 is already paid.' }), 'fallback')).toBe('Order ORD-000042 is already paid.');
  });

  it('shows the title when the body has no detail', () => {
    expect(describeError(new ApiError(503, { title: 'Stock service unavailable' }), 'fallback')).toBe('Stock service unavailable');
  });

  it('treats a blank detail as absent and falls to the title', () => {
    expect(describeError(new ApiError(400, { title: 'Bad request', detail: '   ' }), 'fallback')).toBe('Bad request');
  });

  it('uses the fallback only when the body carries neither', () => {
    expect(describeError(new ApiError(502, undefined), 'fallback')).toBe('fallback');
    expect(describeError(new ApiError(500, { code: 'DOMAIN_ERROR' }), 'fallback')).toBe('fallback');
    expect(describeError(new TypeError('Failed to fetch'), 'fallback')).toBe('fallback');
    expect(describeError(undefined, 'fallback')).toBe('fallback');
  });

  it('the error\'s message is the same words', () => {
    expect(new ApiError(409, { detail: 'd', title: 't' }).message).toBe('d');
    expect(new ApiError(409, { title: 't' }).message).toBe('t');
    expect(new ApiError(409, undefined).message).toBe('Request failed with status 409');
  });
});

describe('readProblem', () => {
  const body = (text: string, type = 'application/problem+json') => new Response(text, { status: 400, headers: { 'Content-Type': type } });

  it('reads a problem document as the parsed body itself, not a field of it', async () => {
    expect(await readProblem(body('{"title":"T","detail":"D","code":"X","status":400}'))).toEqual({ title: 'T', detail: 'D', code: 'X', status: 400 });
  });

  it('answers undefined for an HTML page, an empty body, an array, and a JSON object that is no problem', async () => {
    expect(await readProblem(body('<html>502 Bad Gateway</html>', 'text/html'))).toBeUndefined();
    expect(await readProblem(body(''))).toBeUndefined();
    expect(await readProblem(body('[{"detail":"x"}]'))).toBeUndefined();
    expect(await readProblem(body('{"unrelated":true}'))).toBeUndefined();
  });

  it('does not unwrap an envelope: #7\'s nested `data.data` shape is not a problem', async () => {
    expect(await readProblem(body('{"error":true,"statusCode":400,"data":{"detail":"hidden one level down"}}'))).toBeUndefined();
  });
});
