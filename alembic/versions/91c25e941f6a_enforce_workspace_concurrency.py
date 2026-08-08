"""enforce workspace concurrency

Revision ID: 91c25e941f6a
Revises: 304b32eb8a9e
Create Date: 2026-08-08 15:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "91c25e941f6a"
down_revision: Union[str, Sequence[str], None] = "304b32eb8a9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_case_materials_reference",
        "case_materials",
        ["case_id", "reference_index"],
    )
    op.create_index(
        "uq_agent_runs_active_thread",
        "agent_runs",
        ["owner_id", "thread_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_runs_active_thread", table_name="agent_runs")
    op.drop_constraint(
        "uq_case_materials_reference",
        "case_materials",
        type_="unique",
    )
