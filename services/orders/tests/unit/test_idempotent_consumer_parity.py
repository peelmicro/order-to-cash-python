"""OI12: every per-service copy of the idempotent consumer agrees with the canonical.

`design.md` 6.4's four cases, over the REAL population plus a temporary-tree sentinel for every case
that would otherwise be vacuous at n = 1 (#8 D4: three of its four cases passed with one service).
Pure text: files are read as text, no service is imported, no container. Python has no namespace
declaration, so the normalised region is the BANNER only (the module docstring and any comment
lines before it), #7's original single-region rule.

Case 2 scans the WHOLE canonical after the banner (no excluded region): `ConsumerName` lives in
`consumer_name.py` (amendment A1, #8's shape), so the canonical names no service. Its imports are
the standard library, `sqlalchemy`, and exactly one relative import,
`from .consumer_name import ConsumerName`.
"""

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
CANONICAL = "services/orders/src/otc_orders/infrastructure/messaging/idempotent_consumer.py"
SERVICE_TOKENS = ("orders", "fulfillment", "billing", "notifications", "projector", "otc_")
ALLOWED_IMPORT_ROOTS = frozenset(sys.stdlib_module_names) | {"sqlalchemy"}
PROCESSED_EVENTS_TABLE = '__tablename__ = "processed_events"'


# ----------------------------------------------------------------------------------- instruments


def split_banner(text: str) -> tuple[str, str]:
    """`(banner, body)`: the module docstring plus any comment lines before it, then the rest."""
    tree = ast.parse(text)
    first = tree.body[0] if tree.body else None
    if not (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return "", text
    lines = text.splitlines(keepends=True)
    assert first.end_lineno is not None
    return "".join(lines[: first.end_lineno]), "".join(lines[first.end_lineno :])


def service_roots(root: Path) -> list[Path]:
    return sorted(p for p in (root / "services").glob("*/src/otc_*") if p.is_dir())


def has_relational_ledger(package: Path) -> bool:
    models = package / "infrastructure" / "persistence" / "models.py"
    return models.is_file() and PROCESSED_EVENTS_TABLE in models.read_text(encoding="utf-8")


def consumer_file(package: Path) -> Path:
    return package / "infrastructure" / "messaging" / "idempotent_consumer.py"


def copies(root: Path) -> list[Path]:
    """Every service with BOTH a relational `processed_events` ledger AND its own consumer file:
    read from the filesystem, never from a hand-kept list of service names."""
    return [
        consumer_file(p)
        for p in service_roots(root)
        if has_relational_ledger(p) and consumer_file(p).is_file()
    ]


def divergent_copies(root: Path, canonical: Path) -> list[str]:
    reference = split_banner(canonical.read_text(encoding="utf-8"))[1]
    found = []
    for copy in copies(root):
        if split_banner(copy.read_text(encoding="utf-8"))[1] != reference:
            found.append(f"{copy.relative_to(root)} diverges from the canonical outside the banner")
    return found


DYNAMIC_IMPORTS = frozenset({"__import__", "import_module"})  # as tests/architecture's money guard
ALLOWED_RELATIVE_IMPORT = ("consumer_name", ("ConsumerName",))


def adoptability_problems(text: str) -> list[str]:
    """Why the canonical could not be adopted verbatim by another service (empty = adoptable)."""
    body = split_banner(text)[1]
    problems = []
    scanned = body.lower()
    for token in SERVICE_TOKENS:
        if token in scanned:
            problems.append(f"names {token!r} outside the banner")
    relative = 0
    for node in ast.walk(ast.parse(body)):
        if isinstance(node, ast.Name | ast.Attribute):
            referenced = node.id if isinstance(node, ast.Name) else node.attr
            if referenced in DYNAMIC_IMPORTS:
                problems.append(f"references {referenced!r}: a dynamic import hides its module")
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
            if any(alias.name.split(".")[0] == "importlib" for alias in node.names):
                problems.append("imports 'importlib': a dynamic import hides its module")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module]
            if node.module.split(".")[0] == "importlib":
                problems.append("imports 'importlib': a dynamic import hides its module")
        elif isinstance(node, ast.ImportFrom):
            relative += 1
            shape = (node.module, tuple(alias.name for alias in node.names))
            if node.level != 1 or shape != ALLOWED_RELATIVE_IMPORT:
                problems.append(f"relative import {'.' * node.level}{node.module} is not allowed")
        problems.extend(
            f"imports {module!r}, which is neither the standard library nor sqlalchemy"
            for module in modules
            if module.split(".")[0] not in ALLOWED_IMPORT_ROOTS
        )
    if relative != 1:
        problems.append(f"expected exactly one relative import (consumer_name), found {relative}")
    return problems


def consumers_without_a_copy(root: Path) -> tuple[list[str], list[str]]:
    """`(examined, missing)`: services with a relational ledger and a Kafka consumer of facts, and
    those of them with no consumer file."""
    examined, missing = [], []
    for package in service_roots(root):
        if not has_relational_ledger(package):
            continue
        examined.append(package.name)
        consumes = any(
            "AIOKafkaConsumer" in source.read_text(encoding="utf-8")
            for source in package.rglob("*.py")
        )
        if consumes and not consumer_file(package).is_file():
            missing.append(package.name)
    return examined, missing


def variants_without_a_divergence_note(root: Path, canonical_path: str) -> list[str]:
    """A consumer file in a service with NO relational ledger is a variant: never compared, but its
    banner must name the canonical and carry a line beginning `Divergence:`."""
    found = []
    for package in service_roots(root):
        file = consumer_file(package)
        if has_relational_ledger(package) or not file.is_file():
            continue
        banner = split_banner(file.read_text(encoding="utf-8"))[0]
        if canonical_path not in banner:
            found.append(f"{package.name}: the banner does not cite {canonical_path}")
        if not any(line.startswith("Divergence:") for line in banner.splitlines()):
            found.append(f"{package.name}: the banner has no line beginning 'Divergence:'")
    return found


# -------------------------------------------------------------------------- a temporary tree


def build_tree(root: Path, services: dict[str, dict[str, str]]) -> None:
    """`services`: name -> {relative path below `src/otc_<name>`: content}."""
    for name, files in services.items():
        package = root / "services" / name / "src" / f"otc_{name}"
        for relative, content in files.items():
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


LEDGER = f"class ProcessedEvent:\n    {PROCESSED_EVENTS_TABLE}\n"
SAMPLE = '"""Banner."""\n\nimport enum\n\nVALUE = 1\n'


# --------------------------------------------------------------- case 1: copies equal the canonical


def test_case_1_every_write_models_copy_is_byte_identical_to_the_canonical_after_the_banner() -> (
    None
):
    found = copies(REPO_ROOT)
    canonical = REPO_ROOT / CANONICAL
    assert canonical in found, (
        "the canonical itself is a copy-candidate: it has a ledger and a file"
    )
    assert divergent_copies(REPO_ROOT, canonical) == []
    # at n = 1 the comparison is the canonical with itself: said here, proved non-vacuous below
    print(f"case 1 compared {len(found)} copy/copies (n=1 means the canonical against itself)")


def test_case_1_sentinel_a_copy_that_differs_by_one_character_is_reported(tmp_path: Path) -> None:
    build_tree(
        tmp_path,
        {
            "orders": {
                "infrastructure/persistence/models.py": LEDGER,
                "infrastructure/messaging/idempotent_consumer.py": SAMPLE,
            },
            "billing": {
                "infrastructure/persistence/models.py": LEDGER,
                "infrastructure/messaging/idempotent_consumer.py": SAMPLE.replace("= 1", "= 2"),
            },
        },
    )
    canonical = tmp_path / CANONICAL
    reported = divergent_copies(tmp_path, canonical)
    assert len(reported) == 1
    assert "otc_billing" in reported[0]


def test_case_1_sentinel_a_differing_banner_alone_is_not_a_divergence(tmp_path: Path) -> None:
    build_tree(
        tmp_path,
        {
            "orders": {
                "infrastructure/persistence/models.py": LEDGER,
                "infrastructure/messaging/idempotent_consumer.py": SAMPLE,
            },
            "billing": {
                "infrastructure/persistence/models.py": LEDGER,
                "infrastructure/messaging/idempotent_consumer.py": SAMPLE.replace(
                    "Banner.", "A different banner."
                ),
            },
        },
    )
    assert divergent_copies(tmp_path, tmp_path / CANONICAL) == []


# ------------------------------------------------------------- case 2: the canonical is adoptable


def test_case_2_the_canonical_is_adoptable_verbatim_naming_no_service() -> None:
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    assert adoptability_problems(text) == []


@pytest.mark.parametrize(
    "intruder",
    ["from otc_orders.domain import x", "BillingDb = 1", "FULFILLMENT_X = 1", "import redis"],
)
def test_case_2_sentinel_a_service_name_or_a_foreign_import_in_the_body_is_reported(
    intruder: str,
) -> None:
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    assert adoptability_problems(text + f"\n{intruder}\n"), intruder


def test_case_2_sentinel_a_dynamic_import_in_the_body_is_reported() -> None:
    """Review F4 (arm H2): `importlib.import_module("redis")` names no module the scan can see."""
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    dynamic = '\nimport importlib\n_DRIVER = importlib.import_module("redis")\n'
    problems = adoptability_problems(text + dynamic)
    assert any("importlib" in p for p in problems), problems
    assert any("import_module" in p for p in problems), problems
    assert adoptability_problems(text + '\n_X = __import__("redis")\n')


def test_case_2_sentinel_the_vocabulary_is_not_exempt_anywhere() -> None:
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    assert adoptability_problems(text) == []
    enum_back = '\nclass ConsumerName(enum.Enum):\n    ORDERS_SAGA = "orders.saga"\n'
    assert adoptability_problems(text + enum_back), "the enum inside the canonical counts"


@pytest.mark.parametrize(
    "extra", ["from .other import X", "from .consumer_name import ConsumerName", "from . import y"]
)
def test_case_2_sentinel_any_other_or_a_second_relative_import_is_reported(extra: str) -> None:
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    assert adoptability_problems(text + f"\n{extra}\n"), extra


def test_case_2_sentinel_a_missing_relative_import_is_reported() -> None:
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    assert adoptability_problems(text.replace("from .consumer_name import ConsumerName\n", ""))


# ------------------------------------------------------- case 3: every consumer carries a copy


def consuming_write_models(root: Path) -> set[str]:
    """The write models (services with a relational ledger) that reference `AIOKafkaConsumer`."""
    return {
        package.name
        for package in service_roots(root)
        if has_relational_ledger(package)
        and any(
            "AIOKafkaConsumer" in source.read_text(encoding="utf-8")
            for source in package.rglob("*.py")
        )
    }


def test_case_3_every_write_model_that_consumes_facts_carries_a_copy() -> None:
    examined, missing = consumers_without_a_copy(REPO_ROOT)
    assert len(examined) >= 3, f"the computation must range over the real population: {examined}"
    assert "otc_orders" in examined
    # Feature 16 built the first fact consumer: the saga's `KafkaFactSubscriber` in Orders. The
    # computed set is a literal, so a second consumer (feature 23 / 24) is a deliberate edit here.
    assert consuming_write_models(REPO_ROOT) == {"otc_orders"}
    assert missing == [], f"a consuming write model has no idempotent-consumer copy: {missing}"


def test_case_3_sentinel_the_real_orders_tree_without_its_copy_is_reported(tmp_path: Path) -> None:
    import shutil

    package = tmp_path / "services" / "orders" / "src" / "otc_orders"
    shutil.copytree(
        REPO_ROOT / "services" / "orders" / "src" / "otc_orders",
        package,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    assert consuming_write_models(tmp_path) == {"otc_orders"}
    assert consumers_without_a_copy(tmp_path)[1] == [], "the unmodified copy of the tree is fine"

    consumer_file(package).rename(consumer_file(package).with_name("renamed.py"))

    assert consumers_without_a_copy(tmp_path)[1] == ["otc_orders"]


def test_case_3_sentinel_a_consumer_of_facts_without_a_copy_is_reported(tmp_path: Path) -> None:
    build_tree(
        tmp_path,
        {
            "billing": {
                "infrastructure/persistence/models.py": LEDGER,
                "infrastructure/messaging/consumer.py": "from aiokafka import AIOKafkaConsumer\n",
            },
            "fulfillment": {"infrastructure/persistence/models.py": LEDGER},
        },
    )
    examined, missing = consumers_without_a_copy(tmp_path)
    assert examined == ["otc_billing", "otc_fulfillment"]
    assert missing == ["otc_billing"]


# ------------------------------------------------------------ case 4: variants name the canonical


def test_case_4_a_variant_carries_a_divergence_banner_naming_the_canonical() -> None:
    assert variants_without_a_divergence_note(REPO_ROOT, CANONICAL) == []
    # dormant until features 23/24: no service without a relational ledger has a consumer file yet
    variants = [
        consumer_file(p)
        for p in service_roots(REPO_ROOT)
        if not has_relational_ledger(p) and consumer_file(p).is_file()
    ]
    print(f"case 4 examined {len(variants)} variant(s)")


def test_case_4_sentinel_a_variant_without_a_divergence_line_is_reported(tmp_path: Path) -> None:
    named = (
        f'"""Variant of {CANONICAL}.\n\nDivergence: a document store shares no transaction."""\n'
    )
    unnamed = f'"""Variant of {CANONICAL}."""\n'
    build_tree(
        tmp_path,
        {
            "projector": {"infrastructure/messaging/idempotent_consumer.py": unnamed},
            "notifications": {"infrastructure/messaging/idempotent_consumer.py": named},
        },
    )
    reported = variants_without_a_divergence_note(tmp_path, CANONICAL)
    assert reported == ["otc_projector: the banner has no line beginning 'Divergence:'"]
