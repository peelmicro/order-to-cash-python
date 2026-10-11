"""The closed consumer vocabulary (R17): per-service, identical path in every write model.

Kept out of the canonical `idempotent_consumer.py` so that file names no service (design 6.4, A1).
"""

import enum


class ConsumerName(enum.Enum):
    ORDERS_SAGA = "orders.saga"
    PROJECTOR = "projector"
    NOTIFICATIONS = "notifications"
