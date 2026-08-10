"""Store the committed LangGraph runtime thread pointer.

Revision ID: f1a8c4d92e73
Revises: e5c7a9d21b40
Create Date: 2026-08-10 16:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a8c4d92e73"
down_revision: str | Sequence[str] | None = "e5c7a9d21b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_threads",
        sa.Column("runtime_thread_id", sa.Uuid(), nullable=True),
    )
    op.execute(
        """
        UPDATE conversation_threads
        SET runtime_thread_id = runtime_checkpoint_ns::uuid
        WHERE runtime_checkpoint_ns IS NOT NULL
        """
    )
    op.drop_column("conversation_threads", "runtime_checkpoint_ns")


def downgrade() -> None:
    op.add_column(
        "conversation_threads",
        sa.Column("runtime_checkpoint_ns", sa.String(240), nullable=True),
    )
    op.execute(
        """
        UPDATE conversation_threads
        SET runtime_checkpoint_ns = runtime_thread_id::text
        WHERE runtime_thread_id IS NOT NULL
        """
    )
    op.drop_column("conversation_threads", "runtime_thread_id")
