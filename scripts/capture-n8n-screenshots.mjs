// Drives Chromium against the throwaway n8n started by capture-n8n-screenshots.sh and saves the README images.
// @playwright/test is resolved from apps/web (no root package.json exists), through createRequire.
// Arguments come from the environment set by the shell script: N8N_URL, DEMO_EMAIL, DEMO_PASSWORD, OUT_DIR.
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, '..', 'apps', 'web', 'package.json'));
const { chromium } = require('@playwright/test');

const { N8N_URL, DEMO_EMAIL, DEMO_PASSWORD, OUT_DIR } = process.env;
const workflows = [
  ['otcOrderGenerator', 'n8n-1-order-generator.png'],
  ['otcPaymentRobot', 'n8n-2-payment-robot.png'],
  ['otcStockReplenishment', 'n8n-3-stock-replenishment.png'],
  ['otcBurst', 'n8n-4-burst.png'],
];

// Any onboarding / survey / "what's new" dialog: close it, whatever it is called.
async function dismissModals(page) {
  for (let i = 0; i < 4; i += 1) {
    const dialog = page.locator('[role="dialog"]').first();
    if (!(await dialog.isVisible().catch(() => false))) return;
    const close = dialog.locator('button:has-text("Skip"), button:has-text("Get started"), button:has-text("Close"), button:has-text("Got it"), [aria-label="Close"], button.el-dialog__headerbtn').first();
    if (await close.isVisible().catch(() => false)) await close.click().catch(() => {});
    else await page.keyboard.press('Escape');
    await page.waitForTimeout(500);
  }
}

const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-US' });
  const page = await context.newPage();
  const login = await page.request.post(`${N8N_URL}/rest/login`, { data: { emailOrLdapLoginId: DEMO_EMAIL, password: DEMO_PASSWORD } });
  if (!login.ok()) throw new Error(`n8n login failed: ${login.status()}`);

  await page.goto(`${N8N_URL}/home/workflows`);
  await page.getByText('Order Generator').first().waitFor({ timeout: 30000 });
  await page.getByText('Burst').first().waitFor({ timeout: 30000 });
  await dismissModals(page);
  await page.screenshot({ path: path.join(OUT_DIR, 'n8n-workflows.png') });

  for (const [id, file] of workflows) {
    await page.goto(`${N8N_URL}/workflow/${id}`);
    await page.locator('.vue-flow__node').first().waitFor({ timeout: 30000 });
    await dismissModals(page);
    await page.locator('.vue-flow').first().click({ position: { x: 700, y: 700 }, force: true }).catch(() => {});
    await page.keyboard.press('1'); // n8n's "zoom to fit"
    await page.waitForTimeout(1200);
    await dismissModals(page);
    await page.screenshot({ path: path.join(OUT_DIR, file) });
  }
} finally {
  await browser.close();
}
