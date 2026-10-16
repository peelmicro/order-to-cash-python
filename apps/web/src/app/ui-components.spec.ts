// Acceptance: spartan/ui and TanStack Query for Angular are really in use. The spartan generator exits 0 having
// generated nothing unless components.json exists (CLAUDE.md, Environment notes), so the ARTIFACT is checked, not the exit code.
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const WEB = path.resolve(import.meta.dirname, '..', '..');
const read = (rel: string) => readFileSync(path.join(WEB, rel), 'utf8');

describe('spartan/ui (generated into the app, helm layer)', () => {
  const config = JSON.parse(read('components.json')) as { componentsPath: string; importAlias: string };

  it('components.json exists and names where the components live', () => {
    expect(config.componentsPath).toBe('src/app/ui');
    expect(config.importAlias).toBe('@spartan-ng/helm');
  });

  it('the generated components are on disk with their sources, and tsconfig maps their import alias to each', () => {
    const tsconfig = JSON.parse(read('tsconfig.json')) as { compilerOptions: { paths: Record<string, string[]> } };
    const dirs = readdirSync(path.join(WEB, config.componentsPath), { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => e.name).sort();
    expect(dirs, 'the generator wrote nothing (or a component was removed)').toEqual(['alert', 'badge', 'button', 'card', 'input', 'label', 'table', 'utils']);
    for (const dir of dirs) {
      expect(existsSync(path.join(WEB, config.componentsPath, dir, 'src', 'index.ts')), `${dir}/src/index.ts`).toBe(true);
      expect(tsconfig.compilerOptions.paths[`${config.importAlias}/${dir}`], `tsconfig path for ${dir}`).toEqual([`./${config.componentsPath}/${dir}/src/index.ts`]);
    }
  });

  it('the login page and the shell are built from them', () => {
    for (const page of ['src/app/pages/login.page.ts', 'src/app/pages/(app).page.ts']) expect(read(page), page).toMatch(/from '@spartan-ng\/helm\/(button|alert|card|input|label)'/);
  });

  it('the styles load Tailwind v4 and the spartan preset', () => {
    const css = read('src/styles.css');
    expect(css).toContain("@import 'tailwindcss/utilities.css'");
    expect(css).toContain('@spartan-ng/brain/hlm-tailwind-preset.css');
    expect(read('vite.config.ts')).toContain("from '@tailwindcss/vite'");
  });
});

describe('TanStack Query for Angular', () => {
  const pkg = JSON.parse(read('package.json')) as { dependencies: Record<string, string>; devDependencies: Record<string, string> };

  it('is pinned to an exact version (no range), and the lockfile resolves to the same one', () => {
    const version = pkg.dependencies['@tanstack/angular-query-experimental'];
    expect(version, 'a range would let the lockfile drift silently').toMatch(/^\d+\.\d+\.\d+$/);
    expect(read('pnpm-lock.yaml')).toContain(`'@tanstack/angular-query-experimental@${version}'`);
  });

  it('every runtime library added in feature 29 is pinned exactly', () => {
    const added = ['@angular/cdk', '@spartan-ng/brain', '@tanstack/angular-query-experimental', 'class-variance-authority', 'clsx', 'tailwind-merge', 'tw-animate-css'];
    expect(added.filter((name) => !/^\d+\.\d+\.\d+$/.test(pkg.dependencies[name] ?? '')), 'unpinned runtime libraries').toEqual([]);
    const dev = ['@spartan-ng/cli', '@tailwindcss/vite', '@testing-library/dom', 'openapi-typescript', 'tailwindcss', 'eventsource'];
    expect(dev.filter((name) => !/^\d+\.\d+\.\d+$/.test(pkg.devDependencies[name] ?? '')), 'unpinned dev libraries').toEqual([]);
  });
});
