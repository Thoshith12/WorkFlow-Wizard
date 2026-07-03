"""Add status and error fields

Revision ID: 002_add_status_and_error_fields
Revises: 001_create_rag_registries
Create Date: 2026-06-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002_add_status_and_error_fields'
down_revision: Union[str, None] = '001_create_rag_registries'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update document_registry status length and add error column
    op.alter_column('document_registry', 'status',
               existing_type=sa.String(length=20),
               type_=sa.String(length=50),
               existing_nullable=False)
    op.add_column('document_registry', sa.Column('error', sa.Text(), nullable=True))

    # 2. Add status and error columns to data_source_registry
    op.add_column('data_source_registry', sa.Column('status', sa.String(length=50), server_default=sa.text("'pending'"), nullable=False))
    op.add_column('data_source_registry', sa.Column('error', sa.Text(), nullable=True))
    op.create_index(op.f('ix_data_source_registry_status'), 'data_source_registry', ['status'], unique=False)


def downgrade() -> None:
    # 1. Drop columns and index from data_source_registry
    op.drop_index(op.f('ix_data_source_registry_status'), table_name='data_source_registry')
    op.drop_column('data_source_registry', 'error')
    op.drop_column('data_source_registry', 'status')

    # 2. Revert document_registry status length and drop error column
    op.drop_column('document_registry', 'error')
    op.alter_column('document_registry', 'status',
               existing_type=sa.String(length=50),
               type_=sa.String(length=20),
               existing_nullable=False)
