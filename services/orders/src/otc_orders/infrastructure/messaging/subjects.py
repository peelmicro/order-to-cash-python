"""NATS subjects the Orders service answers or calls (`specs/shared/asyncapi.yaml` channels)."""

ORDERS_CREATE_SUBJECT = "orders.create"
STOCK_CHECK_SUBJECT = "fulfillment.stock.check"
# Replicas of the service share one queue group, so a request is answered by exactly one of them
# (without it, every replica would place the order).
ORDERS_QUEUE_GROUP = "otc-orders"
