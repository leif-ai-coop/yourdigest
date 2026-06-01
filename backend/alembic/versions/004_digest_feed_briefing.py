"""digest per-feed AI briefing: feed_ai_briefing + feed_briefing_prompt

Revision ID: 004
Revises: 003
Create Date: 2026-06-01

Additive: two columns on digest_policy. feed_ai_briefing carries a server_default
so the ALTER is metadata-only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('digest_policy', sa.Column('feed_ai_briefing', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('digest_policy', sa.Column('feed_briefing_prompt', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('digest_policy', 'feed_briefing_prompt')
    op.drop_column('digest_policy', 'feed_ai_briefing')
