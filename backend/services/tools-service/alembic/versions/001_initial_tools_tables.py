"""Create custom_tool_registry and execution_log tables

Revision ID: 001_initial_tools_tables
Revises:
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_tools_tables'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. custom_tool_registry table ─────────────────────────────────────────
    op.create_table(
        'custom_tool_registry',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('version', sa.String(length=50), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('preprocessing_code', sa.Text(), nullable=True),
        sa.Column('processing_code', sa.Text(), nullable=False),
        sa.Column('postprocessing_code', sa.Text(), nullable=True),
        sa.Column('input_schema', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('output_schema', postgresql.JSONB(), nullable=True),
        sa.Column('usage_examples', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('imports', postgresql.ARRAY(sa.String()), server_default=sa.text("ARRAY[]::varchar[]"), nullable=False),
        sa.Column('requirements', postgresql.ARRAY(sa.String()), server_default=sa.text("ARRAY[]::varchar[]"), nullable=False),
        sa.Column('venv_hash', sa.String(length=64), nullable=True),
        sa.Column('config', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('tags', postgresql.ARRAY(sa.String()), server_default=sa.text("ARRAY[]::varchar[]"), nullable=False),
        sa.Column('capabilities', postgresql.ARRAY(sa.String()), server_default=sa.text("ARRAY[]::varchar[]"), nullable=False),
        sa.Column('status', sa.String(length=50), server_default=sa.text("'active'"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'version', name='uq_custom_tool_name_version'),
    )
    op.create_index(op.f('ix_custom_tool_registry_name'), 'custom_tool_registry', ['name'], unique=False)
    op.create_index(op.f('ix_custom_tool_registry_owner_id'), 'custom_tool_registry', ['owner_id'], unique=False)
    op.create_index(op.f('ix_custom_tool_registry_status'), 'custom_tool_registry', ['status'], unique=False)

    # ── 2. execution_log table ────────────────────────────────────────────────
    op.create_table(
        'execution_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tool_name', sa.String(length=255), nullable=False),
        sa.Column('tool_version', sa.String(length=50), nullable=False),
        sa.Column('tool_type', sa.String(length=50), nullable=False),
        sa.Column('executed_by', sa.String(length=255), nullable=False),
        sa.Column('input_payload', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('output_payload', postgresql.JSONB(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_execution_log_tool_name'), 'execution_log', ['tool_name'], unique=False)
    op.create_index(op.f('ix_execution_log_executed_by'), 'execution_log', ['executed_by'], unique=False)
    op.create_index(op.f('ix_execution_log_status'), 'execution_log', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_execution_log_status'), table_name='execution_log')
    op.drop_index(op.f('ix_execution_log_executed_by'), table_name='execution_log')
    op.drop_index(op.f('ix_execution_log_tool_name'), table_name='execution_log')
    op.drop_table('execution_log')
    op.drop_index(op.f('ix_custom_tool_registry_status'), table_name='custom_tool_registry')
    op.drop_index(op.f('ix_custom_tool_registry_owner_id'), table_name='custom_tool_registry')
    op.drop_index(op.f('ix_custom_tool_registry_name'), table_name='custom_tool_registry')
    op.drop_table('custom_tool_registry')
