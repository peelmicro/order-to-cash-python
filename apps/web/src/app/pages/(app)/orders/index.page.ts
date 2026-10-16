import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { RouteMeta } from '@analogjs/router';
import { injectQuery } from '@tanstack/angular-query-experimental';
import { HlmAlertImports } from '@spartan-ng/helm/alert';
import { HlmButtonImports } from '@spartan-ng/helm/button';
import { HlmInputImports } from '@spartan-ng/helm/input';
import { HlmLabelImports } from '@spartan-ng/helm/label';
import { HlmTableImports } from '@spartan-ng/helm/table';
import { ApiClient } from '../../../api/api-client';
import { ORDER_STATUSES, OrderStatusBadge } from '../../../components/order-status-badge';
import { Pager } from '../../../components/pager';
import { displayMoney, formatInstant } from '../../../lib/format';
import { describeError } from '../../../lib/problem';
import { catalogCompaniesQuery, catalogRetailersQuery } from '../../../orders/catalog';
import type { Schemas } from '../../../../shared/api-types';

export const routeMeta: RouteMeta = { title: 'Orders' };

const PAGE_SIZE = 20;
/** The list has no stream of its own in the contract, so it is re-read every 5 s (the same key: a poll never opens a new request kind). */
export const ORDERS_POLL_MS = 5_000;

const ORDERS_FALLBACK = 'The orders could not be loaded.';
const FILTER_FALLBACK = 'the list could not be loaded';

/** The order list (read model, R54): filters, paging, and three distinct states, loading, empty and error. */
@Component({
  selector: 'app-orders-list',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, OrderStatusBadge, Pager, ...HlmAlertImports, ...HlmButtonImports, ...HlmInputImports, ...HlmLabelImports, ...HlmTableImports],
  template: `
    <div class="flex flex-col gap-6">
      <div class="flex items-center justify-between">
        <h1 class="text-xl font-semibold">Orders</h1>
        <a hlmBtn routerLink="/orders/place">Place order</a>
      </div>

      <div class="flex flex-wrap items-end gap-4">
        <div class="flex flex-col gap-1.5">
          <label hlmLabel for="order-status-filter">Status</label>
          <select hlmInput id="order-status-filter" class="w-48" [value]="status()" (change)="setStatus($any($event.target).value)">
            <option value="">All statuses</option>
            @for (option of statuses; track option) {
              <option [value]="option">{{ option }}</option>
            }
          </select>
        </div>
        <div class="flex flex-col gap-1.5">
          <label hlmLabel for="order-retailer-filter">Retailer</label>
          <select hlmInput id="order-retailer-filter" class="w-64" [value]="retailerCode()" (change)="setRetailer($any($event.target).value)">
            <option value="">All retailers</option>
            @for (retailer of retailers.data() ?? []; track retailer.code) {
              <option [value]="retailer.code">{{ retailer.name }} ({{ retailer.code }})</option>
            }
          </select>
          @if (retailers.isError()) {
            <p class="text-destructive text-xs" data-testid="order-retailer-filter-error">Retailer filter unavailable: {{ retailerFilterError() }}</p>
          }
        </div>
        <div class="flex flex-col gap-1.5">
          <label hlmLabel for="order-company-filter">Company</label>
          <select hlmInput id="order-company-filter" class="w-64" [value]="companyCode()" (change)="setCompany($any($event.target).value)">
            <option value="">All companies</option>
            @for (company of companies.data() ?? []; track company.code) {
              <option [value]="company.code">{{ company.name }} ({{ company.code }})</option>
            }
          </select>
          @if (companies.isError()) {
            <p class="text-destructive text-xs" data-testid="order-company-filter-error">Company filter unavailable: {{ companyFilterError() }}</p>
          }
        </div>
        <div class="flex flex-col gap-1.5">
          <label hlmLabel for="order-reference-filter">Reference</label>
          <input hlmInput id="order-reference-filter" class="w-40" placeholder="ORD-000001" [value]="orderReference()" (change)="setReference($any($event.target).value)" />
        </div>
      </div>

      @if (orders.isError()) {
        <div hlmAlert variant="destructive" data-testid="orders-error">
          <p hlmAlertDescription>{{ ordersError() }}</p>
        </div>
      } @else if (orders.isPending()) {
        <p class="text-muted-foreground text-sm" data-testid="orders-loading">Loading orders…</p>
      } @else if (rows().length === 0) {
        <p class="text-muted-foreground rounded-md border border-dashed p-6 text-sm" data-testid="orders-empty">No orders match these filters.</p>
      } @else {
        <table hlmTable data-testid="orders-table">
          <thead hlmTHead>
            <tr hlmTr>
              <th hlmTh scope="col">Reference</th>
              <th hlmTh scope="col">Date</th>
              <th hlmTh scope="col">Retailer</th>
              <th hlmTh scope="col">Company</th>
              <th hlmTh scope="col">Status</th>
              <th hlmTh scope="col" class="text-right">Total</th>
            </tr>
          </thead>
          <tbody hlmTBody>
            @for (order of rows(); track order.orderId) {
              <tr hlmTr data-testid="order-row">
                <td hlmTd class="font-medium">
                  <a [routerLink]="['/orders', order.orderId]" class="hover:underline">{{ order.orderReference }}</a>
                </td>
                <td hlmTd>{{ instant(order.orderDate) }}</td>
                <td hlmTd>{{ order.retailer.name ?? order.retailer.code }}</td>
                <td hlmTd>{{ order.company.name ?? order.company.code }}</td>
                <td hlmTd><app-order-status-badge [status]="order.status" /></td>
                <td hlmTd class="text-right tabular-nums" data-testid="order-total">{{ money(order) }}</td>
              </tr>
            }
          </tbody>
        </table>
      }

      <app-pager [counts]="counts()" [current]="page()" noun="orders" testId="orders-pager" (pageChange)="page.set($event)" />
    </div>
  `,
})
export default class OrdersListPage {
  private readonly api = inject(ApiClient);
  protected readonly statuses = ORDER_STATUSES;

  protected readonly page = signal(1);
  protected readonly status = signal<Schemas['OrderStatus'] | ''>('');
  protected readonly retailerCode = signal('');
  protected readonly companyCode = signal('');
  protected readonly orderReference = signal('');

  protected readonly orders = injectQuery(() => ({
    queryKey: ['orders', { page: this.page(), status: this.status(), retailerCode: this.retailerCode(), companyCode: this.companyCode(), orderReference: this.orderReference() }] as const,
    queryFn: async () =>
      (
        await this.api.listOrders({
          status: this.status() ? [this.status()] : undefined,
          retailerCode: this.retailerCode(),
          companyCode: this.companyCode(),
          orderReference: this.orderReference().trim(),
          page: this.page(),
          pageSize: PAGE_SIZE,
        })
      ).data,
    refetchInterval: ORDERS_POLL_MS,
  }));
  protected readonly retailers = injectQuery(() => catalogRetailersQuery(this.api));
  protected readonly companies = injectQuery(() => catalogCompaniesQuery(this.api));

  protected readonly rows = computed(() => this.orders.data()?.items ?? []);
  /** Only a settled, successful answer has counts: nothing is claimed while loading or after a failure (TanStack keeps `data` after a failed refetch, so the error state is checked first). */
  protected readonly counts = computed(() => (this.orders.isError() ? undefined : this.orders.data()?.page));

  protected ordersError(): string {
    return describeError(this.orders.error(), ORDERS_FALLBACK);
  }
  protected retailerFilterError(): string {
    return describeError(this.retailers.error(), FILTER_FALLBACK);
  }
  protected companyFilterError(): string {
    return describeError(this.companies.error(), FILTER_FALLBACK);
  }

  protected instant(value: string): string {
    return formatInstant(value);
  }
  protected money(order: Schemas['OrderSummary']): string {
    return displayMoney(order.totals.totalAmount, order.currency);
  }

  protected setStatus(value: string): void {
    this.status.set(value as Schemas['OrderStatus'] | '');
    this.page.set(1);
  }
  protected setRetailer(value: string): void {
    this.retailerCode.set(value);
    this.page.set(1);
  }
  protected setCompany(value: string): void {
    this.companyCode.set(value);
    this.page.set(1);
  }
  protected setReference(value: string): void {
    this.orderReference.set(value);
    this.page.set(1);
  }
}
