"""Add pipeline_status, languages, errors columns to document_registry

Revision ID: 003_add_preprocessing_columns
Revises: 002_add_status_and_error_fields
Create Date: 2026-07-03

Adds three new columns to document_registry to support the preprocessing
pipeline stage:

  - pipeline_status: per-stage status string (extraction initiated,
                     extraction completed, preprocessing initiated,
                     preprocessing completed, rejected, failed)
  - languages:       JSONB array of ISO 639-1 codes detected by fasttext
                     e.g. ["en", "fr"]
  - errors:          JSONB blob with stage-namespaced error entries
                     e.g. {"extraction_error": "...",
                           "preprocessing_error": [{"page_number": 2, "reason": "..."}]}

The existing `status`, `language_detected`, and `error` columns are kept
untouched for backwards compatibility.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003_add_preprocessing_columns'
down_revision: Union[str, None] = '002_add_status_and_error_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add pipeline_status column with index
    op.add_column(
        'document_registry',
        sa.Column(
            'pipeline_status',
            sa.String(length=50),
            nullable=True,
        )
    )
    op.create_index(
        op.f('ix_document_registry_pipeline_status'),
        'document_registry',
        ['pipeline_status'],
        unique=False,
    )

    # 2. Add languages JSONB column (default empty array)
    op.add_column(
        'document_registry',
        sa.Column(
            'languages',
            postgresql.JSONB(),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        )
    )

    # 3. Add errors JSONB column (default empty object)
    op.add_column(
        'document_registry',
        sa.Column(
            'errors',
            postgresql.JSONB(),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
        )
    )


def downgrade() -> None:
    op.drop_column('document_registry', 'errors')
    op.drop_column('document_registry', 'languages')
    op.drop_index(
        op.f('ix_document_registry_pipeline_status'),
        table_name='document_registry',
    )
    op.drop_column('document_registry', 'pipeline_status')
