"""`mypy --strict` rejects a float where money or a quantity is expected (acceptance item 3).

`int / int` is a `float` in Python, so `Money(10 / 3, "EUR")` is the classic way a rounding error
enters a money model. The runtime refuses it too (test_money.py), but the type checker should
catch it before the code runs. Each snippet is type-checked by a real `mypy --strict` subprocess
against the real package; the `//` snippets are the controls that prove the checker is not simply
failing on everything (a control that passes is what makes the failure of the `/` snippet mean
something).
"""

import subprocess
import sys
from pathlib import Path

import pytest

KERNEL_SRC = Path(__file__).resolve().parents[1] / "src"
PREAMBLE = "from otc_shared_kernel import Money, Quantity\n"

REJECTED = {
    "Money from true division": (
        'Money(10 / 3, "EUR")\n',
        'Argument 1 to "Money" has incompatible type "float"; expected "int"',
    ),
    "Quantity from true division": (
        "Quantity(7 / 2)\n",
        'Argument 1 to "Quantity" has incompatible type "float"; expected "int"',
    ),
    "Money from a float literal": (
        'Money(100.0, "EUR")\n',
        'Argument 1 to "Money" has incompatible type "float"; expected "int"',
    ),
    "adding a bare int where a Money is expected": (
        'Money(1, "EUR").add(5)\n',
        'Argument 1 to "add" of "Money" has incompatible type "int"; expected "Money"',
    ),
    "multiplying by a bare int through multiply": (
        'Money(1, "EUR").multiply(3)\n',
        'Argument 1 to "multiply" of "Money" has incompatible type "int"; expected "Quantity"',
    ),
}

ACCEPTED = {
    "Money from floor division": 'Money(10 // 3, "EUR")\n',
    "Quantity from floor division": "Quantity(7 // 2)\n",
    "multiply by a Quantity": 'Money(1, "EUR").multiply(Quantity(3))\n',
}


def run_mypy(tmp_path: Path, snippet: str) -> tuple[int, str]:
    source = tmp_path / "snippet.py"
    source.write_text(PREAMBLE + snippet)
    config = tmp_path / "mypy.ini"
    config.write_text(f"[mypy]\nstrict = True\nmypy_path = {KERNEL_SRC}\n")
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
def test_mypy_strict_rejects_a_float_or_a_bare_int_in_money_arithmetic(
    tmp_path: Path, shape: str
) -> None:
    snippet, expected = REJECTED[shape]
    code, output = run_mypy(tmp_path, snippet)
    assert code == 1, f"mypy --strict accepted `{snippet.strip()}` ({shape}):\n{output}"
    assert expected in output, f"mypy failed for another reason on {shape}:\n{output}"


@pytest.mark.parametrize("shape", sorted(ACCEPTED))
def test_mypy_strict_accepts_the_integer_forms(tmp_path: Path, shape: str) -> None:
    code, output = run_mypy(tmp_path, ACCEPTED[shape])
    assert code == 0, f"the control `{ACCEPTED[shape].strip()}` ({shape}) was rejected:\n{output}"
