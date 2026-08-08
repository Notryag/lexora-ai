"""add legal chunk hierarchy

Revision ID: 8f4b3de291a0
Revises: 3a68e2d7c9f1
Create Date: 2026-08-08 18:55:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8f4b3de291a0"
down_revision: Union[str, Sequence[str], None] = "3a68e2d7c9f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "legal_source_chunks",
        sa.Column(
            "heading_path",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("legal_source_chunks", "heading_path")
