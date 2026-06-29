"""Create data_source_registry and document_registry tables

Revision ID: 001_create_rag_registries
Revises: 
Create Date: 2026-06-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_create_rag_registries'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. data_source_registry table ──────────────────────────────────────────
    op.create_table(
        'data_source_registry',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('config', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_data_source_registry_name'), 'data_source_registry', ['name'], unique=True)

    # ── 2. document_registry table ─────────────────────────────────────────────
    op.create_table(
        'document_registry',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('data_source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('file_name', sa.String(length=512), nullable=False),
        sa.Column('language_detected', sa.String(length=10), nullable=True),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('config', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['data_source_id'], ['data_source_registry.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_registry_data_source_id'), 'document_registry', ['data_source_id'], unique=False)
    op.create_index(op.f('ix_document_registry_status'), 'document_registry', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_document_registry_status'), table_name='document_registry')
    op.drop_index(op.f('ix_document_registry_data_source_id'), table_name='document_registry')
    op.drop_table('document_registry')
    op.drop_index(op.f('ix_data_source_registry_name'), table_name='data_source_registry')
    op.drop_table('data_source_registry')
