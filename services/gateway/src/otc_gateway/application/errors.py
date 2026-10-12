"""Application errors of the Gateway. Plain exceptions: `presentation.problems` turns each into a
`Problem` (one translation step), and nothing else decides a status."""

from collections.abc import Mapping


class RpcCallError(Exception):
    """A request-reply call to an owning context did not produce a usable success reply."""

    def __init__(self, subject: str, message: str) -> None:
        super().__init__(message)
        self.subject = subject


class RpcRemoteError(RpcCallError):
    """The responder answered with an `RpcError` (`asyncapi.yaml` `RpcError`)."""

    def __init__(
        self,
        subject: str,
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(subject, message)
        self.code = code
        self.details = details


class RpcTimeoutError(RpcCallError):
    """A responder is subscribed and did not answer within the deadline."""

    def __init__(self, subject: str, timeout_ms: int) -> None:
        super().__init__(subject, f"{subject} did not answer within {timeout_ms} ms.")
        self.timeout_ms = timeout_ms


class RpcUnavailableError(RpcCallError):
    """No responder is subscribed, or the transport itself failed."""


class RpcProtocolError(RpcCallError):
    """The reply is neither the success shape nor an `RpcError`."""


class ReadModelUnavailableError(Exception):
    """The read model (MongoDB) did not answer: the server could not be selected or the connection
    failed. A retryable 503, not an unexpected 500."""


class InvalidCredentialsError(Exception):
    """The submitted operator credentials do not match."""


class InvalidTokenError(Exception):
    """The bearer token is absent, malformed, forged, expired or from another issuer."""


class GatewayNotFoundError(Exception):
    """A resource the Gateway itself looked for does not exist."""


class InvoiceNotFoundError(GatewayNotFoundError):
    """The scan reached the end of `billing.invoice.list` without a match: the one branch that may
    claim the invoice does not exist."""

    def __init__(self, invoice_id: str) -> None:
        super().__init__(f"no invoice for id {invoice_id!r}")
        self.invoice_id = invoice_id


class InvoiceScanBudgetExceededError(Exception):
    """The scan used its page budget while the last page was still full: the invoice MAY exist
    beyond the window, so this is never a 404."""

    def __init__(self, invoice_id: str, scanned: int) -> None:
        super().__init__(
            f"invoice {invoice_id!r} was not found among the {scanned} invoices scanned; "
            "it may exist beyond this gateway's search window"
        )
        self.invoice_id = invoice_id
        self.scanned = scanned


class OrderNotYetProjectedError(Exception):
    """The invoice was found but its order is not in the read model yet: the payment needs the
    order id as its correlation id, so the request is retryable, never wrongly correlated."""

    def __init__(self, order_reference: str) -> None:
        super().__init__(
            f"order {order_reference!r} is not yet projected into the read model; retry"
        )
        self.order_reference = order_reference
