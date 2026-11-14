import { expect, test, type Page } from '@playwright/test';

/**
 * #8 id 106 on the live DOM: a label's `for` must name its control's `id`. #8's place-order form derived both from a module-scope counter that
 * free-ran across every server render, so after a few loads the server wrote `for="product-7"` and the browser `id="product-2"`. In #9 both come from
 * ONE function of the line's key (`fieldId(line, field)` in `place.page.ts`; the key counter is the component's own and restarts at 1 for every form), and
 * this proves it on the running app: five hard loads (a `goto` each, the server rendering every time), and on every load all four per-line fields.
 * The last load adds a second line, so two rows prove their pairs are each other's and not one shared id.
 */
const FIELDS = [
  { label: 'Product', tag: 'select', testId: undefined },
  { label: 'Quantity', tag: 'input', testId: 'quantity-input' },
  { label: 'Unit price override', tag: 'input', testId: 'unit-price-input' },
  { label: 'Line discount', tag: 'input', testId: 'line-discount-input' },
] as const;

async function expectEveryLabelNamesItsOwnControl(page: Page, lineCount: number): Promise<void> {
  const rows = page.getByTestId('order-line');
  await expect(rows).toHaveCount(lineCount);
  // The real <select> for Product only exists once the catalogue has answered; before that a text <input> shares the label.
  await expect(rows.first().getByLabel('Product', { exact: true })).toHaveJSProperty('tagName', 'SELECT');
  for (let row = 0; row < lineCount; row++) {
    for (const field of FIELDS) {
      const line = rows.nth(row);
      const label = line.locator('label', { hasText: field.label });
      await expect(label, `row ${row + 1} has exactly one "${field.label}" label`).toHaveCount(1);
      const forAttribute = await label.getAttribute('for');
      expect(forAttribute, `row ${row + 1} "${field.label}" label has a for attribute`).toBeTruthy();
      // The control the label names, found by id in the whole document, must be a control of THIS row and of the right kind.
      const control = page.locator(`[id="${forAttribute}"]`);
      await expect(control, `the id "${forAttribute}" named by row ${row + 1}'s "${field.label}" label exists exactly once`).toHaveCount(1);
      await expect(line.locator(`[id="${forAttribute}"]`), `"${forAttribute}" is a control inside row ${row + 1}`).toHaveCount(1);
      await expect(control).toHaveJSProperty('tagName', field.tag.toUpperCase());
      if (field.testId) await expect(control).toHaveAttribute('data-testid', field.testId);
      // And the browser agrees: the label's `.control` is that element, and a label-based locator reaches it.
      expect(await label.evaluate((node) => (node as HTMLLabelElement).control?.id), `row ${row + 1} "${field.label}" label.control`).toBe(forAttribute);
      await expect(line.getByLabel(field.label, { exact: true })).toHaveCount(1);
    }
  }
}

test('id 106: across five hard loads, every per-line label names its own control (all four fields; two lines on the last load)', async ({ page }) => {
  for (let load = 1; load <= 5; load++) {
    await page.goto('/orders/place');
    if (load === 5) {
      await page.getByRole('button', { name: 'Add line' }).click();
      await expectEveryLabelNamesItsOwnControl(page, 2);
    } else {
      await expectEveryLabelNamesItsOwnControl(page, 1);
    }
  }
});
