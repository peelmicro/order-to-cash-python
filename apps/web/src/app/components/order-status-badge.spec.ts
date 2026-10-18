// The OrderStatusBadge as a COMPONENT (Angular Testing Library): each of the nine states renders its own text and carries it in `data-status`.
import { render, screen } from '@testing-library/angular';
import { describe, expect, it } from 'vitest';
import { ORDER_STATUSES, OrderStatusBadge } from './order-status-badge';

describe('R-status-badge-component: the badge shows the status it is given', () => {
  it('the population is the nine states of the order state machine', () => {
    expect([...ORDER_STATUSES].sort()).toEqual(['cancelled', 'completed', 'confirmed', 'credit_approved', 'despatched', 'invoiced', 'paid', 'placed', 'stock_reserved']);
  });

  it.each(ORDER_STATUSES)('%s renders its own text and data-status', async (status) => {
    await render(OrderStatusBadge, { inputs: { status } });
    const badge = screen.getByText(status);
    expect(badge.textContent).toBe(status);
    expect(badge.getAttribute('data-status')).toBe(status);
  });
});
