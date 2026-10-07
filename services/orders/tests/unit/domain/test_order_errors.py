"""The domain-error population of the Order aggregate (`design.md` section 10, tasks.md 3.16).

The expected set is a LITERAL of twelve `(class name, CODE)` pairs; the actual set is found by
walking every module of `otc_orders.domain` for `DomainError` subclasses it defines. A thirteenth
class (#8's A4 shape: eleven shipped against a table of ten) fails by name.
"""

import importlib
import pkgutil

import otc_orders.domain
from otc_shared_kernel import DomainError

TABLE = {
    ("OrderMustHaveAtLeastOneLineError", "order.must_have_at_least_one_line"),
    ("OrderTotalMustNotBeNegativeError", "order.total_must_not_be_negative"),
    ("OrderLinesAreFrozenError", "order.lines_are_frozen"),
    ("OrderLineNotFoundError", "order.line_not_found"),
    ("OrderLineCurrencyMismatchError", "order.line_currency_mismatch"),
    ("IllegalOrderTransitionError", "order.illegal_transition"),
    ("OrderNotCancellableError", "order.not_cancellable"),
    ("CancellationReasonRequiredError", "order.cancellation_reason_required"),
    ("UnknownCancellationReasonError", "order.cancellation_reason_unknown"),
    ("CancellationReasonNotApplicableError", "order.cancellation_reason_not_applicable"),
    ("InvalidOrderSnapshotError", "order.snapshot_invalid"),
    ("InstantNotUtcError", "order.instant_not_utc"),
}


def _defined_domain_errors() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for module_info in pkgutil.walk_packages(
        otc_orders.domain.__path__, prefix="otc_orders.domain."
    ):
        module = importlib.import_module(module_info.name)
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, DomainError)
                and value.__module__.startswith("otc_orders.domain")
            ):
                found.add((value.__name__, str(getattr(value, "CODE", None))))
    return found


def test_the_orders_domain_error_population_is_the_literal_table() -> None:
    found = _defined_domain_errors()
    assert len(TABLE) == 12
    assert found == TABLE, (
        f"domain errors differ from design.md section 10: undeclared={sorted(found - TABLE)} "
        f"missing={sorted(TABLE - found)}"
    )
    assert len({code for _, code in found}) == 12, "two domain errors share a code"
