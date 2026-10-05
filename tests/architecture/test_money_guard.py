"""AST money guard: no float, no true division, no decimal in `domain` code or `shared_kernel`.

Money is `int` minor units (CLAUDE.md). This guard reads the AST, so a `/` or `float` that only
appears in a comment or a string literal is NOT a violation, while the same text in real code is
-- including inside `if TYPE_CHECKING:` / `if False:` blocks (decision: those regions are walked
like any other code, because a `float` annotation or a dead `/` is still the wrong type in the
domain; see the sweep sentinels below). `//` (floor division of ints) is allowed.

Round 4, change of instrument (maintainer-approved, final): rounds 1-3 kept a DENY-list of numeric
modules and lost to the next module (`statistics.mean`). The guard now holds an ALLOW-list, a
literal derived by census (AST over the 35 files in `services/*/src/otc_*/domain/**` and
`packages/shared_kernel/src/**`; absolute imports found: `collections` (`.abc`), `dataclasses`,
`datetime`, `hashlib`, `types`, `typing`, `uuid`, plus first-party `otc_shared_kernel` and the
service's own package, e.g. `otc_seed`). `ALLOWED_ROOTS` is exactly that set; the importing
service's own package is added per file. Any other absolute import, in any form (`import x`,
`import x as y`, `import x.y`, `from x import ...`, `from x import *`, `__import__("x")`,
`importlib.import_module("x")`), fails by name, and so does any reference to `__import__` /
`import_module` (a domain has no reason to import dynamically). The builtin names `pow`, `float`
and `round` are refused as a Name reference ANYWHERE (call, alias `_p = pow`, `reduce(pow, ...)`,
`map(pow, ...)`, annotation); census: `sum` x5, `divmod` x1, `abs` x1 are used, `pow`, `float`,
`round` are not. The `getattr` / `__getattribute__` reflection ban is kept.

Redundant after the allow-list (removed): the numeric-module deny-list and its import / from-import
/ dynamic-import branches, and the call-position `pow(...)` exponent rule (a bare `pow` is now
refused as a name). KEPT because they still catch what the allow-list cannot: the `/` and `**`
operators, the `truediv` / `pow` / `ipow` / dunder names as attributes, defs and strings
(`ops.ipow(...)`, `(6).__truediv__`, `def __pow__`), and `from <first-party> import ipow`, since a
first-party helper named `ipow` or `truediv` is allowed by import but is still `**` or `/`.

Residuals (no syntax guard closes them; the backstop is `Money` refusing non-int amounts at
construction, `type(...) is int` in `packages/shared_kernel/src/otc_shared_kernel/money.py`, plus
`mypy --strict`): `vars(x)["pow"]`, `x.__dict__[...]`, `globals()[...]`, `__builtins__` tricks; a
first-party or allowed-module function that itself returns a float under a name not in the families
above; `sum(..., 0.5)` style float literals are caught as literals, but `sum(xs) / n` is the `/`
operator; a stdlib allowed module's float-returning API (`datetime.timedelta.total_seconds()`,
`hashlib` none): `total_seconds()` returns a float and is not named here, so it is a residual.

Why the AST guard and not an import-linter contract: import-linter's graph holds packages
(directories with `__init__.py`); `math` and `operator` are single-module / built-in stdlib, and
`root_packages = ["math"]` is refused with "'math' is a module, not a package" (probed). So the
contract cannot see them, and the AST guard is the only instrument that can.

Accepted residuals (no syntax guard can close them; they need a name the AST cannot evaluate):
`vars(x)["pow"]`, `x.__dict__[...]`, `globals()[...]`, `__builtins__` tricks, and a module reached
through a non-literal `importlib.import_module(name)` (refused by name: `import_module` is a
forbidden name anywhere, so the residual is only a module reached without that name).
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
TRUEDIV_NAMES = {"truediv", "itruediv", "__truediv__", "__rtruediv__", "__itruediv__"}
# The ALLOW-list (a literal, derived by census, see the docstring). Anything else fails by name.
ALLOWED_ROOTS = frozenset(
    {"collections", "dataclasses", "datetime", "hashlib", "types", "typing", "uuid"}
    | {"otc_shared_kernel"}
)
# Builtins that are float sources or `**` by another name, refused as a bare name anywhere.
BANNED_BUILTINS = {"float", "pow", "round"}
# Dynamic import machinery: refused by name, in any position.
DYNAMIC_IMPORT_NAMES = {"__import__", "import_module"}
# Reaching an attribute by a string: `getattr(operator, "pow")` is `**` by another name.
BANNED_REFLECTION = {"getattr", "__getattribute__"}
# `**` spelled as an attribute or protocol: `math.pow`, `operator.pow`, `x.__pow__(-2)` return a
# float for a negative exponent exactly as `10 ** -2` does. A bare `pow(...)` call is judged by
# its exponent below; the attribute and dunder forms are refused outright, like the truediv family.
POW_NAMES = {"pow", "ipow", "__pow__", "__rpow__", "__ipow__"}
POW_DUNDERS = POW_NAMES - {"pow", "ipow"}


def _is_safe_exponent(node: ast.expr) -> bool:
    """`**` rule: the exponent must be a non-negative int literal. A negative literal
    (`10 ** -2`), a float, or a non-literal exponent can produce a float, so it is flagged."""
    return isinstance(node, ast.Constant) and type(node.value) is int and node.value >= 0


def _import_allowed(module: str, own_package: str | None) -> bool:
    top = module.split(".")[0]
    return top in ALLOWED_ROOTS or (own_package is not None and top == own_package)


def violations(source: str, own_package: str | None = None) -> list[str]:
    """Return one claim-naming message per violation found in `source`.

    `own_package` is the importing service's own package (`otc_seed`), allowed besides the literal
    `ALLOWED_ROOTS`; `None` for the kernel and for snippets.
    """
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
        elif isinstance(node, ast.Name) and node.id in BANNED_BUILTINS:
            found.append(f"line {line}: `{node.id}` used as call, annotation or value")
        elif isinstance(node, ast.Name | ast.Attribute) and (
            getattr(node, "id", None) in DYNAMIC_IMPORT_NAMES
            or getattr(node, "attr", None) in DYNAMIC_IMPORT_NAMES
        ):
            found.append(f"line {line}: dynamic import machinery (imports are an allow-list)")
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
        elif isinstance(node, ast.Constant) and node.value in POW_NAMES:
            found.append(
                f"line {line}: `{node.value}` as a string (getattr is `**` by another name)"
            )
        elif isinstance(node, ast.Name) and node.id in BANNED_REFLECTION:
            found.append(f"line {line}: `{node.id}` (reaches any attribute by a string)")
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_REFLECTION:
            found.append(f"line {line}: `.{node.attr}` (reaches any attribute by a string)")
        elif (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name in BANNED_REFLECTION
        ):
            found.append(f"line {line}: `def {node.name}` offers attribute access by a string")
        elif isinstance(node, ast.Attribute) and node.attr in POW_NAMES:
            found.append(f"line {line}: `.{node.attr}` (`**` by another name, can return a float)")
        elif isinstance(node, ast.Name) and node.id in POW_DUNDERS:
            found.append(f"line {line}: `{node.id}` (`**` by another name, can return a float)")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in POW_DUNDERS:
            found.append(f"line {line}: `def {node.name}` offers `**`")
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
                f"line {line}: `import {alias.name}` is outside the import allow-list"
                for alias in node.names
                if not _import_allowed(alias.name, own_package)
            )
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and not _import_allowed(node.module or "", own_package):
                found.append(
                    f"line {line}: `from {node.module} import ...` is outside the import allow-list"
                )
            # `from <first-party> import ipow` binds `**` / `/` to a bare name the attribute rules
            # never see; an allowed module may still export one.
            found.extend(
                f"line {line}: `from {node.module} import {alias.name}` "
                "(`**` or `/` by another name, can return a float)"
                for alias in node.names
                if alias.name in POW_NAMES | TRUEDIV_NAMES
            )
    return found


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
# with a non-literal argument they are flagged as a non-literal dynamic import.


def module_name_of(path: Path, root: Path) -> str:
    """Dotted module name of a file under a `src` directory below `root`."""
    parts = path.relative_to(root).parts
    src = parts.index("src")
    names = [*parts[src + 1 : -1], path.stem]
    if names[-1] == "__init__":
        names.pop()
    return ".".join(names)


def _own_package(path: Path, root: Path) -> str | None:
    """The `otc_<service>` package the file belongs to."""
    return module_name_of(path, root).split(".")[0]


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
        str(path.relative_to(REPO_ROOT)): violations(
            path.read_text(), _own_package(path, REPO_ROOT)
        )
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
    "operator.pow": "import operator\nx = operator.pow(10, -2)\n",
    "operator.pow non-negative": "import operator\nx = operator.pow(2, 8)\n",
    "math.pow": "import math\nx = math.pow(10, 2)\n",
    "from math import pow": "from math import pow\nx = pow(10, 2)\n",
    "from math import pow as alias": "from math import pow as p\nx = p(10, 2)\n",
    "from operator import pow as alias": "from operator import pow as p\nx = p(10, -2)\n",
    "from operator import truediv as alias": "from operator import truediv as t\nx = t(6, 3)\n",
    "from operator import truediv": "from operator import truediv\nx = truediv(6, 3)\n",
    "from operator import __truediv__": "from operator import __truediv__\n",
    "from any module import pow": "from mylib import pow\n",
    "from math import star": "from math import *\nx = pow(10, 2)\n",
    "from operator import star": "from operator import *\n",
    "pow among several from-imports": "from math import floor, pow as p, ceil\n",
    "__pow__ call": "x = (10).__pow__(-2)\n",
    "int.__pow__": "x = int.__pow__(10, 2)\n",
    "__rpow__ access": "f = (10).__rpow__\n",
    "def __pow__": "class A:\n    def __pow__(self, o: int) -> int:\n        return 1\n",
    "getattr pow string": 'x = getattr(6, "__pow__")\n',
    # round 3: the reviewer's three survivors, and the residual he ruled must be fixed now
    "operator.ipow": "import operator\nx = operator.ipow(10, -2)\n",
    "operator.itruediv": "import operator\nx = operator.itruediv(6, 4)\n",
    "getattr(operator, 'pow')": 'import operator\nx = getattr(operator, "pow")(10, -2)\n',
    "getattr(math, 'pow')": 'x = getattr(math, "pow")(10, 2)\n',
    "from mylib import ipow": "from mylib import ipow\n",
    "from mylib import itruediv": "from mylib import itruediv\n",
    "attribute itruediv on a non-module": "x = ops.itruediv(6, 4)\n",
    "attribute ipow on a non-module": "x = ops.ipow(10, -2)\n",
    "pow as a bare string constant": 'NAME = "pow"\n',
    "from operator import ipow": "from operator import ipow\n",
    "from operator import itruediv": "from operator import itruediv\n",
    # round 4: the allow-list. Every module outside it x every import form, including the ones the
    # round-3 deny-list never named (`statistics`, `random`, `builtins`, `functools`, `importlib`).
    "statistics.mean": "import statistics\nx = statistics.mean([1, 2])\n",
    "from statistics import fmean": "from statistics import fmean\n",
    "pow aliased": "_p = pow\n",
    "reduce(pow, ...)": "from collections import reduce\nx = reduce(pow, [10, -2])\n",
    "map(pow, ...)": "x = list(map(pow, [10], [-2]))\n",
    "partial(pow, 10)": "x = partial(pow, 10)\n",
    "pow non-negative call": "y = pow(2, 8)\n",
    "float(x)": "x = float(1)\n",
    "round(x)": "x = round(1)\n",
    "round aliased": "r = round\n",
    "float aliased": "f = float\n",
    "import_module name alone": "g = importlib.import_module\n",
    "__import__ alias": "i = __import__\n",
    "__import__ of an ALLOWED module": '__import__("typing")\n',
    "a first-party-looking module that is not this service": "import otc_orders\n",
    "from first-party import ipow": "from otc_shared_kernel import ipow\n",
    **{
        f"{form} of {mod}": src.format(m=mod)
        for mod in (
            "math",
            "operator",
            "cmath",
            "numpy",
            "fractions",
            "decimal",
            "statistics",
            "random",
            "builtins",
            "functools",
            "itertools",
            "importlib",
            "mathx",
            "otc_orders",
        )
        for form, src in {
            "import": "import {m}\n",
            "import as": "import {m} as alias\n",
            "import submodule": "import {m}.sub\n",
            "from-import": "from {m} import anything\n",
            "from-import as": "from {m} import anything as other\n",
            "from-import star": "from {m} import *\n",
            "from submodule": "from {m}.sub import anything\n",
            "dunder import": '__import__("{m}")\n',
            "import_module": 'import importlib\nimportlib.import_module("{m}")\n',
            "import_module submodule": 'import importlib\nimportlib.import_module("{m}.sub")\n',
            "dotted __import__": 'import importlib\nimportlib.__import__("{m}")\n',
        }.items()
    },
    "getattr call": 'x = getattr(o, "a")\n',
    "getattr with a default": "x = getattr(o, name, None)\n",
    "getattr alias": "g = getattr\n",
    "builtins.getattr": "import builtins\nx = builtins.getattr(o, 'a')\n",
    "__getattribute__ call": 'x = o.__getattribute__("a")\n',
    "def __getattribute__": (
        "class A:\n    def __getattribute__(self, n: str) -> int:\n        return 1\n"
    ),
    "getattr inside if False": "if False:\n    x = getattr(o, 'a')\n",
    "getattr inside a function": "def f(o):\n    return getattr(o, 'a')\n",
    "import math inside a function": "def f() -> int:\n    import math\n    return 1\n",
    "import math inside if TYPE_CHECKING": "if TYPE_CHECKING:\n    import math\n",
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
    "non-negative literal exponent": "x = 2 ** 63\nx **= 2\n",
    "allowed roots, every form": (
        "import collections\nimport collections.abc\nimport dataclasses\nimport datetime\n"
        "import hashlib\nimport types\nimport typing\nimport uuid\nimport otc_shared_kernel\n"
        "from otc_shared_kernel.money import Money\nfrom typing import Any as A\n"
    ),
    "relative imports are not absolute imports": "from . import x\nfrom ..y import z\n",
    "sum / divmod / abs are used and allowed": "x = sum([1])\ny = divmod(7, 2)\nz = abs(-1)\n",
    "similar builtin names": "power = 1\nrounded = 2\nfloats = 3\n",
    "truediv name only in a docstring": (
        'def f() -> int:\n    """Never __truediv__ or fractions."""\n    return 1\n'
    ),
    "pow name only in a docstring": (
        'def f() -> int:\n    """Never operator.pow or __pow__."""\n    return 1\n'
    ),
    "pow name in a longer string": 'x = "no __pow__ or math.pow here"\n',
    "truediv name in a longer string": 'x = "no __truediv__ here"\n',
    "a name that merely contains getattr": "my_getattr_count = 1\nx = hasattr(o, 'a')\n",
    "fractions only in a string": 'x = "from fractions import Fraction"\n',
    "int arithmetic": "x = 6 * 3 + 2 - 1\nx //= 2\n",
    "getattr in a string": 'x = "getattr(o, 1) and import math"\n',
    "getattr in a comment": "x = 1  # getattr(o, 'a'); from operator import pow\n",
    "getattr in a triple-quoted string": 'x = """\ngetattr(o, 1)\nimport math\n"""\n',
    "hasattr / setattr": "x = hasattr(o, 'a')\nsetattr(o, 'a', 1)\n",
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


def _absolute_import_roots(source: str, own_package: str) -> set[str]:
    """Roots of every absolute import in `source`, minus the file's own package (as the guard)."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            roots.add((node.module or "").split(".")[0])
    roots.discard(own_package)
    return roots


def test_the_import_allowlist_is_the_census_derived_from_the_real_population() -> None:
    # Re-derived (AST over the population the guard scans), not a literal compared to a literal:
    # an allowed module that nothing imports, or an import the list lacks, makes the sets differ.
    derived: set[str] = set()
    for path in guarded_files(REPO_ROOT):
        derived |= _absolute_import_roots(path.read_text(), _own_package(path, REPO_ROOT) or "")
    assert derived == set(ALLOWED_ROOTS), (
        f"allow-list not in the census: unused={sorted(set(ALLOWED_ROOTS) - derived)} "
        f"missing={sorted(derived - set(ALLOWED_ROOTS))}"
    )


def test_own_package_is_allowed_and_a_sibling_service_package_is_not() -> None:
    assert not violations("from otc_seed.domain.clock import Clock\n", "otc_seed")
    assert violations("from otc_seed.domain.clock import Clock\n", "otc_orders")
    assert violations("from otc_seed.domain.clock import Clock\n")
