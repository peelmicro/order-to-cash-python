import { describe, expect, it } from 'vitest';
import { pageCount } from './pager';

describe('pageCount: integer arithmetic, at least one page', () => {
  it.each([
    [0, 20, 1],
    [1, 20, 1],
    [19, 20, 1],
    [20, 20, 1],
    [21, 20, 2],
    [40, 20, 2],
    [45, 20, 3],
    [9007199254740991, 1, 9007199254740991],
    [9007199254740990, 2, 4503599627370495],
    [9007199254740991, 200, 45035996273705],
  ])('%i rows at %i per page is %i pages', (total, size, pages) => {
    expect(pageCount(total, size)).toBe(pages);
  });
  it('a nonsense count (negative, fractional, zero size) is one page, never NaN or 0', () => {
    expect([pageCount(-1, 20), pageCount(1.5, 20), pageCount(10, 0), pageCount(Number.NaN, 20)]).toEqual([1, 1, 1, 1]);
  });
});
