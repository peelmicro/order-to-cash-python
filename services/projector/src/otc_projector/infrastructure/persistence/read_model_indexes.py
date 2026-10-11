"""The two indexes of `order_timeline`: created idempotently at boot, then VERIFIED.

`PR22`, `PR39`, `PR52`.

* `uq_order_reference`: `{orderReference: 1}`, unique, `partialFilterExpression: {orderReference:
  {$type: "string"}}`. Identical to the seed's (`services/seed/src/otc_seed/infrastructure/mongo.py:
  39-44`, pinned to `tests/fixtures/read_model_constants.json`): a placeholder carries
  `orderReference: null`, MongoDB compares nulls equal, so a plain unique index would reject the
  second placeholder with E11000. The seed's creation then the projector's, and the reverse, raise
  nothing (`PR39`).
* `ix_status_updatedAt`: `{status: 1, updatedAt: -1}`.

Creating an index with a name that exists with different options is refused by the server with code
85 (`IndexOptionsConflict`) or 86 (`IndexKeySpecsConflict`; measured 86 for plain-versus-partial in
both creation orders). The boot fails with a message naming the index, the code the server ACTUALLY
raised (read from the exception, never a literal) and the `dropIndex` one-liner. On code 85 the
server's complaint is that the same index exists under ANOTHER name ("Index already exists with a
different name: uq_other"), so the index to drop is the one the server named, parsed from its
message; on 86 (and when the message carries no name) it is the expected index.

The creation call's conflict error alone is not enough (`PR52`): a DIFFERENTLY-NAMED unique index
on `orderReference` raises no conflict for a create by name, yet would reject the second
placeholder. So after creating, the stored specifications are read back and compared in key,
uniqueness and partial filter, and any other unique index covering `orderReference` fails the
boot, naming it.
"""

import re
from dataclasses import dataclass
from typing import Any

from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import OperationFailure

ORDER_REFERENCE_INDEX_NAME = "uq_order_reference"
STATUS_UPDATED_AT_INDEX_NAME = "ix_status_updatedAt"
INDEX_CONFLICT_CODES = (85, 86)
EXISTING_NAME_IN_CODE_85 = re.compile(r"different name:\s*(?P<name>[^\s,]+)")


class ReadModelIndexError(RuntimeError):
    """The collection's indexes cannot be the ones the projector needs; the boot must fail."""


@dataclass(frozen=True, slots=True)
class ExpectedIndex:
    name: str
    key: tuple[tuple[str, int], ...]
    unique: bool
    partial_filter: dict[str, Any] | None


ORDER_REFERENCE_INDEX = ExpectedIndex(
    name=ORDER_REFERENCE_INDEX_NAME,
    key=(("orderReference", 1),),
    unique=True,
    partial_filter={"orderReference": {"$type": "string"}},
)
STATUS_UPDATED_AT_INDEX = ExpectedIndex(
    name=STATUS_UPDATED_AT_INDEX_NAME,
    key=(("status", 1), ("updatedAt", -1)),
    unique=False,
    partial_filter=None,
)
EXPECTED_INDEXES = (ORDER_REFERENCE_INDEX, STATUS_UPDATED_AT_INDEX)


def _drop_hint(collection: AsyncCollection[dict[str, Any]], name: str) -> str:
    return f'db.getCollection("{collection.name}").dropIndex("{name}")'


async def _create(collection: AsyncCollection[dict[str, Any]], expected: ExpectedIndex) -> None:
    options: dict[str, Any] = {"name": expected.name, "unique": expected.unique}
    if expected.partial_filter is not None:
        options["partialFilterExpression"] = expected.partial_filter
    try:
        await collection.create_index(list(expected.key), **options)
    except OperationFailure as error:
        if error.code not in INDEX_CONFLICT_CODES:
            raise
        culprit = expected.name
        if error.code == 85:
            named = EXISTING_NAME_IN_CODE_85.search(str(error))
            if named is not None:
                culprit = named.group("name")
        raise ReadModelIndexError(
            f"index {culprit} already exists on {collection.name} with different options "
            f"(expected {expected.name}): the server refused the creation with code {error.code}. "
            f"Drop it and restart: {_drop_hint(collection, culprit)}"
        ) from error


async def ensure_indexes(collection: AsyncCollection[dict[str, Any]]) -> None:
    for expected in EXPECTED_INDEXES:
        await _create(collection, expected)


async def verify_indexes(collection: AsyncCollection[dict[str, Any]]) -> None:
    stored: dict[str, dict[str, Any]] = {}
    async for specification in await collection.list_indexes():
        stored[str(specification["name"])] = dict(specification)
    for expected in EXPECTED_INDEXES:
        found = stored.get(expected.name)
        if found is None:
            raise ReadModelIndexError(f"index {expected.name} is missing from {collection.name}")
        differences = []
        if tuple(found["key"].items()) != expected.key:
            differences.append(f"key {dict(found['key'])} != {dict(expected.key)}")
        if bool(found.get("unique", False)) != expected.unique:
            differences.append(f"unique {bool(found.get('unique', False))} != {expected.unique}")
        if found.get("partialFilterExpression") != expected.partial_filter:
            differences.append(
                f"partialFilterExpression {found.get('partialFilterExpression')} != "
                f"{expected.partial_filter}"
            )
        if differences:
            raise ReadModelIndexError(
                f"index {expected.name} on {collection.name} differs from the expected "
                f"definition ({'; '.join(differences)}). Drop it and restart: "
                f"{_drop_hint(collection, expected.name)}"
            )
    expected_names = {expected.name for expected in EXPECTED_INDEXES}
    for name, found in stored.items():
        if name in expected_names or not found.get("unique", False):
            continue
        if "orderReference" in found["key"]:
            raise ReadModelIndexError(
                f"index {name} on {collection.name} is a unique index covering orderReference "
                f"besides {ORDER_REFERENCE_INDEX_NAME}: it would reject the second placeholder "
                f"(orderReference null). Drop it and restart: {_drop_hint(collection, name)}"
            )
