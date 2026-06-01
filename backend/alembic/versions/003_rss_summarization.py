"""rss summarization: prompts, briefings, per-item AI summary

Revision ID: 003
Revises: a22574149180
Create Date: 2026-06-01

Additive only: new tables rss_prompt + rss_briefing, new columns on rss_feed
and rss_item. Non-null new columns on existing tables carry a server_default
so the ALTER is metadata-only (no table rewrite).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '003'
down_revision: Union[str, None] = 'a22574149180'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- rss_prompt ---
    op.create_table(
        'rss_prompt',
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('prompt_type', sa.String(length=30), server_default='item_summary', nullable=False),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- rss_briefing ---
    op.create_table(
        'rss_briefing',
        sa.Column('feed_id', sa.UUID(), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('model', sa.String(length=200), nullable=True),
        sa.Column('prompt_id', sa.UUID(), nullable=True),
        sa.Column('prompt_version', sa.Integer(), nullable=True),
        sa.Column('item_count', sa.Integer(), nullable=True),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['feed_id'], ['rss_feed.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['prompt_id'], ['rss_prompt.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- rss_feed new columns ---
    op.add_column('rss_feed', sa.Column('auto_summarize_items', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('rss_feed', sa.Column('auto_briefing', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('rss_feed', sa.Column('item_summary_prompt_id', sa.UUID(), nullable=True))
    op.add_column('rss_feed', sa.Column('briefing_prompt_id', sa.UUID(), nullable=True))
    op.add_column('rss_feed', sa.Column('summary_model', sa.String(length=200), nullable=True))
    op.add_column('rss_feed', sa.Column('briefing_count', sa.Integer(), server_default='10', nullable=False))
    op.add_column('rss_feed', sa.Column('last_briefing_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key('fk_rss_feed_item_summary_prompt', 'rss_feed', 'rss_prompt', ['item_summary_prompt_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_rss_feed_briefing_prompt', 'rss_feed', 'rss_prompt', ['briefing_prompt_id'], ['id'], ondelete='SET NULL')

    # --- rss_item new columns ---
    op.add_column('rss_item', sa.Column('ai_summary', sa.Text(), nullable=True))
    op.add_column('rss_item', sa.Column('ai_summary_model', sa.String(length=200), nullable=True))
    op.add_column('rss_item', sa.Column('ai_summary_prompt_id', sa.UUID(), nullable=True))
    op.add_column('rss_item', sa.Column('ai_summary_prompt_version', sa.Integer(), nullable=True))
    op.add_column('rss_item', sa.Column('ai_summarized_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('rss_item', sa.Column('summary_status', sa.String(length=20), server_default='none', nullable=False))
    op.add_column('rss_item', sa.Column('summary_error', sa.Text(), nullable=True))
    op.create_foreign_key('fk_rss_item_ai_summary_prompt', 'rss_item', 'rss_prompt', ['ai_summary_prompt_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_rss_item_ai_summary_prompt', 'rss_item', type_='foreignkey')
    for col in ('summary_error', 'summary_status', 'ai_summarized_at', 'ai_summary_prompt_version',
                'ai_summary_prompt_id', 'ai_summary_model', 'ai_summary'):
        op.drop_column('rss_item', col)

    op.drop_constraint('fk_rss_feed_briefing_prompt', 'rss_feed', type_='foreignkey')
    op.drop_constraint('fk_rss_feed_item_summary_prompt', 'rss_feed', type_='foreignkey')
    for col in ('last_briefing_at', 'briefing_count', 'summary_model', 'briefing_prompt_id',
                'item_summary_prompt_id', 'auto_briefing', 'auto_summarize_items'):
        op.drop_column('rss_feed', col)

    op.drop_table('rss_briefing')
    op.drop_table('rss_prompt')
