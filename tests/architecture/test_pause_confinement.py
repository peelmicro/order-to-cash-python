"""Pausing a container is confined to ONE helper (S6.7): the one that unpauses in a `finally`.

A readiness test pauses a PRIVATE container to prove that a dependency which accepts connections and
answers nothing is reported `down` within its bound. A test that pauses a container and dies before
unpausing leaves it frozen; if that container is shared, every later test stalls. So the only
`.pause()` call in the repository's tests is the one in `tests/observability/health_support.py`'s
`paused(...)`, which wraps it in `try`/`finally`, and the only `.unpause()` is that `finally`'s.

The census reads the AST of every `.py` under the test trees and the root `conftest.py`
(a comment, a docstring or a string that names `.pause(` is not a call). The expected set is the
literal below; anything else, found by subtraction, fails by file and line. The behaviour of the
helper is proven by `tests/observability/test_health_support.py` (a body that raises, a body that
times out, a body that completes: the container is `running` afterwards).
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = "tests/observability/health_support.py"
EXPECTED = {(HELPER, "pause"), (HELPER, "unpause")}
TRAPPED = {"pause", "unpause"}


def calls(root: Path) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    paths = [
        *root.glob("services/*/tests/**/*.py"),
        *root.glob("packages/*/tests/**/*.py"),
        *root.glob("tests/**/*.py"),
        root / "conftest.py",
    ]
    for path in sorted(set(paths)):
        if "__pycache__" in path.parts or not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in TRAPPED
            ):
                found.add((path.relative_to(root).as_posix(), node.func.attr))
    return found


def unpause_is_in_a_finally(root: Path) -> bool:
    tree = ast.parse((root / HELPER).read_text(encoding="utf-8"))
    for function in ast.walk(tree):
        if isinstance(function, ast.FunctionDef) and function.name == "paused":
            for node in ast.walk(function):
                if isinstance(node, ast.Try):
                    return any(
                        isinstance(inner, ast.Attribute) and inner.attr == "unpause"
                        for statement in node.finalbody
                        for inner in ast.walk(statement)
                    )
    return False


def test_s6_the_only_pause_and_unpause_calls_in_the_tests_are_the_helpers() -> None:
    found = calls(REPO_ROOT)
    assert found - EXPECTED == set(), f"a test pauses a container outside the helper: {found}"
    assert found == EXPECTED, f"the helper lost its pause or unpause call: {found}"


def test_s6_the_helpers_unpause_is_inside_a_finally() -> None:
    assert unpause_is_in_a_finally(REPO_ROOT)


def test_sentinel_a_pause_in_a_comment_or_a_string_is_not_a_call(tmp_path: Path) -> None:
    sample = tmp_path / "services/orders/tests/test_x.py"
    sample.parent.mkdir(parents=True)
    sample.write_text('# container.pause()\nTEXT = "container.pause()"\n"""container.pause()"""\n')
    assert calls(tmp_path) == set()


def test_sentinel_a_pause_in_another_test_is_found(tmp_path: Path) -> None:
    sample = tmp_path / "services/orders/tests/integration/test_x.py"
    sample.parent.mkdir(parents=True)
    sample.write_text("def test_x(c):\n    c.get_wrapped_container().pause()\n")
    assert calls(tmp_path) == {("services/orders/tests/integration/test_x.py", "pause")}


def test_sentinel_a_pause_hidden_in_a_type_checking_block_or_an_alias_is_still_found(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "tests/observability/test_y.py"
    sample.parent.mkdir(parents=True)
    sample.write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    wrapped.pause()\n"
        "stop = wrapped.unpause\nstop()\n"
        "getattr(wrapped, 'pause')()\n"
    )
    # the first form is an ordinary call inside a dead region: counted (a census does not run code);
    # the bare attribute reference and the getattr string are NOT calls of `.pause`/`.unpause` and
    # are the instrument's known blind spot, recorded rather than hidden
    assert calls(tmp_path) == {("tests/observability/test_y.py", "pause")}
