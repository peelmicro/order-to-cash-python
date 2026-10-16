import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { HlmButtonImports } from '@spartan-ng/helm/button';

/** The number of pages for `total` rows, at least 1, by integer arithmetic: `(total - total % size)` is an exact multiple of `size`, so the one division is exact. */
export function pageCount(total: number, pageSize: number): number {
  if (!Number.isSafeInteger(total) || !Number.isSafeInteger(pageSize) || total < 0 || pageSize < 1) return 1;
  const remainder = total % pageSize;
  const whole = (total - remainder) / pageSize;
  return Math.max(1, remainder === 0 ? whole : whole + 1);
}

const DEFAULT_LABEL = 'Pagination';

export interface PageCounts {
  page: number;
  pageSize: number;
  total: number;
}

/**
 * Previous / next with a count. While the page is not known (`counts` undefined: loading, or failed) it claims NO count (#8 review S4: a pager
 * that said "Page 1 of 1" while the list was still loading), and both buttons are off.
 */
@Component({
  selector: 'app-pager',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [...HlmButtonImports],
  template: `
    <nav class="flex items-center justify-between gap-4 text-sm" [attr.aria-label]="label()" [attr.data-testid]="testId()">
      <span class="text-muted-foreground" data-testid="pager-count">{{ summary() }}</span>
      <span class="flex gap-2">
        <button hlmBtn variant="outline" size="sm" type="button" [attr.aria-label]="buttonName('Previous')" [disabled]="!counts() || current() <= 1" (click)="pageChange.emit(current() - 1)">Previous</button>
        <button hlmBtn variant="outline" size="sm" type="button" [attr.aria-label]="buttonName('Next')" [disabled]="!counts() || current() >= pages()" (click)="pageChange.emit(current() + 1)">Next</button>
      </span>
    </nav>
  `,
})
export class Pager {
  readonly counts = input<PageCounts | undefined>(undefined);
  readonly current = input.required<number>();
  readonly noun = input.required<string>();
  readonly testId = input('pager');
  /** The landmark's name: a page with two pagers (billing) names each, so a screen reader can tell them apart. */
  readonly label = input(DEFAULT_LABEL);

  /** A pager with the default landmark name keeps plain `Previous`/`Next`; a page with several pagers names each button after its landmark (`Next (Invoices pagination)`), so the control census cannot merge two pagers' buttons (stage 3 review A6). */
  protected buttonName(action: 'Previous' | 'Next'): string | null {
    return this.label() === DEFAULT_LABEL ? null : `${action} (${this.label()})`;
  }
  readonly pageChange = output<number>();

  /** At least one page, so an empty result reads "Page 1 of 1" rather than "of 0". */
  protected readonly pages = computed(() => {
    const counts = this.counts();
    return counts ? pageCount(counts.total, counts.pageSize) : 0;
  });

  protected readonly summary = computed(() => {
    const counts = this.counts();
    return counts ? `Page ${counts.page} of ${this.pages()} · ${counts.total} ${this.noun()}` : '';
  });
}
