import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end tests drive the real stack: `scripts/dev-stack.sh up` at the repository root (infrastructure containers, the six services as
 * `uv run` host processes, the web app built and served by `scripts/serve.mjs`). Playwright's own `webServer` option is deliberately not used:
 * #9 has no composed stack until phase 23, so the script is today's equivalent (#8 did the same, #8's `playwright.config.ts` header).
 *
 * Base URL: `E2E_BASE_URL` if set, else `http://localhost:${WEB_PORT}` (3010 when `WEB_PORT` is unset too, `serve.mjs`'s default). `.env` is
 * the source of truth for `WEB_PORT` (the `test:e2e` script loads it), so the suite runs unchanged against another stack by exporting
 * `E2E_BASE_URL` (feature 36 runs it against the composed one).
 */
const baseURL = process.env['E2E_BASE_URL'] ?? `http://localhost:${process.env['WEB_PORT'] ?? 3010}`;

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: {
    // The saga crosses six services over Kafka, NATS and MongoDB and settles in about a second locally, but this is a shared dev box, not a
    // dedicated runner: the auto-waiting assertion timeout is generous, never a way to paper over a race (see the synchronisation rule in
    // happy-path.spec.ts: wait only for terminal or monotonic facts).
    timeout: 30_000,
  },
  // Deliberately 0: a suite that "passes on retry" teaches people to re-run rather than investigate. A failure is a finding until its mechanism is shown.
  retries: 0,
  fullyParallel: true,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'setup', testMatch: /global\.setup\.ts/ },
    {
      name: 'chromium',
      testIgnore: /global\.setup\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        // Under test-results/ so the sealed session cookie is covered by the existing `.gitignore` entry and never needs its own.
        storageState: './test-results/.auth/operator.json',
      },
      dependencies: ['setup'],
    },
  ],
});
