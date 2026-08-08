"""create legal knowledge base

Revision ID: c4e1196f8a02
Revises: b7d42a818d31
Create Date: 2026-08-08 17:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "c4e1196f8a02"
down_revision: Union[str, Sequence[str], None] = "b7d42a818d31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "legal_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("issuing_authority", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("effective_on", sa.Date(), nullable=True),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=False),
        sa.Column("version_label", sa.String(length=200), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('effective', 'amended', 'repealed', 'not_effective')",
            name="ck_legal_source_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_url",
            "content_sha256",
            name="uq_legal_sources_url_content",
        ),
    )
    op.create_index(
        "ix_legal_sources_status_title",
        "legal_sources",
        ["status", "title"],
        unique=False,
    )
    op.create_table(
        "legal_source_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("article_label", sa.String(length=80), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["legal_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference", name="uq_legal_source_chunks_reference"),
        sa.UniqueConstraint(
            "source_id",
            "chunk_index",
            name="uq_legal_source_chunks_index",
        ),
    )
    op.create_index(
        "ix_legal_source_chunks_source",
        "legal_source_chunks",
        ["source_id", "chunk_index"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_legal_source_chunks_source", table_name="legal_source_chunks")
    op.drop_table("legal_source_chunks")
    op.drop_index("ix_legal_sources_status_title", table_name="legal_sources")
    op.drop_table("legal_sources")
