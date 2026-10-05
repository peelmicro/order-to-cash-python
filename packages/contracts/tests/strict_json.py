"""The strict JSON comparer shared by the contracts tests (loaded by path: pytest runs in importlib
mode, so test directories are not importable packages)."""

from typing import Any


def strict_json_differences(expected: Any, actual: Any, path: str = "$") -> list[str]:
    """Every difference between two parsed JSON documents; `[]` means semantically equal.

    Objects: key order immaterial, key set exact. Arrays: order significant, length exact.
    Scalars: the Python TYPE must match (`int` is not `float` is not `bool`) and so must the value.
    """
    if type(expected) is not type(actual):
        return [
            f"{path}: {type(expected).__name__} {expected!r} vs {type(actual).__name__} {actual!r}"
        ]
    if isinstance(expected, dict):
        found: list[str] = []
        for key in sorted(expected.keys() | actual.keys()):
            if key not in actual:
                found.append(f"{path}.{key}: missing from the actual document")
            elif key not in expected:
                found.append(f"{path}.{key}: not in the expected document")
            else:
                found.extend(strict_json_differences(expected[key], actual[key], f"{path}.{key}"))
        return found
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [f"{path}: array length {len(expected)} vs {len(actual)}"]
        return [
            d
            for i, (e, a) in enumerate(zip(expected, actual, strict=True))
            for d in strict_json_differences(e, a, f"{path}[{i}]")
        ]
    return [] if expected == actual else [f"{path}: {expected!r} vs {actual!r}"]
