import { expect, test as setup } from '@playwright/test';

/**
 * Logs in ONCE, through the real UI (`/login`, the real form, the real `POST /api/auth/login` -> Gateway round trip), and saves the sealed session
 * cookie as `storageState`. The `chromium` project depends on this one, so the login flow is exercised for real exactly once per run and every scenario
 * starts authenticated. Field ids and button text read from `src/app/pages/login.page.ts` (`#username`, `#password`, "Sign in").
 */
const STORAGE_STATE = './test-results/.auth/operator.json';

setup('authenticate as the operator', async ({ page }) => {
  const username = process.env['GATEWAY_OPERATOR_USERNAME'] ?? 'operator';
  const password = process.env['GATEWAY_OPERATOR_PASSWORD'];
  if (!password) {
    throw new Error('GATEWAY_OPERATOR_PASSWORD is not set: run through `pnpm test:e2e` (it loads the root .env) or export it.');
  }

  await page.goto('/login');
  await page.locator('#username').fill(username);
  await page.locator('#password').fill(password);

  const submit = page.getByRole('button', { name: 'Sign in' });
  await expect(submit).toBeEnabled();
  await submit.click();

  // Real navigation away from /login into the authenticated area; the app redirects any unauthenticated request straight back.
  await expect(page).toHaveURL(/\/orders$/);

  await page.context().storageState({ path: STORAGE_STATE });
});
