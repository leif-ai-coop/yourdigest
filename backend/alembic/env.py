import os
import sys
from logging.config import fileConfig
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy import create_engine

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.models import Base
target_metadata = Base.metadata

# Override URL from environment
database_url = os.environ.get("DATABASE_URL", "")
if database_url:
    # Alembic needs sync driver
    sync_url = database_url.replace("+asyncpg", "").replace("postgresql://", "postgresql+psycopg2://")
    if "psycopg2" not in sync_url and "postgresql://" in sync_url:
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://")
    # Simplest: just use psycopg2 or raw postgresql
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    config.set_main_option("sqlalchemy.url", sync_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
