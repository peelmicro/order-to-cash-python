// The sweep and the page tests render the app in the Angular test bed with the harness's providers (browser-harness.ts).
// For that to be "as the browser does", the harness must mount every provider the real application config has.
import { describe, expect, it } from 'vitest';
import { appConfig } from './app.config';

/** The providers of app.config.ts, as last reviewed; browser-harness.ts mounts the same ones (the file-router, the title strategy, the query client). */
const REVIEWED_PROVIDERS = 5;

describe('the application config', () => {
  it('has exactly the providers the harness mirrors', () => {
    expect(appConfig.providers.length, 'a provider was added to app.config.ts: add it to src/app/testing/browser-harness.ts too, then update this count').toBe(REVIEWED_PROVIDERS);
  });
});
