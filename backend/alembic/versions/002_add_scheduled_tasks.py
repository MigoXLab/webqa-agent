"""Add scheduled_tasks table.

Revision ID: 002_add_scheduled_tasks
Revises: 001_initial_consolidated
Create Date: 2026-02-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_add_scheduled_tasks'
down_revision: Union[str, None] = '001_initial_consolidated'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create scheduled_tasks table
    op.create_table(
        'scheduled_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('businesses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('environment_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('environments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('test_case_ids', postgresql.JSONB, nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('workers', sa.Integer, nullable=False, server_default='1'),
        sa.Column('cron_expression', sa.String(100), nullable=False),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create indexes
    op.create_index('ix_scheduled_tasks_business_id', 'scheduled_tasks', ['business_id'])
    op.create_index('ix_scheduled_tasks_enabled', 'scheduled_tasks', ['enabled'])
    op.create_index('ix_scheduled_tasks_next_run_at', 'scheduled_tasks', ['next_run_at'])


def downgrade() -> None:
    op.drop_index('ix_scheduled_tasks_next_run_at', 'scheduled_tasks')
    op.drop_index('ix_scheduled_tasks_enabled', 'scheduled_tasks')
    op.drop_index('ix_scheduled_tasks_business_id', 'scheduled_tasks')
    op.drop_table('scheduled_tasks')
