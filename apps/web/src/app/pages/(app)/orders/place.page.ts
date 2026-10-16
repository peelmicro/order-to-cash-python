import { DraftValue } from '../../../components/draft-value';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { RouteMeta } from '@analogjs/router';
import { injectMutation, injectQuery, QueryClient } from '@tanstack/angular-query-experimental';
import { HlmAlertImports } from '@spartan-ng/helm/alert';
import { HlmButtonImports } from '@spartan-ng/helm/button';
import { HlmCardImports } from '@spartan-ng/helm/card';
import { HlmInputImports } from '@spartan-ng/helm/input';
import { HlmLabelImports } from '@spartan-ng/helm/label';
import { ApiClient } from '../../../api/api-client';
import { amountPhrase, displayMoney } from '../../../lib/format';
import { describeError } from '../../../lib/problem';
import { catalogCompaniesQuery, catalogProductsQuery, catalogRetailersQuery } from '../../../orders/catalog';
import { currencyExponent, currencyInputStep, formatMoney, lineTotal, minorUnitsToDecimalString, parseDecimalToMinorUnits, sumMinorUnits } from '../../../../lib/money';
import type { Schemas } from '../../../../shared/api-types';

export const routeMeta: RouteMeta = { title: 'Place order' };

/** Shown only when a failed catalogue answer carried no problem text at all (an HTML error page, an empty body). */
const CATALOG_FALLBACK = 'The catalogue could not be loaded.';
const PLACE_FALLBACK = 'Placing the order failed.';
/** The one line of help beside a failed catalogue: it stays true whatever the problem says (the sweep's reviewed label). */
export const CATALOG_MANUAL_ENTRY_HELP = 'You can still type the codes by hand.';

/** The R42 demo: one line whose total ends in .99, which the credit simulator refuses, so the saga compensates. */
const COMPENSATION_DEMO_UNIT_PRICE = 24_999;

/**
 * A draft line keeps what the operator TYPED, as text. The integers the wire needs are derived only when needed (the running total, the submit), so an
 * in-progress keystroke like "19." is never reformatted under the cursor, and a typed "19.99" never passes through a float on its way to 1999.
 */
interface DraftLine {
  /** Identity of the line within THIS form. Handed out by the form's own counter, so it restarts at 1 for every form instance (#8 id 106). */
  key: number;
  productCode: string;
  quantity: string;
  unitPrice: string;
  lineDiscount: string;
  /** Money boxes whose text the browser could not parse: a `type="number"` input then reports `value === ""` with `validity.badInput`, so the empty string must NOT be read as "not overridden". */
  unparseable: { quantity?: true; unitPrice?: true; lineDiscount?: true };
}

interface LineProblems {
  quantity?: string;
  unitPrice?: string;
  lineDiscount?: string;
}

function parseQuantity(input: string): number | undefined {
  const text = input.trim();
  if (!/^\d+$/.test(text)) return undefined;
  const value = Number(text);
  return Number.isSafeInteger(value) && value >= 1 ? value : undefined;
}

@Component({
  selector: 'app-place-order',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DraftValue, ...HlmAlertImports, ...HlmButtonImports, ...HlmCardImports, ...HlmInputImports, ...HlmLabelImports],
  template: `
    <div class="flex flex-col gap-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h1 class="text-xl font-semibold">Place order</h1>
        <button hlmBtn variant="outline" type="button" (click)="fillCompensationDemo()">Fill demo order (.99 → compensation)</button>
      </div>

      @if (catalogErrors().length > 0) {
        <div class="flex flex-col gap-2" data-testid="catalog-unavailable">
          @for (text of catalogErrors(); track text) {
            <div hlmAlert variant="destructive" data-testid="catalog-error">
              <p hlmAlertDescription>{{ text }}</p>
            </div>
          }
          <p class="text-muted-foreground text-sm" data-testid="catalog-manual-entry">{{ manualEntryHelp }}</p>
        </div>
      }

      <section hlmCard>
        <header hlmCardHeader>
          <h2 hlmCardTitle>Order</h2>
          <p hlmCardDescription>201 means the order was accepted, not that the saga finished.</p>
        </header>
        <div hlmCardContent>
          <form class="flex flex-col gap-6" novalidate data-testid="place-order-form" (submit)="submit($event)">
            <div class="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_8rem]">
              <div class="flex min-w-0 flex-col gap-1.5">
                <label hlmLabel for="retailer">Retailer</label>
                @if (retailersUsable()) {
                  <select hlmInput id="retailer" [value]="retailerCode()" (change)="selectRetailer($any($event.target).value)">
                    <option value="">Select a retailer</option>
                    @for (retailer of retailers.data() ?? []; track retailer.code) {
                      <option [value]="retailer.code">{{ retailer.name }} ({{ retailer.code }})</option>
                    }
                  </select>
                } @else {
                  <input hlmInput id="retailer" placeholder="e.g. CarrefourEs" [value]="retailerCode()" (input)="retailerCode.set($any($event.target).value)" />
                }
              </div>
              <div class="flex min-w-0 flex-col gap-1.5">
                <label hlmLabel for="company">Company</label>
                @if (companiesUsable()) {
                  <select hlmInput id="company" [value]="companyCode()" (change)="companyCode.set($any($event.target).value)">
                    <option value="">Select a company</option>
                    @for (company of companies.data() ?? []; track company.code) {
                      <option [value]="company.code">{{ company.name }} ({{ company.code }})</option>
                    }
                  </select>
                } @else {
                  <input hlmInput id="company" placeholder="e.g. IBERFOODS" [value]="companyCode()" (input)="companyCode.set($any($event.target).value)" />
                }
              </div>
              <div class="flex min-w-0 flex-col gap-1.5">
                <label hlmLabel for="currency">Currency</label>
                <input hlmInput id="currency" list="currency-options" maxlength="3" [value]="currency()" (input)="currency.set($any($event.target).value)" />
                <datalist id="currency-options">
                  @for (code of currencies(); track code) {
                    <option [value]="code"></option>
                  }
                </datalist>
              </div>
            </div>

            <div class="flex flex-col gap-3">
              <div class="flex items-center justify-between">
                <span class="text-sm font-medium">Lines</span>
                <button hlmBtn variant="outline" size="sm" type="button" (click)="addLine()">Add line</button>
              </div>
              @for (line of lines(); track line.key; let index = $index) {
                <div class="grid grid-cols-1 items-start gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_6rem_minmax(0,1fr)_minmax(0,1fr)_auto]" data-testid="order-line">
                  <div class="flex min-w-0 flex-col gap-1.5 sm:col-span-2 lg:col-span-1">
                    <label hlmLabel [for]="fieldId(line, 'product')">Product</label>
                    @if (productsUsable()) {
                      <select hlmInput [id]="fieldId(line, 'product')" [value]="line.productCode" (change)="updateLine(line.key, { productCode: $any($event.target).value })">
                        <option value="">Select a product</option>
                        @for (product of products.data() ?? []; track product.code) {
                          <option [value]="product.code">{{ product.name }} ({{ product.code }}) — {{ price(product) }}</option>
                        }
                      </select>
                    } @else {
                      <input hlmInput [id]="fieldId(line, 'product')" placeholder="e.g. PRD-0001" [value]="line.productCode" (input)="updateLine(line.key, { productCode: $any($event.target).value })" />
                    }
                  </div>
                  <div class="flex min-w-0 flex-col gap-1.5">
                    <label hlmLabel [for]="fieldId(line, 'quantity')">Quantity</label>
                    <input hlmInput type="number" min="1" step="1" inputmode="numeric" data-testid="quantity-input" [id]="fieldId(line, 'quantity')" [appDraftValue]="line.quantity" [attr.aria-invalid]="problemsFor(line).quantity ? true : null" (input)="typeQuantity(line.key, $any($event.target))" />
                    @if (problemsFor(line).quantity; as problem) {
                      <span class="text-destructive text-xs">{{ problem }}</span>
                    }
                  </div>
                  <div class="flex min-w-0 flex-col gap-1.5">
                    <label hlmLabel [for]="fieldId(line, 'unit-price')">Unit price override</label>
                    <input hlmInput type="number" min="0" inputmode="decimal" data-testid="unit-price-input" [attr.step]="step()" [id]="fieldId(line, 'unit-price')" [attr.placeholder]="catalogPlaceholder(line)" [appDraftValue]="line.unitPrice" [attr.aria-invalid]="problemsFor(line).unitPrice ? true : null" (input)="typeMoney(line.key, 'unitPrice', $any($event.target))" />
                    @if (problemsFor(line).unitPrice; as problem) {
                      <span class="text-destructive text-xs">{{ problem }}</span>
                    }
                  </div>
                  <div class="flex min-w-0 flex-col gap-1.5">
                    <label hlmLabel [for]="fieldId(line, 'line-discount')">Line discount</label>
                    <input hlmInput type="number" min="0" inputmode="decimal" data-testid="line-discount-input" [attr.step]="step()" [id]="fieldId(line, 'line-discount')" [attr.placeholder]="zeroPlaceholder()" [appDraftValue]="line.lineDiscount" [attr.aria-invalid]="problemsFor(line).lineDiscount ? true : null" (input)="typeMoney(line.key, 'lineDiscount', $any($event.target))" />
                    @if (problemsFor(line).lineDiscount; as problem) {
                      <span class="text-destructive text-xs">{{ problem }}</span>
                    }
                  </div>
                  <div class="flex flex-col gap-1.5">
                    <span class="hidden select-none lg:invisible lg:block" aria-hidden="true">&nbsp;</span>
                    <button hlmBtn variant="ghost" size="sm" type="button" [disabled]="lines().length < 2" [attr.aria-label]="'Remove line ' + (index + 1)" (click)="removeLine(line.key)">Remove</button>
                  </div>
                </div>
              }
            </div>

            <div class="flex items-center justify-between gap-4">
              <span class="text-muted-foreground text-sm">Running total (an estimate; the server computes the authoritative total)</span>
              <span class="text-lg font-semibold tabular-nums" data-testid="running-total">{{ runningTotal() }}</span>
            </div>

            <div class="flex flex-col gap-1.5">
              <label hlmLabel for="notes">Notes</label>
              <input hlmInput id="notes" [value]="notes()" (input)="notes.set($any($event.target).value)" />
            </div>

            @if (headerProblem(); as problem) {
              <p class="text-destructive text-sm" data-testid="place-order-incomplete">{{ problem }}</p>
            }

            @if (placeOrder.isError()) {
              <div hlmAlert variant="destructive" data-testid="place-order-error">
                <p hlmAlertDescription>{{ placeError() }}</p>
              </div>
            }

            <div>
              <button hlmBtn type="submit" [disabled]="submitting()">{{ submitting() ? 'Placing…' : 'Place order' }}</button>
            </div>
          </form>
        </div>
      </section>
    </div>
  `,
})
export default class PlaceOrderPage {
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  private readonly queryClient = inject(QueryClient);
  protected readonly manualEntryHelp = CATALOG_MANUAL_ENTRY_HELP;

  protected readonly retailers = injectQuery(() => catalogRetailersQuery(this.api));
  protected readonly companies = injectQuery(() => catalogCompaniesQuery(this.api));
  protected readonly products = injectQuery(() => catalogProductsQuery(this.api));

  protected readonly retailerCode = signal('');
  protected readonly companyCode = signal('');
  protected readonly currency = signal('EUR');
  protected readonly notes = signal('');
  /** Counter of THIS form instance (not of the module): a fresh form starts at 1, in the browser and in every test. */
  private lastLineKey = 1;
  protected readonly lines = signal<DraftLine[]>([{ key: 1, productCode: '', quantity: '1', unitPrice: '', lineDiscount: '', unparseable: {} }]);
  protected readonly showProblems = signal(false);
  /** Set synchronously by the submit handler, before any request exists: the mutation's own pending flag is not yet true for a second `submit` in the same task. */
  protected readonly submitting = signal(false);
  /** The key of the last attempt and the body it carried: the same draft retried sends the same `Idempotency-Key` (the server returns the first order), an edited draft a new one. */
  private attempt: { key: string; body: string } | undefined;

  protected readonly placeOrder = injectMutation(() => ({
    mutationFn: (variables: { request: Schemas['PlaceOrderRequest']; idempotencyKey: string }) => this.api.placeOrder(variables.request, variables.idempotencyKey),
    onSuccess: async (response) => {
      await this.queryClient.invalidateQueries({ queryKey: ['orders'] });
      await this.router.navigate(['/orders', response.data.orderId]);
    },
    onSettled: () => this.submitting.set(false),
  }));

  protected readonly retailersUsable = computed(() => !this.retailers.isError() && (this.retailers.data()?.length ?? 0) > 0);
  protected readonly companiesUsable = computed(() => !this.companies.isError() && (this.companies.data()?.length ?? 0) > 0);
  protected readonly productsUsable = computed(() => !this.products.isError() && (this.products.data()?.length ?? 0) > 0);

  /** Each failing catalogue query's OWN words (problem `detail`, else `title`), once per distinct text, so three identical 503s read once and two different failures both reach the user (#8 review B1). */
  protected readonly catalogErrors = computed(() => {
    const failures: unknown[] = [];
    if (this.retailers.isError()) failures.push(this.retailers.error());
    if (this.companies.isError()) failures.push(this.companies.error());
    if (this.products.isError()) failures.push(this.products.error());
    return [...new Set(failures.map((error) => describeError(error, CATALOG_FALLBACK)))];
  });

  protected readonly step = computed(() => currencyInputStep(this.currency()));
  protected readonly priceByCode = computed(() => new Map((this.products.data() ?? []).map((product) => [product.code, product.price])));
  protected readonly currencies = computed(() => {
    const codes = new Set<string>([this.currency()]);
    for (const party of [...(this.retailers.data() ?? []), ...(this.companies.data() ?? [])]) codes.add(party.currency);
    for (const product of this.products.data() ?? []) codes.add(product.currency);
    return [...codes].filter((code) => code.length > 0).sort();
  });

  protected readonly runningTotal = computed(() => {
    const exponent = currencyExponent(this.currency());
    if (this.lines().some((line) => line.productCode && (line.unparseable.unitPrice || line.unparseable.lineDiscount))) return '—';
    const total = sumMinorUnits(
      this.lines()
        .filter((line) => line.productCode)
        .map((line) => lineTotal({ quantity: parseQuantity(line.quantity) ?? 0, unitPrice: parseDecimalToMinorUnits(line.unitPrice, exponent), lineDiscount: parseDecimalToMinorUnits(line.lineDiscount, exponent) }, this.priceByCode().get(line.productCode))),
    );
    return total === undefined ? '—' : formatMoney(total, this.currency());
  });

  protected readonly headerProblem = computed(() =>
    this.showProblems() && (!this.retailerCode().trim() || !this.companyCode().trim() || !this.lines().some((line) => line.productCode.trim())) ? 'Choose a retailer, a company and at least one product.' : undefined,
  );

  /** The id of one control of one line, the SAME function for the label's `for` and the control's `id` (#8 id 106). Component-scoped through the line's key; no module state. */
  protected fieldId(line: DraftLine, field: string): string {
    return `line-${line.key}-${field}`;
  }

  protected price(product: Schemas['Product']): string {
    return displayMoney(product.price, product.currency);
  }
  protected catalogPlaceholder(line: DraftLine): string {
    const catalogPrice = this.priceByCode().get(line.productCode);
    return catalogPrice === undefined ? 'catalogue' : minorUnitsToDecimalString(catalogPrice, currencyExponent(this.currency()));
  }
  protected zeroPlaceholder(): string {
    return minorUnitsToDecimalString(0, currencyExponent(this.currency()));
  }

  protected problemsFor(line: DraftLine): LineProblems {
    if (!this.showProblems()) return {};
    const exponent = currencyExponent(this.currency());
    const problems: LineProblems = {};
    if (line.unparseable.quantity) problems.quantity = 'Quantity: the browser could not read what was typed. Enter a whole number of at least 1.';
    else if (parseQuantity(line.quantity) === undefined) problems.quantity = 'Quantity: enter a whole number of at least 1.';
    if (line.unparseable.unitPrice || (line.unitPrice.trim() && parseDecimalToMinorUnits(line.unitPrice, exponent) === undefined)) problems.unitPrice = `Enter ${amountPhrase(line.unitPrice, this.currency())} (${this.currency()}).`;
    if (line.unparseable.lineDiscount || (line.lineDiscount.trim() && parseDecimalToMinorUnits(line.lineDiscount, exponent) === undefined)) problems.lineDiscount = `Enter ${amountPhrase(line.lineDiscount, this.currency())} (${this.currency()}).`;
    return problems;
  }

  protected placeError(): string {
    return describeError(this.placeOrder.error(), PLACE_FALLBACK);
  }

  protected selectRetailer(code: string): void {
    this.retailerCode.set(code);
    // The retailer trades in one currency (Party.currency); follow it so the order is not silently placed in another. The field stays editable.
    const selected = this.retailers.data()?.find((retailer) => retailer.code === code);
    if (selected) this.currency.set(selected.currency);
  }

  protected addLine(): void {
    this.lastLineKey += 1;
    this.lines.update((current) => [...current, { key: this.lastLineKey, productCode: '', quantity: '1', unitPrice: '', lineDiscount: '', unparseable: {} }]);
  }
  protected removeLine(key: number): void {
    this.lines.update((current) => (current.length > 1 ? current.filter((line) => line.key !== key) : current));
  }
  protected updateLine(key: number, patch: Partial<DraftLine>): void {
    this.lines.update((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));
  }

  /** The quantity box was edited: keep its text AND whether the browser could parse it (`validity.badInput`), so an unparseable text is never confused with an empty one (the money boxes' rule, applied to every number box: src/app/number-boxes.spec.ts). */
  protected typeQuantity(key: number, target: HTMLInputElement): void {
    this.lines.update((current) => current.map((line) => (line.key === key ? { ...line, quantity: target.value, unparseable: target.validity?.badInput ? { ...line.unparseable, quantity: true as const } : { ...line.unparseable, quantity: undefined } } : line)));
  }

  /** A money box was edited: keep its text AND whether the browser could parse it (`validity.badInput`), because an unparseable text arrives as `""`. */
  protected typeMoney(key: number, field: 'unitPrice' | 'lineDiscount', target: HTMLInputElement): void {
    this.lines.update((current) => current.map((line) => (line.key === key ? { ...line, [field]: target.value, unparseable: target.validity?.badInput ? { ...line.unparseable, [field]: true as const } : { ...line.unparseable, [field]: undefined } } : line)));
  }

  protected fillCompensationDemo(): void {
    const retailer = this.retailers.data()?.[0];
    const demoCurrency = retailer?.currency ?? this.currency();
    this.retailerCode.set(retailer?.code ?? 'CarrefourEs');
    this.companyCode.set(this.companies.data()?.[0]?.code ?? 'IBERFOODS');
    this.currency.set(demoCurrency);
    this.notes.set('demo — compensation path (.99)');
    this.lastLineKey += 1;
    this.lines.set([{ key: this.lastLineKey, productCode: this.products.data()?.[0]?.code ?? 'PRD-0001', quantity: '1', unitPrice: minorUnitsToDecimalString(COMPENSATION_DEMO_UNIT_PRICE, currencyExponent(demoCurrency)), lineDiscount: '', unparseable: {} }]);
  }

  /** The wire request from the typed draft, or `undefined` while anything is missing or does not parse (the problems are shown, nothing is sent). */
  private buildRequest(): Schemas['PlaceOrderRequest'] | undefined {
    const exponent = currencyExponent(this.currency());
    const chosen = this.lines().filter((line) => line.productCode.trim());
    if (!this.retailerCode().trim() || !this.companyCode().trim() || chosen.length === 0) return undefined;
    const wireLines: Schemas['PlaceOrderLine'][] = [];
    for (const line of chosen) {
      const quantity = parseQuantity(line.quantity);
      if (line.unparseable.quantity || quantity === undefined) return undefined;
      const wire: Schemas['PlaceOrderLine'] = { productCode: line.productCode.trim(), quantity };
      if (line.unparseable.unitPrice || line.unparseable.lineDiscount) return undefined;
      if (line.unitPrice.trim()) {
        const unitPrice = parseDecimalToMinorUnits(line.unitPrice, exponent);
        if (unitPrice === undefined) return undefined;
        wire.unitPrice = unitPrice;
      }
      if (line.lineDiscount.trim()) {
        const lineDiscount = parseDecimalToMinorUnits(line.lineDiscount, exponent);
        if (lineDiscount === undefined) return undefined;
        if (lineDiscount > 0) wire.lineDiscount = lineDiscount;
      }
      wireLines.push(wire);
    }
    if (!/^[A-Za-z]{3}$/.test(this.currency().trim())) return undefined;
    const request: Schemas['PlaceOrderRequest'] = { retailerCode: this.retailerCode().trim(), companyCode: this.companyCode().trim(), currency: this.currency().trim().toUpperCase(), lines: wireLines };
    if (this.notes().trim()) request.notes = this.notes().trim();
    return request;
  }

  protected submit(event: Event): void {
    event.preventDefault();
    // One in flight at a time, decided HERE and synchronously: a double click, a held Enter or a second `submit` event in the same task all end here.
    if (this.submitting()) return;
    this.showProblems.set(true);
    const request = this.buildRequest();
    if (!request) return;
    const body = JSON.stringify(request);
    this.attempt = this.attempt?.body === body ? this.attempt : { key: crypto.randomUUID(), body };
    this.submitting.set(true);
    this.placeOrder.mutate({ request, idempotencyKey: this.attempt.key });
  }
}
