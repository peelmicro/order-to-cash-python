import { currencyExponent, formatMoney, minorUnitsToDecimalString, parseDecimalToMinorUnits } from '../../lib/money';

/** An instant for people: `2026-10-15 10:00:12 UTC` from the wire's `YYYY-MM-DDTHH:MM:SS.mmmZ`. Text surgery, no `Date` and no `Intl`: the wire form is already UTC. */
export function formatInstant(instant: string | undefined): string {
  if (!instant) return '—';
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?Z$/.exec(instant);
  return match ? `${match[1]} ${match[2]} UTC` : instant;
}

/** Money for a table cell: the table's text, or a dash for a value that is not an exact count of minor units (the wire guarantees one; a page must not crash on a bad row). */
export function displayMoney(minorUnits: number | undefined, currency: string | undefined): string {
  if (minorUnits === undefined || currency === undefined) return '—';
  try {
    return formatMoney(minorUnits, currency);
  } catch {
    return '—';
  }
}

/**
 * What a refused money text should have been, as the end of "Enter …" (stage 3 review A2): a text that is well formed for the currency (digits, at most its decimals)
 * but too large is refused for its SIZE, naming the largest amount the page can send, not for decimals it does not have.
 */
export function amountPhrase(text: string, currency: string): string {
  const exponent = currencyExponent(currency);
  const wellFormed = new RegExp(exponent === 0 ? '^\\d+$' : `^(\\d+(\\.\\d{1,${exponent}})?|\\.\\d{1,${exponent}})$`).test(text.trim());
  if (wellFormed && parseDecimalToMinorUnits(text, exponent) === undefined) return `an amount of at most ${minorUnitsToDecimalString(Number.MAX_SAFE_INTEGER, exponent)}`;
  if (exponent === 0) return 'a whole amount';
  return `an amount with at most ${exponent} decimal${exponent === 1 ? '' : 's'}`;
}
