"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Connector
    op.create_table('connector',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('type', sa.String(50), nullable=False, unique=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column('icon', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('connector_instance',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('connector_type', sa.String(50), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('config_encrypted', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column('last_sync_at', sa.String(50), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('metadata_json', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Mail
    op.create_table('mail_account',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('display_name', sa.String(200), nullable=True),
        sa.Column('imap_host', sa.String(255), nullable=False),
        sa.Column('imap_port', sa.Integer(), default=993),
        sa.Column('imap_use_ssl', sa.Boolean(), default=True),
        sa.Column('smtp_host', sa.String(255), nullable=False),
        sa.Column('smtp_port', sa.Integer(), default=587),
        sa.Column('smtp_use_tls', sa.Boolean(), default=True),
        sa.Column('username', sa.String(255), nullable=False),
        sa.Column('password_encrypted', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column('last_sync_uid', sa.Integer(), default=0),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('mail_message',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mail_account.id'), nullable=False),
        sa.Column('message_id', sa.String(500), nullable=True),
        sa.Column('uid', sa.Integer(), nullable=False),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('from_address', sa.String(500), nullable=False),
        sa.Column('to_addresses', sa.Text(), nullable=True),
        sa.Column('cc_addresses', sa.Text(), nullable=True),
        sa.Column('date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('body_text', sa.Text(), nullable=True),
        sa.Column('body_html', sa.Text(), nullable=True),
        sa.Column('is_read', sa.Boolean(), default=False),
        sa.Column('is_flagged', sa.Boolean(), default=False),
        sa.Column('is_archived', sa.Boolean(), default=False),
        sa.Column('folder', sa.String(200), default='INBOX'),
        sa.Column('raw_headers', sa.Text(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_mail_message_account_uid', 'mail_message', ['account_id', 'uid'], unique=True)
    op.create_index('ix_mail_message_date', 'mail_message', ['date'])
    op.create_index('ix_mail_message_is_read', 'mail_message', ['is_read'])

    op.create_table('mail_attachment',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mail_message.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(500), nullable=True),
        sa.Column('content_type', sa.String(200), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('content_id', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('mail_link',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mail_message.id', ondelete='CASCADE'), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('domain', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Classification
    op.create_table('classification_rule',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('priority', sa.Integer(), default=0),
        sa.Column('conditions', postgresql.JSON(), nullable=True),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('mail_classification',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mail_message.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('confidence', sa.Float(), default=0.0),
        sa.Column('priority', sa.Integer(), default=0),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('action_required', sa.Boolean(), default=False),
        sa.Column('due_date', sa.String(50), nullable=True),
        sa.Column('tags', postgresql.JSON(), nullable=True),
        sa.Column('classified_by', sa.String(50), default='llm'),
        sa.Column('llm_model', sa.String(100), nullable=True),
        sa.Column('llm_prompt_version', sa.String(50), nullable=True),
        sa.Column('raw_llm_response', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Forwarding
    op.create_table('forwarding_policy',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source_category', sa.String(100), nullable=True),
        sa.Column('target_email', sa.String(255), nullable=False),
        sa.Column('conditions', postgresql.JSON(), nullable=True),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column('priority', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('forwarding_whitelist',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email_pattern', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('forwarding_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mail_message.id'), nullable=False),
        sa.Column('policy_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('forwarding_policy.id'), nullable=False),
        sa.Column('target_email', sa.String(255), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Digest
    op.create_table('digest_policy',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('schedule_cron', sa.String(100), nullable=False),
        sa.Column('target_email', sa.String(255), nullable=True),
        sa.Column('include_categories', postgresql.JSON(), nullable=True),
        sa.Column('exclude_categories', postgresql.JSON(), nullable=True),
        sa.Column('max_items', sa.Integer(), default=50),
        sa.Column('include_weather', sa.Boolean(), default=True),
        sa.Column('include_feeds', sa.Boolean(), default=True),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column('template', sa.String(100), default='default'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('digest_run',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('policy_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('digest_policy.id'), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('item_count', sa.Integer(), default=0),
        sa.Column('html_content', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('digest_section',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('digest_run.id', ondelete='CASCADE'), nullable=False),
        sa.Column('section_type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('order', sa.Integer(), default=0),
        sa.Column('metadata_json', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # RSS
    op.create_table('rss_feed',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('url', sa.Text(), nullable=False, unique=True),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column('fetch_interval_minutes', sa.Integer(), default=60),
        sa.Column('last_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('rss_item',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rss_feed.id', ondelete='CASCADE'), nullable=False),
        sa.Column('guid', sa.String(500), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('link', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('author', sa.String(200), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_read', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Weather
    op.create_table('weather_source',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('provider', sa.String(50), default='openmeteo'),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('weather_snapshot',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('source_name', sa.String(200), nullable=False),
        sa.Column('data', postgresql.JSON(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # LLM
    op.create_table('llm_provider_config',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('provider_type', sa.String(50), nullable=False),
        sa.Column('base_url', sa.String(500), nullable=False),
        sa.Column('api_key_encrypted', sa.Text(), nullable=True),
        sa.Column('default_model', sa.String(200), nullable=False),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column('extra_config', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('llm_task',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('task_type', sa.String(100), nullable=False),
        sa.Column('model', sa.String(200), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), default=0),
        sa.Column('completion_tokens', sa.Integer(), default=0),
        sa.Column('total_tokens', sa.Integer(), default=0),
        sa.Column('cost_usd', sa.Float(), default=0.0),
        sa.Column('duration_ms', sa.Integer(), default=0),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('input_preview', sa.Text(), nullable=True),
        sa.Column('output_preview', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('llm_prompt_version',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('task_type', sa.String(100), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('user_prompt_template', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Assistant
    op.create_table('assistant_conversation',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('user_id', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('assistant_message',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('assistant_conversation.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), default=0),
        sa.Column('metadata_json', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Audit
    op.create_table('audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(100), nullable=True),
        sa.Column('entity_id', sa.String(100), nullable=True),
        sa.Column('user', sa.String(200), nullable=True),
        sa.Column('details', postgresql.JSON(), nullable=True),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table('app_setting',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('key', sa.String(200), nullable=False, unique=True),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Seed default connectors
    op.execute("""
        INSERT INTO connector (id, type, name, description, enabled, icon, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'email', 'E-Mail (IMAP/SMTP)', 'Email accounts via IMAP and SMTP', true, 'mail', now(), now()),
            (gen_random_uuid(), 'rss', 'RSS Feed', 'RSS/Atom feed reader', true, 'rss', now(), now()),
            (gen_random_uuid(), 'weather', 'Weather (OpenMeteo)', 'Weather data from OpenMeteo API', true, 'cloud', now(), now())
    """)


def downgrade() -> None:
    tables = [
        'app_setting', 'audit_log',
        'assistant_message', 'assistant_conversation',
        'llm_prompt_version', 'llm_task', 'llm_provider_config',
        'weather_snapshot', 'weather_source',
        'rss_item', 'rss_feed',
        'digest_section', 'digest_run', 'digest_policy',
        'forwarding_log', 'forwarding_whitelist', 'forwarding_policy',
        'mail_classification', 'classification_rule',
        'mail_link', 'mail_attachment', 'mail_message', 'mail_account',
        'connector_instance', 'connector',
    ]
    for t in tables:
        op.drop_table(t)
