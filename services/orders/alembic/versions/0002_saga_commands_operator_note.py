"""saga_commands.operator_note: the operator's free-text note, carried until the cancellation that
completes it (feature 41, `orders_cancel_responder`).

An operator cancellation from `stock_reserved`, `credit_approved` or `confirmed` is accepted now and
completed later, by a fact (`stock.released.v1` or `credit.released.v1`). The note arrives with the
request and must reach `order.cancelled.v1`, so it has to be stored between the two. No existing
column can hold it: `payload` is the verbatim `stock.release` request, which declares no `note`
(`asyncapi.yaml` `StockReleaseRequestPayload`), `triggering_event_id` is a uuid, and `last_error` is
the dispatcher's. One nullable `text` column, written only by the operator-cancel enqueue, read by
the step that completes the cancellation. Additive: no existing row changes, and the column is not
one of feature 27's (`triggering_event_envelope`, `triggering_event_topic`, `dead_lettered_at`).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("saga_commands", sa.Column("operator_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("saga_commands", "operator_note")
