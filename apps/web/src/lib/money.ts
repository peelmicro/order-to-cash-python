import { currencyExponent } from './currency-exponent';

export { currencyExponent, currencyInputStep } from './currency-exponent';

/**
 * Money at the human edge (SA-5). Every amount on the wire is an integer count of minor units; this module is the only place a
 * typed decimal becomes one, or one becomes text, and it does both DIGIT-WISE: the whole and fractional digits are joined as text
 * and converted to an integer once. No floating-point step exists: no `/`, no `parseFloat`, no rounding, no `toFixed`, no `Intl`
 * (`0.29 * 100` is `28.999999999999996`; #7 shipped that bug, review pass 5). `src/lib/money.spec.ts` scans this file's syntax tree
 * for each of those.
 *
 * Exact for every safe integer: a value is accepted only when it is at most `Number.MAX_SAFE_INTEGER`, checked on the digits
 * with BigInt before the single conversion to `number`; arithmetic across lines runs in BigInt too and answers `undefined`
 * when the result leaves the safe range, never an inexact number.
 */

const MAX_SAFE = BigInt(Number.MAX_SAFE_INTEGER);
const DIGITS = /^\d+$/;

function toSafeInteger(digits: string): number | undefined {
  const value = BigInt(digits);
  return value <= MAX_SAFE ? Number(value) : undefined;
}

/**
 * A typed decimal (`"19.99"`) as integer minor units (`1999`) for a currency whose exponent is `exponent`. `undefined`, never a
 * wrong number, for: blank, a sign, scientific notation, a separator other than one `.`, more fractional digits than the currency
 * has (`"1.005"` in EUR), any fractional digit in a 0-exponent currency, a lone `.`, a trailing `.`, and anything above the safe range.
 */
export function parseDecimalToMinorUnits(input: string, exponent: number): number | undefined {
  const text = input.trim();
  const dot = text.indexOf('.');
  const whole = dot < 0 ? text : text.slice(0, dot);
  const fraction = dot < 0 ? '' : text.slice(dot + 1);
  if (dot >= 0 && (exponent === 0 || fraction === '' || fraction.length > exponent || text.indexOf('.', dot + 1) >= 0)) return undefined;
  if (whole === '' && fraction === '') return undefined;
  if ((whole !== '' && !DIGITS.test(whole)) || (fraction !== '' && !DIGITS.test(fraction))) return undefined;
  return toSafeInteger(`${whole}${fraction.padEnd(exponent, '0')}`);
}

/** {@link parseDecimalToMinorUnits} with the exponent looked up from the currency code. */
export function parseAmount(input: string, currency: string): number | undefined {
  return parseDecimalToMinorUnits(input, currencyExponent(currency));
}

function assertSafe(minorUnits: number): void {
  if (!Number.isSafeInteger(minorUnits)) throw new RangeError(`money: ${String(minorUnits)} is not a safe integer count of minor units`);
}

/** Integer minor units as the plain decimal an input shows (`24999, 2` -> `"249.99"`; `5, 2` -> `"0.05"`; `1999, 0` -> `"1999"`). */
export function minorUnitsToDecimalString(minorUnits: number, exponent: number): string {
  assertSafe(minorUnits);
  const digits = String(Math.abs(minorUnits)).padStart(exponent + 1, '0');
  const split = digits.length - exponent;
  const body = exponent === 0 ? digits : `${digits.slice(0, split)}.${digits.slice(split)}`;
  return minorUnits < 0 ? `-${body}` : body;
}

export function toDecimalString(minorUnits: number, currency: string): string {
  return minorUnitsToDecimalString(minorUnits, currencyExponent(currency));
}

/**
 * Minor units for people, in the one shape the backends write timeline text in (`otc_shared_kernel.format_money`): groups of
 * three joined by a space, the currency's own number of decimals, the ISO code after the amount: `124250, "EUR"` -> `"1 242.50 EUR"`.
 */
export function formatMoney(minorUnits: number, currency: string): string {
  const code = currency.trim().toUpperCase();
  const decimal = minorUnitsToDecimalString(Math.abs(minorUnits), currencyExponent(code));
  const dot = decimal.indexOf('.');
  const whole = dot < 0 ? decimal : decimal.slice(0, dot);
  const grouped = whole.replace(/\B(?=(\d{3})+$)/g, ' ');
  return `${minorUnits < 0 ? '-' : ''}${grouped}${dot < 0 ? '' : decimal.slice(dot)} ${code}`;
}

export interface DraftLineAmounts {
  quantity: number;
  /** The typed override, or undefined for the catalogue price. */
  unitPrice?: number | undefined;
  lineDiscount?: number | undefined;
}

/** One line: price x quantity - discount, in BigInt; `undefined` when the result is outside the safe-integer range (the server's total is the authority). */
export function lineTotal(line: DraftLineAmounts, catalogPrice: number | undefined): number | undefined {
  const price = BigInt(line.unitPrice ?? catalogPrice ?? 0);
  const quantity = BigInt(Number.isSafeInteger(line.quantity) && line.quantity > 0 ? line.quantity : 0);
  const total = price * quantity - BigInt(line.lineDiscount ?? 0);
  return total >= -MAX_SAFE && total <= MAX_SAFE ? Number(total) : undefined;
}

/** A sum of line totals; `undefined` as soon as any part is, or the sum leaves the safe range. */
export function sumMinorUnits(parts: ReadonlyArray<number | undefined>): number | undefined {
  let sum = 0n;
  for (const part of parts) {
    if (part === undefined) return undefined;
    sum += BigInt(part);
  }
  return sum >= -MAX_SAFE && sum <= MAX_SAFE ? Number(sum) : undefined;
}
