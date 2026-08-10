"""Alembic ownership filter for tables managed by lower-level runtimes."""

NORTH_OWNED_TABLES = frozenset(
    {
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoint_migrations",
    }
)


def include_lexora_schema_name(
    name: str | None,
    type_: str,
    parent_names: dict[str, str | None],
) -> bool:
    del parent_names
    return not (type_ == "table" and name in NORTH_OWNED_TABLES)
