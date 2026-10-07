"""The three fact topics the saga consumes (`asyncapi.yaml`: `ordersFacts`, `fulfillmentFacts`,
`billingFacts`). A unit test reads the spec and compares: the constants are not the authority.

Topics are per service, not per fact, so routing is on `envelope.eventType`, never on the topic.
`ORDERS_FACTS_TOPIC` already exists (the outbox's topic) and is reused, not retyped.
"""

from otc_orders.infrastructure.outbox.topic import ORDERS_FACTS_TOPIC

FULFILLMENT_FACTS_TOPIC = "otc.fulfillment.facts.v1"
BILLING_FACTS_TOPIC = "otc.billing.facts.v1"

SAGA_FACT_TOPICS = (ORDERS_FACTS_TOPIC, FULFILLMENT_FACTS_TOPIC, BILLING_FACTS_TOPIC)
