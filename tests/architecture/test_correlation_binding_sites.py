"""R58 / OR7: `correlationId` is bound at EXACTLY the sites of `design.md` 2.4, under one key.

#8 bound `order_id` in its saga dispatcher and `correlation_id` in its relay, so those lines carried
no `correlationId` key at all and no test noticed. Here the population is read by AST from
`services/*/src`:

1. the set of (module, function) containing a `bound_contextvars` call equals `EXPECTED_SITES`, a
   literal (the `design.md` 2.4 table), so a deleted site and an added one both fail by name;
2. every such call passes exactly one keyword and it is literally `correlationId` (no positional,
   no `**splat`);
3. no `bind_contextvars` is called anywhere: in a consumer loop that runs in ONE task, a binding
   that is not reset leaks fact N's id onto fact N+1's lines (ledger L8);
4. neither name is imported under an alias (`import ... as x` hides a call from 1 - 3).

Premises of the instrument: P1 it is an AST walk, so a call inside a string or a comment is not a
call (not counted) and a call inside `if TYPE_CHECKING:` or `if False:` IS counted (it is code in
the tree; the census over-reports rather than under-reports); P2 a call is recognised as
`bound_contextvars(...)` or `<anything>.bound_contextvars(...)`; P3 the enclosing function is the
nearest `def` / `async def`, qualified by its classes. The sentinels below arm P1 - P3 on temporary
trees, and a pristine tree passes.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

GATEWAY = "services/gateway/src/otc_gateway"
ORDERS = "services/orders/src/otc_orders"
FULFILLMENT = "services/fulfillment/src/otc_fulfillment"
BILLING = "services/billing/src/otc_billing"
NOTIFICATIONS = "services/notifications/src/otc_notifications"
PROJECTOR = "services/projector/src/otc_projector"

# design.md 2.4, one entry per row of the table (the responder and relay rows are one per service).
EXPECTED_SITES: frozenset[tuple[str, str]] = frozenset(
    {
        (f"{GATEWAY}/presentation/asgi.py", "CorrelationMiddleware.__call__"),
        (f"{ORDERS}/presentation/orders_create_responder.py", "OrdersCreateResponder._serve"),
        (f"{FULFILLMENT}/presentation/stock_responder.py", "StockResponder._serve"),
        (f"{BILLING}/presentation/credit_responder.py", "CreditResponder._serve"),
        (f"{ORDERS}/presentation/saga_facts_consumer.py", "SagaFactsConsumerTask.handle"),
        (
            f"{PROJECTOR}/presentation/projector_facts_consumer.py",
            "ProjectorFactsConsumerTask.handle",
        ),
        (
            f"{NOTIFICATIONS}/presentation/notification_facts_consumer.py",
            "NotificationFactsConsumerTask.handle",
        ),
        (
            f"{ORDERS}/infrastructure/saga/command_dispatcher.py",
            "SagaCommandDispatcher.dispatch_claimed",
        ),
        (f"{ORDERS}/infrastructure/outbox/relay.py", "OutboxRelay._cycle"),
        (f"{FULFILLMENT}/infrastructure/outbox/relay.py", "OutboxRelay._cycle"),
        (f"{BILLING}/infrastructure/outbox/relay.py", "OutboxRelay._cycle"),
    }
)
KEY = "correlationId"
BOUND = "bound_contextvars"
BARE = "bind_contextvars"


def _name_of(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


class _Walker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.functions: list[str] = []
        self.sites: list[tuple[str, ast.Call]] = []
        self.bare: list[int] = []
        self.aliased: list[int] = []

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.functions.append(".".join(self.scope))
        self.generic_visit(node)
        self.functions.pop()
        self.scope.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.aliased.extend(
            node.lineno for alias in node.names if alias.name in {BOUND, BARE} and alias.asname
        )

    def visit_Call(self, node: ast.Call) -> None:
        name = _name_of(node.func)
        if name == BOUND:
            self.sites.append((self.functions[-1] if self.functions else "<module>", node))
        elif name == BARE:
            self.bare.append(node.lineno)
        self.generic_visit(node)


def scan(root: Path) -> tuple[set[tuple[str, str]], list[str]]:
    """The (module, function) population under `root/services/*/src` and every rule broken."""
    sites: set[tuple[str, str]] = set()
    broken: list[str] = []
    for path in sorted(root.glob("services/*/src/**/*.py")):
        rel = path.relative_to(root).as_posix()
        walker = _Walker()
        walker.visit(ast.parse(path.read_text(encoding="utf-8")))
        for function, call in walker.sites:
            sites.add((rel, function))
            keywords = [keyword.arg for keyword in call.keywords]
            if call.args or keywords != [KEY]:
                broken.append(
                    f"{rel}:{call.lineno} {function}: bound_contextvars must pass exactly the "
                    f"keyword `{KEY}` and nothing else, found args={len(call.args)} "
                    f"keywords={keywords}"
                )
        broken.extend(f"{rel}:{line}: bare {BARE} (it never resets)" for line in walker.bare)
        broken.extend(
            f"{rel}:{line}: {BOUND}/{BARE} imported under an alias" for line in walker.aliased
        )
    return sites, broken


def census(root: Path) -> list[str]:
    sites, broken = scan(root)
    broken.extend(
        f"expected binding site missing: {site}" for site in sorted(EXPECTED_SITES - sites)
    )
    broken.extend(f"unexpected binding site: {site}" for site in sorted(sites - EXPECTED_SITES))
    return broken


def test_r58_correlation_id_is_bound_at_exactly_the_sites_of_the_design() -> None:
    assert census(REPO_ROOT) == []


def test_r58_the_population_is_not_empty_and_has_eleven_sites() -> None:
    sites, _ = scan(REPO_ROOT)
    assert len(EXPECTED_SITES) == 11
    assert sites == set(EXPECTED_SITES)


# ---------------------------------------------------------------------------------------- sentinels


def _tree(tmp_path: Path, body: str) -> Path:
    module = tmp_path / "services/orders/src/otc_orders/probe.py"
    module.parent.mkdir(parents=True)
    module.write_text(body, encoding="utf-8")
    return tmp_path


SITE = (
    "from structlog.contextvars import bound_contextvars\n"
    "async def f(order):\n"
    "    with bound_contextvars(correlationId=order):\n"
    "        pass\n"
)


def test_sentinel_a_pristine_tree_scans_clean(tmp_path: Path) -> None:
    sites, broken = scan(_tree(tmp_path, SITE))
    assert sites == {("services/orders/src/otc_orders/probe.py", "f")}
    assert broken == []


def test_sentinel_a_snake_case_key_fails_the_scan(tmp_path: Path) -> None:
    """#8's defect (`OutboxRelay.cs:151`): the key `correlation_id`."""
    _, broken = scan(_tree(tmp_path, SITE.replace("correlationId=", "correlation_id=")))
    assert any("correlation_id" in message for message in broken)


def test_sentinel_a_bare_bind_is_reported(tmp_path: Path) -> None:
    body = (
        "import structlog\n"
        "def f(order):\n"
        "    structlog.contextvars.bind_contextvars(correlationId=order)\n"
    )
    _, broken = scan(_tree(tmp_path, body))
    assert any("bare" in message for message in broken)


def test_sentinel_an_aliased_import_is_reported(tmp_path: Path) -> None:
    body = "from structlog.contextvars import bound_contextvars as hidden\n"
    _, broken = scan(_tree(tmp_path, body))
    assert any("alias" in message for message in broken)


@pytest.mark.parametrize(
    "body",
    [
        "# with bound_contextvars(correlationId=order):\n",
        'TEXT = "with bound_contextvars(correlationId=order):"\n',
        'TEXT = """\nwith bound_contextvars(correlationId=order):\n"""\n',
        '"""bound_contextvars(correlationId=order)"""\n',
    ],
)
def test_sentinel_a_call_in_a_comment_or_string_is_not_counted(tmp_path: Path, body: str) -> None:
    sites, broken = scan(_tree(tmp_path, body))
    assert sites == set()
    assert broken == []


@pytest.mark.parametrize("guard", ["TYPE_CHECKING", "False"])
def test_sentinel_a_call_in_a_dead_region_is_counted(tmp_path: Path, guard: str) -> None:
    body = f"if {guard}:\n    bound_contextvars(correlationId=1)\n"
    sites, _ = scan(_tree(tmp_path, body))
    assert sites == {("services/orders/src/otc_orders/probe.py", "<module>")}


def test_sentinel_a_missing_expected_site_is_named(tmp_path: Path) -> None:
    """The empty tree has no site: every expected one is reported missing by name."""
    messages = census(tmp_path)
    assert len([m for m in messages if m.startswith("expected binding site missing")]) == 11
