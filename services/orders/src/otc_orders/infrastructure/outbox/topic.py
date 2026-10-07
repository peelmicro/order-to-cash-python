"""The one topic the Orders outbox publishes to (`asyncapi.yaml`, channel `ordersFacts`).

A unit test reads the spec and compares: the constant is not the authority, the spec is.
"""

ORDERS_FACTS_TOPIC = "otc.orders.facts.v1"
