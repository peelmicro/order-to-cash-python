"""The one topic the Billing outbox publishes to (`asyncapi.yaml`, channel `billingFacts`).

A unit test reads the spec and compares: the constant is not the authority, the spec is.
"""

BILLING_FACTS_TOPIC = "otc.billing.facts.v1"
