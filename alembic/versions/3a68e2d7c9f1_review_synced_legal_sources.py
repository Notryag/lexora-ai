"""review synced legal sources

Revision ID: 3a68e2d7c9f1
Revises: c4e1196f8a02
Create Date: 2026-08-08 18:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "3a68e2d7c9f1"
down_revision: Union[str, Sequence[str], None] = "c4e1196f8a02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "legal_sources",
        sa.Column(
            "review_status",
            sa.String(length=32),
            server_default="approved",
            nullable=False,
        ),
    )
    op.alter_column(
        "legal_sources", "verified_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )
    op.create_check_constraint(
        "ck_legal_source_review_status",
        "legal_sources",
        "review_status IN ('pending', 'approved', 'rejected')",
    )
    op.drop_index("ix_legal_sources_status_title", table_name="legal_sources")
    op.create_index(
        "ix_legal_sources_retrieval",
        "legal_sources",
        ["status", "review_status", "title"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_legal_sources_retrieval", table_name="legal_sources")
    op.create_index(
        "ix_legal_sources_status_title",
        "legal_sources",
        ["status", "title"],
        unique=False,
    )
    op.drop_constraint("ck_legal_source_review_status", "legal_sources", type_="check")
    op.execute("UPDATE legal_sources SET verified_at = created_at WHERE verified_at IS NULL")
    op.alter_column(
        "legal_sources", "verified_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
    op.drop_column("legal_sources", "review_status")
