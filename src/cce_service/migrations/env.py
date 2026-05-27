"""Alembic environment for the CCE service Postgres schema.

Online-only (we don't ship offline SQL dumps): reads the DSN from the
``CCE_POSTGRES_DSN`` env var and runs the migrations in
``versions/`` against it. ClickHouse migrations are not managed here
— see ``clickhouse/0001_records.sql`` for the bootstrap SQL.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

# alembic.context.config is populated by `alembic` CLI.
config = context.config

# Allow either CCE_POSTGRES_DSN or alembic.ini[alembic].sqlalchemy.url
dsn = os.environ.get("CCE_POSTGRES_DSN")
if dsn:
    config.set_main_option("sqlalchemy.url", dsn)

target_metadata = None  # raw-SQL migrations only — no autogenerate.


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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
