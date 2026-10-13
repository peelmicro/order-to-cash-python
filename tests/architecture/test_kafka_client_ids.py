"""BC34 / L26: the five services' default Kafka client ids are non-empty and pairwise distinct.

Two producers sharing a client id are indistinguishable on the broker (quotas, logs, metrics), and
aiokafka sends an empty string verbatim (measured), so an empty default would be sent as is. Every
client-id variable is REMOVED from the environment for the construction, so the defaults themselves
are what is read, and the working directory is empty, so a developer's `.env` cannot supply one.

The per-service half (an empty or blank variable fails the boot naming the variable) is each
service's settings test: `test_orders_settings_env.py`, `test_fulfillment_settings_env.py`,
`test_billing_settings_env.py`, `test_notifications_settings_env.py` and the Projector's
`test_projector_settings_env.py`.
"""

from pathlib import Path

import pytest

from otc_billing.infrastructure.settings import KafkaSettings as BillingKafka
from otc_fulfillment.infrastructure.settings import KafkaSettings as FulfillmentKafka
from otc_notifications.composition import DEAD_LETTER_CLIENT_ID as NOTIFICATIONS_DLQ
from otc_notifications.composition import HEALTH_CLIENT_ID as NOTIFICATIONS_HEALTH
from otc_notifications.infrastructure.settings import KafkaSettings as NotificationsKafka
from otc_orders.composition import DEAD_LETTER_CLIENT_ID as ORDERS_DLQ
from otc_orders.composition import DLQ_DEPTH_CLIENT_ID as ORDERS_DLQ_DEPTH
from otc_orders.composition import HEALTH_CLIENT_ID as ORDERS_HEALTH
from otc_orders.infrastructure.messaging.kafka_fact_subscriber import CLIENT_ID as ORDERS_SAGA
from otc_orders.infrastructure.settings import KafkaSettings as OrdersKafka
from otc_projector.composition import DEAD_LETTER_CLIENT_ID as PROJECTOR_DLQ
from otc_projector.composition import HEALTH_CLIENT_ID as PROJECTOR_HEALTH
from otc_projector.infrastructure.settings import KafkaSettings as ProjectorKafka

CLIENT_ID_VARIABLES = (
    "KAFKA_CLIENT_ID",
    "FULFILLMENT_KAFKA_CLIENT_ID",
    "BILLING_KAFKA_CLIENT_ID",
    "NOTIFICATIONS_KAFKA_CLIENT_ID",
    "PROJECTOR_KAFKA_CLIENT_ID",
)


def test_bc34_the_five_default_client_ids_are_non_empty_and_pairwise_distinct(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # no `.env` of a developer can supply a value
    for variable in CLIENT_ID_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    ids = {
        "orders": OrdersKafka().client_id,
        "fulfillment": FulfillmentKafka().client_id,
        "billing": BillingKafka().client_id,
        "notifications": NotificationsKafka().client_id,
        "projector": ProjectorKafka().client_id,
    }

    for service, client_id in ids.items():
        assert client_id.strip(), f"{service}'s default client id is empty or blank"
    assert len(set(ids.values())) == 5, f"two services share a default client id: {ids}"
    assert ids == {
        "orders": "otc-orders",
        "fulfillment": "otc-fulfillment",
        "billing": "otc-billing",
        "notifications": "otc-notifications",
        "projector": "otc-projector",
    }


def test_or8_the_dead_letter_client_ids_are_distinct_from_every_other_client_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Feature 27 S4.9: each fact consumer's dead-letter producer has its own id, so the broker
    tells it apart from the service's relay or consumer connection. `otc-orders-dlq-depth` (S5.6)
    and the three readiness-probe admin clients (`otc-<svc>-health`, S6.2) are in the table."""
    monkeypatch.chdir(tmp_path)
    for variable in CLIENT_ID_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    ids = {
        "orders relay": OrdersKafka().client_id,
        "fulfillment relay": FulfillmentKafka().client_id,
        "billing relay": BillingKafka().client_id,
        "notifications consumer": NotificationsKafka().client_id,
        "projector consumer": ProjectorKafka().client_id,
        "orders saga consumer": ORDERS_SAGA,
        "orders dead letters": ORDERS_DLQ,
        "projector dead letters": PROJECTOR_DLQ,
        "notifications dead letters": NOTIFICATIONS_DLQ,
        "orders dead-letter depth": ORDERS_DLQ_DEPTH,
        "orders health probe": ORDERS_HEALTH,
        "notifications health probe": NOTIFICATIONS_HEALTH,
        "projector health probe": PROJECTOR_HEALTH,
    }

    assert all(client_id.strip() for client_id in ids.values()), ids
    assert len(set(ids.values())) == len(ids), f"two connections share a client id: {ids}"
    assert (ORDERS_DLQ, PROJECTOR_DLQ, NOTIFICATIONS_DLQ) == (
        "otc-orders-dlq",
        "otc-projector-dlq",
        "otc-notifications-dlq",
    )
    assert ORDERS_DLQ_DEPTH == "otc-orders-dlq-depth"
    assert (ORDERS_HEALTH, NOTIFICATIONS_HEALTH, PROJECTOR_HEALTH) == (
        "otc-orders-health",
        "otc-notifications-health",
        "otc-projector-health",
    )
