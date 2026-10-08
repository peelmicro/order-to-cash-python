"""NATS subjects the Fulfillment service answers (`specs/shared/asyncapi.yaml` channels)."""

STOCK_CHECK_SUBJECT = "fulfillment.stock.check"
STOCK_RESERVE_SUBJECT = "fulfillment.stock.reserve"
STOCK_RELEASE_SUBJECT = "fulfillment.stock.release"
STOCK_LIST_SUBJECT = "fulfillment.stock.list"
STOCK_REPLENISH_SUBJECT = "fulfillment.stock.replenish"
DESPATCH_CREATE_SUBJECT = "fulfillment.despatch.create"
# Replicas of the service share one queue group, so a request is answered by exactly one of them
# (without it, every replica would reserve the same stock).
FULFILLMENT_QUEUE_GROUP = "otc-fulfillment"
