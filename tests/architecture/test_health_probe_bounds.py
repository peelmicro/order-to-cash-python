"""R60 / OR6 (S6.6): no readiness probe can hang the endpoint (ledger L31).

#7's NATS probe shipped without a bound and #8 needed a whole enumeration test for the same defect.
This module reads the AST of `services/*/src` and asserts, for the population below:

1. the probe classes (`*Probe` under `infrastructure/health/`) are exactly the literal
   `EXPECTED_PROBES`; the found set is compared with the literal both ways (a probe added without
   being listed fails by name, a listed one that vanished fails by name);
2. every probe's `__call__` runs each of its `await`s inside `async with asyncio.timeout(<bound>)`
   where the bound is `self._bound` (not `None`, not a literal that could be `None`), and that
   `async with` is not under an `if False:` / `if TYPE_CHECKING:` region (a dead region never runs);
3. the two bounds that live in a library call are present too: `connect_args={"timeout": ...}` in
   the PostgreSQL probe's `create_async_engine`, `timeout=` in the NATS probe's `flush`;
4. `HealthCheck.run` awaits `self.probe()` inside `async with asyncio.timeout(self.timeout_seconds)`
   and nothing else in `services/*/src` calls a `.probe(...)`: every probe, including the local
   `async def` probes of a composition root, goes through that one bounded call site;
5. the `HealthCheck(...)` constructions under `services/*/src` are exactly the literal
   `EXPECTED_CHECKS` (file, check name, probe expression), and none passes a `timeout_seconds`.

An AST is read so that a mention in a comment, a docstring or a string is not a bound (rows 4, 6),
and a bound hidden in a dead region does not count (row 5). The sentinels build temporary trees and
prove each form is a difference; the real-tree arms are recorded in the implementation record.
"""

import ast
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES = {
    "orders": "otc_orders",
    "gateway": "otc_gateway",
    "fulfillment": "otc_fulfillment",
    "billing": "otc_billing",
    "notifications": "otc_notifications",
    "projector": "otc_projector",
}
HEALTH_DIR = "infrastructure/health"
CHECKS_MODULE = "infrastructure/health/checks.py"
GATEWAY_CHECKS_MODULE = "infrastructure/health_checks.py"
# (service, module, class): every probe class. A literal, compared with the AST census both ways.
EXPECTED_PROBES: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("orders", "postgres_probe.py", "PostgresProbe"),
        ("fulfillment", "postgres_probe.py", "PostgresProbe"),
        ("billing", "postgres_probe.py", "PostgresProbe"),
        ("notifications", "postgres_probe.py", "PostgresProbe"),
        ("orders", "kafka_probe.py", "KafkaAdminProbe"),
        ("notifications", "kafka_probe.py", "KafkaAdminProbe"),
        ("projector", "kafka_probe.py", "KafkaAdminProbe"),
        ("orders", "nats_probe.py", "NatsProbe"),
        ("fulfillment", "nats_probe.py", "NatsProbe"),
        ("billing", "nats_probe.py", "NatsProbe"),
        ("projector", "nats_probe.py", "NatsProbe"),
        ("gateway", "nats_probe.py", "NatsProbe"),
        ("projector", "mongo_probe.py", "MongoProbe"),
        ("gateway", "mongo_probe.py", "MongoProbe"),
    }
)
# (service, module, check name, probe expression): every `HealthCheck(...)` construction.
EXPECTED_CHECKS: frozenset[tuple[str, str, str, str]] = frozenset(
    {
        ("orders", "composition.py", "writeModel", "write_model"),
        ("orders", "composition.py", "rpcTransport", "rpc_transport"),
        ("orders", "composition.py", "factStream", "fact_stream"),
        ("fulfillment", "composition.py", "writeModel", "write_model"),
        ("fulfillment", "composition.py", "rpcTransport", "rpc_transport"),
        ("billing", "composition.py", "writeModel", "write_model"),
        ("billing", "composition.py", "rpcTransport", "rpc_transport"),
        ("notifications", "composition.py", "writeModel", "write_model"),
        ("notifications", "composition.py", "factStream", "fact_stream"),
        ("projector", "composition.py", "readModel", "read_model"),
        ("projector", "composition.py", "factStream", "fact_stream"),
        ("projector", "composition.py", "rpcTransport", "rpc_transport"),
        ("gateway", "composition.py", "rpcTransport", "NatsProbe(connection)"),
        ("gateway", "composition.py", "readModel", "MongoProbe(database)"),
        ("gateway", "composition.py", "streamSignals", "stream_signals"),
    }
)


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def source_files(root: Path) -> list[tuple[str, Path]]:
    return [
        (path.relative_to(root / "services").parts[0], path)
        for path in sorted(root.glob("services/*/src/**/*.py"))
        if "__pycache__" not in path.parts
        and path.relative_to(root / "services").parts[0] in SERVICES
    ]


def probe_classes(root: Path) -> dict[tuple[str, str, str], ast.ClassDef]:
    found: dict[tuple[str, str, str], ast.ClassDef] = {}
    for service, path in source_files(root):
        if path.parent.as_posix().endswith(HEALTH_DIR) and path.name.endswith("_probe.py"):
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.ClassDef) and node.name.endswith("Probe"):
                    found[(service, path.name, node.name)] = node
    return found


def is_timeout_call(node: ast.expr, bound_ok: str) -> bool:
    """`asyncio.timeout(<bound_ok>)`, with exactly that argument expression."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "timeout"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
        and len(node.args) == 1
        and not node.keywords
        and ast.unparse(node.args[0]) == bound_ok
    )


def is_dead_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Constant):
        return not test.value
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def parents_of(function: ast.AsyncFunctionDef) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(function):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def unbounded_awaits(function: ast.AsyncFunctionDef, bound_ok: str) -> list[int]:
    """Line numbers of the `await`s in `function` that are not inside a LIVE
    `async with asyncio.timeout(bound_ok)`."""
    parents = parents_of(function)
    lines: list[int] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Await):
            continue
        bounded = False
        cursor: ast.AST | None = parents.get(node)
        dead = False
        while cursor is not None and cursor is not function:
            if isinstance(cursor, ast.If) and is_dead_test(cursor.test):
                dead = True
            if isinstance(cursor, ast.AsyncWith) and any(
                is_timeout_call(item.context_expr, bound_ok) for item in cursor.items
            ):
                bounded = True
            cursor = parents.get(cursor)
        if not bounded or dead:
            lines.append(node.lineno)
    return lines


def call_method(cls: ast.ClassDef) -> ast.AsyncFunctionDef | None:
    for node in cls.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "__call__":
            return node
    return None


def library_bound_problems(service: str, module: str, cls: ast.ClassDef) -> list[str]:
    label = f"{service}/{module}"
    problems: list[str] = []
    calls = [n for n in ast.walk(cls) if isinstance(n, ast.Call)]
    if module == "postgres_probe.py":
        engines = [
            c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "create_async_engine"
        ]
        keyword_dicts = [
            kw.value
            for call in engines
            for kw in call.keywords
            if kw.arg == "connect_args" and isinstance(kw.value, ast.Dict)
        ]
        if not any(
            isinstance(key, ast.Constant) and key.value == "timeout"
            for d in keyword_dicts
            for key in d.keys
        ):
            problems.append(f"{label}: create_async_engine has no connect_args timeout")
    if module == "nats_probe.py":
        flushes = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "flush"]
        if not flushes or not all(any(kw.arg == "timeout" for kw in f.keywords) for f in flushes):
            problems.append(f"{label}: a flush() has no timeout=")
    return problems


def probe_violations(root: Path) -> list[str]:
    found = probe_classes(root)
    problems: list[str] = []
    for key in sorted(set(found) - EXPECTED_PROBES):
        problems.append(f"{'/'.join(key)}: a probe class that is not in EXPECTED_PROBES")
    for key in sorted(EXPECTED_PROBES - set(found)):
        problems.append(f"{'/'.join(key)}: listed in EXPECTED_PROBES but not found")
    for (service, module, name), cls in sorted(found.items()):
        method = call_method(cls)
        label = f"{service}/{module}:{name}"
        if method is None:
            problems.append(f"{label}: has no async __call__")
            continue
        if not any(isinstance(n, ast.Await) for n in ast.walk(method)):
            problems.append(f"{label}: __call__ awaits nothing, so it probes nothing")
        for line in unbounded_awaits(method, "self._bound"):
            problems.append(
                f"{label}: the await at line {line} is not inside asyncio.timeout(self._bound)"
            )
        problems.extend(library_bound_problems(service, module, cls))
    return problems


def probe_call_sites(root: Path) -> list[str]:
    """Every `.probe(...)` call under `services/*/src` (the census; the bound is checked apart)."""
    sites: list[str] = []
    for service, path in source_files(root):
        for node in ast.walk(parse(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "probe"
            ):
                sites.append(f"{service}/{path.relative_to(root).as_posix().split('/src/')[1]}")
    return sites


def checks_run_violations(root: Path, module: str = CHECKS_MODULE) -> list[str]:
    path = root / "services/orders/src/otc_orders" / module
    problems: list[str] = []
    runs = [
        n for n in ast.walk(parse(path)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "run"
    ]
    if len(runs) != 1:
        return [f"{module}: expected exactly one HealthCheck.run, found {len(runs)}"]
    awaits_probe = [
        n
        for n in ast.walk(runs[0])
        if isinstance(n, ast.Await)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute)
        and n.value.func.attr == "probe"
    ]
    if len(awaits_probe) != 1:
        problems.append(f"{module}: run() must await self.probe() exactly once")
    for line in unbounded_awaits(runs[0], "self.timeout_seconds"):
        problems.append(
            f"{module}: the await at line {line} is not inside "
            "asyncio.timeout(self.timeout_seconds)"
        )
    return problems


def health_check_constructions(root: Path) -> tuple[set[tuple[str, str, str, str]], list[str]]:
    found: set[tuple[str, str, str, str]] = set()
    problems: list[str] = []
    for service, path in source_files(root):
        for node in ast.walk(parse(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "HealthCheck"
            ):
                module = path.name
                label = f"{service}/{module}"
                if any(kw.arg == "timeout_seconds" for kw in node.keywords):
                    problems.append(f"{label}: a HealthCheck overrides timeout_seconds")
                name_arg = node.args[0] if node.args else None
                if not (isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)):
                    problems.append(f"{label}: a HealthCheck whose name is not a literal")
                    continue
                probe_arg = node.args[1] if len(node.args) > 1 else None
                found.add(
                    (
                        service,
                        module,
                        name_arg.value,
                        "?" if probe_arg is None else ast.unparse(probe_arg),
                    )
                )
    return found, problems


def check_violations(root: Path) -> list[str]:
    found, problems = health_check_constructions(root)
    for key in sorted(found - EXPECTED_CHECKS):
        problems.append(f"{'/'.join(key)}: a HealthCheck that is not in EXPECTED_CHECKS")
    for key in sorted(EXPECTED_CHECKS - found):
        problems.append(f"{'/'.join(key)}: listed in EXPECTED_CHECKS but not found")
    return problems


CHECK_RUN_SITES = frozenset(
    {
        "orders/otc_orders/infrastructure/health/checks.py",
        "fulfillment/otc_fulfillment/infrastructure/health/checks.py",
        "billing/otc_billing/infrastructure/health/checks.py",
        "notifications/otc_notifications/infrastructure/health/checks.py",
        "projector/otc_projector/infrastructure/health/checks.py",
        "gateway/otc_gateway/infrastructure/health_checks.py",
    }
)


def stray_probe_calls(root: Path) -> list[str]:
    """The `.probe(...)` call sites that are not one of the six `HealthCheck.run` copies."""
    return sorted(set(probe_call_sites(root)) - CHECK_RUN_SITES)


def all_violations(root: Path) -> list[str]:
    return [
        *probe_violations(root),
        *checks_run_violations(root),
        *check_violations(root),
        *(
            f"{site}: a .probe(...) call outside HealthCheck.run"
            for site in stray_probe_calls(root)
        ),
    ]


# ------------------------------------------------------------------------------------ real tree


def test_or6_every_probe_runs_under_a_bound() -> None:
    assert probe_violations(REPO_ROOT) == []
    assert len(probe_classes(REPO_ROOT)) == 14 == len(EXPECTED_PROBES)


def test_or6_the_one_call_site_of_a_probe_is_bounded() -> None:
    assert checks_run_violations(REPO_ROOT) == []
    assert set(probe_call_sites(REPO_ROOT)) == CHECK_RUN_SITES, (
        "one call site per copy of checks.py"
    )


def test_or6_every_health_check_construction_is_a_listed_one_and_keeps_the_default_bound() -> None:
    assert check_violations(REPO_ROOT) == []
    found, _ = health_check_constructions(REPO_ROOT)
    assert len(found) == 15 == len(EXPECTED_CHECKS)


def test_or6_nothing_else_under_src_calls_a_probe() -> None:
    assert stray_probe_calls(REPO_ROOT) == []


# ------------------------------------------------------------------------------------- sentinels


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """The health modules and the compositions of every service, in their real layout."""
    for service, package in SERVICES.items():
        base = Path("services") / service / "src" / package
        (tmp_path / base / "infrastructure").mkdir(parents=True)
        shutil.copytree(
            REPO_ROOT / base / HEALTH_DIR,
            tmp_path / base / HEALTH_DIR,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copyfile(REPO_ROOT / base / "composition.py", tmp_path / base / "composition.py")
    gateway = Path("services/gateway/src/otc_gateway") / GATEWAY_CHECKS_MODULE
    shutil.copyfile(REPO_ROOT / gateway, tmp_path / gateway)
    return tmp_path


def module_of(root: Path, service: str, name: str) -> Path:
    return root / "services" / service / "src" / SERVICES[service] / HEALTH_DIR / name


def test_sentinel_the_pristine_tree_has_no_violation(tree: Path) -> None:
    assert all_violations(tree) == []


def test_sentinel_a_removed_bound_is_named(tree: Path) -> None:
    path = module_of(tree, "billing", "nats_probe.py")
    text = path.read_text(encoding="utf-8")
    assert "async with asyncio.timeout(self._bound):" in text
    path.write_text(text.replace("async with asyncio.timeout(self._bound):", "if True:"))
    problems = probe_violations(tree)
    assert problems
    assert all(p.startswith("billing/nats_probe.py:NatsProbe") for p in problems)


def test_sentinel_a_bound_of_none_is_named(tree: Path) -> None:
    path = module_of(tree, "orders", "kafka_probe.py")
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("asyncio.timeout(self._bound)", "asyncio.timeout(None)", 1))
    problems = probe_violations(tree)
    assert any("orders/kafka_probe.py:KafkaAdminProbe" in p for p in problems)


def test_sentinel_a_bound_that_is_only_a_comment_or_a_string_is_not_a_bound(tree: Path) -> None:
    path = module_of(tree, "projector", "mongo_probe.py")
    text = path.read_text(encoding="utf-8")
    mutated = text.replace(
        "async with asyncio.timeout(self._bound):",
        "# async with asyncio.timeout(self._bound):\n"
        '        _ = "async with asyncio.timeout(self._bound):"\n'
        "        if True:",
    )
    assert mutated != text
    path.write_text(mutated)
    assert any(
        "projector/mongo_probe.py:MongoProbe" in p and "not inside" in p
        for p in probe_violations(tree)
    )


@pytest.mark.parametrize("dead", ["if False:", "if TYPE_CHECKING:"])
def test_sentinel_a_bound_inside_a_dead_region_is_not_a_bound(tree: Path, dead: str) -> None:
    path = module_of(tree, "fulfillment", "nats_probe.py")
    text = path.read_text(encoding="utf-8")
    old = (
        "        async with asyncio.timeout(self._bound):\n"
        "            await self._connection.flush(timeout=math.ceil(self._bound))"
    )
    assert old in text
    new = (
        f"        {dead}\n            async with asyncio.timeout(self._bound):\n"
        "                pass\n        await self._connection.flush(timeout=math.ceil(self._bound))"
    )
    path.write_text(text.replace(old, new))
    assert any("fulfillment/nats_probe.py:NatsProbe" in p for p in probe_violations(tree))


def test_sentinel_an_unlisted_unbounded_probe_class_is_named(tree: Path) -> None:
    extra = module_of(tree, "gateway", "redis_probe.py")
    extra.write_text(
        "class RedisProbe:\n"
        "    async def __call__(self) -> None:\n"
        "        await self._client.ping()\n"
    )
    problems = probe_violations(tree)
    assert (
        "gateway/redis_probe.py/RedisProbe: a probe class that is not in EXPECTED_PROBES"
        in problems
    )
    assert any("gateway/redis_probe.py:RedisProbe: the await at line 3" in p for p in problems)


def test_sentinel_a_listed_probe_that_vanished_is_named(tree: Path) -> None:
    module_of(tree, "notifications", "kafka_probe.py").unlink()
    assert (
        "notifications/kafka_probe.py/KafkaAdminProbe: listed in EXPECTED_PROBES but not found"
        in probe_violations(tree)
    )


def test_sentinel_a_missing_library_bound_is_named(tree: Path) -> None:
    pg = module_of(tree, "orders", "postgres_probe.py")
    pg.write_text(
        pg.read_text(encoding="utf-8").replace(
            'connect_args={"timeout": bound_seconds}', "connect_args={}"
        )
    )
    nats = module_of(tree, "projector", "nats_probe.py")
    nats.write_text(
        nats.read_text(encoding="utf-8").replace("flush(timeout=math.ceil(self._bound))", "flush()")
    )
    problems = probe_violations(tree)
    assert "orders/postgres_probe.py: create_async_engine has no connect_args timeout" in problems
    assert "projector/nats_probe.py: a flush() has no timeout=" in problems


def test_sentinel_an_unbounded_health_check_run_is_named(tree: Path) -> None:
    path = tree / "services/orders/src/otc_orders" / CHECKS_MODULE
    text = path.read_text(encoding="utf-8")
    assert "async with asyncio.timeout(self.timeout_seconds):" in text
    path.write_text(text.replace("async with asyncio.timeout(self.timeout_seconds):", "if True:"))
    assert any(
        "not inside asyncio.timeout(self.timeout_seconds)" in p for p in checks_run_violations(tree)
    )


def test_sentinel_a_health_check_that_is_not_listed_or_overrides_its_bound_is_named(
    tree: Path,
) -> None:
    path = tree / "services/billing/src/otc_billing/composition.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + '\n\nextra = HealthCheck("cache", cache_probe, timeout_seconds=600)\n'
    )
    problems = check_violations(tree)
    assert "billing/composition.py: a HealthCheck overrides timeout_seconds" in problems
    assert (
        "billing/composition.py/cache/cache_probe: a HealthCheck that is not in EXPECTED_CHECKS"
        in problems
    )


def test_sentinel_a_probe_called_outside_health_check_run_is_named(tree: Path) -> None:
    path = tree / "services/billing/src/otc_billing/composition.py"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n\nasync def peek(check):\n    await check.probe()\n"
    )
    assert "billing/otc_billing/composition.py: a .probe(...) call outside HealthCheck.run" in (
        all_violations(tree)
    )
