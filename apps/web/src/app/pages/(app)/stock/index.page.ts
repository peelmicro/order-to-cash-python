import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouteMeta } from '@analogjs/router';
import { injectMutation, injectQuery, QueryClient } from '@tanstack/angular-query-experimental';
import { HlmAlertImports } from '@spartan-ng/helm/alert';
import { HlmBadgeImports } from '@spartan-ng/helm/badge';
import { HlmButtonImports } from '@spartan-ng/helm/button';
import { HlmInputImports } from '@spartan-ng/helm/input';
import { HlmLabelImports } from '@spartan-ng/helm/label';
import { HlmTableImports } from '@spartan-ng/helm/table';
import { ApiClient } from '../../../api/api-client';
import { DraftValue } from '../../../components/draft-value';
import { Pager } from '../../../components/pager';
import { describeError } from '../../../lib/problem';
import { catalogProductsQuery } from '../../../orders/catalog';
import type { Schemas } from '../../../../shared/api-types';

export const routeMeta: RouteMeta = { title: 'Stock' };

const PAGE_SIZE = 20;
const STOCK_FALLBACK = 'The stock could not be loaded.';
const PRODUCTS_FALLBACK = 'the catalogue could not be loaded';
const REPLENISH_FALLBACK = 'Replenishing the stock failed.';
const UNITS_INVALID = 'Units to add: enter a whole number of at least 1.';
const UNITS_UNREADABLE = `Units to add: the browser could not read what was typed. Enter a whole number of at least 1.`;

type StockItem = Schemas['StockItem'];

interface Replenished {
  item: StockItem;
  units: number;
  response: Schemas['ReplenishStockResponse'];
}

const rowKey = (item: Pick<StockItem, 'companyCode' | 'productCode'>) => `${item.companyCode}:${item.productCode}`;

/** A units count the Gateway accepts (`Quantity`: a whole number of at least 1), from typed text; `undefined` for anything else. */
function parseUnits(input: string): number | undefined {
  const text = input.trim();
  if (!/^\d+$/.test(text)) return undefined;
  const value = Number(text);
  return Number.isSafeInteger(value) && value >= 1 ? value : undefined;
}

/**
 * Stock: a live read of Fulfillment (on hand, reserved, available = on hand - reserved, invariant F1) with a delta replenish per line.
 * Each row shows the product's NAME with its code beside it (#8 id 101): `StockItem.productName` when the answer carries one, else the catalogue's,
 * else the code alone, once. A failed catalogue read never hides the table.
 */
@Component({
  selector: 'app-stock',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DraftValue, Pager, ...HlmAlertImports, ...HlmBadgeImports, ...HlmButtonImports, ...HlmInputImports, ...HlmLabelImports, ...HlmTableImports],
  template: `
    <div class="flex flex-col gap-6">
      <div>
        <h1 class="text-xl font-semibold">Stock</h1>
        <p class="text-muted-foreground text-sm">A live read of Fulfillment's on-hand and reserved units, not the order read model, so there is no projection lag. Available = on hand − reserved.</p>
      </div>

      @if (products.isError()) {
        <p class="text-destructive text-sm" data-testid="stock-products-error">Product names unavailable: {{ productsError() }}</p>
      }

      <div class="flex flex-wrap items-end gap-4">
        <div class="flex flex-col gap-1.5">
          <label hlmLabel for="stock-company-filter">Company</label>
          <input hlmInput id="stock-company-filter" class="w-48" placeholder="e.g. IBERFOODS" [value]="companyCode()" (change)="setCompany($any($event.target).value)" />
        </div>
        <div class="flex flex-col gap-1.5">
          <label hlmLabel for="stock-product-filter">Product</label>
          <input hlmInput id="stock-product-filter" class="w-48" placeholder="e.g. PRD-0001" [value]="productCode()" (change)="setProduct($any($event.target).value)" />
        </div>
        <div class="flex items-center gap-2 pb-2">
          <input id="stock-below-threshold" type="checkbox" [checked]="belowThreshold()" (change)="setBelowThreshold($any($event.target).checked)" />
          <label hlmLabel for="stock-below-threshold">Low stock only</label>
        </div>
      </div>

      @if (active(); as item) {
        <div class="flex flex-col gap-3 rounded-md border p-4" data-testid="replenish-form">
          @if (outcome(); as done) {
            <p class="text-sm text-emerald-700" data-testid="replenish-outcome">Added {{ done.units }} units to {{ done.item.productCode }} for {{ done.item.companyCode }}{{ onHandAfter(done) }}</p>
            <div>
              <button hlmBtn type="button" size="sm" variant="outline" (click)="close()">Close</button>
            </div>
          } @else {
            <form class="flex flex-col gap-3" novalidate (submit)="submit($event)">
              <p class="text-sm font-medium">Replenish {{ displayName(item) ?? item.productCode }} ({{ item.companyCode }})</p>
              <p class="text-muted-foreground text-xs">This <strong>adds</strong> to on-hand stock: a delta, not a target level. Submitting the same amount twice adds it twice; reservations are untouched. After a timeout, read the list again before retrying: the top-up may have been applied.</p>
              <div class="flex flex-wrap items-end gap-3">
                <div class="flex flex-col gap-1.5">
                  <label hlmLabel for="replenish-units">Units to add</label>
                  <input hlmInput id="replenish-units" class="w-36" type="number" min="1" step="1" inputmode="numeric" placeholder="e.g. 100" data-testid="replenish-units-input" [appDraftValue]="unitsDraft()" [appDraftReset]="unitsReset()" [attr.aria-invalid]="unitsProblem() ? true : null" (input)="typeUnits($any($event.target))" />
                </div>
                <button hlmBtn type="submit" [disabled]="submitting()">{{ submitting() ? 'Adding…' : 'Add units' }}</button>
                <button hlmBtn type="button" variant="ghost" [disabled]="submitting()" (click)="close()">Cancel</button>
              </div>
              @if (unitsProblem(); as problem) {
                <p class="text-destructive text-sm" data-testid="replenish-units-problem">{{ problem }}</p>
              }
              @if (replenish.isError()) {
                <div hlmAlert variant="destructive" data-testid="replenish-error">
                  <p hlmAlertDescription>{{ replenishError() }}</p>
                </div>
              }
            </form>
          }
        </div>
      }

      @if (stock.isError()) {
        <div hlmAlert variant="destructive" data-testid="stock-error">
          <p hlmAlertDescription>{{ stockError() }}</p>
        </div>
      } @else if (stock.isPending()) {
        <p class="text-muted-foreground text-sm" data-testid="stock-loading">Loading stock…</p>
      } @else if (rows().length === 0) {
        <p class="text-muted-foreground rounded-md border border-dashed p-6 text-sm" data-testid="stock-empty">No stock lines match these filters.</p>
      } @else {
        <table hlmTable data-testid="stock-table">
          <thead hlmTHead>
            <tr hlmTr>
              <th hlmTh scope="col">Company</th>
              <th hlmTh scope="col">Product</th>
              <th hlmTh scope="col" class="text-right">On hand</th>
              <th hlmTh scope="col" class="text-right">Reserved</th>
              <th hlmTh scope="col" class="text-right">Available</th>
              <th hlmTh scope="col" class="text-right">Threshold</th>
              <th hlmTh scope="col"><span class="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody hlmTBody>
            @for (item of rows(); track rowId(item)) {
              <tr hlmTr data-testid="stock-row">
                <td hlmTd>{{ item.companyCode }}</td>
                <td hlmTd class="font-medium" data-testid="stock-product">
                  @if (displayName(item); as name) {
                    {{ name }} <span class="text-muted-foreground text-xs">({{ item.productCode }})</span>
                  } @else {
                    {{ item.productCode }}
                  }
                </td>
                <td hlmTd class="text-right tabular-nums" data-testid="stock-units">{{ item.units }}</td>
                <td hlmTd class="text-right tabular-nums" data-testid="stock-reserved">{{ item.reservedUnits }}</td>
                <td hlmTd class="text-right" data-testid="stock-available">
                  <span hlmBadge [variant]="item.availableUnits < item.lowStockThreshold ? 'destructive' : 'secondary'">{{ item.availableUnits }}</span>
                </td>
                <td hlmTd class="text-muted-foreground text-right tabular-nums">{{ item.lowStockThreshold }}</td>
                <td hlmTd class="text-right">
                  <button hlmBtn type="button" size="sm" variant="outline" data-testid="replenish-button" [disabled]="submitting()" [attr.aria-label]="'Replenish ' + item.productCode + ' for ' + item.companyCode" (click)="open(item)">Replenish</button>
                </td>
              </tr>
            }
          </tbody>
        </table>
      }

      <app-pager [counts]="counts()" [current]="page()" noun="stock lines" testId="stock-pager" (pageChange)="page.set($event)" />
    </div>
  `,
})
export default class StockPage {
  private readonly api = inject(ApiClient);
  private readonly queryClient = inject(QueryClient);

  protected readonly page = signal(1);
  protected readonly companyCode = signal('');
  protected readonly productCode = signal('');
  protected readonly belowThreshold = signal(false);

  protected readonly stock = injectQuery(() => ({
    queryKey: ['stock', { page: this.page(), companyCode: this.companyCode(), productCode: this.productCode(), belowThreshold: this.belowThreshold() }] as const,
    queryFn: async () =>
      (
        await this.api.listStock({
          companyCode: this.companyCode(),
          productCode: this.productCode(),
          // The parameter is sent only when set: the Gateway's default is false, so a page that is not filtering asks the plain question.
          belowThreshold: this.belowThreshold() ? 'true' : undefined,
          page: this.page(),
          pageSize: PAGE_SIZE,
        })
      ).data,
  }));
  protected readonly products = injectQuery(() => catalogProductsQuery(this.api));

  protected readonly rows = computed(() => this.stock.data()?.items ?? []);
  /** Only a settled, successful answer has counts: nothing is claimed while loading or after a failure (TanStack keeps `data` after a failed refetch, so the error is checked first). */
  protected readonly counts = computed(() => (this.stock.isError() ? undefined : this.stock.data()?.page));
  protected readonly nameByCode = computed(() => new Map((this.products.data() ?? []).map((product) => [product.code, product.name])));

  // The replenish panel. Drafts of its one number box: written by the box (`typeUnits`) and, from outside, by `open` alone (another row, or the same one again). `close` writes no draft: it removes the panel, and its box with it.
  protected readonly active = signal<StockItem | undefined>(undefined);
  protected readonly unitsDraft = signal('');
  protected readonly unitsBad = signal(false);
  /** Bumped by `open()`: tells the box to clear itself even when its draft is `""` already (a box holding unreadable text reports `""`). */
  protected readonly unitsReset = signal(0);
  protected readonly showUnitsProblem = signal(false);
  protected readonly outcome = signal<Replenished | undefined>(undefined);
  /** Set synchronously by the submit handler, before any request exists: a second `submit` in the same task ends there (a top-up is a delta, so a repeat adds again). */
  protected readonly submitting = signal(false);

  protected readonly replenish = injectMutation(() => ({
    mutationFn: (variables: { request: Schemas['ReplenishStockRequest']; item: StockItem; units: number }) => this.api.replenishStock(variables.request),
    onSuccess: async (response, variables) => {
      this.outcome.set({ item: variables.item, units: variables.units, response: response.data });
      await this.queryClient.invalidateQueries({ queryKey: ['stock'] });
    },
    onSettled: () => this.submitting.set(false),
  }));

  /** Two sentences, because they are two different mistakes: a text the browser could not read at all (`badInput`), and a number that is not a whole count of at least 1. */
  protected readonly unitsProblem = computed(() => {
    if (!this.showUnitsProblem() || this.parsedUnits() !== undefined) return undefined;
    return this.unitsBad() ? UNITS_UNREADABLE : UNITS_INVALID;
  });
  private readonly parsedUnits = computed(() => (this.unitsBad() ? undefined : parseUnits(this.unitsDraft())));

  protected rowId(item: StockItem): string {
    return rowKey(item);
  }

  /** The product's name for people: the stock line's own `productName` wins, else the catalogue's; `undefined` when neither is known, so the caller shows the code once. */
  protected displayName(item: StockItem): string | undefined {
    return item.productName?.trim() || this.nameByCode().get(item.productCode) || undefined;
  }

  protected stockError(): string {
    return describeError(this.stock.error(), STOCK_FALLBACK);
  }
  protected productsError(): string {
    return describeError(this.products.error(), PRODUCTS_FALLBACK);
  }
  protected replenishError(): string {
    return describeError(this.replenish.error(), REPLENISH_FALLBACK);
  }

  /** An answered replenish that omits this line has no new level to show: say so, never a blank that reads as still working. */
  protected onHandAfter(done: Replenished): string {
    const updated = done.response.items.find((candidate) => rowKey(candidate) === rowKey(done.item));
    return updated ? `. On hand is now ${updated.units}.` : '. The answer did not include this line’s new on-hand level.';
  }

  protected setCompany(value: string): void {
    this.companyCode.set(value.trim());
    this.page.set(1);
  }
  protected setProduct(value: string): void {
    this.productCode.set(value.trim());
    this.page.set(1);
  }
  protected setBelowThreshold(value: boolean): void {
    this.belowThreshold.set(value);
    this.page.set(1);
  }

  /** The panel opens for a row, or moves to another one: the draft starts empty and a failure on the previous row does not follow. */
  protected open(item: StockItem): void {
    this.active.set(item);
    this.unitsDraft.set('');
    this.unitsBad.set(false);
    this.unitsReset.update((count) => count + 1);
    this.showUnitsProblem.set(false);
    this.outcome.set(undefined);
    this.replenish.reset();
  }
  protected close(): void {
    this.active.set(undefined);
    this.outcome.set(undefined);
    this.replenish.reset();
  }

  /** The units box was edited: keep its text AND whether the browser could parse it (`validity.badInput`), because an unparseable text arrives as `""`. */
  protected typeUnits(target: HTMLInputElement): void {
    this.unitsDraft.set(target.value);
    this.unitsBad.set(target.validity?.badInput === true);
  }

  protected submit(event: Event): void {
    event.preventDefault();
    if (this.submitting()) return;
    const item = this.active();
    if (!item) return;
    this.showUnitsProblem.set(true);
    const units = this.parsedUnits();
    if (units === undefined) return;
    this.submitting.set(true);
    this.replenish.mutate({ request: { companyCode: item.companyCode, lines: [{ productCode: item.productCode, units }] }, item, units });
  }
}
