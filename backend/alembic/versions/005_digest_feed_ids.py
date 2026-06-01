"""digest per-policy feed selection: digest_policy.feed_ids

Revision ID: 005
Revises: 004
Create Date: 2026-06-01

Additive: one nullable JSON column on digest_policy (null/empty = all feeds).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('digest_policy', sa.Column('feed_ids', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('digest_policy', 'feed_ids')
