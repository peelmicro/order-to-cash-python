// Measures, once and by script, how far the platform's CLDR currency digits disagree with the ISO 4217 table the web carries
// (src/lib/currency-exponents.json, SA-5). Not a test and not part of the build: its output is recorded in progress/impl_web_app.md.
// Run: node scripts/cldr-disagreement.mjs
import { readFileSync } from 'node:fs';

const table = JSON.parse(readFileSync(new URL('../src/lib/currency-exponents.json', import.meta.url), 'utf8'));
const iso = (code) => table[code] ?? 2;
const cldr = (code) => new Intl.NumberFormat('en', { style: 'currency', currency: code }).resolvedOptions().maximumFractionDigits;

const listed = Object.keys(table).map((code) => ({ code, iso: iso(code), cldr: cldr(code) }));
const listedWrong = listed.filter((row) => row.iso !== row.cldr);
const supported = Intl.supportedValuesOf('currency');
const allWrong = supported.map((code) => ({ code, iso: iso(code), cldr: cldr(code) })).filter((row) => row.iso !== row.cldr);

console.log(`node ${process.version}, ICU ${process.versions.icu}, CLDR ${process.versions.cldr}`);
console.log(`table rows: ${listed.length}; CLDR disagrees on ${listedWrong.length} of them: ${listedWrong.map((row) => `${row.code} (ISO ${row.iso}, CLDR ${row.cldr})`).join(', ')}`);
console.log(`Intl.supportedValuesOf('currency'): ${supported.length} codes; CLDR disagrees with the table (listed rows, default 2 elsewhere) on ${allWrong.length}: ${allWrong.map((row) => `${row.code} (ISO ${row.iso}, CLDR ${row.cldr})`).join(', ')}`);

// Angular's own table (the one CurrencyPipe uses) is CLDR data too.
await import('@angular/compiler');
const { getNumberOfCurrencyDigits } = await import('@angular/common');
const angularWrong = supported.map((code) => ({ code, iso: iso(code), angular: getNumberOfCurrencyDigits(code) })).filter((row) => row.iso !== row.angular);
console.log(`Angular getNumberOfCurrencyDigits over the same ${supported.length} codes disagrees with the table on ${angularWrong.length}: ${angularWrong.map((row) => `${row.code} (ISO ${row.iso}, Angular ${row.angular})`).join(', ')}`);
