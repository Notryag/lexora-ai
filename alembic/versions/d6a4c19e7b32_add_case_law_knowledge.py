"""add case law knowledge

Revision ID: d6a4c19e7b32
Revises: c7e1a4b6d2f0
Create Date: 2026-08-09 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "d6a4c19e7b32"
down_revision: Union[str, Sequence[str], None] = "c7e1a4b6d2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "case_law_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_number", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("issuing_authority", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'withdrawn')", name="ck_case_law_status"),
        sa.CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')",
            name="ck_case_law_review_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_url", "content_sha256", name="uq_case_law_url_content"),
    )
    op.create_index(
        "ix_case_law_retrieval",
        "case_law_sources",
        ["status", "review_status", "case_number"],
        unique=False,
    )
    op.create_table(
        "case_law_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("section_label", sa.String(length=80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["case_law_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference", name="uq_case_law_chunks_reference"),
        sa.UniqueConstraint("source_id", "chunk_index", name="uq_case_law_chunks_index"),
    )
    op.create_index(
        "ix_case_law_chunks_source",
        "case_law_chunks",
        ["source_id", "chunk_index"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_case_law_chunks_source", table_name="case_law_chunks")
    op.drop_table("case_law_chunks")
    op.drop_index("ix_case_law_retrieval", table_name="case_law_sources")
    op.drop_table("case_law_sources")
