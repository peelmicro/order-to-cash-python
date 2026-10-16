// SA-5 on the web side: the exponent table is the ISO 4217 one, read from the JSON that packages/shared_kernel/tests/test_currency_exponent.py
// compares with the Python table in both directions. This file is the other half of that parity: the same 26 rows typed here as a literal, so a one-row
// corruption of the JSON fails a web test AND the Python one, each naming the code. (#8 id 103 read its exponent from Intl, which disagrees; #8's
// first parity guard parsed source text and lost three ways; the instrument here is a comparison of data, not of text.)
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { currencyExponent, currencyInputStep, nonDefaultExponents } from './currency-exponent';

const JSON_PATH = path.resolve(import.meta.dirname, 'currency-exponents.json');

/** ISO 4217, typed from the standard (the zero-, three- and four-decimal sets), NOT derived from the file under test. */
const ISO_4217_NON_DEFAULT: Record<string, number> = {
  BIF: 0, CLP: 0, DJF: 0, GNF: 0, ISK: 0, JPY: 0, KMF: 0, KRW: 0, PYG: 0, RWF: 0, UGX: 0, VND: 0, VUV: 0, XAF: 0, XOF: 0, XPF: 0,
  BHD: 3, IQD: 3, JOD: 3, KWD: 3, LYD: 3, OMR: 3, TND: 3,
  CLF: 4, UYW: 4,
  UYI: 0,
};

describe('currency-exponents.json is the ISO 4217 table (R-parity, web side)', () => {
  it('every one of the 26 rows is the literal row, and no row is missing or extra: the failure names the code', () => {
    const raw = JSON.parse(readFileSync(JSON_PATH, 'utf8')) as Record<string, unknown>;
    const problems: string[] = [];
    for (const code of Object.keys(ISO_4217_NON_DEFAULT)) if (!(code in raw)) problems.push(`${code}: in the literal, missing from the JSON`);
    for (const code of Object.keys(raw)) if (!(code in ISO_4217_NON_DEFAULT)) problems.push(`${code}: in the JSON, missing from the literal`);
    for (const [code, exponent] of Object.entries(ISO_4217_NON_DEFAULT)) if (code in raw && raw[code] !== exponent) problems.push(`${code}: ISO 4217 says ${exponent}, the JSON says ${JSON.stringify(raw[code])}`);
    expect(problems.sort()).toEqual([]);
    expect(Object.keys(ISO_4217_NON_DEFAULT)).toHaveLength(26);
  });

  it('a key written twice is a divergence (JSON.parse keeps the last one silently)', () => {
    const keys = [...readFileSync(JSON_PATH, 'utf8').matchAll(/"([A-Z]{3})"\s*:/g)].map((match) => match[1]!);
    expect(keys.filter((key, index) => keys.indexOf(key) !== index)).toEqual([]);
    expect(keys).toHaveLength(26);
  });

  it('the module serves exactly the file on disk, read independently of its import', () => {
    expect(nonDefaultExponents()).toEqual(JSON.parse(readFileSync(JSON_PATH, 'utf8')));
  });

  it('the table never lists the default exponent', () => {
    expect(Object.values(nonDefaultExponents()).filter((exponent) => exponent === 2)).toEqual([]);
  });
});

describe('currencyExponent and currencyInputStep (R-step: the input step follows the exponent)', () => {
  it.each([
    ['EUR', 2, '0.01'],
    ['GBP', 2, '0.01'],
    ['USD', 2, '0.01'],
    ['HUF', 2, '0.01'],
    ['JPY', 0, '1'],
    ['BHD', 3, '0.001'],
    ['IQD', 3, '0.001'],
    ['KWD', 3, '0.001'],
    ['CLF', 4, '0.0001'],
    ['UYI', 0, '1'],
    ['ZZZ', 2, '0.01'],
  ])('%s has exponent %i and step %s', (code, exponent, step) => {
    expect(currencyExponent(code)).toBe(exponent);
    expect(currencyInputStep(code)).toBe(step);
  });

  it('is case-insensitive and ignores surrounding space', () => {
    expect([currencyExponent('jpy'), currencyExponent(' bhd '), currencyInputStep('iqd')]).toEqual([0, 3, '0.001']);
  });

  it('a key of Object.prototype is not a currency: the answer is the default, a number, never a function', () => {
    for (const word of ['constructor', '__proto__', 'toString', 'hasOwnProperty', 'valueOf']) {
      expect(currencyExponent(word), word).toBe(2);
      expect(currencyInputStep(word), word).toBe('0.01');
    }
  });
});
