"""Generate the wire models from `specs/shared/asyncapi.yaml` and `specs/shared/openapi.yaml`.

    uv run python scripts/generate_contracts.py          # (re)write the committed modules
    uv run python scripts/generate_contracts.py --check  # regenerate in memory, fail on any drift

What it does, per spec:

1. extracts `components.schemas` into a JSON-Schema document (`#/components/schemas/X` becomes
   `#/$defs/X`; `description`, `examples` and `title` are dropped because they live in the spec and
   would only add lines past the repository's 100-column ruff limit; `format: int64` becomes the
   explicit `minimum`/`maximum` Pydantic can enforce, because the spec declares the width);
2. runs the pinned `datamodel-code-generator` over it (no timestamp, no per-field alias: camelCase
   is `WireModel`'s one alias generator, snake_case names come from `--snake-case-field`);
3. formats the result with the repository's own ruff configuration, through stdin, so the committed
   file passes `ruff format --check` and `ruff check` unchanged wherever it is generated.

It also writes `generated/nullable.py`: the fields each spec declares nullable, which is the
per-field None decision `otc_contracts.wire` applies.

Output is deterministic: no timestamp, and the header carries a 64-bit prefix (16 hex digits) of
each spec file's SHA-256, so any edit of a spec (even one that changes no generated line) makes
`--check` fail until regenerated.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
SPECS = REPO / "specs" / "shared"
OUT = REPO / "packages" / "contracts" / "src" / "otc_contracts" / "generated"
GENERATOR_VERSION = "0.83.0"

# Schemas that describe transport headers (Kafka / NATS header keys such as `content-type`), not
# JSON bodies. Their property names are not camelCase, so the one camelCase alias generator cannot
# represent them, and no body is ever parsed into them.
EXCLUDED_SCHEMAS: dict[str, frozenset[str]] = {
    "asyncapi": frozenset({"FactHeaders", "DeadLetterHeaders", "RpcHeaders"}),
    "openapi": frozenset(),
}
# Formats the generator would turn into a type with no wire writer (`AnyUrl` normalises,
# `SecretStr` hides): they stay plain `str`. A format not listed here, in INT_RANGES or in
# KEPT_FORMATS is refused.
STRING_FORMATS_DROPPED = frozenset({"uri", "password"})
KEPT_FORMATS = frozenset({"uuid", "date-time"})
INT_RANGES = {"int64": (-(2**63), 2**63 - 1), "int32": (-(2**31), 2**31 - 1)}
# datamodel-codegen options. Every one is a decision recorded in progress/impl_contracts_package.md.
CODEGEN_ARGS = [
    "--input-file-type", "jsonschema",
    "--output-model-type", "pydantic_v2.BaseModel",
    "--base-class", "otc_contracts.wire.WireModel",
    "--target-python-version", "3.14",
    "--snake-case-field",
    "--no-alias",
    "--use-annotated",
    "--field-constraints",
    "--use-standard-collections",
    "--use-union-operator",
    "--collapse-root-models",
    "--skip-root-model",
    "--disable-timestamp",
    "--formatters", "builtin",
]  # fmt: skip


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite(node: Any, *, in_schema: bool, excluded: frozenset[str]) -> Any:
    """Copy of a schema tree with refs rewritten and documentation keywords dropped."""
    if isinstance(node, list):
        return [_rewrite(item, in_schema=in_schema, excluded=excluded) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if in_schema and key in {"description", "examples", "title", "$comment"}:
            continue
        if key == "$ref" and isinstance(value, str):
            out[key] = value.replace("#/components/schemas/", "#/$defs/")
        elif key == "properties" and in_schema and isinstance(value, dict):
            # a mapping of property NAMES to schemas: a property may legitimately be called
            # `description` or `title`, so its keys are never treated as keywords
            out[key] = {
                name: _rewrite(sub, in_schema=True, excluded=excluded)
                for name, sub in value.items()
            }
        elif key in {"enum", "required", "const", "default", "type"}:
            out[key] = value
        else:
            out[key] = _rewrite(value, in_schema=True, excluded=excluded)
    fmt = out.get("format")
    if in_schema and fmt in STRING_FORMATS_DROPPED:
        del out["format"]
    elif in_schema and fmt in INT_RANGES and out.get("type") == "integer":
        low, high = INT_RANGES[fmt]
        out.setdefault("minimum", low)
        out.setdefault("maximum", high)
    elif in_schema and fmt is not None and fmt not in KEPT_FORMATS | INT_RANGES.keys():
        raise SystemExit(f"unhandled schema format {fmt!r}: decide it in generate_contracts.py")
    return out


def _flatten_compositions(schemas: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Merge `allOf: [{$ref: Base}, {properties: ...}]` into one flat object schema.

    The generator would emit `class XEvent(Envelope)` and re-declare `payload` with a narrower
    type, which `mypy --strict` rejects as an incompatible override. Flattening keeps the
    envelope's property order (the wire field order), replaces an overridden property wholesale
    (`eventType` becomes the `const`, `payload` becomes the `$ref`) and keeps `required`.
    """
    flat: dict[str, Any] = {}
    merged: list[str] = []
    for name, schema in schemas.items():
        parts = schema.get("allOf") if isinstance(schema, dict) else None
        if (
            parts
            and len(parts) == 2
            and "$ref" in parts[0]
            and parts[1].get("type") == "object"
            and "properties" in parts[1]
        ):
            base = schemas[parts[0]["$ref"].rsplit("/", 1)[-1]]
            properties = {**base["properties"], **parts[1]["properties"]}
            flat[name] = {
                "type": "object",
                "properties": properties,
                "required": [*base.get("required", []), *parts[1].get("required", [])],
            }
            merged.append(name)
        else:
            flat[name] = schema
    return flat, merged


def _is_nullable(prop: Any) -> bool:
    if not isinstance(prop, dict):
        return False
    kind = prop.get("type")
    if kind == "null" or (isinstance(kind, list) and "null" in kind) or prop.get("nullable"):
        return True
    return any(
        _is_nullable(sub) for key in ("oneOf", "anyOf", "allOf") for sub in prop.get(key, [])
    )


def load_spec(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """`(json_schema_document, {class_name: sorted nullable wire names})` for one spec."""
    spec = yaml.safe_load((SPECS / f"{name}.yaml").read_text(encoding="utf-8"))
    schemas: dict[str, Any] = spec["components"]["schemas"]
    excluded = EXCLUDED_SCHEMAS[name]
    missing = excluded - schemas.keys()
    if missing:
        raise SystemExit(f"{name}.yaml no longer declares the excluded schemas {sorted(missing)}")
    kept, merged = _flatten_compositions({k: v for k, v in schemas.items() if k not in excluded})
    if name == "asyncapi" and not {k for k in kept if k.endswith("Event")} <= set(merged):
        raise SystemExit(f"composed schemas {merged} do not include every *Event schema")
    nullable = {
        key: sorted(p for p, sub in schema["properties"].items() if _is_nullable(sub))
        for key, schema in kept.items()
        if isinstance(schema, dict) and schema.get("properties")
    }
    nullable = {k: v for k, v in nullable.items() if v}
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": _rewrite(kept, in_schema=False, excluded=excluded),
    }
    return document, nullable


def _ruff(source: str, filename: str, *args: str) -> str:
    """Run ruff on `source` as if it lived at `filename`, with the repository's configuration."""
    result = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        [
            sys.executable,
            "-m",
            "ruff",
            *args,
            "--config",
            str(REPO / "pyproject.toml"),
            "--stdin-filename",
            filename,
            "-",
        ],
        input=source,
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    if result.returncode not in (0, 1) or (args[0] == "format" and result.returncode != 0):
        raise SystemExit(f"ruff {args[0]} failed:\n{result.stderr}")
    return result.stdout


def generate_module(name: str, header: str) -> tuple[str, dict[str, Any]]:
    document, nullable = load_spec(name)
    with tempfile.TemporaryDirectory() as tmp:
        schema_file = Path(tmp) / f"{name}.schema.json"
        schema_file.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        out_file = Path(tmp) / f"{name}.py"
        subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [
                sys.executable,
                "-m",
                "datamodel_code_generator",
                "--input",
                str(schema_file),
                "--output",
                str(out_file),
                *CODEGEN_ARGS,
            ],
            check=True,
            cwd=REPO,
        )
        body = out_file.read_text(encoding="utf-8")
    # drop the generator's own two-line header, keep the repository's marker
    body = "\n".join(line for line in body.split("\n") if not line.startswith("# generated by"))
    body = "\n".join(line for line in body.split("\n") if not line.startswith("#   filename:"))
    source = header + "\n" + body.lstrip("\n")
    path = f"packages/contracts/src/otc_contracts/generated/{name}.py"
    source = _ruff(source, path, "check", "--fix", "--quiet", "--select", "I,F401,UP")
    source = _ruff(source, path, "format")
    return source, nullable


def render_nullable(nullable_by_module: dict[str, dict[str, Any]], header: str) -> str:
    lines = [
        header,
        '"""Fields each spec declares nullable: the only ones whose `None` is written `null`."""',
        "",
        "NULLABLE_FIELDS: dict[str, frozenset[str]] = {",
    ]
    for module in sorted(nullable_by_module):
        for cls in sorted(nullable_by_module[module]):
            names = ", ".join(json.dumps(n) for n in nullable_by_module[module][cls])
            lines.append(f'    "{module}.{cls}": frozenset({{{names}}}),')
    lines.append("}")
    source = "\n".join(lines) + "\n"
    path = "packages/contracts/src/otc_contracts/generated/nullable.py"
    return _ruff(source, path, "format")


def header_for(*names: str) -> str:
    specs = "".join(
        f"# Source: specs/shared/{n}.yaml sha256-prefix16={_sha256(SPECS / f'{n}.yaml')[:16]}\n"
        for n in names
    )
    return (
        "# GENERATED FILE - DO NOT EDIT.\n"
        "# Regenerate with `uv run python scripts/generate_contracts.py`.\n"
        f"{specs}"
        f"# Generator: datamodel-code-generator {GENERATOR_VERSION}, generate_contracts.py\n"
        "# `quality.sh` section 5 fails when this file differs from a fresh generation.\n"
    )


def generate_all() -> dict[str, str]:
    installed = version("datamodel-code-generator")
    if installed != GENERATOR_VERSION:
        raise SystemExit(
            f"datamodel-code-generator {installed} installed, {GENERATOR_VERSION} pinned"
        )
    files: dict[str, str] = {}
    nullable: dict[str, dict[str, Any]] = {}
    for name in ("asyncapi", "openapi"):
        files[f"{name}.py"], nullable[name] = generate_module(name, header_for(name))
    files["nullable.py"] = render_nullable(nullable, header_for("asyncapi", "openapi"))
    return files


def drifted(files: dict[str, str], out: Path = OUT) -> list[str]:
    """Names of the generated files whose committed text differs from `files` (or is missing)."""
    return [
        n
        for n, text in files.items()
        if not (out / n).exists() or (out / n).read_text("utf-8") != text
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed output drifts")
    parser.add_argument("--out", type=Path, default=OUT, help="directory of the generated modules")
    args = parser.parse_args()
    out: Path = args.out
    files = generate_all()
    if args.check:
        stale = drifted(files, out)
        if stale:
            for name in stale:
                print(
                    f"DRIFT: {out / name} differs from a fresh generation",
                    file=sys.stderr,
                )
            print(
                "run `uv run python scripts/generate_contracts.py` and commit it", file=sys.stderr
            )
            return 1
        print(f"contracts drift check: {len(files)} generated files match a fresh generation")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    for n, text in files.items():
        (out / n).write_text(text, encoding="utf-8")
        print(f"wrote {out / n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
