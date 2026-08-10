from __future__ import annotations

import pytest

from lexora_ai.db.schema_ownership import (
    NORTH_OWNED_TABLES,
    include_lexora_schema_name,
)


@pytest.mark.parametrize("table_name", sorted(NORTH_OWNED_TABLES))
def test_north_owned_tables_are_excluded_from_lexora_schema_comparison(
    table_name: str,
) -> None:
    assert not include_lexora_schema_name(
        table_name,
        "table",
        {"schema_name": None},
    )


def test_lexora_tables_remain_in_schema_comparison() -> None:
    assert include_lexora_schema_name(
        "legal_cases",
        "table",
        {"schema_name": None},
    )


def test_filter_does_not_hide_non_table_objects() -> None:
    assert include_lexora_schema_name(
        "checkpoints",
        "index",
        {"table_name": "legal_cases"},
    )
