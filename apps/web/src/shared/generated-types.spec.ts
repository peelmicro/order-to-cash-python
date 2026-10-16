// The generated OpenAPI types are consumed through ONE module (src/shared/api-types.ts), by the browser
// client and by the BFF. Population: every source file under src/ read off the disk.
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = path.resolve(import.meta.dirname, '..');

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) sourceFiles(full, out);
    else if (/\.ts$/.test(entry.name)) out.push(full);
  }
  return out;
}

describe('the generated types have one importer', () => {
  const files = sourceFiles(SRC).map((f) => path.relative(SRC, f).split(path.sep).join('/'));
  const importers = files.filter((rel) => /from\s+['"][^'"]*generated\/openapi['"]/.test(readFileSync(path.join(SRC, rel), 'utf8')));

  it('only src/shared/api-types.ts (and the sweep helper that parses the file as text) names generated/openapi', () => {
    expect(files.length).toBeGreaterThan(20);
    expect(importers).toEqual(['shared/api-types.ts']);
  });

  it('the browser client and the BFF both take their wire shapes from it', () => {
    const consumers = (dir: string) => files.filter((rel) => rel.startsWith(dir) && /shared\/api-types'/.test(readFileSync(path.join(SRC, rel), 'utf8')));
    expect(consumers('app/api/'), 'the API client does not use the generated types').toContain('app/api/api-client.ts');
    expect(consumers('server/lib/') .length, 'the BFF does not use the generated types').toBeGreaterThan(0);
  });
});
