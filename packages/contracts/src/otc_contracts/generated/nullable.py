# GENERATED FILE - DO NOT EDIT.
# Regenerate with `uv run python scripts/generate_contracts.py`.
# Source: specs/shared/asyncapi.yaml sha256-prefix16=56ec7c72229a9c61
# Source: specs/shared/openapi.yaml sha256-prefix16=8dd55cf5f16f2b50
# Generator: datamodel-code-generator 0.83.0, generate_contracts.py
# `quality.sh` section 5 fails when this file differs from a fresh generation.

"""Fields each spec declares nullable: the only ones whose `None` is written `null`."""

NULLABLE_FIELDS: dict[str, frozenset[str]] = {
    "asyncapi.InvoiceView": frozenset({"paidAt"}),
    "openapi.Invoice": frozenset({"paidAt"}),
    "openapi.OrderDetail": frozenset({"cancellationReason"}),
    "openapi.OrderReferences": frozenset(
        {"despatchReference", "invoiceReference", "paymentReference"}
    ),
    "openapi.OrderStreamUpdate": frozenset({"cancellationReason"}),
    "openapi.OrderSummary": frozenset({"cancellationReason"}),
    "openapi.StreamReady": frozenset({"orderId"}),
}
