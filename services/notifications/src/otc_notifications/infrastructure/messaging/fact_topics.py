"""The three fact topics the service consumes (`asyncapi.yaml`: `ordersFacts`, `fulfillmentFacts`,
`billingFacts`). A unit test reads the spec and compares: the constants are not the authority.

Notifications reads all three because its seven notified facts (`domain-model.md` 7.3) span all
three producers. Topics are per service, not per fact, so which of the fourteen facts on them is
acted on is decided on `envelope.eventType` (`application/notified_facts.py`), never on the topic.
"""

ORDERS_FACTS_TOPIC = "otc.orders.facts.v1"
FULFILLMENT_FACTS_TOPIC = "otc.fulfillment.facts.v1"
BILLING_FACTS_TOPIC = "otc.billing.facts.v1"

NOTIFICATION_FACT_TOPICS = (ORDERS_FACTS_TOPIC, FULFILLMENT_FACTS_TOPIC, BILLING_FACTS_TOPIC)
