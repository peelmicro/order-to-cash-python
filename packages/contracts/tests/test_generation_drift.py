"""Feature 8 acceptance item 1: the committed models ARE what the generator writes from the specs.

`quality.sh` section 5 runs `scripts/generate_contracts.py --check`; these tests prove the same
property inside pytest, and prove the check is not vacuous (it must flag a planted difference).
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "generate_contracts.py"
GENERATED = REPO_ROOT / "packages" / "contracts" / "src" / "otc_contracts" / "generated"
GENERATED_FILES = {"asyncapi.py", "openapi.py", "nullable.py"}


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_contracts", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_contracts"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fresh() -> dict[str, str]:
    files: dict[str, str] = load_script().generate_all()
    return files


def test_a_fresh_generation_writes_exactly_the_three_committed_files(fresh: dict[str, str]) -> None:
    assert set(fresh) == GENERATED_FILES
    assert {p.name for p in GENERATED.glob("*.py")} == GENERATED_FILES | {"__init__.py"}


def test_the_committed_generated_files_equal_a_fresh_generation(fresh: dict[str, str]) -> None:
    for name, text in fresh.items():
        assert (GENERATED / name).read_text("utf-8") == text, f"{name} drifted from the generator"


def test_generation_is_deterministic(fresh: dict[str, str]) -> None:
    assert load_script().generate_all() == fresh


def test_every_generated_file_is_marked_as_generated_and_names_its_source(
    fresh: dict[str, str],
) -> None:
    for name, text in fresh.items():
        assert text.startswith("# GENERATED FILE - DO NOT EDIT."), name
        assert "# Generator: datamodel-code-generator 0.83.0" in text, name
    assert "# Source: specs/shared/asyncapi.yaml sha256-prefix16=" in fresh["asyncapi.py"]
    assert "# Source: specs/shared/openapi.yaml sha256-prefix16=" in fresh["openapi.py"]


def test_the_drift_check_flags_an_edited_file_and_a_missing_file_by_name(
    fresh: dict[str, str], tmp_path: Path
) -> None:
    """Sentinels: the instrument must be able to fail."""
    script = load_script()
    for name in GENERATED_FILES:
        shutil.copy(GENERATED / name, tmp_path / name)
    assert script.drifted(fresh, tmp_path) == []
    edited = tmp_path / "asyncapi.py"
    edited.write_text(edited.read_text("utf-8") + "\n# hand edit\n", encoding="utf-8")
    assert script.drifted(fresh, tmp_path) == ["asyncapi.py"]
    (tmp_path / "nullable.py").unlink()
    assert sorted(script.drifted(fresh, tmp_path)) == ["asyncapi.py", "nullable.py"]


def test_the_check_command_names_the_drifted_file_and_exits_non_zero(tmp_path: Path) -> None:
    """The real CLI against a scratch copy of the generated directory with one file edited."""
    for name in GENERATED_FILES:
        shutil.copy(GENERATED / name, tmp_path / name)
    target = tmp_path / "openapi.py"
    target.write_bytes(target.read_bytes() + b"\n# planted drift\n")
    result = subprocess.run(  # noqa: S603 - fixed argument list
        [sys.executable, str(SCRIPT), "--check", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 1
    assert f"DRIFT: {tmp_path / 'openapi.py'} differs" in result.stderr
    assert "asyncapi.py" not in result.stderr
    assert "nullable.py" not in result.stderr
