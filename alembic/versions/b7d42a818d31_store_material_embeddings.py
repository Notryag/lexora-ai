"""store material embeddings

Revision ID: b7d42a818d31
Revises: 91c25e941f6a
Create Date: 2026-08-08 16:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "b7d42a818d31"
down_revision: Union[str, Sequence[str], None] = "91c25e941f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("case_material_chunks", sa.Column("embedding", Vector(), nullable=True))
    op.add_column(
        "case_material_chunks",
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("case_material_chunks", "embedding_model")
    op.drop_column("case_material_chunks", "embedding")
