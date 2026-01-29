"""Initial consolidated migration.

Revision ID: 001_initial_consolidated
Revises:
Create Date: 2026-01-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_consolidated'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create businesses table
    op.create_table(
        'businesses',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), unique=True, nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create environments table
    op.create_table(
        'environments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('businesses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('url', sa.String(500), nullable=False),
        sa.Column('browser_config', postgresql.JSONB, nullable=True),
        sa.Column('ignore_rules', postgresql.JSONB, nullable=True),
        sa.Column('auth_type', sa.String(20), nullable=False, server_default='none'),
        sa.Column('sso_username', sa.String(200), nullable=True),
        sa.Column('sso_password', sa.String(200), nullable=True),
        sa.Column('cookies', postgresql.JSONB, nullable=True),
        sa.Column('sso_env', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create test_cases table
    op.create_table(
        'test_cases',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('businesses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('login_required', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('steps', postgresql.JSONB, nullable=False),
        sa.Column('snapshot', sa.String(100), nullable=True),
        sa.Column('use_snapshot', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create executions table
    op.create_table(
        'executions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('businesses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('environment_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('environments.id', ondelete='SET NULL'), nullable=True),
        sa.Column('trigger_type', sa.String(20), nullable=False, server_default='manual'),
        sa.Column('scheduled_task_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('workers', sa.Integer, nullable=False, server_default='1'),
        sa.Column('test_case_ids', postgresql.JSONB, nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('oss_report_url', sa.String(1000), nullable=True),
        sa.Column('local_report_path', sa.String(500), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('results', postgresql.JSONB, nullable=True),
        sa.Column('result_count', postgresql.JSONB, nullable=True),
    )

    # Create indexes
    op.create_index('ix_environments_business_id', 'environments', ['business_id'])
    op.create_index('ix_test_cases_business_id', 'test_cases', ['business_id'])
    op.create_index('ix_executions_business_id', 'executions', ['business_id'])
    op.create_index('ix_executions_status', 'executions', ['status'])


def downgrade() -> None:
    op.drop_table('executions')
    op.drop_table('test_cases')
    op.drop_table('environments')
    op.drop_table('businesses')
