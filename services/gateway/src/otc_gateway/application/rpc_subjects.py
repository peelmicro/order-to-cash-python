"""The eight subjects the Gateway calls: the `address:` of `specs/shared/asyncapi.yaml` channels.

Transcribed, not imported from another service (service independence), and asserted against the
contract by `tests/unit/test_rpc_subjects.py`, which reads the channel addresses from the YAML:
a subject typed here that the contract does not declare, or a declared Gateway-called subject
missing here, fails by name (#8 defect D1 asserted a constant against itself).
"""

from typing import Final

ORDERS_CREATE: Final = "orders.create"
ORDERS_CANCEL: Final = "orders.cancel"
CATALOG_REFERENCE_LIST: Final = "catalog.reference.list"
STOCK_LIST: Final = "fulfillment.stock.list"
STOCK_REPLENISH: Final = "fulfillment.stock.replenish"
CREDIT_LIST: Final = "billing.credit.list"
INVOICE_LIST: Final = "billing.invoice.list"
PAYMENT_REGISTER: Final = "billing.payment.register"
