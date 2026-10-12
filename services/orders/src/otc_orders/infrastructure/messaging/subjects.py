"""NATS subjects the Orders service answers or calls (`specs/shared/asyncapi.yaml` channels)."""

ORDERS_CREATE_SUBJECT = "orders.create"
ORDERS_CANCEL_SUBJECT = "orders.cancel"
CATALOG_REFERENCE_LIST_SUBJECT = "catalog.reference.list"
STOCK_CHECK_SUBJECT = "fulfillment.stock.check"
# Replicas of the service share one queue group, so a request is answered by exactly one of them
# (without it, every replica would place the order). Every subject Orders answers joins it.
ORDERS_QUEUE_GROUP = "otc-orders"
