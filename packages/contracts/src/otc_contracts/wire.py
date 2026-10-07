"""The one serializer configuration of the wire (feature 8, `contracts_package`).

Every decision is made here, once, and nowhere else:

* **camelCase** on the wire through ONE mechanism: `alias_generator=to_camel` on `WireModel`. The
  generator is told `--no-alias`, so no generated field carries its own `Field(alias=...)`.
* **compact JSON, non-ASCII raw**: written by `to_wire_json` with explicit `separators` and
  `ensure_ascii=False`, not by whatever a library defaults to. Pydantic's JSON mode happens to
  write the same bytes; the writer does not rely on that.
* **`Instant` as `YYYY-MM-DDTHH:MM:SS.mmmZ`** from `format_instant`, an explicit formatter.
  Pydantic's own datetime output writes microseconds (`.442000Z`), so `WireModel`'s JSON-mode
  serializer replaces every datetime it holds (directly, in a list, or in a dict such as
  `Envelope.payload`) with `format_instant`. `model_dump_json()`, `model_dump(mode="json")` and a
  FastAPI `response_model` therefore agree with `to_wire_json`.
* **None**: a `None` is written as an explicit `null` only for a field that the spec declares
  nullable (`generated/nullable.py`, itself generated from the spec); every other `None` is absent.
* **Integers are strict**: `"8934"`, `8934.0` and `True` are refused for an integer field when
  parsing (`strict=True`) and when writing: an instance built past validation
  (`model_copy(update=...)`, `model_construct`) is re-validated by `to_wire_json` AND by the
  JSON-mode serializer, so no JSON path writes it. Assignment is refused (`frozen=True`).

The generated `RootModel`s (`asyncapi.Quantity`, `asyncapi.ProductCode`, and the reference types in
`openapi`) are NOT wire models: they derive from `pydantic.RootModel`, not `WireModel`, are lax, and
nothing references them (the spec's value objects are inlined as constrained fields). The
generator emits them from the spec's named schemas and its output is not edited, so they are
documented here as non-wire. Do not use one to parse or write a message.
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


def wire_instant(value: datetime) -> datetime:
    """The one millisecond truncation: an aware instant, in UTC, cut (never rounded) to `.mmm`.

    `timestamptz(3)` ROUNDS (`.123987` is stored as `.124`) while `format_instant` TRUNCATES
    (`.123`); every instant the outbox path stores or writes goes through here first, so the stored
    value, the envelope's `occurredAt` and every payload instant are the same millisecond (OI19).
    A naive datetime is refused: it has no instant. A non-UTC offset is converted to UTC.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("an Instant must be timezone-aware; a naive datetime has no instant")
    utc = value.astimezone(UTC)
    return utc.replace(microsecond=utc.microsecond // 1000 * 1000)


def _nullable_for(model_type: type) -> frozenset[str]:
    """Nullable wire names of a generated class and of every generated base (a subclass declared
    elsewhere keeps its explicit `null`s)."""
    names: set[str] = set()
    for cls in model_type.__mro__:
        names |= NULLABLE_FIELDS.get(f"{cls.__module__.rsplit('.', 1)[-1]}.{cls.__name__}", set())
    return frozenset(names)


def _holds_datetime(value: object) -> bool:
    if isinstance(value, datetime):
        return True
    if isinstance(value, list | tuple):
        return any(_holds_datetime(item) for item in value)
    if isinstance(value, dict):
        return any(_holds_datetime(item) for item in value.values())
    return False


def _json_ready(value: Any) -> Any:
    """The JSON-mode form of a value that holds a datetime: instants through `format_instant`,
    the rest as the wire writes it. A nested `WireModel` serialises itself."""
    if isinstance(value, datetime):
        return format_instant(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, WireModel):
        return value.model_dump(mode="json")
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    return value


class WireModel(BaseModel):
    """Base class of every generated wire model.

    Immutable (`frozen=True`): an attribute assignment is refused. `model_copy(update=...)` and
    `model_construct` skip validation, so the JSON-mode serializer re-validates the instance
    before writing (as `to_wire_json` does) and raises `ValidationError` naming the field.
    Its JSON-mode serialisation writes instants as `.mmmZ` wherever they sit (a field, a list, a
    dict), so `model_dump_json()`, `model_dump(mode="json")` and a FastAPI `response_model` agree
    with `to_wire_json`. Python mode is unchanged: datetimes stay objects.
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
        if info.mode_is_json():
            # Every JSON path refuses an instance that skipped validation. Python mode does not
            # enter this branch, so the nested dump below cannot recurse.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # the wrong type warns; the validation refuses
                python_dump = self.model_dump(mode="python")
            type(self).model_validate(python_dump)
        data: dict[str, Any] = handler(self)
        if info.mode_is_json():
            # Pydantic's own JSON mode writes microseconds. Replace every field that holds a
            # datetime, however deep (a list of instants, an `Any` dict payload).
            for name, field in type(self).model_fields.items():
                key = field.serialization_alias or field.alias or name
                value = getattr(self, name)
                if key in data and _holds_datetime(value):
                    data[key] = _json_ready(value)
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

    The model's own JSON paths (`model_dump_json`, `model_dump(mode="json")`) now agree with it on
    validation, instants, None and field order. What it still adds: it validates BEFORE any
    serialization, naming the field; separators, `ensure_ascii=False` and `allow_nan=False` are
    stated, not inherited from a library default; and a value with no wire form (a `Decimal` in an
    untyped payload) raises `TypeError`.
    """
    with warnings.catch_warnings():
        # a field holding the wrong type makes the serializer warn; validation below is the refusal
        warnings.simplefilter("ignore")
        dumped = to_wire_dict(model)
    type(model).model_validate(dumped)
    # `model_validate` re-checks only the top-level model: a WireModel held in an `Any` field (an
    # `Envelope.payload` value) is already a plain dict in `dumped`. The JSON-mode dump enters every
    # nested model's serializer, which re-validates it, so the canonical writer refuses what
    # `model_dump_json` refuses. Its result is discarded: the bytes come from `json.dumps` below.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.model_dump(mode="json")
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
