"""`SagaCommandKind`: the six commands the saga issues over NATS, with their wire tokens.

The token is what `saga_commands.command` stores (the longest, `despatch.create`, is 15 characters
in a `varchar(30)`). `credit.release` is present because it is a saga command in `asyncapi.yaml`
(`creditRelease`); no step of the table owes it until feature 41 adds the rows.
"""

from enum import Enum


class SagaCommandKind(Enum):
    STOCK_RESERVE = "stock.reserve"
    STOCK_RELEASE = "stock.release"
    DESPATCH_CREATE = "despatch.create"
    CREDIT_HOLD = "credit.hold"
    INVOICE_ISSUE = "invoice.issue"
    CREDIT_RELEASE = "credit.release"
