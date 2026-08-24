from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from hermes.content_team.schema import upgrade_schema


@pytest.mark.asyncio
async def test_upgrade_schema_adds_keywords_to_legacy_topics() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                "CREATE TABLE topics (id VARCHAR(36) PRIMARY KEY, title VARCHAR(255) NOT NULL)"
            )
        )
        await upgrade_schema(connection)
        columns = await connection.run_sync(
            lambda sync_connection: sa.inspect(sync_connection).get_columns("topics")
        )
        assert any(column["name"] == "keywords" for column in columns)
        await upgrade_schema(connection)
    await engine.dispose()
