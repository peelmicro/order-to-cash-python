"""The one serializer configuration of the wire (feature 8, `contracts_package`).

Every decision is made here, once, and nowhere else:

* **camelCase** on the wire through ONE mechanism: `alias_generator=to_camel` on `WireModel`. The
  generator is told `--no-alias`, so no generated field carries its own `Field(alias=...)`.
* **compact JSON, non-ASCII raw**: written by `to_wire_json` with explicit `separators` and
  `ensure_ascii=False`, not by whatever a library defaults to.
* **`Instant` as `YYYY-MM-DDTHH:MM:SS.mmmZ`** from `format_instant`, an explicit formatter.
  Pydantic's own datetime output writes microseconds (`.442000Z`), which is why the writer starts
  from a python-mode dump and formats datetimes itself.
* **None**: a `None` is written as an explicit `null` only for a field that the spec declares
  nullable (`generated/nullable.py`, itself generated from the spec); every other `None` is absent.
* **Integers are strict when parsing**: `"8934"`, `8934.0` and `True` are refused for an integer
  field (`strict=True`); Pydantic's lax mode would turn them into `8934`/`8934`/`1`.

`model_dump_json` is deliberately not the writer: it would emit microsecond instants.
"""

import json
import warnings
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    model_serializer,
)
from pydantic.alias_generators import to_camel

from otc_contracts.generated.nullable import NULLABLE_FIELDS


def format_instant(value: datetime) -> str:
    """Write an aware datetime as `YYYY-MM-DDTHH:MM:SS.mmmZ` (UTC; sub-millisecond truncated).

    A naive datetime is refused: it has no instant. A non-UTC offset is converted to UTC.
    Truncation (not rounding) matches `.fff` in #8 and `toISOString()` in #7.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("an Instant must be timezone-aware; a naive datetime has no instant")
    utc = value.astimezone(UTC)
    return (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}"
        f"T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}.{utc.microsecond // 1000:03d}Z"
    )


def _nullable_for(model_type: type) -> frozenset[str]:
    """Nullable wire names of a generated class and of every generated base (a subclass declared
    elsewhere keeps its explicit `null`s)."""
    names: set[str] = set()
    for cls in model_type.__mro__:
        names |= NULLABLE_FIELDS.get(f"{cls.__module__.rsplit('.', 1)[-1]}.{cls.__name__}", set())
    return frozenset(names)


class WireModel(BaseModel):
    """Base class of every generated wire model.

    Immutable (`frozen=True`): an attribute assignment is refused. `model_copy(update=...)` and
    `model_construct` still skip validation, so `to_wire_json` re-validates before writing.
    Its JSON-mode serialisation writes instants as `.mmmZ`, so `model_dump_json()`,
    `model_dump(mode="json")` and a FastAPI `response_model` agree with `to_wire_json`.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        # Both directions so that Python code can construct a model with snake_case keyword
        # arguments (what mypy sees) while `from_wire_json` parses by alias only.
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
        strict=True,
        frozen=True,
    )

    @model_serializer(mode="wrap")
    def _serialize(
        self, handler: SerializerFunctionWrapHandler, info: SerializationInfo
    ) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if info.mode_is_json():
            # Pydantic's own JSON mode writes microseconds; replace every datetime field.
            for name, field in type(self).model_fields.items():
                key = field.serialization_alias or field.alias or name
                value = getattr(self, name)
                if key in data and isinstance(value, datetime):
                    data[key] = format_instant(value)
        nullable = _nullable_for(type(self))
        return {
            name: value for name, value in data.items() if value is not None or name in nullable
        }


def _default(value: object) -> str:
    """Hooks for the python-mode objects JSON has no native form for. Everything else, notably a
    `Decimal` or any other number type, is refused rather than guessed: money is `int` minor
    units. (Enums are `StrEnum`, a `str`, which `json` writes natively.)"""
    if isinstance(value, datetime):
        return format_instant(value)
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"{type(value).__name__} has no wire representation")


def to_wire_dict(model: WireModel) -> dict[str, Any]:
    """The python-mode dump the writer serialises (datetimes and UUIDs still objects)."""
    return model.model_dump(mode="python")


def to_wire_json(model: WireModel) -> str:
    """The wire form: compact, non-ASCII raw, camelCase, `.mmmZ` instants.

    What this adds beyond the model's own JSON serialisation (`model_dump_json`, which now agrees
    on instants, None and field order): (1) it RE-VALIDATES the instance first, because
    `model_copy(update=...)` and `model_construct` skip validation, so a bool, float or string in
    an integer field, or a bad UUID, is refused here with the field named; (2) separators,
    `ensure_ascii=False` and `allow_nan=False` are stated, not inherited from a library default;
    (3) a value with no wire form (a `Decimal` in an untyped payload) raises `TypeError`.
    """
    with warnings.catch_warnings():
        # a field holding the wrong type makes the serializer warn; validation below is the refusal
        warnings.simplefilter("ignore")
        dumped = to_wire_dict(model)
    type(model).model_validate(dumped)
    return json.dumps(
        dumped,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_default,
    )


def from_wire_json[M: WireModel](model_type: type[M], data: str | bytes) -> M:
    """Parse the wire form: by alias only, integers strict."""
    return model_type.model_validate_json(data, by_alias=True, by_name=False)
