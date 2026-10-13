"""Item 7 (#8 id 77): no fixture runs a server with reload, and no test tree imports a file watcher.

#8's analogue was a host builder's `reloadOnChange` (`HostInotifyReloadGuardTests`). uvicorn has no
file watcher unless asked, so the guard is about what the tests ask for. The census reads the AST of
every `.py` under `services/*/tests`, `packages/*/tests`, `tests/` and the root `conftest.py`
(the guard's own file is excluded where the listing is built: its sentinels spell the forbidden
forms), plus the web configs by text.

* The POPULATION is every call that starts a server: `uvicorn.run` / `uvicorn.Config` /
  `uvicorn.Server` (by module attribute or by `from uvicorn import ...`, aliases followed); every
  `Popen` / `run` / `check_call` / `check_output` / `call` / `create_subprocess_exec` /
  `python_module` whose argument list holds the string `"uvicorn"` or a `"-m"` followed by an
  `otc_...` module; and every `Popen` / `create_subprocess_exec` whose argument is NOT a literal
  list (an opaque argv: the shared `spawn` helper), so a new server-starting helper is a deliberate
  edit; and every SHELL spawn, which is opaque by construction (a command line in a string): a call
  with `shell=True`, `os.system`, `os.popen`, `create_subprocess_shell`. The count per file is
  compared with the literal `EXPECTED_POPULATION`.
* The VIOLATIONS are searched over the whole tree, not only the population (a server started
  through a helper the population does not recognise must still not reload): a keyword named
  `reload` (unless literally `False`) or `reload_*` on any call; a string constant holding the TOKEN
  `--reload` or `--watch` (at the start or after whitespace, so a command line in a string is read)
  or `UVICORN_RELOAD...` (docstrings and `assert` messages are not counted); an import of
  `watchfiles` (`import`, `from`, or `import_module("watchfiles")`).

Premises: P1 an AST walk, so a comment is not code and a string that is a docstring is not counted,
while a call under `if TYPE_CHECKING:` or `if False:` IS counted (the census over-reports); P2 a
call is recognised by the last name of its callee; P3 an argument list is read through nested
list/tuple literals, a non-constant element standing as a placeholder (so `[sys.executable, "-m",
"uvicorn"]` is read as `[None, "-m", "uvicorn"]`). Known blind spot, recorded not hidden: an argv
built in a variable and passed by name is an opaque argv (counted under the opaque rule, which a
literal list with a name in it is not). The sentinels arm P1 - P3 on temporary trees.
"""

import ast
import re
from collections import Counter
from itertools import pairwise
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = "tests/architecture/test_no_reload_servers.py"

UVICORN_ENTRYPOINTS = {"run", "Config", "Server"}
PROCESS_CALLS = {
    "Popen",
    "run",
    "check_call",
    "check_output",
    "call",
    "create_subprocess_exec",
    "python_module",
}
OPAQUE_CALLS = {"Popen", "create_subprocess_exec"}
FORBIDDEN_STRING = re.compile(r"(^|\s)--(reload|watch)([-=\s]|$)|^UVICORN_RELOAD")
SHELL_CALLS = {"create_subprocess_shell"}
SHELL_MODULE_CALLS = {"system", "popen"}  # `os.system`, `os.popen`
WEB_FORBIDDEN = re.compile(r"reload|watch", re.IGNORECASE)

# One entry per file, the number of server-starting call sites it holds (design.md 8.1; the record
# lists them one by one, S7.2).
EXPECTED_POPULATION: dict[str, int] = {
    "services/gateway/tests/conftest.py": 2,  # uvicorn.Config, uvicorn.Server
    "services/gateway/tests/integration/test_gateway_listens_on_gateway_port.py": 1,
    "services/gateway/tests/integration/test_gateway_log_contract.py": 1,
    "services/gateway/tests/integration/test_gateway_shutdown_with_open_streams.py": 1,
    "services/orders/tests/integration/test_orders_host_lifespan.py": 1,
    "services/orders/tests/integration/test_orders_host_sigterm.py": 1,
    "services/orders/tests/integration/test_orders_log_contract.py": 1,
    "services/fulfillment/tests/integration/test_fulfillment_log_contract.py": 1,
    "services/billing/tests/integration/test_billing_log_contract.py": 1,
    "services/notifications/tests/integration/test_notifications_log_contract.py": 1,
    "services/projector/tests/integration/test_projector_log_contract.py": 1,
    "tests/observability/log_contract_support.py": 1,  # the opaque argv of `spawn`
}


def listed_files(root: Path) -> list[Path]:
    paths = [
        *root.glob("services/*/tests/**/*.py"),
        *root.glob("packages/*/tests/**/*.py"),
        *root.glob("tests/**/*.py"),
        root / "conftest.py",
    ]
    return [
        path
        for path in sorted(set(paths))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.relative_to(root).as_posix() != THIS_FILE
    ]


def callee_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def flatten(node: ast.expr) -> list[str | None]:
    """Strings of an argument, nested list/tuple literals read through, others as `None`."""
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else [None]
    if isinstance(node, ast.List | ast.Tuple):
        items: list[str | None] = []
        for element in node.elts:
            items.extend(flatten(element.value if isinstance(element, ast.Starred) else element))
        return items
    return [None]


def docstring_nodes(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            found.add(id(node.value))
    return found


def assert_message_nodes(tree: ast.AST) -> set[int]:
    """The constants inside an `assert`'s message: prose about a forbidden flag, not a request."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and node.msg is not None:
            found.update(id(part) for part in ast.walk(node.msg))
    return found


def uvicorn_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    """(local names bound to the module `uvicorn`, local names bound to one of its entry points)."""
    modules: set[str] = set()
    entries: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(
                (alias.asname or alias.name) for alias in node.names if alias.name == "uvicorn"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "uvicorn":
            entries.update(
                (alias.asname or alias.name)
                for alias in node.names
                if alias.name in UVICORN_ENTRYPOINTS
            )
    return modules, entries


def is_server_call(call: ast.Call, modules: set[str], entries: set[str]) -> bool:
    func = call.func
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in modules
        and func.attr in UVICORN_ENTRYPOINTS
    ):
        return True
    if isinstance(func, ast.Name) and func.id in entries:
        return True
    name = callee_name(call)
    if name not in PROCESS_CALLS:
        return False
    arguments: list[str | None] = []
    if name == "python_module":
        arguments.append("-m")
    for argument in call.args:
        arguments.extend(flatten(argument))
    if "uvicorn" in arguments:
        return True
    return any(
        first == "-m" and isinstance(second, str) and second.startswith("otc_")
        for first, second in pairwise(arguments)
    )


def is_shell_spawn(call: ast.Call) -> bool:
    """A command line in a string: `shell=True` on any call, `os.system`, `os.popen`,
    `create_subprocess_shell`. Opaque by construction, whatever the string holds."""
    if callee_name(call) in SHELL_CALLS:
        return True
    func = call.func
    if (
        isinstance(func, ast.Attribute)
        and func.attr in SHELL_MODULE_CALLS
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    ):
        return True
    return any(
        keyword.arg == "shell"
        and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is False)
        for keyword in call.keywords
    )


def is_opaque_spawn(call: ast.Call) -> bool:
    """A `Popen` / `create_subprocess_exec` whose argv is not a literal list or tuple."""
    if is_shell_spawn(call):
        return True
    if callee_name(call) not in OPAQUE_CALLS:
        return False
    if callee_name(call) == "create_subprocess_exec":
        return False  # its argv is the positional arguments themselves
    if not call.args:
        return False
    return not isinstance(call.args[0], ast.List | ast.Tuple)


def population(root: Path) -> Counter[str]:
    found: Counter[str] = Counter()
    for path in listed_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules, entries = uvicorn_names(tree)
        relative = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                is_server_call(node, modules, entries) or is_opaque_spawn(node)
            ):
                found[relative] += 1
    return found


def violations(root: Path) -> list[str]:
    found: list[str] = []
    for path in listed_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(root).as_posix()
        docstrings = docstring_nodes(tree) | assert_message_nodes(tree)
        for node in ast.walk(tree):
            where = f"{relative}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg is None:
                        continue
                    if keyword.arg.startswith("reload_") or (
                        keyword.arg == "reload"
                        and not (
                            isinstance(keyword.value, ast.Constant) and keyword.value.value is False
                        )
                    ):
                        found.append(f"{where}: asks for reload ({keyword.arg}=...)")
                if callee_name(node) == "import_module" and any(
                    isinstance(arg, ast.Constant) and arg.value == "watchfiles" for arg in node.args
                ):
                    found.append(f"{where}: imports watchfiles")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstrings and FORBIDDEN_STRING.search(node.value):
                    found.append(f"{where}: the string {node.value!r} asks for reload")
            elif isinstance(node, ast.Import):
                if any(alias.name.split(".")[0] == "watchfiles" for alias in node.names):
                    found.append(f"{where}: imports watchfiles")
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] == "watchfiles":
                    found.append(f"{where}: imports watchfiles")
    return found


def web_violations(root: Path) -> list[str]:
    found: list[str] = []
    configs = [
        *root.glob("apps/web/playwright.config.*"),
        *root.glob("apps/web/vite*.config.*"),
    ]
    for path in sorted(configs):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if WEB_FORBIDDEN.search(line):
                found.append(f"{path.relative_to(root).as_posix()}:{number}: {line.strip()}")
    return found


def test_item_7_no_test_asks_a_server_for_reload_or_imports_a_file_watcher() -> None:
    assert violations(REPO_ROOT) == []


def test_item_7_the_web_configs_ask_for_no_reload_or_watcher() -> None:
    assert web_violations(REPO_ROOT) == []


def test_item_7_the_population_of_server_starting_calls_equals_the_literal() -> None:
    found = population(REPO_ROOT)
    assert dict(found) == EXPECTED_POPULATION, (
        "a server-starting call site was added or removed; edit EXPECTED_POPULATION on purpose "
        f"(found {dict(found)})"
    )
    assert sum(found.values()) == 13


def _tree(tmp_path: Path, name: str, text: str) -> Path:
    sample = tmp_path / name
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text(text)
    return tmp_path


def test_sentinel_a_pristine_tree_has_no_violation_and_no_population(tmp_path: Path) -> None:
    _tree(tmp_path, "tests/test_x.py", "def test_x():\n    assert True\n")
    assert violations(tmp_path) == []
    assert population(tmp_path) == Counter()


def test_sentinel_reload_true_in_a_fixture_is_found(tmp_path: Path) -> None:
    _tree(tmp_path, "tests/test_x.py", "import uvicorn\nuvicorn.run(app, reload=True)\n")
    assert [v.split(": ", 1)[1] for v in violations(tmp_path)] == ["asks for reload (reload=...)"]
    assert population(tmp_path) == Counter({"tests/test_x.py": 1})


def test_sentinel_reload_false_is_not_a_request(tmp_path: Path) -> None:
    _tree(tmp_path, "tests/test_x.py", "import uvicorn\nuvicorn.run(app, reload=False)\n")
    assert violations(tmp_path) == []


def test_sentinel_a_reload_dirs_keyword_is_found(tmp_path: Path) -> None:
    _tree(tmp_path, "tests/test_x.py", "config(reload_dirs=['src'])\n")
    assert len(violations(tmp_path)) == 1


def test_sentinel_reload_in_a_subprocess_argv_is_found_and_counted(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "tests/test_x.py",
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-m', 'uvicorn', 'otc_x.main:app', '--reload'])\n",
    )
    assert len(violations(tmp_path)) == 1
    assert population(tmp_path) == Counter({"tests/test_x.py": 1})


def test_sentinel_the_reload_environment_variable_is_found(tmp_path: Path) -> None:
    _tree(tmp_path, "tests/test_x.py", "ENV = {'UVICORN_RELOAD': '1'}\nENV2 = 'UVICORN_RELOAD'\n")
    assert len(violations(tmp_path)) == 2  # the dict key and the plain string


def test_sentinel_a_comment_a_docstring_and_a_message_are_not_counted(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "tests/test_x.py",
        '"""run with --reload and import watchfiles"""\n'
        "# uvicorn.run(app, reload=True)\n"
        "def test_x():\n"
        '    """--reload"""\n'
        '    assert True, "the server must not be started with --reload"\n',
    )
    assert violations(tmp_path) == []
    assert population(tmp_path) == Counter()


def test_sentinel_a_reload_under_type_checking_is_still_counted(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "tests/test_x.py",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    serve(reload=True)\n",
    )
    assert len(violations(tmp_path)) == 1


def test_sentinel_an_aliased_uvicorn_import_is_in_the_population(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "tests/test_x.py",
        "from uvicorn import run as serve\nimport uvicorn as u\n"
        "serve(app)\nu.Server(u.Config(app))\n",
    )
    assert population(tmp_path) == Counter({"tests/test_x.py": 3})


def test_sentinel_watchfiles_in_any_import_form_is_found(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "tests/test_x.py",
        "import watchfiles\nfrom watchfiles import awatch\nimportlib.import_module('watchfiles')\n",
    )
    assert len(violations(tmp_path)) == 3


def test_sentinel_a_module_pair_and_python_module_are_in_the_population(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "tests/test_x.py",
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, '-m', 'otc_gateway'])\n"
        "python_module('otc_gateway')\n"
        "python_module('uvicorn', 'otc_x.main:app')\n"
        "subprocess.run([sys.executable, '-m', 'mypy'])\n",
    )
    assert population(tmp_path) == Counter({"tests/test_x.py": 3})


def test_sentinel_an_opaque_argv_is_in_the_population(tmp_path: Path) -> None:
    _tree(tmp_path, "tests/test_x.py", "import subprocess\nsubprocess.Popen(list(command))\n")
    assert population(tmp_path) == Counter({"tests/test_x.py": 1})


def test_sentinel_a_web_config_that_watches_is_found(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "apps/web/playwright.config.ts",
        "export default { webServer: { command: 'vite --watch' } };\n",
    )
    assert len(web_violations(tmp_path)) == 1
    assert web_violations(tmp_path / "empty") == []


def test_sentinel_a_shell_string_spawn_is_found_and_counted_in_every_form(tmp_path: Path) -> None:
    """Probe 9a of the round-1 review: neither form was seen before the shell forms joined the
    population and the `--reload` token was searched inside a command line."""
    _tree(
        tmp_path,
        "tests/test_x.py",
        "import os, subprocess\n"
        'subprocess.run("python -m uvicorn otc_orders.main:app --port 0 --reload", shell=True)\n'
        'os.system("uvicorn otc_orders.main:app --reload")\n',
    )
    assert len(violations(tmp_path)) == 2
    assert population(tmp_path) == Counter({"tests/test_x.py": 2})


def test_sentinel_every_shell_spawn_is_in_the_population_whatever_it_runs(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "tests/test_x.py",
        "import asyncio, os, subprocess\n"
        'os.popen("ls")\n'
        'asyncio.create_subprocess_shell("ls")\n'
        'subprocess.call("ls", shell=True)\n'
        'subprocess.call("ls", shell=False)\n',
    )
    assert violations(tmp_path) == []
    assert population(tmp_path) == Counter({"tests/test_x.py": 3})


def test_sentinel_the_reload_token_is_found_inside_a_command_line_string(tmp_path: Path) -> None:
    _tree(tmp_path, "tests/test_x.py", 'CMD = "uvicorn app:app --watch ."\nOK = "--reloaded"\n')
    assert len(violations(tmp_path)) == 1
