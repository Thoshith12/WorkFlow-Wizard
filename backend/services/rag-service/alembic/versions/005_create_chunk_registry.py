"""Create chunk_registry table.

Revision ID: 005_create_chunk_registry
Revises: 004_refactor_document_registry
Create Date: 2026-07-07

Creates the chunk_registry table which tracks every text chunk produced
by the chunking pipeline through its full lifecycle:
    initiated → chunking → embedding → embeddings_generated
             → vector_store_successful | failed
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005_create_chunk_registry"
down_revision: Union[str, None] = "004_refactor_document_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chunk_registry",
        # ── Primary key ───────────────────────────────────────────────────────
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),

        # ── Parent references ─────────────────────────────────────────────────
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("data_source_registry.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "data_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("data_source_registry.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_registry.id", ondelete="CASCADE"),
            nullable=False,
        ),

        # ── Chunk content ─────────────────────────────────────────────────────
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_language", sa.String(10), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),

        # ── Config snapshot ───────────────────────────────────────────────────
        sa.Column(
            "config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),

        # ── Embedding & vector store ──────────────────────────────────────────
        sa.Column("embedding_model", sa.String(255), nullable=True),
        sa.Column("vector_collection", sa.String(255), nullable=True),

        # ── Lifecycle ─────────────────────────────────────────────────────────
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'initiated'"),
        ),
        sa.Column("error", sa.Text(), nullable=True),

        # ── Timestamps ────────────────────────────────────────────────────────
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    op.create_index("ix_chunk_registry_job_id",        "chunk_registry", ["job_id"])
    op.create_index("ix_chunk_registry_data_source_id","chunk_registry", ["data_source_id"])
    op.create_index("ix_chunk_registry_document_id",   "chunk_registry", ["document_id"])
    op.create_index("ix_chunk_registry_status",        "chunk_registry", ["status"])
    op.create_index("ix_chunk_registry_chunk_index",   "chunk_registry", ["chunk_index"])


def downgrade() -> None:
    op.drop_index("ix_chunk_registry_chunk_index",    table_name="chunk_registry")
    op.drop_index("ix_chunk_registry_status",         table_name="chunk_registry")
    op.drop_index("ix_chunk_registry_document_id",    table_name="chunk_registry")
    op.drop_index("ix_chunk_registry_data_source_id", table_name="chunk_registry")
    op.drop_index("ix_chunk_registry_job_id",         table_name="chunk_registry")
    op.drop_table("chunk_registry")
