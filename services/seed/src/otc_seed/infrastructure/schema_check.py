"""Compare the seed's table definitions with the LIVE database.

`schema_problems` returns one sentence per divergence (an empty list means the database is what
`tables.py` says it is). It is the oracle of two guards: the seed refuses to write into a database
that diverges (boot-time validation, `postgres.PostgresSeedTarget.verify`), and
`tests/integration/test_seed_tables_match_migration.py` runs it against the Alembic-migrated
templates of the three services, so a migration that changes a seeded table fails a test instead of
a first deployment.

Compared per table: existence; per column the PostgreSQL type text, nullability and whether it is
an identity column; the primary key; every foreign key (columns, referred table and columns,
`ON DELETE`); the set of unique column-sets (unique constraints and unique indexes alike). Indexes
that are not unique, defaults and constraint NAMES are deliberately not compared: nothing the seed
writes depends on them.
"""

from sqlalchemy import MetaData, Table, UniqueConstraint, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.ext.asyncio import AsyncConnection

_DIALECT = postgresql.dialect()  # type: ignore[no-untyped-call]


def _expected(table: Table) -> dict[str, object]:
    uniques = {
        tuple(c.name for c in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    } | {tuple(c.name for c in index.columns) for index in table.indexes if index.unique}
    return {
        "columns": {
            c.name: (c.type.compile(dialect=_DIALECT), bool(c.nullable), c.identity is not None)
            for c in table.columns
        },
        "pk": tuple(c.name for c in table.primary_key.columns),
        "fks": {
            (
                tuple(e.parent.name for e in fk.elements),
                fk.referred_table.name,
                tuple(e.column.name for e in fk.elements),
                fk.ondelete,
            )
            for fk in table.foreign_key_constraints
        },
        "uniques": uniques,
    }


def _actual(inspector: Inspector, name: str) -> dict[str, object]:
    pk = tuple(inspector.get_pk_constraint(name)["constrained_columns"])
    uniques = {tuple(u["column_names"]) for u in inspector.get_unique_constraints(name)} | {
        tuple(str(c) for c in index["column_names"])
        for index in inspector.get_indexes(name)
        if index.get("unique")
    }
    # The primary key's own index is not a unique CONSTRAINT of the model.
    uniques.discard(pk)
    return {
        "columns": {
            c["name"]: (
                c["type"].compile(dialect=_DIALECT),
                bool(c["nullable"]),
                bool(c.get("identity")),
            )
            for c in inspector.get_columns(name)
        },
        "pk": pk,
        "fks": {
            (
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                (fk.get("options") or {}).get("ondelete"),
            )
            for fk in inspector.get_foreign_keys(name)
        },
        "uniques": uniques,
    }


def problems_in(connection: Connection, metadata: MetaData) -> list[str]:
    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    found: list[str] = []
    for table in metadata.sorted_tables:
        if table.name not in existing:
            found.append(f"table {table.name} does not exist (is the database migrated to head?)")
            continue
        expected, actual = _expected(table), _actual(inspector, table.name)
        for key in ("columns", "pk", "fks", "uniques"):
            if expected[key] == actual[key]:
                continue
            if key == "columns":
                want, have = expected["columns"], actual["columns"]
                if not (isinstance(want, dict) and isinstance(have, dict)):
                    raise TypeError("columns are described as dicts")
                for column in sorted(set(want) | set(have)):
                    if want.get(column) != have.get(column):
                        found.append(
                            f"{table.name}.{column}: seed expects {want.get(column)}, "
                            f"database has {have.get(column)}"
                        )
            else:
                found.append(
                    f"{table.name} {key}: seed expects {expected[key]}, database has {actual[key]}"
                )
    return found


async def schema_problems(connection: AsyncConnection, metadata: MetaData) -> list[str]:
    return await connection.run_sync(problems_in, metadata)
