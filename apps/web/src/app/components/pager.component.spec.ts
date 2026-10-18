// The Pager as a COMPONENT (Angular Testing Library's render + screen): what it renders, the enabled state of Previous / Next, and the click output.
// pager.spec.ts covers only the pure `pageCount`; the pages' own specs cover the pager inside a page.
import { render, screen } from '@testing-library/angular';
import { fireEvent } from '@testing-library/dom';
import { describe, expect, it, vi } from 'vitest';
import { Pager, type PageCounts } from './pager';

// A disabled button: HTMLElement.click() is inert on it, as in a browser; a synthetic dispatched MouseEvent (fireEvent.click) is NOT suppressed by jsdom, so it is used only on enabled buttons.
const button = (name: string) => screen.getByRole<HTMLButtonElement>('button', { name });

async function mount(counts: PageCounts | undefined, current: number, extra: Record<string, unknown> = {}) {
  const pageChange = vi.fn<(page: number) => void>();
  await render(Pager, { inputs: { counts, current, noun: 'orders', ...extra }, on: { pageChange } });
  return pageChange;
}

describe('R-pager-component: the Pager renders its count and enables Previous / Next by position', () => {
  it('in the middle: the count reads "Page 2 of 3 · 45 orders", both buttons are enabled, and each click emits the neighbouring page', async () => {
    const pageChange = await mount({ page: 2, pageSize: 20, total: 45 }, 2);
    expect(screen.getByTestId('pager-count').textContent).toBe('Page 2 of 3 · 45 orders');
    expect(button('Previous').disabled).toBe(false);
    expect(button('Next').disabled).toBe(false);
    fireEvent.click(button('Next'));
    fireEvent.click(button('Previous'));
    expect(pageChange.mock.calls.map((call) => call[0])).toEqual([3, 1]);
  });

  it('on the first page Previous is disabled and a click emits nothing; Next is enabled', async () => {
    const pageChange = await mount({ page: 1, pageSize: 20, total: 45 }, 1);
    expect(button('Previous').disabled).toBe(true);
    expect(button('Next').disabled).toBe(false);
    button('Previous').click();
    expect(pageChange).not.toHaveBeenCalled();
  });

  it('on the last page Next is disabled and a click emits nothing; Previous is enabled', async () => {
    const pageChange = await mount({ page: 3, pageSize: 20, total: 45 }, 3);
    expect(button('Next').disabled).toBe(true);
    expect(button('Previous').disabled).toBe(false);
    button('Next').click();
    expect(pageChange).not.toHaveBeenCalled();
  });

  it('an empty result reads "Page 1 of 1 · 0 orders" with both buttons disabled', async () => {
    await mount({ page: 1, pageSize: 20, total: 0 }, 1);
    expect(screen.getByTestId('pager-count').textContent).toBe('Page 1 of 1 · 0 orders');
    expect([button('Previous').disabled, button('Next').disabled]).toEqual([true, true]);
  });

  it('while the page is not known (counts undefined) it claims NO count and both buttons are disabled, even at page 2', async () => {
    await mount(undefined, 2);
    expect(screen.getByTestId('pager-count').textContent).toBe('');
    expect([button('Previous').disabled, button('Next').disabled]).toEqual([true, true]);
  });

  it('a named pager labels its landmark and its buttons after it; the default keeps plain Previous / Next', async () => {
    await mount({ page: 2, pageSize: 20, total: 45 }, 2, { label: 'Invoices pagination', testId: 'invoices-pager' });
    expect(screen.getByRole('navigation', { name: 'Invoices pagination' }).getAttribute('data-testid')).toBe('invoices-pager');
    expect(button('Previous (Invoices pagination)').textContent?.trim()).toBe('Previous');
    expect(button('Next (Invoices pagination)').textContent?.trim()).toBe('Next');
  });
});
