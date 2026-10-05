"""AST money guard: no float, no true division, no decimal in `domain` code or `shared_kernel`.

Money is `int` minor units (CLAUDE.md). This guard reads the AST, so a `/` or `float` that only
appears in a comment or a string literal is NOT a violation, while the same text in real code is
-- including inside `if TYPE_CHECKING:` / `if False:` blocks (decision: those regions are walked
like any other code, because a `float` annotation or a dead `/` is still the wrong type in the
domain; see the sweep sentinels below). `//` (floor division of ints) is allowed.
"""

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES = ["gateway", "orders", "fulfillment", "billing", "notifications", "projector", "seed"]


def guarded_files(root: Path) -> list[Path]:
    """Every .py under every service `domain` (recursively) and under packages/shared_kernel/src."""
    files: list[Path] = []
    for domain in sorted(root.glob("services/*/src/otc_*/domain")):
        files.extend(sorted(domain.rglob("*.py")))
    files.extend(sorted((root / "packages" / "shared_kernel" / "src").rglob("*.py")))
    return files


def _annotation_strings(tree: ast.AST) -> list[tuple[ast.expr, int]]:
    """Parse string annotations (`x: "float"`) so a quoted type is judged like a bare one.

    Each parsed expression is returned with the real line of the annotation it came from, so a
    violation inside a quoted annotation is reported at that line, not at `line 1` of the snippet.
    """
    parsed: list[tuple[ast.expr, int]] = []
    annotations: list[ast.expr | None] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign | ast.arg):
            annotations.append(node.annotation)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            annotations.append(node.returns)
    for annotation in annotations:
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            parsed.append((ast.parse(annotation.value, mode="eval").body, annotation.lineno))
    return parsed


# `/` spelled as its protocol: the dunders and `operator.truediv` are the same operation.
TRUEDIV_NAMES = {"truediv", "__truediv__", "__rtruediv__", "__itruediv__"}
# M1 bans "decimal, floating-point or fixed-point": `fractions` is exact rational arithmetic, the
# same major-unit escape hatch as `decimal`, and is stdlib (so the import allowlist cannot see it).
BANNED_NUMERIC_MODULES = {"decimal", "fractions"}


def _is_safe_exponent(node: ast.expr) -> bool:
    """`**` rule: the exponent must be a non-negative int literal. A negative literal
    (`10 ** -2`), a float, or a non-literal exponent can produce a float, so it is flagged."""
    return isinstance(node, ast.Constant) and type(node.value) is int and node.value >= 0


def violations(source: str) -> list[str]:
    """Return one claim-naming message per violation found in `source`."""
    tree = ast.parse(source)
    found: list[str] = []
    nodes: list[tuple[ast.AST, int | None]] = [(n, None) for n in ast.walk(tree)]
    for extra, extra_line in _annotation_strings(tree):
        nodes.extend((n, extra_line) for n in ast.walk(extra))
    for node, line_override in nodes:
        line = line_override or getattr(node, "lineno", 0)
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            found.append(f"line {line}: float literal (money is int minor units)")
        elif isinstance(node, ast.Constant) and node.value in TRUEDIV_NAMES:
            found.append(
                f"line {line}: `{node.value}` as a string (getattr is `/` by another name)"
            )
        elif isinstance(node, ast.Name) and node.id == "float":
            found.append(f"line {line}: `float` used as call, annotation or value")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            found.append(f"line {line}: true division `/` (int / int is a float)")
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Div):
            found.append(f"line {line}: true division `/=` (int / int is a float)")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            if not _is_safe_exponent(node.right):
                found.append(f"line {line}: `**` with a negative or non-literal exponent")
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Pow):
            if not _is_safe_exponent(node.value):
                found.append(f"line {line}: `**=` with a negative or non-literal exponent")
        elif isinstance(node, ast.Name | ast.Attribute) and (
            getattr(node, "id", None) in TRUEDIV_NAMES
            or getattr(node, "attr", None) in TRUEDIV_NAMES
        ):
            found.append(f"line {line}: `truediv` family (`/` by another name)")
        elif (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in TRUEDIV_NAMES
        ):
            found.append(f"line {line}: `def {node.name}` offers true division")
        elif isinstance(node, ast.Import):
            found.extend(
                f"line {line}: `import {alias.name}` (decimal/fractions are not money types)"
                for alias in node.names
                if alias.name.split(".")[0] in BANNED_NUMERIC_MODULES
            )
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in BANNED_NUMERIC_MODULES:
                found.append(f"line {line}: `from {node.module} import ...` (decimal/fractions)")
        elif isinstance(node, ast.Call) and _imports_banned_dynamically(node):
            found.append(f"line {line}: dynamic import of `decimal` or `fractions`")
        elif isinstance(node, ast.Call) and _is_unsafe_pow_call(node):
            found.append(f"line {line}: `pow(...)` with a negative or non-literal exponent")
    return found


def _is_unsafe_pow_call(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Name)
        and func.id == "pow"
        and (len(call.args) < 2 or not _is_safe_exponent(call.args[1]))
    )


def _imports_banned_dynamically(call: ast.Call) -> bool:
    func = call.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if name not in {"__import__", "import_module"} or not call.args:
        return False
    first = call.args[0]
    return (
        isinstance(first, ast.Constant)
        and isinstance(first.value, str)
        and first.value.split(".")[0] in BANNED_NUMERIC_MODULES
    )


# --------------------------------------------------------------------------- import allowlist
# Domain purity as an ALLOWLIST (the import-linter forbidden contract is a deny-list and cannot
# know every top-level module a distribution installs, e.g. PyMongo's `bson`). Rule: a module
# under a service `domain` may import only the standard library (`sys.stdlib_module_names`),
# `otc_shared_kernel`, and its own `otc_<service>.domain` tree; a module under `otc_shared_kernel`
# may import only the standard library and `otc_shared_kernel`. A domain importing its own
# application/infrastructure/presentation is NOT checked here: the layers contract owns that
# claim (we rely on it); this guard only refuses it as a side effect of the rule above.
# Relative imports are resolved against the file's package and must land inside the allowed
# tree. `importlib.import_module` / `__import__` with a literal are checked like `import x`;
# with a non-literal argument they are flagged as unverifiable.


def module_name_of(path: Path, root: Path) -> str:
    """Dotted module name of a file under a `src` directory below `root`."""
    parts = path.relative_to(root).parts
    src = parts.index("src")
    names = [*parts[src + 1 : -1], path.stem]
    if names[-1] == "__init__":
        names.pop()
    return ".".join(names)


def _allowed(module: str, own_domain: str | None) -> bool:
    top = module.split(".")[0]
    if top in sys.stdlib_module_names or top == "otc_shared_kernel":
        return True
    return own_domain is not None and (module == own_domain or module.startswith(own_domain + "."))


def import_violations(source: str, module: str, *, is_package: bool) -> list[str]:
    """Return one message per import that is outside the allowlist."""
    top = module.split(".")[0]
    own_domain = f"{top}.domain" if top.startswith("otc_") and top != "otc_shared_kernel" else None
    package = module if is_package else module.rpartition(".")[0]
    found: list[str] = []

    def check(target: str, line: int, how: str) -> None:
        if not _allowed(target, own_domain):
            found.append(f"line {line}: {how} `{target}` is outside the domain import allowlist")

    for node in ast.walk(ast.parse(source)):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                check(alias.name, line, "import")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                target = ".".join([*base, *([node.module] if node.module else [])])
                check(target, line, "relative import resolving to")
            else:
                check(node.module or "", line, "from-import of")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in {"__import__", "import_module"}:
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    check(first.value, line, "dynamic import of")
                else:
                    found.append(f"line {line}: dynamic import with a non-literal argument")
    return found


# --------------------------------------------------------------------------- the real population


def test_money_guard_finds_no_violation_in_domain_or_shared_kernel() -> None:
    problems = {
        str(path.relative_to(REPO_ROOT)): violations(path.read_text())
        for path in guarded_files(REPO_ROOT)
    }
    offenders = {path: found for path, found in problems.items() if found}
    assert not offenders, (
        f"money guard: float / true division / decimal in domain code: {offenders}"
    )


def test_domain_and_shared_kernel_import_only_the_allowlist() -> None:
    offenders: dict[str, list[str]] = {}
    for path in guarded_files(REPO_ROOT):
        found = import_violations(
            path.read_text(), module_name_of(path, REPO_ROOT), is_package=path.stem == "__init__"
        )
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found
    assert not offenders, (
        f"domain import allowlist: non-stdlib/non-kernel import in domain: {offenders}"
    )


def test_money_guard_walks_the_nested_domain_and_shared_kernel_population() -> None:
    # Non-vacuity. The expected set is a LITERAL (not derived from the walk), so an empty or
    # mis-rooted walk, or one that stops at the first directory level, fails here.
    expected = {
        *(f"services/{s}/src/otc_{s}/domain/value_objects/__init__.py" for s in SERVICES),
        *(f"services/{s}/src/otc_{s}/domain/__init__.py" for s in SERVICES),
        "packages/shared_kernel/src/otc_shared_kernel/__init__.py",
    }
    walked = {str(p.relative_to(REPO_ROOT)) for p in guarded_files(REPO_ROOT)}
    assert walked, "money guard walked ZERO files: the guard is vacuous"
    assert expected <= walked, f"money guard population is missing: {sorted(expected - walked)}"


def test_money_guard_service_population_matches_the_literal_service_list() -> None:
    on_disk = {p.name for p in (REPO_ROOT / "services").iterdir() if p.is_dir()}
    assert on_disk == set(SERVICES), (
        "a service was added or removed: update SERVICES so its domain is walked by the guard"
    )


# --------------------------------------------------------------------------- the instrument itself
# Sweep sentinels: every shape below MUST be detected, otherwise "no violation found" means nothing.

MUST_DETECT = {
    "float literal": "PRICE = 1.5\n",
    "exponent float literal": "PRICE = 1e3\n",
    "float() call": "x = float(3)\n",
    "float annotation": "def f(a: float) -> int:\n    return 1\n",
    "float return annotation": "def f() -> float:\n    return 1\n",
    "string annotation": 'x: "float" = 1\n',
    "true division": "x = 6 / 3\n",
    "true division augmented": "x = 6\nx /= 3\n",
    "import decimal": "import decimal\n",
    "import decimal as alias": "import decimal as d\n",
    "from decimal import Decimal": "from decimal import Decimal\n",
    "from decimal import star": "from decimal import *\n",
    "operator.truediv": "import operator\nx = operator.truediv(6, 3)\n",
    "dynamic import_module": 'import importlib\nm = importlib.import_module("decimal")\n',
    "dunder import": '__import__("decimal")\n',
    "import fractions": "import fractions\n",
    "from fractions import Fraction": "from fractions import Fraction\n",
    "from fractions import star": "from fractions import *\n",
    "dynamic fractions": 'import importlib\nm = importlib.import_module("fractions")\n',
    "dunder fractions import": '__import__("fractions")\n',
    "__truediv__ call": "x = (6).__truediv__(3)\n",
    "int.__truediv__": "x = int.__truediv__(6, 3)\n",
    "__rtruediv__ access": "f = (6).__rtruediv__\n",
    "__itruediv__ access": "f = (6).__itruediv__\n",
    "def __truediv__": "class A:\n    def __truediv__(self, o: int) -> int:\n        return 1\n",
    "def __rtruediv__": "class A:\n    def __rtruediv__(self, o: int) -> int:\n        return 1\n",
    "getattr truediv string": 'x = getattr(6, "__truediv__")\n',
    "negative exponent": "x = 10 ** -2\n",
    "non-literal exponent": "n = 2\nx = 10 ** n\n",
    "float exponent via name": "x = 4 ** 0.5\n",
    "augmented negative exponent": "x = 10\nx **= -1\n",
    "pow negative": "x = pow(10, -2)\n",
    "pow non-literal": "n = 2\nx = pow(10, n)\n",
    "TYPE_CHECKING fractions": "if TYPE_CHECKING:\n    from fractions import Fraction\n",
    "inside if TYPE_CHECKING": "if TYPE_CHECKING:\n    x = 6 / 3\n",
    "inside if False": "if False:\n    from decimal import Decimal\n",
    "inside function body": "def f() -> int:\n    return 6 / 3\n",
}

MUST_NOT_DETECT = {
    "slash in a comment": "x = 1  # 6 / 3 and float and import decimal\n",
    "slash in a string": 'x = "6 / 3, float(1), 1.5, from decimal import Decimal"\n',
    "slash in a raw string": 'x = r"6 / 3 \\d float(1)"\n',
    "slash in a triple-quoted string": 'x = """\n6 / 3\nimport decimal\n1.5\n"""\n',
    "slash in a docstring": 'def f() -> int:\n    """Never use 6 / 3 or float."""\n    return 1\n',
    "floor division": "x = 6 // 3\n",
    "non-negative literal exponent": "x = 2 ** 63\nx **= 2\ny = pow(2, 8)\n",
    "truediv name only in a docstring": (
        'def f() -> int:\n    """Never __truediv__ or fractions."""\n    return 1\n'
    ),
    "truediv name in a longer string": 'x = "no __truediv__ here"\n',
    "fractions only in a string": 'x = "from fractions import Fraction"\n',
    "int arithmetic": "x = 6 * 3 + 2 - 1\nx //= 2\n",
    "similar names": "floating = 1\nfloat_free = 2\ndecimals = 3\n",
}


@pytest.mark.parametrize("shape", sorted(MUST_DETECT))
def test_money_guard_detects_shape(shape: str) -> None:
    assert violations(MUST_DETECT[shape]), f"money guard failed to detect: {shape}"


@pytest.mark.parametrize("shape", sorted(MUST_NOT_DETECT))
def test_money_guard_ignores_text_that_is_not_code(shape: str) -> None:
    assert not violations(MUST_NOT_DETECT[shape]), f"money guard false positive on: {shape}"


@pytest.mark.parametrize(
    ("relative_dir", "label"),
    [
        ("services/orders/src/otc_orders/domain/value_objects", "nested service domain"),
        ("packages/shared_kernel/src/otc_shared_kernel", "shared_kernel"),
    ],
)
def test_money_guard_walk_reaches_a_planted_file(
    tmp_path: Path, relative_dir: str, label: str
) -> None:
    # Behavioural check of the walker itself: a violating file placed at the real shape is both
    # walked and reported (shape `/`), in a nested domain path and in shared_kernel.
    planted = tmp_path / relative_dir
    planted.mkdir(parents=True)
    (planted / "planted.py").write_text("x = 6 / 3\n")
    domain_init = tmp_path / "services/orders/src/otc_orders/domain"
    domain_init.mkdir(parents=True, exist_ok=True)
    files = guarded_files(tmp_path)
    assert any(f.name == "planted.py" for f in files), f"walker missed the planted file ({label})"
    assert any(violations(f.read_text()) for f in files if f.name == "planted.py")


# Sentinels for the allowlist: (source, module name of the file, is it a package __init__)
ALLOW_MUST_DETECT = {
    "bson": ("from bson import ObjectId\n", "otc_orders.domain.value_objects", True),
    "gridfs": ("import gridfs\n", "otc_orders.domain.order", False),
    "unlisted library": ("import aiosmtplib\n", "otc_billing.domain", True),
    "other service": ("import otc_fulfillment\n", "otc_orders.domain.order", False),
    "own application": ("from otc_orders.application import x\n", "otc_orders.domain.order", False),
    "cqrs": ("import otc_cqrs\n", "otc_orders.domain.order", False),
    "kernel imports a service domain": (
        "import otc_orders.domain\n",
        "otc_shared_kernel.money",
        False,
    ),
    "kernel imports third party": ("import pydantic\n", "otc_shared_kernel", True),
    "relative import escaping the domain": (
        "from .. import application\n",
        "otc_orders.domain.order",
        False,
    ),
    "relative import to infrastructure": (
        "from ...infrastructure import x\n",
        "otc_orders.domain.value_objects.vo",
        False,
    ),
    "import_module literal": (
        'import importlib\nimportlib.import_module("bson")\n',
        "otc_orders.domain.order",
        False,
    ),
    "__import__ literal": ('__import__("gridfs")\n', "otc_orders.domain.order", False),
    "dynamic non-literal": (
        "import importlib\nimportlib.import_module(name)\n",
        "otc_orders.domain.order",
        False,
    ),
}

ALLOW_MUST_NOT_DETECT = {
    "stdlib from-import": ("from dataclasses import dataclass\n", "otc_orders.domain.order", False),
    "stdlib import": ("import enum\nimport uuid\n", "otc_orders.domain.order", False),
    "__future__": ("from __future__ import annotations\n", "otc_orders.domain.order", False),
    "shared kernel": (
        "from otc_shared_kernel import Money\n",
        "otc_orders.domain.order",
        False,
    ),
    "shared kernel submodule": (
        "from otc_shared_kernel.money import Money\n",
        "otc_orders.domain.order",
        False,
    ),
    "own domain absolute": (
        "from otc_orders.domain.value_objects import X\n",
        "otc_orders.domain.order",
        False,
    ),
    "relative within domain": ("from .value_objects import X\n", "otc_orders.domain.order", False),
    "relative within nested domain": (
        "from ..order import X\n",
        "otc_orders.domain.value_objects.vo",
        False,
    ),
    "relative from package init": ("from . import x\n", "otc_orders.domain", True),
    "kernel imports kernel": (
        "from otc_shared_kernel.money import M\n",
        "otc_shared_kernel.x",
        False,
    ),
    "kernel relative": ("from .money import M\n", "otc_shared_kernel.x", False),
    "bson only in a string": (
        'x = "from bson import ObjectId"  # import bson\n',
        "otc_orders.domain.o",
        False,
    ),
}


@pytest.mark.parametrize("shape", sorted(ALLOW_MUST_DETECT))
def test_import_allowlist_detects_shape(shape: str) -> None:
    source, module, is_pkg = ALLOW_MUST_DETECT[shape]
    assert import_violations(source, module, is_package=is_pkg), (
        f"import allowlist failed to detect: {shape}"
    )


@pytest.mark.parametrize("shape", sorted(ALLOW_MUST_NOT_DETECT))
def test_import_allowlist_accepts_shape(shape: str) -> None:
    source, module, is_pkg = ALLOW_MUST_NOT_DETECT[shape]
    assert not import_violations(source, module, is_package=is_pkg), (
        f"import allowlist false positive on: {shape}"
    )


def test_module_name_of_resolves_nested_and_package_files() -> None:
    root = Path("/r")
    nested = root / "services/orders/src/otc_orders/domain/value_objects/__init__.py"
    assert module_name_of(nested, root) == "otc_orders.domain.value_objects"
    kernel = root / "packages/shared_kernel/src/otc_shared_kernel/money.py"
    assert module_name_of(kernel, root) == "otc_shared_kernel.money"


def test_a_violation_inside_a_quoted_annotation_is_reported_at_its_real_line() -> None:
    found = violations('x = 1\ny = 2\nz: "float" = 3\n')
    assert found == ["line 3: `float` used as call, annotation or value"], found
