"""The notified-fact filter (acceptance 4; R17 context; `domain-model.md` 7.2 and 7.3).

#8's first review: the handler guards were invoked PAST the filter and never crossed it, so deleting
five of the seven entries left the suite green. Here the filter is the keys of ONE dictionary
(`NOTIFIED_FACTS`, which is also the routing), and these tests cross it: the literal below
classifies all FOURTEEN facts of 7.2, the keys must equal the notified literal exactly, and
`test_the_consumer_*` (`presentation`, next file) drives every one of the fourteen through the real
consumer, dispatcher and handlers.

The expected set is a literal here, and ALSO read from `specs/shared/asyncapi.yaml` (the
`notificationsConsume*` operations): neither the code nor this literal is the authority.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from otc_contracts import FACT_MODELS
from otc_notifications.application import messages
from otc_notifications.application.notified_facts import NOTIFIED_FACTS

ASYNCAPI = Path(__file__).resolve().parents[4] / "specs" / "shared" / "asyncapi.yaml"

# domain-model.md 7.2 (the fourteen), classified by 7.3: the seven Notifications consumes, and the
# seven it deliberately does not (stock.* and credit.* are saga mechanics, saga_failed diagnostic).
NOTIFIED = {
    "order.placed.v1",
    "order.confirmed.v1",
    "order.despatched.v1",
    "invoice.issued.v1",
    "payment.received.v1",
    "order.completed.v1",
    "order.cancelled.v1",
}
NOT_NOTIFIED = {
    "stock.reserved.v1",
    "stock.rejected.v1",
    "stock.released.v1",
    "credit.approved.v1",
    "credit.rejected.v1",
    "credit.released.v1",
    "order.saga_failed.v1",
}
COMMAND_OF = {
    "order.placed.v1": "NotifyOrderPlacedCommand",
    "order.confirmed.v1": "NotifyOrderConfirmedCommand",
    "order.despatched.v1": "NotifyOrderDespatchedCommand",
    "invoice.issued.v1": "NotifyInvoiceIssuedCommand",
    "payment.received.v1": "NotifyPaymentReceivedCommand",
    "order.completed.v1": "NotifyOrderCompletedCommand",
    "order.cancelled.v1": "NotifyOrderCancelledCommand",
}


def spec_notified_event_types() -> set[str]:
    document: dict[str, Any] = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    found: set[str] = set()
    for name, operation in document["operations"].items():
        if not name.startswith("notificationsConsume"):
            continue
        for ref in operation["messages"]:
            _, _, channel, _, message = ref["$ref"].split("/")
            component = document["channels"][channel]["messages"][message]["$ref"].rsplit("/", 1)[1]
            found.add(document["components"]["messages"][component]["name"])
    return found


def test_the_fourteen_facts_are_classified_exactly_once() -> None:
    assert len(NOTIFIED) == 7
    assert len(NOT_NOTIFIED) == 7
    assert NOTIFIED.isdisjoint(NOT_NOTIFIED)
    assert set(FACT_MODELS) == NOTIFIED | NOT_NOTIFIED, "the literal covers all fourteen, no more"


def test_the_literal_equals_the_spec_s_notifications_operations() -> None:
    assert spec_notified_event_types() == NOTIFIED


def test_the_filter_is_exactly_the_seven_notified_types() -> None:
    """Delete any one entry: this fails naming it. Add any non-notified type (each `stock.*` and
    `credit.*` fact, `order.saga_failed.v1`): this fails naming it."""
    assert set(NOTIFIED_FACTS) == NOTIFIED, (
        f"missing {sorted(NOTIFIED - set(NOTIFIED_FACTS))}, "
        f"extra {sorted(set(NOTIFIED_FACTS) - NOTIFIED)}"
    )


@pytest.mark.parametrize("event_type", sorted(NOT_NOTIFIED))
def test_a_non_notified_fact_is_not_routed(event_type: str) -> None:
    assert event_type not in NOTIFIED_FACTS


@pytest.mark.parametrize("event_type", sorted(NOTIFIED))
def test_each_notified_fact_parses_with_its_own_model_into_its_own_command(
    event_type: str, facts: Any
) -> None:
    fact = NOTIFIED_FACTS[event_type]
    assert fact.event_model is FACT_MODELS[event_type]
    command = fact.command(event=facts.event(event_type))
    assert type(command).__name__ == COMMAND_OF[event_type]
    assert getattr(messages, COMMAND_OF[event_type]) is type(command)


def test_the_seven_commands_are_the_seven_messages_of_the_application() -> None:
    declared = {name for name in vars(messages) if name.startswith("Notify")}
    assert declared == set(COMMAND_OF.values())
