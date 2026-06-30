"""mail search: pg_trgm GIN indexes for ILIKE acceleration

Revision ID: 006
Revises: 005
Create Date: 2026-06-30

Adds the pg_trgm extension and trigram GIN indexes on the four columns the
inbox full-text search runs ILIKE against (subject, from_address, to_addresses,
body_text). All four searched columns are indexed so the OR-block is fully
index-accelerated (a single unindexed OR branch would force a seq scan).

Additive / index-only. The migration uses plain (non-CONCURRENT) CREATE INDEX
IF NOT EXISTS: fine for disaster-recovery (empty table, no lock concern) and
re-run safe. On the live (non-empty) DB the indexes are created out-of-band with
CREATE INDEX CONCURRENTLY and this revision is then `alembic stamp`ed.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("subject", "from_address", "to_addresses", "body_text")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for col in _COLUMNS:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_mail_message_{col}_trgm "
            f"ON mail_message USING gin ({col} gin_trgm_ops)"
        )


def downgrade() -> None:
    for col in _COLUMNS:
        op.execute(f"DROP INDEX IF EXISTS ix_mail_message_{col}_trgm")
    # pg_trgm extension is left in place (may be used elsewhere).
