// Money (SA-5, backlog 103): parse, format and step from the ISO 4217 table, digit-wise, exact for every safe integer.
// Expected strings are typed here, never produced by the function; every figure is non-round so "divide by 100" cannot pass by coincidence for the
// currencies whose exponent is not 2 (HUF 2 where CLDR says 0, IQD 3 where CLDR says 0, JPY 0, BHD 3, CLF 4).
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import { currencyInputStep, formatMoney, lineTotal, minorUnitsToDecimalString, parseAmount, parseDecimalToMinorUnits, sumMinorUnits, toDecimalString } from './money';

describe('R-parse: a typed decimal becomes exact integer minor units, never through a float', () => {
  it('the classic float traps: "0.29" -> 29, "19.99" -> 1999, "1.10" -> 110, "249.99" -> 24999, "4.35" -> 435, "1.15" -> 115', () => {
    // What the float route produces, to show these are the dangerous inputs:
    expect(Math.floor(Number('0.29') * 100)).toBe(28);
    expect(Number('19.99') * 100).not.toBe(1999);
    expect(Number('4.35') * 100).not.toBe(435);
    for (const [text, minor] of [['0.29', 29], ['19.99', 1999], ['1.10', 110], ['249.99', 24999], ['4.35', 435], ['1.15', 115]] as const) {
      expect(parseDecimalToMinorUnits(text, 2), text).toBe(minor);
    }
  });

  it('"1.005" is REJECTED for a 2-decimal currency (never rounded to 100 or 101) and is exactly 1005 for a 3-decimal one', () => {
    expect(parseAmount('1.005', 'EUR')).toBeUndefined();
    expect(parseAmount('1.005', 'BHD')).toBe(1005);
    expect(parseAmount('1.5', 'BHD')).toBe(1500);
  });

  it.each([
    ['', undefined], ['   ', undefined], ['-5', undefined], ['+5', undefined], ['1e3', undefined], ['1,000.00', undefined], ['NaN', undefined], ['20.', undefined], ['.', undefined],
    ['abc', undefined], ['1.2.3', undefined], ['٣', undefined], ['1 000', undefined], ['0x10', undefined],
    ['.99', 99], ['007.50', 750], ['  20.50  ', 2050], ['0', 0], ['0.00', 0], ['20', 2000], ['0.1', 10],
  ])('parseDecimalToMinorUnits(%j, 2) === %j', (input, expected) => {
    expect(parseDecimalToMinorUnits(input, 2)).toBe(expected);
  });

  it('exactly the safe-integer range: the maximum parses, one more minor unit is refused, for every exponent', () => {
    expect(parseDecimalToMinorUnits('90071992547409.91', 2)).toBe(9007199254740991);
    expect(parseDecimalToMinorUnits('90071992547409.92', 2)).toBeUndefined();
    expect(parseDecimalToMinorUnits('9007199254740.991', 3)).toBe(9007199254740991);
    expect(parseDecimalToMinorUnits('9007199254740.992', 3)).toBeUndefined();
    expect(parseDecimalToMinorUnits('9007199254740991', 0)).toBe(9007199254740991);
    expect(parseDecimalToMinorUnits('9007199254740992', 0)).toBeUndefined();
    expect(parseDecimalToMinorUnits('900719925474.0991', 4)).toBe(9007199254740991);
    expect(parseDecimalToMinorUnits('900719925474.0992', 4)).toBeUndefined();
  });

  it('round-trips every value in a wide range for every exponent: minor units -> decimal text -> the same minor units', () => {
    for (const exponent of [0, 2, 3, 4]) {
      for (let minor = 0; minor < 200_000; minor += 7) expect(parseDecimalToMinorUnits(minorUnitsToDecimalString(minor, exponent), exponent), `${minor} @${exponent}`).toBe(minor);
      for (const edge of [Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER - 1, 2 ** 52, 2 ** 52 + 1, 10 ** 15 + 1]) expect(parseDecimalToMinorUnits(minorUnitsToDecimalString(edge, exponent), exponent), `${edge} @${exponent}`).toBe(edge);
    }
  });
});

describe('R-format: human text from the table, in the backends\' shape (otc_shared_kernel.format_money)', () => {
  // The vectors of packages/shared_kernel/tests/test_money_text.py (its int64 maximum is not a safe integer; see below).
  it.each([
    [16130, 'EUR', '161.30 EUR'], [24999, 'EUR', '249.99 EUR'], [10055, 'GBP', '100.55 GBP'], [5, 'EUR', '0.05 EUR'], [0, 'USD', '0.00 USD'],
    [123456789, 'EUR', '1 234 567.89 EUR'], [100000, 'EUR', '1 000.00 EUR'], [999, 'EUR', '9.99 EUR'], [1234567, 'JPY', '1 234 567 JPY'],
    [1234, 'KWD', '1.234 KWD'], [12345, 'CLF', '1.2345 CLF'], [-5, 'EUR', '-0.05 EUR'], [-123456, 'EUR', '-1 234.56 EUR'],
  ])('formatMoney(%i, %s) === %j', (minor, currency, text) => {
    expect(formatMoney(minor, currency)).toBe(text);
  });

  it('HUF (2), IQD (3), JPY (0), BHD (3) and EUR (2) format through their own exponent, where CLDR says 0 for HUF and IQD', () => {
    expect(formatMoney(12345, 'HUF')).toBe('123.45 HUF');
    expect(formatMoney(12345, 'IQD')).toBe('12.345 IQD');
    expect(formatMoney(1999, 'JPY')).toBe('1 999 JPY');
    expect(formatMoney(1005, 'BHD')).toBe('1.005 BHD');
    expect(formatMoney(24999, 'EUR')).toBe('249.99 EUR');
  });

  it('HUF, IQD, JPY, BHD and EUR parse through their own exponent and refuse one digit more', () => {
    expect([parseAmount('123.45', 'HUF'), parseAmount('123.456', 'HUF')]).toEqual([12345, undefined]);
    expect([parseAmount('12.345', 'IQD'), parseAmount('12.3456', 'IQD')]).toEqual([12345, undefined]);
    expect([parseAmount('1999', 'JPY'), parseAmount('19.99', 'JPY'), parseAmount('1999.', 'JPY')]).toEqual([1999, undefined, undefined]);
    expect([parseAmount('1.005', 'BHD'), parseAmount('1.0055', 'BHD')]).toEqual([1005, undefined]);
    expect([parseAmount('249.99', 'EUR'), parseAmount('249.999', 'EUR')]).toEqual([24999, undefined]);
  });

  it('HUF, IQD, JPY, BHD and EUR give the input step of one minor unit', () => {
    expect(['HUF', 'IQD', 'JPY', 'BHD', 'EUR'].map(currencyInputStep)).toEqual(['0.01', '0.001', '1', '0.001', '0.01']);
  });

  it('plain decimals for inputs: no grouping, the currency\'s own decimals', () => {
    expect(toDecimalString(24999, 'EUR')).toBe('249.99');
    expect(toDecimalString(24999, 'JPY')).toBe('24999');
    expect([minorUnitsToDecimalString(5, 2), minorUnitsToDecimalString(0, 2), minorUnitsToDecimalString(-150, 2), minorUnitsToDecimalString(1005, 3), minorUnitsToDecimalString(12345, 4)]).toEqual(['0.05', '0.00', '-1.50', '1.005', '1.2345']);
  });

  it('exact for the safe-integer maximum and its neighbours, and a value that is not a safe integer is refused, not guessed', () => {
    expect(formatMoney(9007199254740991, 'EUR')).toBe('90 071 992 547 409.91 EUR');
    expect(formatMoney(-9007199254740991, 'EUR')).toBe('-90 071 992 547 409.91 EUR');
    expect(formatMoney(9007199254740991, 'JPY')).toBe('9 007 199 254 740 991 JPY');
    expect(formatMoney(9007199254740990, 'BHD')).toBe('9 007 199 254 740.990 BHD');
    expect(() => formatMoney(9007199254740992, 'EUR')).toThrow(RangeError);
    expect(() => formatMoney(1.5, 'EUR')).toThrow(RangeError);
    expect(() => formatMoney(Number.NaN, 'EUR')).toThrow(RangeError);
  });
});

describe('R-total: draft arithmetic is integer arithmetic and says so when it cannot be exact', () => {
  it('override over catalogue price, minus the line discount', () => {
    expect(lineTotal({ quantity: 3, unitPrice: 1999 }, 500)).toBe(5997);
    expect(lineTotal({ quantity: 3 }, 500)).toBe(1500);
    expect(lineTotal({ quantity: 2, lineDiscount: 50 }, 500)).toBe(950);
    expect(lineTotal({ quantity: 0 }, 500)).toBe(0);
    expect(lineTotal({ quantity: 2 }, undefined)).toBe(0);
  });
  it('a result outside the safe range is undefined (never an inexact number), and so is every sum that contains one', () => {
    expect(lineTotal({ quantity: 2, unitPrice: 9007199254740991 }, undefined)).toBeUndefined();
    expect(lineTotal({ quantity: 1, unitPrice: 9007199254740991 }, undefined)).toBe(9007199254740991);
    expect(sumMinorUnits([9007199254740991, 1])).toBeUndefined();
    expect(sumMinorUnits([9007199254740990, 1])).toBe(9007199254740991);
    expect(sumMinorUnits([5, undefined])).toBeUndefined();
    expect(sumMinorUnits([])).toBe(0);
  });
});

// ── The syntax of the money code: no float, no division, no locale data ────────────────────────────

const LIB = path.resolve(import.meta.dirname);
const APP = path.resolve(import.meta.dirname, '..', 'app');

function walk(dir: string, skip: (rel: string) => boolean): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!skip(full)) out.push(...walk(full, skip));
    } else if (entry.name.endsWith('.ts') && !entry.name.endsWith('.spec.ts')) out.push(full);
  }
  return out;
}

function violationsOf(source: string): string[] {
  const hits: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isBinaryExpression(node) && (node.operatorToken.kind === ts.SyntaxKind.SlashToken || node.operatorToken.kind === ts.SyntaxKind.SlashEqualsToken)) hits.push('division (/)');
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.AsteriskAsteriskToken) hits.push('exponentiation (**) of money');
    if (ts.isIdentifier(node) && ['parseFloat', 'toFixed', 'toLocaleString', 'toPrecision', 'Intl', 'NumberFormat', 'getNumberOfCurrencyDigits', 'CurrencyPipe', 'formatCurrency', 'getCurrencySymbol'].includes(node.text)) hits.push(node.text);
    if (ts.isPropertyAccessExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'Math' && ['round', 'floor', 'ceil', 'trunc', 'fround'].includes(node.name.text)) hits.push(`Math.${node.name.text}`);
    // A pipe inside a template string (the decorators' `template`): `{{ x | currency }}` or `[a]="x | number"`. Type unions are not strings, so they never match.
    if ((ts.isStringLiteralLike(node) || ts.isTemplateLiteral(node)) && /(\{\{|=")[^}"]*\|\s*(currency|number|decimal|percent)\b/.test(node.getText())) hits.push('number/currency pipe');
    ts.forEachChild(node, visit);
  };
  visit(ts.createSourceFile('money.ts', source, ts.ScriptTarget.Latest, true));
  return [...new Set(hits)].sort();
}

const violations = (file: string) => violationsOf(readFileSync(file, 'utf8'));

describe('R-no-float: the money code has no division, no float conversion and no locale data', () => {
  const moneyFiles = [path.join(LIB, 'money.ts'), path.join(LIB, 'currency-exponent.ts')];

  it('money.ts and currency-exponent.ts: the walk sees them, and the syntax tree holds none of: "/", "**", parseFloat, toFixed, Math.round/floor/ceil/trunc, Intl, getNumberOfCurrencyDigits, CurrencyPipe', () => {
    expect(moneyFiles.every((file) => readFileSync(file, 'utf8').length > 500)).toBe(true);
    expect(Object.fromEntries(moneyFiles.map((file) => [path.basename(file), violations(file)]))).toEqual({ 'money.ts': [], 'currency-exponent.ts': [] });
  });

  it('no file of the app or src/lib reaches for Intl, Angular\'s currency digits or the currency pipe (population: every non-test .ts under both, by directory walk)', () => {
    const population = [...walk(LIB, () => false), ...walk(APP, (full) => full.endsWith(`${path.sep}ui`) || full.endsWith(`${path.sep}testing`))];
    expect(population.length, 'the walk is vacuous').toBeGreaterThan(8);
    expect(Object.fromEntries(population.map((file) => [path.relative(path.dirname(LIB), file), violations(file).filter((hit) => !['division (/)', 'exponentiation (**) of money'].includes(hit))]).filter(([, hits]) => (hits as string[]).length > 0))).toEqual({});
  });

  it('the instrument itself sees each shape it claims to (sentinels: a guard must be seen to fail)', () => {
    const probe = 'const a = 5 / 2; let b = 1; b /= 3; const c = parseFloat("1.5"); const d = new Intl.NumberFormat("en"); const e = Math.round(1.5); const f = (1).toFixed(2); const g = `{{ x | currency }}`; const h = 2 ** 3;';
    expect(violationsOf(probe)).toEqual(['Intl', 'Math.round', 'NumberFormat', 'division (/)', 'exponentiation (**) of money', 'number/currency pipe', 'parseFloat', 'toFixed']);
    expect(violationsOf('type T = string | number | undefined; const s = "a | number"; // 5 / 2')).toEqual([]);
  });
});
