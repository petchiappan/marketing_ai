"""add agent_name to tool_configs

Revision ID: 2a3b4c5d6e7f
Revises:
Create Date: 2026-02-22
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '2a3b4c5d6e7f'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tool_configs', sa.Column('agent_name', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('tool_configs', 'agent_name')
