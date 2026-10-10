"""Feature 22 acceptance 2: there is NO internal payment timer anywhere (an absence claim).

An absence is a search result, so the search is a guard with a literal expected population and a
sentinel that it must catch (`CLAUDE.md`: a sweep needs a case that must fail to detect). Payment
is initiated from OUTSIDE the system only: the Gateway's caller (the operator, a test, the external
n8n robot) sends `billing.payment.register`. Four claims, each a search over the whole tree:

1. **No service or package mentions the subject but Billing itself** (and the seed's deterministic
   fixture ids): nothing inside the system can send it. `generated/` is excluded at the source (it
   is the contract's channel table, not a caller).
2. **`RegisterPaymentCommand` is built in exactly one place**, the NATS request decoder.
3. **No scheduling construct** (`asyncio.sleep`, `call_later`, `call_at`, `threading.Timer`, a
   scheduler library) exists in any service or package source except the classified literal below:
   deadlock/retry pacing, none of which touches a payment.
4. **The n8n workflows**: three of four are schedule-triggered, the fourth a webhook; the only one
   that mentions a payment is the external robot, and it speaks HTTP to the Gateway, never NATS and
   never Billing's subject.

Loop scope: nothing here is async.
"""

import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]

SUBJECT = re.compile(r"payment\.register")
COMMAND_CALL = re.compile(r"RegisterPaymentCommand\(")
TIMER = re.compile(
    r"\b(?:asyncio\.sleep|call_later|call_at|threading\.Timer|apscheduler|aiocron|croniter"
    r"|schedule\.every)\b"
)

# claim 1: the seed derives deterministic ids for HISTORIC fixture sagas (a string passed to
# `deterministic_id`, and the docstring that explains it); it sends nothing at runtime
EXPECTED_SUBJECT_MENTIONS_OUTSIDE_BILLING = {
    "services/seed/src/otc_seed/domain/data/sagas.py": 2,
}
# claim 2: the class statement, and the one decoder that builds it from a NATS request
EXPECTED_COMMAND_CALLS = {
    "services/billing/src/otc_billing/application/messages.py": 1,
    "services/billing/src/otc_billing/presentation/payment_wire.py": 1,
}
# claim 3: every hit classified. All are pacing of a RETRY (an outbox deadlock back-off in the four
# relay copies' three sites, Fulfillment's stock-transaction deadlock re-run, Orders' saga command
# dispatcher back-off); none is a clock that decides a payment.
EXPECTED_TIMER_HITS = {
    "services/billing/src/otc_billing/infrastructure/outbox/relay.py": 1,
    "services/fulfillment/src/otc_fulfillment/infrastructure/outbox/relay.py": 1,
    "services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py": 1,
    "services/orders/src/otc_orders/infrastructure/outbox/relay.py": 1,
    "services/orders/src/otc_orders/infrastructure/saga/command_dispatcher.py": 1,
}
# claim 4
EXPECTED_TRIGGERS = {
    "1-order-generator.json": {"n8n-nodes-base.scheduleTrigger"},
    "2-payment-robot.json": {"n8n-nodes-base.scheduleTrigger"},
    "3-stock-replenishment.json": {"n8n-nodes-base.scheduleTrigger"},
    "4-burst.json": {"n8n-nodes-base.webhook"},
}
TRIGGER_TYPES = ("n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.webhook", "n8n-nodes-base.cron")


def source_files(root: Path) -> Iterable[Path]:
    """Every `.py` under `services/*/src` and `packages/*/src`, `generated/` excluded AT THE SOURCE
    (the walk never descends into it), `__pycache__` too."""
    for tree in (*sorted(root.glob("services/*/src")), *sorted(root.glob("packages/*/src"))):
        stack = [tree]
        while stack:
            here = stack.pop()
            for child in sorted(here.iterdir()):
                if child.is_dir():
                    if child.name not in {"generated", "__pycache__"}:
                        stack.append(child)
                elif child.suffix == ".py":
                    yield child


def hits(root: Path, pattern: re.Pattern[str], *, skip: str | None = None) -> Counter[str]:
    found: Counter[str] = Counter()
    for path in source_files(root):
        relative = path.relative_to(root).as_posix()
        if skip is not None and relative.startswith(skip):
            continue
        count = len(pattern.findall(path.read_text(encoding="utf-8")))
        if count:
            found[relative] = count
    return found


def workflow_triggers(workflows: Path) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for path in sorted(workflows.glob("*.json")):
        nodes = json.loads(path.read_text(encoding="utf-8"))["nodes"]
        result[path.name] = {n["type"] for n in nodes if n["type"] in TRIGGER_TYPES}
    return result


def test_no_service_or_package_but_billing_mentions_the_payment_subject() -> None:
    found = hits(REPO_ROOT, SUBJECT, skip="services/billing/")

    assert dict(found) == EXPECTED_SUBJECT_MENTIONS_OUTSIDE_BILLING, (
        f"something inside the system mentions billing.payment.register: {dict(found)}"
    )


def test_the_register_command_is_built_only_by_the_nats_request_decoder() -> None:
    found = hits(REPO_ROOT, COMMAND_CALL)

    assert dict(found) == EXPECTED_COMMAND_CALLS, (
        f"RegisterPaymentCommand is built somewhere else: {dict(found)}"
    )


def test_every_scheduling_construct_in_the_sources_is_a_classified_retry_pacing() -> None:
    found = hits(REPO_ROOT, TIMER)

    assert dict(found) == EXPECTED_TIMER_HITS, (
        f"an unclassified scheduling construct (or a lost classified one): {dict(found)}"
    )


def test_the_n8n_workflows_are_externally_triggered_and_only_the_robot_pays_via_the_gateway() -> (
    None
):
    workflows = REPO_ROOT / "n8n" / "workflows"

    assert workflow_triggers(workflows) == EXPECTED_TRIGGERS
    mentioning_payments = {
        p.name
        for p in sorted(workflows.glob("*.json"))
        if "/payments" in p.read_text(encoding="utf-8")
    }
    assert mentioning_payments == {"2-payment-robot.json"}
    for path in sorted(workflows.glob("*.json")):
        text = path.read_text(encoding="utf-8").lower()
        assert "nats" not in text, f"{path.name} speaks NATS"
        assert "billing.payment" not in text, f"{path.name} names Billing's subject"
    robot = (workflows / "2-payment-robot.json").read_text(encoding="utf-8")
    assert "OTC_GATEWAY_URL" in robot, "the robot does not go through the Gateway"


# ----------------------------------------------------------------- the sentinels: must be caught


def test_the_search_catches_a_planted_timer_a_planted_caller_and_a_planted_schedule(
    tmp_path: Path,
) -> None:
    """A search that cannot fail is not a search: plant one violation per claim in a scratch tree
    shaped like the repository and show each claim's instrument sees it."""
    planted = tmp_path / "services" / "orders" / "src" / "otc_orders" / "payment_timer.py"
    planted.parent.mkdir(parents=True)
    planted.write_text(
        "import asyncio\n"
        "async def pay_overdue():\n"
        "    await asyncio.sleep(60)\n"
        "    send('billing.payment.register', RegisterPaymentCommand(invoice_id=None))\n",
        encoding="utf-8",
    )
    hidden = tmp_path / "packages" / "contracts" / "src" / "x" / "generated"
    hidden.mkdir(parents=True)
    (hidden / "ignored.py").write_text("asyncio.sleep(1)  # payment.register\n", encoding="utf-8")
    workflows = tmp_path / "n8n" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "5-timer.json").write_text(
        json.dumps({"nodes": [{"type": "n8n-nodes-base.scheduleTrigger", "name": "t"}]}),
        encoding="utf-8",
    )

    assert dict(hits(tmp_path, SUBJECT)) == {
        "services/orders/src/otc_orders/payment_timer.py": 1
    }, "the subject search missed a caller (or descended into generated/)"
    assert dict(hits(tmp_path, COMMAND_CALL)) == {
        "services/orders/src/otc_orders/payment_timer.py": 1
    }
    assert dict(hits(tmp_path, TIMER)) == {"services/orders/src/otc_orders/payment_timer.py": 1}
    assert workflow_triggers(workflows) == {"5-timer.json": {"n8n-nodes-base.scheduleTrigger"}}
    assert workflow_triggers(workflows) != EXPECTED_TRIGGERS
