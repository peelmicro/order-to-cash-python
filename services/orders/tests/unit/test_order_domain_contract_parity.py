"""The aggregate's closed sets against the generated wire models (design.md 11.1; tasks 2.2, 4.16).

The pure domain tests may not import `otc_contracts` (that is what keeps the domain free of wire
models), so the two checks that need it live here, one directory up.
"""

from enum import Enum

import pytest

from otc_contracts.facts import FACT_MODELS
from otc_contracts.generated import asyncapi, openapi
from otc_orders.domain.events import OrderCancelled, OrderCompleted, OrderConfirmed, OrderPlaced
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.compensation_step import CompensationStepKind
from otc_orders.domain.value_objects.order_status import OrderStatus


def _tokens(enum: type[Enum]) -> set[str]:
    return {str(member.value) for member in enum}


@pytest.mark.parametrize(
    ("domain", "generated"),
    [
        (OrderStatus, asyncapi.OrderStatus),
        (OrderStatus, openapi.OrderStatus),
        (CancellationReason, asyncapi.CancellationReason),
        (CancellationReason, openapi.CancellationReason),
        (CompensationStepKind, asyncapi.Step),
    ],
    ids=[
        "status-asyncapi",
        "status-openapi",
        "reason-asyncapi",
        "reason-openapi",
        "compensation-step-asyncapi",
    ],
)
def test_domain_tokens_equal_the_generated_contract_enums_both_ways(
    domain: type[Enum], generated: type[Enum]
) -> None:
    only_in_domain = _tokens(domain) - _tokens(generated)
    only_in_contract = _tokens(generated) - _tokens(domain)
    assert not only_in_domain, f"{domain.__name__} has tokens the contract lacks: {only_in_domain}"
    assert not only_in_contract, (
        f"{domain.__name__} lacks tokens the contract has: {only_in_contract}"
    )
    assert len(domain) == len(generated)


def test_order_event_types_are_all_declared_in_the_shared_fact_catalogue() -> None:
    types = {
        OrderPlaced.EVENT_TYPE,
        OrderConfirmed.EVENT_TYPE,
        OrderCompleted.EVENT_TYPE,
        OrderCancelled.EVENT_TYPE,
    }
    assert len(types) == 4
    assert types <= set(FACT_MODELS)
    order_facts = {key for key in FACT_MODELS if key.startswith("order.")}
    # `order.despatched.v1` is Fulfillment's fact, `order.saga_failed.v1` the dead-letter feature's.
    assert order_facts - {"order.saga_failed.v1", "order.despatched.v1"} == types
