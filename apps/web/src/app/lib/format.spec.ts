import { describe, expect, it } from 'vitest';
import { displayMoney, formatInstant } from './format';

describe('formatInstant: the wire\'s UTC instant as text, without Date or Intl', () => {
  it.each([
    ['2026-10-15T10:00:12.345Z', '2026-10-15 10:00:12 UTC'],
    ['2026-01-02T03:04:05Z', '2026-01-02 03:04:05 UTC'],
    ['2026-12-31T23:59:59.999Z', '2026-12-31 23:59:59 UTC'],
  ])('%s -> %s', (wire, text) => {
    expect(formatInstant(wire)).toBe(text);
  });
  it('anything else is shown as it came (never invented), and a missing instant is a dash', () => {
    expect(formatInstant('yesterday')).toBe('yesterday');
    expect(formatInstant(undefined)).toBe('—');
    expect(formatInstant('2026-10-15T10:00:12+02:00')).toBe('2026-10-15T10:00:12+02:00');
  });
});

describe('displayMoney: a table cell never crashes the page', () => {
  it('formats exact counts and shows a dash for a missing value or one that is not an exact count', () => {
    expect(displayMoney(124250, 'EUR')).toBe('1 242.50 EUR');
    expect(displayMoney(undefined, 'EUR')).toBe('—');
    expect(displayMoney(5, undefined)).toBe('—');
    expect(displayMoney(1.5, 'EUR')).toBe('—');
    expect(displayMoney(Number.NaN, 'EUR')).toBe('—');
    expect(displayMoney(9007199254740992, 'EUR')).toBe('—');
  });
});
