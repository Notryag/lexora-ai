"""add structured case profile

Revision ID: c7e1a4b6d2f0
Revises: 8f4b3de291a0
Create Date: 2026-08-08 20:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c7e1a4b6d2f0"
down_revision: Union[str, Sequence[str], None] = "8f4b3de291a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "legal_cases",
        sa.Column(
            "profile",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("legal_cases", "profile")
