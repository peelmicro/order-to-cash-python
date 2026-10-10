"""BC34 / L26: the three services' default Kafka client ids are non-empty and pairwise distinct.

Two producers sharing a client id are indistinguishable on the broker (quotas, logs, metrics), and
aiokafka sends an empty string verbatim (measured), so an empty default would be sent as is. Every
client-id variable is REMOVED from the environment for the construction, so the defaults themselves
are what is read, and the working directory is empty, so a developer's `.env` cannot supply one.

The per-service half (an empty or blank variable fails the boot naming the variable) is each
service's settings test: `test_orders_settings_env.py`, `test_fulfillment_settings_env.py`,
`test_billing_settings_env.py`.
"""

from pathlib import Path

import pytest

from otc_billing.infrastructure.settings import KafkaSettings as BillingKafka
from otc_fulfillment.infrastructure.settings import KafkaSettings as FulfillmentKafka
from otc_orders.infrastructure.settings import KafkaSettings as OrdersKafka

CLIENT_ID_VARIABLES = ("KAFKA_CLIENT_ID", "FULFILLMENT_KAFKA_CLIENT_ID", "BILLING_KAFKA_CLIENT_ID")


def test_bc34_the_three_default_client_ids_are_non_empty_and_pairwise_distinct(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # no `.env` of a developer can supply a value
    for variable in CLIENT_ID_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    ids = {
        "orders": OrdersKafka().client_id,
        "fulfillment": FulfillmentKafka().client_id,
        "billing": BillingKafka().client_id,
    }

    for service, client_id in ids.items():
        assert client_id.strip(), f"{service}'s default client id is empty or blank"
    assert len(set(ids.values())) == 3, f"two services share a default client id: {ids}"
    assert ids == {
        "orders": "otc-orders",
        "fulfillment": "otc-fulfillment",
        "billing": "otc-billing",
    }
