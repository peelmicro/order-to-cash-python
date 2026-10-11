"""C8 (PR18, PR19, PR27): the handler, over fakes.

* PR27: one handler, no branching on `eventType` (the fourteen variations live in `project`).
* PR18: a suppressed redelivery (`DUPLICATE`) publishes nothing, and the signal is built from the
  document the writer returned AFTER the apply, not from the delta.
* PR19: a publication failure is logged (one ERROR naming both subjects) and swallowed; a failure of
  the writer propagates.
"""

import ast
import logging
from pathlib import Path
from typing import Any

import pytest

from otc_projector.application.handlers import ProjectFactHandler
from otc_projector.application.messages import ProjectFactCommand
from otc_projector.application.outcome import ProjectionOutcome
from otc_projector.application.ports.read_model import AfterApplied, AppliedDocument, AppliedTotals
from otc_projector.application.scope import ProjectorScope
from otc_projector.domain.projection_delta import ProjectionDelta, TimelineEntryDelta

SRC = Path(__file__).resolve().parents[2] / "src" / "otc_projector"

POST_APPLY = AppliedDocument(
    order_id="post-apply-order",
    order_reference="ORD-555555",
    status="paid",
    cancellation_reason=None,
    despatch_reference="DES-555555",
    invoice_reference="INV-555555",
    payment_reference="PAY-555555",
    totals=AppliedTotals(initial_amount=1, initial_discount=2, total_amount=3),
)


class FakeWriter:
    def __init__(self, outcome: ProjectionOutcome, document: AppliedDocument = POST_APPLY) -> None:
        self.outcome = outcome
        self.document = document
        self.deltas: list[ProjectionDelta] = []
        self.error: Exception | None = None

    async def apply(
        self, delta: ProjectionDelta, *, after_applied: AfterApplied
    ) -> ProjectionOutcome:
        self.deltas.append(delta)
        if self.error is not None:
            raise self.error
        if self.outcome is ProjectionOutcome.PROCESSED:
            await after_applied(self.document)
        return self.outcome


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[AppliedDocument, TimelineEntryDelta]] = []
        self.error: Exception | None = None

    async def publish(self, applied: AppliedDocument, entry: TimelineEntryDelta) -> None:
        self.calls.append((applied, entry))
        if self.error is not None:
            raise self.error


def handler_for(writer: FakeWriter, publisher: FakePublisher) -> ProjectFactHandler:
    return ProjectFactHandler(ProjectorScope(read_model=writer, signals=publisher))


async def test_pr27_the_handler_projects_and_applies_with_no_branching_on_event_type(
    facts: Any,
) -> None:
    writer, publisher = FakeWriter(ProjectionOutcome.PROCESSED), FakePublisher()
    handler = handler_for(writer, publisher)
    for event_type in ("order.placed.v1", "credit.rejected.v1"):
        outcome = await handler.handle(ProjectFactCommand(event=facts.build(event_type)))
        assert outcome is ProjectionOutcome.PROCESSED
    assert [d.entry.event_type for d in writer.deltas] == ["order.placed.v1", "credit.rejected.v1"]
    assert len(publisher.calls) == 2


def test_pr27_the_handler_module_never_reads_the_event_type() -> None:
    tree = ast.parse((SRC / "application" / "handlers.py").read_text(encoding="utf-8"))
    reads = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
    assert "event_type" not in reads, "the handler branches on or reads eventType"


async def test_pr18_a_duplicate_publishes_nothing(facts: Any) -> None:
    writer, publisher = FakeWriter(ProjectionOutcome.DUPLICATE), FakePublisher()
    outcome = await handler_for(writer, publisher).handle(
        ProjectFactCommand(event=facts.build("order.confirmed.v1"))
    )
    assert outcome is ProjectionOutcome.DUPLICATE
    assert len(writer.deltas) == 1, "the writer was not asked"
    assert len(publisher.calls) == 0, "a suppressed redelivery published a signal"


async def test_pr18_the_signal_is_built_from_the_post_apply_document(facts: Any) -> None:
    writer, publisher = FakeWriter(ProjectionOutcome.PROCESSED), FakePublisher()
    await handler_for(writer, publisher).handle(
        ProjectFactCommand(event=facts.build("order.despatched.v1"))
    )
    assert len(publisher.calls) == 1
    applied, entry = publisher.calls[0]
    assert applied is POST_APPLY, "the publisher did not receive the document the writer returned"
    assert entry is writer.deltas[0].entry


async def test_pr19_a_publication_failure_is_logged_and_swallowed(
    facts: Any, caplog: pytest.LogCaptureFixture
) -> None:
    writer, publisher = FakeWriter(ProjectionOutcome.PROCESSED), FakePublisher()
    publisher.error = ConnectionError("nats is gone")
    event = facts.build("invoice.issued.v1")
    with caplog.at_level(logging.ERROR, logger="otc_projector.application.handlers"):
        try:
            outcome = await handler_for(writer, publisher).handle(ProjectFactCommand(event=event))
        except Exception as error:
            pytest.fail(f"PR19: a publication failure escaped the handler: {error!r}")
    assert outcome is ProjectionOutcome.PROCESSED, "a publication failure changed the outcome"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1, [r.getMessage() for r in caplog.records]
    message = errors[0].getMessage()
    order_id = str(event.correlation_id)
    assert f"readmodel.order.updated.{order_id}" in message
    assert f"readmodel.timeline.appended.{order_id}" in message
    assert errors[0].__dict__["eventId"] == str(event.event_id)
    assert errors[0].__dict__["correlationId"] == order_id


async def test_pr19_a_writer_failure_propagates(facts: Any) -> None:
    writer, publisher = FakeWriter(ProjectionOutcome.PROCESSED), FakePublisher()
    writer.error = RuntimeError("mongo is gone")
    with pytest.raises(RuntimeError, match="mongo is gone"):
        await handler_for(writer, publisher).handle(
            ProjectFactCommand(event=facts.build("order.placed.v1"))
        )
    assert publisher.calls == []


def test_pr19_no_other_module_catches_a_publication_failure() -> None:
    """The handler is the only place a `publish` is wrapped in a `try`."""
    catchers = set()
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Try) and any(
                isinstance(inner, ast.Attribute) and inner.attr == "publish"
                for statement in node.body
                for inner in ast.walk(statement)
            ):
                catchers.add(str(path.relative_to(SRC)))
    assert catchers == {"application/handlers.py"}, catchers
