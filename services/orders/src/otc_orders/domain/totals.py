"""Order totals (invariant O3, R6): a pure function over a candidate tuple of lines.

Named `Money` methods only (`add`, `subtract`, `multiply`): the kernel's operators are typed
`other: object`, so `mypy` would not see a wrong operand. The function does not check the sign;
callers decide, which keeps it total.
"""

from dataclasses import dataclass

from otc_orders.domain.order_line import OrderLine
from otc_shared_kernel import Money


@dataclass(frozen=True, slots=True)
class OrderTotals:
    initial_amount: Money
    initial_discount: Money
    total_amount: Money


def compute_totals(lines: tuple[OrderLine, ...], currency: str) -> OrderTotals:
    initial_amount = Money.zero(currency)
    line_discounts = Money.zero(currency)
    for line in lines:
        initial_amount = initial_amount.add(line.unit_price.multiply(line.quantity))
        line_discounts = line_discounts.add(line.line_discount)
    order_discount = Money.zero(currency)  # R6's order-level term: always zero (design.md 5.4)
    initial_discount = line_discounts.add(order_discount)
    return OrderTotals(initial_amount, initial_discount, initial_amount.subtract(initial_discount))
