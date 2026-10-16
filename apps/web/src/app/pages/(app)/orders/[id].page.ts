import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { RouteMeta } from '@analogjs/router';
import { injectQuery, QueryClient } from '@tanstack/angular-query-experimental';
import { map } from 'rxjs';
import { HlmAlertImports } from '@spartan-ng/helm/alert';
import { HlmBadgeImports } from '@spartan-ng/helm/badge';
import { HlmButtonImports } from '@spartan-ng/helm/button';
import { HlmCardImports } from '@spartan-ng/helm/card';
import { ApiClient } from '../../../api/api-client';
import { OrderStatusBadge } from '../../../components/order-status-badge';
import { displayMoney, formatInstant } from '../../../lib/format';
import { applyOrderUpdate, applyTimelineAppended, causingEntry, pendingRetryDelayMs, RefetchPlan, type OrderDetailResult } from '../../../lib/order-detail';
import type { OrderStreamClient, StreamConnectionStatus } from '../../../lib/order-stream-client';
import { describeError } from '../../../lib/problem';
import type { Schemas } from '../../../../shared/api-types';

export const routeMeta: RouteMeta = { title: 'Order' };

const DETAIL_FALLBACK = 'The order could not be loaded.';

const CONNECTION_LABEL: Record<StreamConnectionStatus, string> = {
  connecting: 'Connecting…',
  connected: 'Live',
  reconnecting: 'Reconnecting…',
  'gave-up': 'Connection lost',
};

export const orderDetailKey = (orderId: string) => ['order-detail', orderId] as const;

/**
 * One order: header, references and the live saga timeline (R50, R55). ONE stream per page, opened with the page and closed when it is left (closing is
 * what makes the BFF abort its upstream Gateway request). The stream is a notification channel: a fresh connection answers `stream.ready` with
 * `resumed: false`, which re-reads the order, so a fact that landed between the first read and the subscription is not lost; frames then patch the
 * cache, and a frame that arrives while the answer is still `202 ProjectionPending` re-reads it at once, which is how a pending page fills in.
 */
@Component({
  selector: 'app-order-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, OrderStatusBadge, ...HlmAlertImports, ...HlmBadgeImports, ...HlmButtonImports, ...HlmCardImports],
  template: `
    <div class="flex flex-col gap-6">
      <div class="flex items-center justify-between">
        <h1 class="text-xl font-semibold">Order detail</h1>
        <a routerLink="/orders" class="text-muted-foreground text-sm hover:underline">Back to orders</a>
      </div>

      @if (detail.isError()) {
        <div hlmAlert variant="destructive" data-testid="order-detail-error">
          <p hlmAlertDescription>{{ detailError() }}</p>
        </div>
      }

      @if (pending(); as waiting) {
        <div class="flex flex-col gap-2 rounded-md border border-dashed p-6 text-sm" data-testid="order-detail-pending" aria-live="polite">
          <p class="font-medium">Waiting for this order to appear</p>
          <p class="text-muted-foreground" data-testid="order-detail-pending-message">{{ waiting.pending.message ?? defaultPendingMessage }}</p>
          <p class="text-muted-foreground" data-testid="order-detail-pending-schedule">
            Checking again every {{ seconds(waiting.retryAfterMs) }} s, as the Gateway asked@if (detail.isFetching()) {
              · checking…
            }
          </p>
          <div>
            <button hlmBtn variant="outline" size="sm" type="button" (click)="checkNow()">Check now</button>
          </div>
        </div>
      } @else if (ready(); as order) {
        <section hlmCard>
          <header hlmCardHeader class="flex flex-row flex-wrap items-start justify-between gap-3">
            <div class="min-w-0">
              <h2 hlmCardTitle data-testid="order-detail-reference">{{ order.orderReference ?? order.orderId }}</h2>
              <p class="text-muted-foreground truncate text-sm">{{ order.retailer?.name ?? order.retailer?.code ?? '—' }} · {{ order.company?.name ?? order.company?.code ?? '—' }}</p>
            </div>
            <div class="flex items-center gap-2">
              <app-order-status-badge [status]="order.status" data-testid="order-detail-status" />
              <span hlmBadge [variant]="connectionVariant()" data-testid="stream-status" [attr.data-status]="streamStatus()">{{ connectionLabel() }}</span>
              @if (streamStatus() === 'gave-up') {
                <button hlmBtn variant="outline" size="sm" type="button" data-testid="stream-retry" (click)="retryConnection()">Retry connection</button>
              }
            </div>
          </header>
          <div hlmCardContent class="flex flex-col gap-3">
            @if (order.headerComplete === false) {
              <p class="text-muted-foreground text-xs" data-testid="order-detail-header-incomplete">Header still filling in: the timeline is real, some fields are not projected yet.</p>
            }
            <dl class="flex flex-wrap gap-x-8 gap-y-3 text-sm">
              <div>
                <dt class="text-muted-foreground">Total</dt>
                <dd class="font-medium" data-testid="order-detail-total">{{ total(order) }}</dd>
              </div>
              @if (order.cancellationReason) {
                <div>
                  <dt class="text-muted-foreground">Cancellation reason</dt>
                  <dd class="font-medium" data-testid="order-detail-cancellation">{{ order.cancellationReason }}</dd>
                </div>
              }
              @if (order.references?.despatchReference) {
                <div>
                  <dt class="text-muted-foreground">Despatch</dt>
                  <dd class="font-medium">{{ order.references?.despatchReference }}</dd>
                </div>
              }
              @if (order.references?.invoiceReference) {
                <div>
                  <dt class="text-muted-foreground">Invoice</dt>
                  <dd class="font-medium">{{ order.references?.invoiceReference }}</dd>
                </div>
              }
              @if (order.references?.paymentReference) {
                <div>
                  <dt class="text-muted-foreground">Payment</dt>
                  <dd class="font-medium">{{ order.references?.paymentReference }}</dd>
                </div>
              }
            </dl>
            @if ((order.items?.length ?? 0) > 0) {
              <ul class="text-muted-foreground text-sm" data-testid="order-detail-items">
                @for (item of order.items ?? []; track item.productCode) {
                  <li>{{ itemLine(item, order.currency) }}</li>
                }
              </ul>
            }
          </div>
        </section>

        <section class="flex flex-col gap-3" aria-labelledby="timeline-heading">
          <h2 id="timeline-heading" class="text-muted-foreground text-sm font-semibold">Timeline</h2>
          @if (order.events.length === 0) {
            <p class="text-muted-foreground text-sm">No facts recorded yet.</p>
          } @else {
            <ol class="flex flex-col gap-2" data-testid="order-timeline">
              @for (event of order.events; track event.eventId) {
                <li
                  [attr.id]="entryId(event.eventId)"
                  data-testid="timeline-entry"
                  [attr.data-event-id]="event.eventId"
                  class="flex items-start justify-between gap-4 rounded-md border p-3 text-sm transition-colors"
                  [class.bg-muted]="highlighted() === event.eventId"
                >
                  <div class="min-w-0">
                    <p class="font-medium">{{ event.summary }}</p>
                    <p class="text-muted-foreground text-xs">{{ event.eventType }}</p>
                    @if (cause(event, order.events); as causing) {
                      <p class="text-muted-foreground text-xs" data-testid="timeline-causation">
                        caused by <a [attr.href]="'#' + entryId(causing.eventId)" class="underline decoration-dotted underline-offset-2" data-testid="timeline-causation-link" (click)="goToCause($event, causing.eventId)">{{ causing.eventType }}</a>
                      </p>
                    }
                  </div>
                  <span class="text-muted-foreground text-xs whitespace-nowrap">{{ instant(event.occurredAt) }}</span>
                </li>
              }
            </ol>
          }
        </section>
      } @else if (detail.isPending()) {
        <p class="text-muted-foreground text-sm" data-testid="order-detail-loading">Loading order…</p>
      }
    </div>
  `,
})
export default class OrderDetailPage {
  private readonly api = inject(ApiClient);
  private readonly queryClient = inject(QueryClient);
  protected readonly defaultPendingMessage = 'The order was accepted and is not projected yet.';

  protected readonly orderId = toSignal(inject(ActivatedRoute).paramMap.pipe(map((params) => params.get('id') ?? '')), { initialValue: inject(ActivatedRoute).snapshot.paramMap.get('id') ?? '' });

  private readonly plan = new RefetchPlan();
  /** The live client of THIS page; the stream effect owns it. */
  private client: OrderStreamClient | undefined;
  protected readonly streamStatus = signal<StreamConnectionStatus>('connecting');
  protected readonly highlighted = signal<string | undefined>(undefined);

  protected readonly detail = injectQuery(() => ({
    queryKey: orderDetailKey(this.orderId()),
    queryFn: () => this.fetchDetail(this.orderId()),
    refetchInterval: (query: { state: { data: OrderDetailResult | undefined } }) => this.plan.interval(query.state.data),
    refetchIntervalInBackground: false,
  }));

  protected readonly pending = computed(() => {
    const data = this.detail.data();
    return data?.kind === 'pending' ? data : undefined;
  });
  protected readonly ready = computed(() => {
    const data = this.detail.data();
    return data?.kind === 'ready' ? data.detail : undefined;
  });
  protected readonly connectionLabel = computed(() => CONNECTION_LABEL[this.streamStatus()]);
  protected readonly connectionVariant = computed(() => (this.streamStatus() === 'connected' ? 'secondary' : this.streamStatus() === 'gave-up' ? 'destructive' : 'outline'));

  constructor() {
    // One stream per order id, opened with the page and closed when the page (or the id) goes.
    effect((onCleanup) => {
      const orderId = this.orderId();
      untracked(() => {
        this.plan.reset();
        const client = this.api.orderStream(orderId, {
          onOrderUpdated: (update) => this.patch((current) => applyOrderUpdate(current, update), orderId),
          onTimelineAppended: (entry) => this.patch((current) => applyTimelineAppended(current, entry), orderId),
          onResync: () => void this.detail.refetch(),
          onStatusChange: (status) => this.streamStatus.set(status),
        });
        this.client = client;
        client.connect();
        onCleanup(() => {
          client.disconnect();
          if (this.client === client) this.client = undefined;
        });
      });
    });

    // An EventSource cannot say WHY it gave up: a dropped network and a refused (signed-out) stream look the same. So when it gives up, ask the
    // order again through the query client, which CAN say: a 401 there reaches the app's sign-out redirect (session/signed-out.ts), and any other
    // failure is shown in its own words. Without this a TERMINAL order, which is never re-read, stayed on "Connection lost" with an expired
    // session (#8 backlog id 98).
    effect(() => {
      if (this.streamStatus() === 'gave-up') untracked(() => void this.detail.refetch());
    });
  }

  private async fetchDetail(orderId: string): Promise<OrderDetailResult> {
    const response = await this.api.getOrder(orderId);
    this.plan.noteRead();
    if (response.status === 202) {
      const pending = response.data as Schemas['ProjectionPending'];
      return { kind: 'pending', pending, retryAfterMs: pendingRetryDelayMs(response.retryAfterSeconds, pending) };
    }
    const detail = response.data as Schemas['OrderDetail'];
    // A fetched snapshot already contains these facts: a replayed frame of either type for one of them is a redelivery.
    this.client?.seedSeenEventIds(detail.events.map((event) => event.eventId));
    return { kind: 'ready', detail };
  }

  /** A live frame: patch the cache; while the answer is still pending there is nothing to patch, so the frame is the cue to read it again. */
  private patch(change: (current: OrderDetailResult | undefined) => OrderDetailResult | undefined, orderId: string): void {
    const current = this.queryClient.getQueryData<OrderDetailResult>(orderDetailKey(orderId));
    if (current?.kind === 'pending') {
      void this.detail.refetch();
      return;
    }
    this.queryClient.setQueryData<OrderDetailResult | undefined>(orderDetailKey(orderId), change);
  }

  protected detailError(): string {
    return describeError(this.detail.error(), DETAIL_FALLBACK);
  }

  protected checkNow(): void {
    void this.detail.refetch();
  }

  /** Retry re-checks through a query first, so it never reopens a stream the session can no longer open; a refusal there ends at the sign-in page or in the error above. */
  protected async retryConnection(): Promise<void> {
    const checked = await this.detail.refetch();
    if (checked.isSuccess) this.client?.connect();
  }

  /** The retry interval in seconds as text (`60000` -> `60`, `500` -> `0.5`): a figure for a sentence, not money. */
  protected seconds(milliseconds: number): string {
    return String(milliseconds / 1000);
  }
  protected instant(value: string): string {
    return formatInstant(value);
  }
  protected total(order: Schemas['OrderDetail']): string {
    return displayMoney(order.totals?.totalAmount, order.currency);
  }
  protected itemLine(item: Schemas['OrderItem'], currency: string | undefined): string {
    const discount = item.lineDiscount > 0 ? ` (− ${displayMoney(item.lineDiscount, currency)})` : '';
    return `${item.quantity} × ${item.name ?? item.productCode} at ${displayMoney(item.unitPrice, currency)}${discount}`;
  }
  protected entryId(eventId: string): string {
    return `timeline-entry-${eventId}`;
  }
  protected cause(entry: Schemas['TimelineEntry'], events: readonly Schemas['TimelineEntry'][]): Schemas['TimelineEntry'] | undefined {
    return causingEntry(entry, events);
  }
  protected goToCause(event: Event, eventId: string): void {
    event.preventDefault();
    this.highlighted.set(eventId);
    document.getElementById(this.entryId(eventId))?.scrollIntoView?.({ block: 'center' });
  }
}
