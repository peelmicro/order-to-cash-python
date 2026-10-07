"""`OrderLine` (an entity inside the Order aggregate) and `OrderLineInput` (what `place` takes)."""

from dataclasses import dataclass

from otc_shared_kernel import Entity, Money, Quantity, UniqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderLineInput:
    product_code: str
    description: str | None
    quantity: Quantity
    unit_price: Money
    line_discount: Money


class OrderLine(Entity):
    """Immutable: changing a line replaces it with a new `OrderLine` carrying the same id.

    Two lines with the same product and price are different lines (identity equality, not value).
    """

    __slots__ = ("_description", "_line_discount", "_product_code", "_quantity", "_unit_price")

    def __init__(
        self,
        line_id: UniqueId,
        *,
        product_code: str,
        description: str | None,
        quantity: Quantity,
        unit_price: Money,
        line_discount: Money,
    ) -> None:
        super().__init__(line_id)
        self._product_code = product_code
        self._description = description
        self._quantity = quantity
        self._unit_price = unit_price
        self._line_discount = line_discount

    @property
    def product_code(self) -> str:
        return self._product_code

    @property
    def description(self) -> str | None:
        return self._description

    @property
    def quantity(self) -> Quantity:
        return self._quantity

    @property
    def unit_price(self) -> Money:
        return self._unit_price

    @property
    def line_discount(self) -> Money:
        return self._line_discount
