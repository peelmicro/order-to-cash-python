import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { HlmBadgeImports } from '@spartan-ng/helm/badge';
import type { Schemas } from '../../shared/api-types';

/** The order state machine's states, typed so the compiler fails here if openapi.yaml's `OrderStatus` gains or loses one. */
const STATUS_SET = { placed: true, stock_reserved: true, credit_approved: true, confirmed: true, despatched: true, invoiced: true, paid: true, completed: true, cancelled: true } satisfies Record<Schemas['OrderStatus'], true>;
export const ORDER_STATUSES = Object.keys(STATUS_SET) as Schemas['OrderStatus'][];

@Component({
  selector: 'app-order-status-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [...HlmBadgeImports],
  template: `<span hlmBadge [variant]="variant()" [attr.data-status]="status()">{{ status() }}</span>`,
})
export class OrderStatusBadge {
  readonly status = input.required<Schemas['OrderStatus']>();
  protected readonly variant = computed(() => (this.status() === 'cancelled' ? 'destructive' : this.status() === 'completed' || this.status() === 'paid' ? 'secondary' : 'outline'));
}
