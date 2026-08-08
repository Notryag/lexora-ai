"""index persisted material chunks

Revision ID: 304b32eb8a9e
Revises: f553c5ad03ea
Create Date: 2026-08-08 14:04:13.977436
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = '304b32eb8a9e'
down_revision: Union[str, Sequence[str], None] = 'f553c5ad03ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("case_materials", sa.Column("reference_index", sa.Integer(), nullable=True))
    op.execute(
        """
        WITH numbered AS (
            SELECT id, row_number() OVER (
                PARTITION BY case_id ORDER BY created_at, id
            ) AS reference_index
            FROM case_materials
        )
        UPDATE case_materials
        SET reference_index = numbered.reference_index
        FROM numbered
        WHERE case_materials.id = numbered.id
        """
    )
    op.alter_column("case_materials", "reference_index", nullable=False)
    op.create_table('case_material_chunks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('material_id', sa.Uuid(), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('reference', sa.String(length=32), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['legal_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['material_id'], ['case_materials.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'reference', name='uq_case_chunks_reference'),
    sa.UniqueConstraint('material_id', 'chunk_index', name='uq_material_chunks_index')
    )
    op.create_index('ix_case_material_chunks_case', 'case_material_chunks', ['owner_id', 'case_id'], unique=False)
    op.execute(
        """
        INSERT INTO case_material_chunks (
            id, case_id, material_id, owner_id, chunk_index, reference, content
        )
        SELECT
            gen_random_uuid(), case_id, id, owner_id, 1,
            'M' || reference_index || '\\:C1', content
        FROM case_materials
        """
    )


def downgrade() -> None:
    op.drop_index('ix_case_material_chunks_case', table_name='case_material_chunks')
    op.drop_table('case_material_chunks')
    op.drop_column('case_materials', 'reference_index')
