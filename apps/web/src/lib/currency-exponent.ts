import nonDefaultTable from './currency-exponents.json';

/**
 * ISO 4217's minor-unit exponent of a currency code (SA-5, `specs/shared/openapi.yaml` Money section): a property of the code
 * itself, never of a locale. The table is `./currency-exponents.json`, the ONE committed copy for the web, which
 * `packages/shared_kernel/tests/test_currency_exponent.py` compares with the Python table in both directions. Neither `Intl`
 * (ICU/CLDR display digits) nor Angular's `getNumberOfCurrencyDigits` / `CurrencyPipe` (the same CLDR data) is consulted
 * anywhere: `scripts/cldr-disagreement.mjs` measured how far they diverge, and `src/lib/money.spec.ts` fails if a source file
 * reaches for either. Only the codes whose exponent is not 2 are listed; every other code defaults to 2.
 */
export const DEFAULT_EXPONENT = 2;

const TABLE: ReadonlyMap<string, number> = new Map(Object.entries(nonDefaultTable));

/** The listed (non-default) codes, for tests; a copy, so a caller cannot change the table. */
export function nonDefaultExponents(): Record<string, number> {
  return Object.fromEntries(TABLE);
}

/**
 * The exponent of `currency` (case-insensitive, surrounding space ignored). A Map lookup, not an object lookup: a plain object
 * answers `constructor` or `__proto__` with a function, which would flow into the arithmetic as a "number".
 */
export function currencyExponent(currency: string): number {
  return TABLE.get(currency.trim().toUpperCase()) ?? DEFAULT_EXPONENT;
}

/** The `step` of a money `<input type="number">` for `currency`: one minor unit (`"0.01"` for EUR, `"1"` for JPY, `"0.001"` for BHD, `"0.0001"` for CLF). */
export function currencyInputStep(currency: string): string {
  const exponent = currencyExponent(currency);
  return exponent === 0 ? '1' : `0.${'1'.padStart(exponent, '0')}`;
}
