"""The three fact topics the projector consumes (`asyncapi.yaml`: `ordersFacts`, `fulfillmentFacts`,
`billingFacts`). A unit test reads the spec and compares: the constants are not the authority.

The projector is the only consumer of all fourteen facts (`domain-model.md` 7.3), and the fourteen
are spread over the three topics, one per producing service. Which fact is which is decided on
`envelope.eventType` through `otc_contracts.FACT_MODELS`, never on the topic.
"""

ORDERS_FACTS_TOPIC = "otc.orders.facts.v1"
FULFILLMENT_FACTS_TOPIC = "otc.fulfillment.facts.v1"
BILLING_FACTS_TOPIC = "otc.billing.facts.v1"

PROJECTOR_FACT_TOPICS = (ORDERS_FACTS_TOPIC, FULFILLMENT_FACTS_TOPIC, BILLING_FACTS_TOPIC)
