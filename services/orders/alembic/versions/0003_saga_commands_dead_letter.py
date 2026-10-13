"""saga_commands dead-letter columns: the received envelope, its topic, the first-park marker and
the enqueue-time trace (feature 27 `observability_reliability`, `R29`, `OR3`, `OR10`).

Five additive, nullable columns; no existing row changes.

* `triggering_event_envelope` (`bytea`): the bytes the saga consumed, stored exactly. `json` would
  validate and re-encode the text and `jsonb` would normalise it (CLAUDE.md "payload columns"), and
  a dead letter is the ORIGINAL bytes. Null for a command that no fact triggered (the operator
  cancel's compensation, gate G1) and for rows that predate this revision.
* `triggering_event_topic` (`varchar(64)`): the source topic; the `.dlq` name is this plus `.dlq`,
  never guessed from the event type.
* `dead_lettered_at` (`timestamptz(3)`): the at-most-once marker of the first park.
* `trace_parent` (`varchar(55)`): the W3C `traceparent` recorded at enqueue, restored by the
  sweeper as the parent of the dispatch span (`OR10`, gate G3).
* `first_failed_at` (`timestamptz(3)`): the instant of the row's first failed attempt, set once by
  `COALESCE` wherever the ledger records a failure (`park`, `reject`) and sent as the first-park
  dead letter's `x-first-failed-at` (SA-3), the park instant being `x-failed-at`.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "saga_commands", sa.Column("triggering_event_envelope", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "saga_commands", sa.Column("triggering_event_topic", sa.String(64), nullable=True)
    )
    op.add_column(
        "saga_commands",
        sa.Column("dead_lettered_at", pg.TIMESTAMP(timezone=True, precision=3), nullable=True),
    )
    op.add_column("saga_commands", sa.Column("trace_parent", sa.String(55), nullable=True))
    op.add_column(
        "saga_commands",
        sa.Column("first_failed_at", pg.TIMESTAMP(timezone=True, precision=3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("saga_commands", "first_failed_at")
    op.drop_column("saga_commands", "trace_parent")
    op.drop_column("saga_commands", "dead_lettered_at")
    op.drop_column("saga_commands", "triggering_event_topic")
    op.drop_column("saga_commands", "triggering_event_envelope")
