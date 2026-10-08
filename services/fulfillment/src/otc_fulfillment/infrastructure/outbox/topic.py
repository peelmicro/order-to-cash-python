"""The one topic the Fulfillment outbox publishes to (`asyncapi.yaml`, channel `fulfillmentFacts`).

A unit test reads the spec and compares: the constant is not the authority, the spec is.
"""

FULFILLMENT_FACTS_TOPIC = "otc.fulfillment.facts.v1"
