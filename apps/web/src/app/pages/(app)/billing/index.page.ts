import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouteMeta } from '@analogjs/router';
import { RouterLink } from '@angular/router';
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
import { amountPhrase, displayMoney, formatInstant } from '../../../lib/format';
import { describeError } from '../../../lib/problem';
import { currencyExponent, currencyInputStep, minorUnitsToDecimalString, parseDecimalToMinorUnits } from '../../../../lib/money';
import type { Schemas } from '../../../../shared/api-types';

export const routeMeta: RouteMeta = { title: 'Billing' };

const PAGE_SIZE = 20;
const CREDITS_FALLBACK = 'The credit limits could not be loaded.';
const INVOICES_FALLBACK = 'The invoices could not be loaded.';
const PAYMENT_FALLBACK = 'Registering the payment failed.';
const ORDER_LINK_FALLBACK = 'the request failed';
/** The wire's own limit on a remittance reference (openapi.yaml `PaymentReference.maxLength`). */
const REFERENCE_MAX = 30;

type Invoice = Schemas['Invoice'];

/** The invoice statuses, typed so the compiler fails here if openapi.yaml's `InvoiceStatus` gains or loses one. */
const STATUS_SET = { issued: true, paid: true } satisfies Record<Schemas['InvoiceStatus'], true>;
const INVOICE_STATUSES = Object.keys(STATUS_SET) as Schemas['InvoiceStatus'][];

interface PaymentResult {
  /** The HTTP status the Gateway answered: 201 (this call recorded the payment) or 200 (an idempotent replay). */
  status: number;
  response: Schemas['RegisterPaymentResponse'];
}

/** A starting point for the remittance reference, shaped like openapi.yaml's example (`PAY-2026-08-18-000019`): deterministic per invoice and day, because the reference IS the idempotency key (B10, R48), so submitting the same one twice is a replay, not a second payment. */
export function suggestPaymentReference(invoice: Pick<Invoice, 'invoiceReference'>, now: Date = new Date()): string {
  return `PAY-${now.toISOString().slice(0, 10)}-${invoice.invoiceReference.replace(/^INV-/, '')}`;
}

/** Minutes as the filter wants them: a whole number of at least 0; `undefined` for anything else. */
function parseMinutes(input: string): number | undefined {
  const text = input.trim();
  if (!/^\d+$/.test(text)) return undefined;
  const value = Number(text);
  return Number.isSafeInteger(value) ? value : undefined;
}

/** Billing: credit limits and invoices (read models of the Billing context) and Register payment, the only way an invoice becomes `paid`. */
@Component({
  selector: 'app-billing',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DraftValue, Pager, RouterLink, ...HlmAlertImports, ...HlmBadgeImports, ...HlmButtonImports, ...HlmInputImports, ...HlmLabelImports, ...HlmTableImports],
  template: `
    <div class="flex flex-col gap-8">
      <h1 class="text-xl font-semibold">Billing</h1>

      <section class="flex flex-col gap-4" aria-labelledby="credits-heading">
        <div>
          <h2 id="credits-heading" class="text-lg font-semibold">Credit limits</h2>
          <p class="text-muted-foreground text-sm">Available = limit − held − open exposure (invariant B1). A credit check fails when the order's hold exceeds what is available (R39), so a line below the order's amount fails it, not only a line at zero.</p>
        </div>
        <div class="flex flex-wrap items-end gap-4">
          <div class="flex flex-col gap-1.5">
            <label hlmLabel for="credit-retailer-filter">Credit retailer</label>
            <input hlmInput id="credit-retailer-filter" class="w-48" placeholder="e.g. CarrefourEs" [value]="creditRetailer()" (change)="setCreditRetailer($any($event.target).value)" />
          </div>
          <div class="flex flex-col gap-1.5">
            <label hlmLabel for="credit-company-filter">Credit company</label>
            <input hlmInput id="credit-company-filter" class="w-48" placeholder="e.g. IBERFOODS" [value]="creditCompany()" (change)="setCreditCompany($any($event.target).value)" />
          </div>
        </div>
        @if (credits.isError()) {
          <div hlmAlert variant="destructive" data-testid="credits-error">
            <p hlmAlertDescription>{{ creditsError() }}</p>
          </div>
        } @else if (credits.isPending()) {
          <p class="text-muted-foreground text-sm" data-testid="credits-loading">Loading credit limits…</p>
        } @else if (creditRows().length === 0) {
          <p class="text-muted-foreground rounded-md border border-dashed p-6 text-sm" data-testid="credits-empty">No credit lines match these filters.</p>
        } @else {
          <table hlmTable data-testid="credits-table">
            <thead hlmTHead>
              <tr hlmTr>
                <th hlmTh scope="col">Retailer</th>
                <th hlmTh scope="col">Company</th>
                <th hlmTh scope="col" class="text-right">Limit</th>
                <th hlmTh scope="col" class="text-right">Held</th>
                <th hlmTh scope="col" class="text-right">Open exposure</th>
                <th hlmTh scope="col" class="text-right">Available</th>
              </tr>
            </thead>
            <tbody hlmTBody>
              @for (credit of creditRows(); track credit.creditCode) {
                <tr hlmTr data-testid="credit-row">
                  <td hlmTd>{{ credit.retailerCode }}</td>
                  <td hlmTd>{{ credit.companyCode }}</td>
                  <td hlmTd class="text-right tabular-nums" data-testid="credit-limit">{{ money(credit.creditLimit, credit.currency) }}</td>
                  <td hlmTd class="text-right tabular-nums" data-testid="credit-held">{{ money(credit.activeHolds, credit.currency) }}</td>
                  <td hlmTd class="text-right tabular-nums" data-testid="credit-exposure">{{ money(credit.openExposure, credit.currency) }}</td>
                  <td hlmTd class="text-right tabular-nums" [class.text-destructive]="credit.availableCredit === 0" [class.font-medium]="credit.availableCredit === 0" data-testid="credit-available">{{ money(credit.availableCredit, credit.currency) }}</td>
                </tr>
              }
            </tbody>
          </table>
        }
        <app-pager [counts]="creditCounts()" [current]="creditPage()" noun="credit lines" label="Credits pagination" testId="credits-pager" (pageChange)="creditPage.set($event)" />
      </section>

      <section class="flex flex-col gap-4" aria-labelledby="invoices-heading">
        <h2 id="invoices-heading" class="text-lg font-semibold">Invoices</h2>
        <div class="flex flex-wrap items-end gap-4">
          <div class="flex flex-col gap-1.5">
            <label hlmLabel for="invoice-status-filter">Invoice status</label>
            <select hlmInput id="invoice-status-filter" class="w-48" [value]="invoiceStatus()" (change)="setInvoiceStatus($any($event.target).value)">
              <option value="">All statuses</option>
              @for (status of statuses; track status) {
                <option [value]="status">{{ status }}</option>
              }
            </select>
          </div>
          <div class="flex flex-col gap-1.5">
            <label hlmLabel for="invoice-retailer-filter">Invoice retailer</label>
            <input hlmInput id="invoice-retailer-filter" class="w-48" placeholder="e.g. CarrefourEs" [value]="invoiceRetailer()" (change)="setInvoiceRetailer($any($event.target).value)" />
          </div>
          <div class="flex flex-col gap-1.5">
            <label hlmLabel for="invoice-company-filter">Invoice company</label>
            <input hlmInput id="invoice-company-filter" class="w-48" placeholder="e.g. IBERFOODS" [value]="invoiceCompany()" (change)="setInvoiceCompany($any($event.target).value)" />
          </div>
          <div class="flex flex-col gap-1.5">
            <label hlmLabel for="invoice-order-filter">Invoice order reference</label>
            <input hlmInput id="invoice-order-filter" class="w-40" placeholder="ORD-000042" [value]="invoiceOrder()" (change)="setInvoiceOrder($any($event.target).value)" />
          </div>
          <div class="flex flex-col gap-1.5">
            <label hlmLabel for="invoice-age-filter">Issued at least (minutes) ago</label>
            <input hlmInput id="invoice-age-filter" class="w-40" type="number" min="0" step="1" inputmode="numeric" data-testid="invoice-age-input" [appDraftValue]="ageDraft()" [attr.aria-invalid]="ageProblem() ? true : null" (input)="typeAge($any($event.target))" (change)="applyAge()" />
            @if (ageProblem(); as problem) {
              <span class="text-destructive text-xs" data-testid="invoice-age-problem">{{ problem }}</span>
            }
          </div>
        </div>

        @if (paying(); as invoice) {
          <div class="flex flex-col gap-3 rounded-md border p-4" data-testid="payment-form">
            <p class="text-sm font-medium">Register payment for {{ invoice.invoiceReference }} ({{ invoice.orderReference }}): {{ money(invoice.totalAmount, invoice.currency) }}</p>
            <form class="flex flex-col gap-3" novalidate (submit)="submit($event)">
              <div class="grid grid-cols-1 items-start gap-3 sm:grid-cols-[minmax(0,1fr)_12rem_auto]">
                <div class="flex min-w-0 flex-col gap-1.5">
                  <label hlmLabel for="payment-reference">Payment reference</label>
                  <input hlmInput id="payment-reference" maxlength="30" data-testid="payment-reference-input" [value]="referenceDraft()" [attr.aria-invalid]="referenceProblem() ? true : null" (input)="referenceDraft.set($any($event.target).value)" />
                  @if (referenceProblem(); as problem) {
                    <span class="text-destructive text-xs" data-testid="payment-reference-problem">{{ problem }}</span>
                  }
                </div>
                <div class="flex min-w-0 flex-col gap-1.5">
                  <label hlmLabel for="payment-amount">Amount</label>
                  <input hlmInput id="payment-amount" type="number" min="0" inputmode="decimal" data-testid="payment-amount-input" [attr.step]="paymentStep()" [appDraftValue]="amountDraft()" [appDraftReset]="amountReset()" [attr.aria-invalid]="amountProblem() ? true : null" (input)="typeAmount($any($event.target))" />
                  <span class="text-muted-foreground text-xs">in {{ invoice.currency }}, the invoice's own currency</span>
                  @if (amountProblem(); as problem) {
                    <span class="text-destructive text-xs" data-testid="payment-amount-problem">{{ problem }}</span>
                  }
                </div>
                <div class="flex items-end gap-2 sm:pt-6">
                  <button hlmBtn type="submit" [disabled]="submitting()">{{ submitting() ? 'Registering…' : 'Submit payment' }}</button>
                  <button hlmBtn type="button" variant="ghost" [disabled]="submitting()" (click)="closePayment()">{{ result() ? 'Close' : 'Cancel' }}</button>
                </div>
              </div>
            </form>
            @if (registerPayment.isError()) {
              <div hlmAlert variant="destructive" data-testid="payment-error">
                <p hlmAlertDescription>{{ paymentError() }}</p>
              </div>
            }
            @if (result(); as done) {
              @if (done.response.outcome === 'accepted') {
                <p class="text-sm text-emerald-700" data-testid="payment-outcome-accepted" [attr.data-http-status]="done.status">Payment {{ done.response.paymentReference }} recorded (HTTP {{ done.status }}). Invoice {{ done.response.invoiceReference }} is now {{ done.response.invoiceStatus }}.</p>
              } @else {
                <p class="text-sm text-amber-700" data-testid="payment-outcome-duplicate" [attr.data-http-status]="done.status">Payment {{ done.response.paymentReference }} was already recorded (HTTP {{ done.status }}). Nothing new was created: this was an idempotent replay.</p>
              }
              <p class="text-muted-foreground text-sm">
                The order completes once the saga catches up: {{ done.response.orderReference ?? 'its order' }} moves to paid and then completed.
                @if (orderLink.isError()) {
                  <span class="text-destructive" data-testid="view-order-link-error">The order link could not be resolved: {{ orderLinkError() }}</span>
                } @else if (orderLink.isLoading()) {
                  <span data-testid="view-order-link-resolving">Resolving the order link…</span>
                } @else if (orderLink.data(); as orderId) {
                  <a class="underline" data-testid="view-order-link" [routerLink]="['/orders', orderId]">Watch it on the order's live timeline</a>
                } @else if (orderLink.isSuccess()) {
                  <span data-testid="view-order-link-not-found">No order was found for {{ done.response.orderReference }}, so there is no timeline to link to.</span>
                }
              </p>
            }
          </div>
        }

        @if (invoices.isError()) {
          <div hlmAlert variant="destructive" data-testid="invoices-error">
            <p hlmAlertDescription>{{ invoicesError() }}</p>
          </div>
        } @else if (invoices.isPending()) {
          <p class="text-muted-foreground text-sm" data-testid="invoices-loading">Loading invoices…</p>
        } @else if (invoiceRows().length === 0) {
          <p class="text-muted-foreground rounded-md border border-dashed p-6 text-sm" data-testid="invoices-empty">No invoices match these filters.</p>
        } @else {
          <table hlmTable data-testid="invoices-table">
            <thead hlmTHead>
              <tr hlmTr>
                <th hlmTh scope="col">Invoice</th>
                <th hlmTh scope="col">Order</th>
                <th hlmTh scope="col">Retailer</th>
                <th hlmTh scope="col">Company</th>
                <th hlmTh scope="col">Issued</th>
                <th hlmTh scope="col" class="text-right">Total</th>
                <th hlmTh scope="col">Status</th>
                <th hlmTh scope="col"><span class="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody hlmTBody>
              @for (invoice of invoiceRows(); track invoice.invoiceId) {
                <tr hlmTr data-testid="invoice-row">
                  <td hlmTd class="font-medium">{{ invoice.invoiceReference }}</td>
                  <td hlmTd>{{ invoice.orderReference }}</td>
                  <td hlmTd>{{ invoice.retailerCode }}</td>
                  <td hlmTd>{{ invoice.companyCode }}</td>
                  <td hlmTd>{{ instant(invoice.invoiceDate) }}</td>
                  <td hlmTd class="text-right tabular-nums" data-testid="invoice-total">{{ money(invoice.totalAmount, invoice.currency) }}</td>
                  <td hlmTd><span hlmBadge [variant]="invoice.status === 'paid' ? 'secondary' : 'outline'" data-testid="invoice-status">{{ invoice.status }}</span></td>
                  <td hlmTd class="text-right">
                    @if (invoice.status === 'issued') {
                      <button hlmBtn type="button" size="sm" variant="outline" data-testid="register-payment-button" [disabled]="submitting()" [attr.aria-label]="'Register payment ' + invoice.invoiceReference" (click)="openPayment(invoice)">Register payment</button>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        }
        <app-pager [counts]="invoiceCounts()" [current]="invoicePage()" noun="invoices" label="Invoices pagination" testId="invoices-pager" (pageChange)="invoicePage.set($event)" />
      </section>
    </div>
  `,
})
export default class BillingPage {
  private readonly api = inject(ApiClient);
  private readonly queryClient = inject(QueryClient);
  protected readonly statuses = INVOICE_STATUSES;

  // Credits
  protected readonly creditPage = signal(1);
  protected readonly creditRetailer = signal('');
  protected readonly creditCompany = signal('');
  protected readonly credits = injectQuery(() => ({
    queryKey: ['credits', { page: this.creditPage(), retailerCode: this.creditRetailer(), companyCode: this.creditCompany() }] as const,
    queryFn: async () => (await this.api.listCredits({ retailerCode: this.creditRetailer(), companyCode: this.creditCompany(), page: this.creditPage(), pageSize: PAGE_SIZE })).data,
  }));
  protected readonly creditRows = computed(() => this.credits.data()?.items ?? []);
  protected readonly creditCounts = computed(() => (this.credits.isError() ? undefined : this.credits.data()?.page));

  // Invoices
  protected readonly invoicePage = signal(1);
  protected readonly invoiceStatus = signal<Schemas['InvoiceStatus'] | ''>('');
  protected readonly invoiceRetailer = signal('');
  protected readonly invoiceCompany = signal('');
  protected readonly invoiceOrder = signal('');
  protected readonly issuedBeforeMinutes = signal<number | undefined>(undefined);
  protected readonly invoices = injectQuery(() => ({
    queryKey: ['invoices', { page: this.invoicePage(), status: this.invoiceStatus(), retailerCode: this.invoiceRetailer(), companyCode: this.invoiceCompany(), orderReference: this.invoiceOrder(), issuedBeforeMinutes: this.issuedBeforeMinutes() }] as const,
    queryFn: async () =>
      (
        await this.api.listInvoices({
          status: this.invoiceStatus(),
          retailerCode: this.invoiceRetailer(),
          companyCode: this.invoiceCompany(),
          orderReference: this.invoiceOrder(),
          issuedBeforeMinutes: this.issuedBeforeMinutes(),
          page: this.invoicePage(),
          pageSize: PAGE_SIZE,
        })
      ).data,
  }));
  protected readonly invoiceRows = computed(() => this.invoices.data()?.items ?? []);
  protected readonly invoiceCounts = computed(() => (this.invoices.isError() ? undefined : this.invoices.data()?.page));

  // The age filter's number box. Drafts: the box (`typeAge`) is the only writer.
  protected readonly ageDraft = signal('');
  protected readonly ageBad = signal(false);
  protected readonly ageRefused = signal(false);
  protected readonly ageProblem = computed(() => (this.ageRefused() ? 'Issued at least (minutes) ago: enter a whole number of minutes, 0 or more.' : undefined));

  // The Register payment panel. Drafts of its number box: written by the box (`typeAmount`) and, from outside, by `openPayment` alone (another invoice, or the same one again). `closePayment` writes no draft: it removes the panel, and its box with it.
  protected readonly paying = signal<Invoice | undefined>(undefined);
  protected readonly referenceDraft = signal('');
  protected readonly amountDraft = signal('');
  protected readonly amountBad = signal(false);
  /** Bumped by `openPayment()`: see `unitsReset` in the stock page. */
  protected readonly amountReset = signal(0);
  protected readonly showPaymentProblems = signal(false);
  protected readonly result = signal<PaymentResult | undefined>(undefined);
  /** Set synchronously by the submit handler, before any request exists: a second `submit` in the same task ends there. */
  protected readonly submitting = signal(false);

  protected readonly registerPayment = injectMutation(() => ({
    mutationFn: (variables: { invoice: Invoice; request: Schemas['RegisterPaymentRequest'] }) => this.api.registerPayment(variables.invoice.invoiceId, variables.request),
    onSuccess: async (response) => {
      this.result.set({ status: response.status, response: response.data });
      // The payment changes both lists: the invoice becomes paid and its credit exposure is released.
      await Promise.all([this.queryClient.invalidateQueries({ queryKey: ['invoices'] }), this.queryClient.invalidateQueries({ queryKey: ['credits'] })]);
    },
    onSettled: () => this.submitting.set(false),
  }));

  /**
   * The order the paid invoice belongs to. An invoice carries only the order's business reference (openapi.yaml `listInvoices`), so the id the order page needs is looked up by that reference,
   * and only from a payment that SUCCEEDED (`result` is set by `onSuccess` alone and cleared by `openPayment`/`closePayment`): the reference is the response's own, never a filter box's.
   * `null` is the lookup's own answer "no such order"; it is told apart from "not asked yet" and from a failed lookup.
   */
  protected readonly orderLink = injectQuery(() => ({
    queryKey: ['orders', 'by-reference', this.result()?.response.orderReference] as const,
    queryFn: async () => (await this.api.listOrders({ orderReference: this.result()?.response.orderReference, page: 1, pageSize: 1 })).data.items[0]?.orderId ?? null,
    enabled: Boolean(this.result()?.response.orderReference),
  }));

  protected readonly paymentStep = computed(() => currencyInputStep(this.paying()?.currency ?? ''));
  private readonly parsedAmount = computed(() => {
    const invoice = this.paying();
    return invoice === undefined || this.amountBad() ? undefined : parseDecimalToMinorUnits(this.amountDraft(), currencyExponent(invoice.currency));
  });
  protected readonly amountProblem = computed(() => {
    const invoice = this.paying();
    if (!invoice || !this.showPaymentProblems() || this.parsedAmount() !== undefined) return undefined;
    const phrase = amountPhrase(this.amountDraft(), invoice.currency);
    return `${this.amountBad() ? 'Amount: the browser could not read what was typed. Enter' : 'Amount: enter'} ${phrase} (${invoice.currency}).`;
  });
  protected readonly referenceProblem = computed(() => {
    if (!this.showPaymentProblems()) return undefined;
    const reference = this.referenceDraft().trim();
    return reference === '' || reference.length > REFERENCE_MAX ? `Payment reference: enter the remittance reference, 1 to ${REFERENCE_MAX} characters.` : undefined;
  });

  protected creditsError(): string {
    return describeError(this.credits.error(), CREDITS_FALLBACK);
  }
  protected invoicesError(): string {
    return describeError(this.invoices.error(), INVOICES_FALLBACK);
  }
  protected paymentError(): string {
    return describeError(this.registerPayment.error(), PAYMENT_FALLBACK);
  }
  protected orderLinkError(): string {
    return describeError(this.orderLink.error(), ORDER_LINK_FALLBACK);
  }
  protected money(minorUnits: number, currency: string): string {
    return displayMoney(minorUnits, currency);
  }
  protected instant(value: string): string {
    return formatInstant(value);
  }

  protected setCreditRetailer(value: string): void {
    this.creditRetailer.set(value.trim());
    this.creditPage.set(1);
  }
  protected setCreditCompany(value: string): void {
    this.creditCompany.set(value.trim());
    this.creditPage.set(1);
  }
  protected setInvoiceStatus(value: string): void {
    this.invoiceStatus.set(value as Schemas['InvoiceStatus'] | '');
    this.invoicePage.set(1);
  }
  protected setInvoiceRetailer(value: string): void {
    this.invoiceRetailer.set(value.trim());
    this.invoicePage.set(1);
  }
  protected setInvoiceCompany(value: string): void {
    this.invoiceCompany.set(value.trim());
    this.invoicePage.set(1);
  }
  protected setInvoiceOrder(value: string): void {
    this.invoiceOrder.set(value.trim());
    this.invoicePage.set(1);
  }

  /** The age box was edited: keep its text AND whether the browser could parse it (`validity.badInput`), because an unparseable text arrives as `""`. */
  protected typeAge(target: HTMLInputElement): void {
    this.ageDraft.set(target.value);
    const unreadable = target.validity?.badInput === true;
    this.ageBad.set(unreadable);
    // Refused NOW, not on `change`: Chromium fires no `change` for an unreadable text typed into an EMPTY box (live: 0 events on Tab or Enter), so a refusal that waited for it never came.
    // A readable text clears the refusal; `applyAge` (on `change`) still refuses a readable text that is not a whole number of minutes.
    this.ageRefused.set(unreadable);
  }
  /** The age box was committed: an empty box clears the filter, a whole number sets it, anything else is refused in words and the filter is left as it was. */
  protected applyAge(): void {
    const text = this.ageDraft().trim();
    if (this.ageBad() || (text !== '' && parseMinutes(text) === undefined)) {
      this.ageRefused.set(true);
      return;
    }
    this.ageRefused.set(false);
    this.issuedBeforeMinutes.set(text === '' ? undefined : parseMinutes(text));
    this.invoicePage.set(1);
  }

  /** The panel opens for an invoice, or moves to another one: the drafts start from that invoice (its reference suggestion, its exact total) and a failure on the previous one does not follow. */
  protected openPayment(invoice: Invoice): void {
    this.paying.set(invoice);
    this.referenceDraft.set(suggestPaymentReference(invoice));
    this.amountDraft.set(minorUnitsToDecimalString(invoice.totalAmount, currencyExponent(invoice.currency)));
    this.amountBad.set(false);
    this.amountReset.update((count) => count + 1);
    this.showPaymentProblems.set(false);
    this.result.set(undefined);
    this.registerPayment.reset();
  }
  protected closePayment(): void {
    this.paying.set(undefined);
    this.result.set(undefined);
    this.registerPayment.reset();
  }

  /** The amount box was edited: keep its text AND whether the browser could parse it (`validity.badInput`), because an unparseable text arrives as `""`. */
  protected typeAmount(target: HTMLInputElement): void {
    this.amountDraft.set(target.value);
    this.amountBad.set(target.validity?.badInput === true);
  }

  protected submit(event: Event): void {
    event.preventDefault();
    if (this.submitting()) return;
    const invoice = this.paying();
    if (!invoice) return;
    this.showPaymentProblems.set(true);
    const amount = this.parsedAmount();
    const reference = this.referenceDraft().trim();
    if (amount === undefined || reference === '' || reference.length > REFERENCE_MAX) return;
    this.submitting.set(true);
    // The reference IS the idempotency key (invariant B10): there is no header, and a resend of the same remittance is answered 200 `duplicate`.
    this.registerPayment.mutate({ invoice, request: { paymentReference: reference, amount: { amount, currency: invoice.currency }, valueDate: new Date().toISOString(), source: 'operator' } });
  }
}
