"""NATS subjects the Billing service answers (`specs/shared/asyncapi.yaml` channels)."""

CREDIT_HOLD_SUBJECT = "billing.credit.hold"
CREDIT_RELEASE_SUBJECT = "billing.credit.release"
CREDIT_LIST_SUBJECT = "billing.credit.list"
INVOICE_ISSUE_SUBJECT = "billing.invoice.issue"
INVOICE_LIST_SUBJECT = "billing.invoice.list"
PAYMENT_REGISTER_SUBJECT = "billing.payment.register"
# Replicas of the service share one queue group, so a request is answered by exactly one of them
# (without it, every replica would hold the same credit).
BILLING_QUEUE_GROUP = "otc-billing"
