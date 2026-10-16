/// <reference types="vitest" />

import { defineConfig } from 'vite';
import analog from '@analogjs/platform';
import tailwindcss from '@tailwindcss/vite';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  build: {
    target: ['es2020'],
  },
  resolve: {
    mainFields: ['module'],
    // Vite 8 resolves tsconfig `paths` natively; vite-tsconfig-paths is not used (Phase 1 finding).
    tsconfigPaths: true,
  },
  plugins: [
    // ssr: false is a decision, not a default: every page sits behind a cookie session whose data comes from the
    // BFF, so there is nothing to render on the server and no Angular TransferState to carry state (or a token)
    // into the page. The Nitro server still runs, as the BFF (src/server/**) and as the static host.
    // prerender.routes: [] stops Analog's default prerender of '/', which would need the SSR build.
    analog({ ssr: false, prerender: { routes: [] } }),
    tailwindcss(),
  ],
  test: {
    globals: true,
    reporters: ['default'],
    // Two projects: the BFF and the build-level suites run in plain Node (real sockets, no DOM);
    // the Angular suites run in jsdom with the Angular test bed.
    projects: [
      {
        extends: true,
        test: {
          name: 'server',
          environment: 'node',
          include: ['src/server/**/*.spec.ts', 'src/lib/**/*.spec.ts', 'src/shared/**/*.spec.ts', 'scripts/**/*.spec.ts', 'src/build/**/*.spec.ts'],
          // The production-build suite builds the app and starts it (see src/build/production-bff.spec.ts).
          testTimeout: 60_000,
          hookTimeout: 240_000,
        },
      },
      {
        extends: true,
        test: {
          name: 'app',
          environment: 'jsdom',
          setupFiles: ['src/test-setup.ts'],
          // @analogjs/router holds a placeholder for the page glob that only the Vite transform fills in: it must be
          // inlined, or provideFileRouter() would see no pages at all ("Cannot match any routes").
          server: { deps: { inline: [/analogjs/] } },
          include: ['src/app/**/*.spec.ts'],
          testTimeout: 60_000,
        },
      },
    ],
  },
}));
