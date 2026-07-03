"""Refactor document_registry columns

Revision ID: 004_refactor_document_registry
Revises: 003_add_preprocessing_columns
Create Date: 2026-07-03

Refactors the document_registry table by cleaning up redundant columns:
  - Drops old `status` column
  - Drops old `error` column
  - Drops temporary `languages` column (from migration 003)
  - Recreates `language_detected` column as JSONB (to store language lists)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004_refactor_document_registry'
down_revision: Union[str, None] = '003_add_preprocessing_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop old status, error, and languages columns
    op.drop_column('document_registry', 'status')
    op.drop_column('document_registry', 'error')
    op.drop_column('document_registry', 'languages')

    # 2. Recreate language_detected as JSONB list/array
    op.drop_column('document_registry', 'language_detected')
    op.add_column(
        'document_registry',
        sa.Column(
            'language_detected',
            postgresql.JSONB(),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        )
    )


def downgrade() -> None:
    # Recreate language_detected as String(10)
    op.drop_column('document_registry', 'language_detected')
    op.add_column(
        'document_registry',
        sa.Column(
            'language_detected',
            sa.String(length=10),
            nullable=True,
        )
    )

    # Re-add status, error, and languages columns
    op.add_column(
        'document_registry',
        sa.Column(
            'status',
            sa.String(length=50),
            server_default=sa.text("'pending'"),
            nullable=False,
        )
    )
    op.create_index(
        'ix_document_registry_status',
        'document_registry',
        ['status'],
        unique=False,
    )
    op.add_column(
        'document_registry',
        sa.Column(
            'error',
            sa.Text(),
            nullable=True,
        )
    )
    op.add_column(
        'document_registry',
        sa.Column(
            'languages',
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        )
    )
