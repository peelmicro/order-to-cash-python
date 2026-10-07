"""`mypy --strict` keeps the result type through `send` / `ask`, ties it to the handler, and
rejects wrong use (#8 D8).

Each snippet is type-checked by a real `mypy --strict` subprocess against the real package. The
ACCEPTED controls are what make a rejection mean something: they prove the checker is not simply
failing on everything. `reveal_type` proves the result is `int`, not `Any` (under --strict, `Any`
would also pass an `int` assignment). The "wrong result type" shapes prove the handler side: a
handler whose result differs from the `R` of its `Command[R]` / `Query[R]` is refused at
registration.
"""

import subprocess
import sys
from pathlib import Path

import pytest

CQRS_SRC = Path(__file__).resolve().parents[1] / "src"
PREAMBLE = """\
from dataclasses import dataclass
from otc_cqrs import Command, Query, HandlerRegistry, Dispatcher

class Scope: ...

@dataclass(frozen=True)
class Place(Command[int]):
    quantity: int

@dataclass(frozen=True)
class Other(Command[int]):
    pass

@dataclass(frozen=True)
class Count(Query[int]):
    pass

@dataclass(frozen=True)
class Ping(Command[None]):
    pass

class WrongResultHandler:
    async def handle(self, command: Place, /) -> str:
        return "not an int"

class WrongQueryResultHandler:
    async def handle(self, query: Count, /) -> str:
        return "not an int"

class PingHandler:
    async def handle(self, command: Ping, /) -> None:
        return None

class CountHandler:
    async def handle(self, query: Count, /) -> int:
        return 0

class PlaceHandler:
    async def handle(self, command: Place, /) -> int:
        return command.quantity

class OtherHandler:
    async def handle(self, command: Other, /) -> int:
        return 0

async def use(d: Dispatcher[Scope], r: HandlerRegistry[Scope], s: Scope) -> None:
"""

REJECTED = {
    "an int result assigned to str": (
        "    x: str = await d.send(Place(1), s)\n",
        'Argument 1 to "send" of "Dispatcher" has incompatible type "Place"; '
        'expected "Command[str]"',
    ),
    "a query result assigned to str": (
        "    x: str = await d.ask(Count(), s)\n",
        'Argument 1 to "ask" of "Dispatcher" has incompatible type "Count"; expected "Query[str]"',
    ),
    "a query sent as a command": (
        "    await d.send(Count(), s)\n",
        'Argument 1 to "send" of "Dispatcher" has incompatible type "Count"',
    ),
    "a command asked as a query": (
        "    await d.ask(Place(1), s)\n",
        'Argument 1 to "ask" of "Dispatcher" has incompatible type "Place"',
    ),
    "a handler for the wrong command": (
        "    r.register_command(Place, lambda scope: OtherHandler())\n",
        "has incompatible type",
    ),
    "a command handler returning the wrong result type": (
        "    r.register_command(Place, lambda scope: WrongResultHandler())\n",
        'expected "Callable[[Scope], CommandHandler[Place, int]]"',
    ),
    "a query handler returning the wrong result type": (
        "    r.register_query(Count, lambda scope: WrongQueryResultHandler())\n",
        'expected "Callable[[Scope], QueryHandler[Count, int]]"',
    ),
    "a command class registered that is not a Command": (
        "    r.register_command(int, lambda scope: PlaceHandler())\n",
        'expected "CommandType[',
    ),
    "a non-message object": (
        "    await d.send(object(), s)\n",
        'Argument 1 to "send" of "Dispatcher" has incompatible type "object"',
    ),
    "the wrong scope type": (
        "    await d.send(Place(1), 5)\n",
        'Argument 2 to "send" of "Dispatcher" has incompatible type "int"; expected "Scope"',
    ),
}

ACCEPTED = {
    "an int result assigned to int": "    x: int = await d.send(Place(1), s)\n",
    "a query result assigned to int": "    x: int = await d.ask(Count(), s)\n",
    "a no-result command with a None handler": (
        "    r.register_command(Ping, lambda scope: PingHandler())\n"
    ),
    "a query with a matching handler": (
        "    r.register_query(Count, lambda scope: CountHandler())\n"
    ),
    "a matching handler": "    r.register_command(Place, lambda scope: PlaceHandler())\n",
}


def run_mypy(tmp_path: Path, body: str) -> tuple[int, str]:
    source = tmp_path / "snippet.py"
    source.write_text(PREAMBLE + body)
    config = tmp_path / "mypy.ini"
    config.write_text(f"[mypy]\nstrict = True\nmypy_path = {CQRS_SRC}\n")
    completed = subprocess.run(  # noqa: S603 - fixed argv: this interpreter running mypy
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(config),
            "--cache-dir",
            str(tmp_path / ".mypy_cache"),
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    return completed.returncode, completed.stdout + completed.stderr


@pytest.mark.parametrize("shape", sorted(REJECTED))
def test_mypy_strict_rejects_wrong_dispatcher_use(tmp_path: Path, shape: str) -> None:
    body, expected = REJECTED[shape]
    code, output = run_mypy(tmp_path, body)
    assert code == 1, f"mypy --strict accepted `{body.strip()}` ({shape}):\n{output}"
    assert expected in output, f"mypy failed for another reason on {shape}:\n{output}"


@pytest.mark.parametrize("shape", sorted(ACCEPTED))
def test_mypy_strict_accepts_the_correct_forms(tmp_path: Path, shape: str) -> None:
    code, output = run_mypy(tmp_path, ACCEPTED[shape])
    assert code == 0, f"the control `{ACCEPTED[shape].strip()}` ({shape}) was rejected:\n{output}"


def test_the_result_type_survives_dispatch_as_int_not_any(tmp_path: Path) -> None:
    code, output = run_mypy(
        tmp_path,
        "    reveal_type(await d.send(Place(1), s))\n    reveal_type(await d.ask(Count(), s))\n",
    )
    assert code == 0, output
    assert output.count('Revealed type is "int"') == 2, output
    assert "Any" not in output
