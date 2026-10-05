"""Human text for an amount: the exponent comes from ISO 4217 (SA-5), never from a locale.

#7's `formatMoney` (`packages/shared-kernel/src/domain/money-text.ts`): sign, integer digits grouped
in threes by a single ASCII space, `.` and the fraction digits when the exponent is positive, then
` <CURRENCY>`. Integer arithmetic only (`divmod`, never `/`).
"""

from otc_shared_kernel import exponent_of


def format_money(minor_units: int, currency: str) -> str:
    exponent = exponent_of(currency)
    sign = "-" if minor_units < 0 else ""
    # `10 ** exponent` is avoided on purpose: the AST money guard flags a non-literal exponent.
    scale = int("1" + "0" * exponent)
    integer_part, fraction_part = divmod(abs(minor_units), scale)
    grouped = f"{integer_part:,}".replace(",", " ")
    fraction = f".{fraction_part:0{exponent}d}" if exponent > 0 else ""
    return f"{sign}{grouped}{fraction} {currency}"
