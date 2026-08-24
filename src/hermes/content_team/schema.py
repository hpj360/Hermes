"""Idempotent additive schema upgrades for the content-team runtime."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection


async def upgrade_schema(connection: AsyncConnection) -> None:
    """Apply model changes that SQLAlchemy ``create_all`` cannot apply."""
    table_names = await connection.run_sync(
        lambda sync_connection: sa.inspect(sync_connection).get_table_names()
    )
    if "topics" not in table_names:
        return
    columns = await connection.run_sync(
        lambda sync_connection: sa.inspect(sync_connection).get_columns("topics")
    )
    if any(column["name"] == "keywords" for column in columns):
        return
    await connection.execute(
        sa.text("ALTER TABLE topics ADD COLUMN keywords JSON NOT NULL DEFAULT '[]'")
    )
