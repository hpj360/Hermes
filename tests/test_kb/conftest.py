"""测试公共 fixture。

设计：
- tmp_db：每个测试用独立临时 SQLite 数据库，避免互相干扰
- reset_settings：每个测试重置 Settings 单例
- client：FastAPI TestClient（基于 create_app()）
- seeded_importer：已导入种子数据的 ImportService
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """每个测试用独立临时数据库。"""
    db_path = tmp_path / "test_kb.db"
    monkeypatch.setenv("KB_DB_PATH", str(db_path))
    # 重置单例
    from hermes_kb import database as db_mod

    db_mod._ENGINE = None
    from hermes_kb.config import reset_settings

    reset_settings()
    yield db_path
    # 测试后清理
    db_mod._ENGINE = None
    reset_settings()


@pytest.fixture
def client(tmp_db: Path):
    """FastAPI TestClient。

    自动确认年龄门，使受保护接口（/api/ask、/api/lab/*）在测试中可直接访问，
    避免每个测试重复 client.post("/api/age-gate/confirm")。
    年龄门本身的校验逻辑由 test_age_gate.py 覆盖。
    """
    from fastapi.testclient import TestClient

    from hermes_kb.app import create_app

    app = create_app()
    with TestClient(app) as c:
        c.post("/api/age-gate/confirm", json={"confirmed": True})
        yield c


@pytest.fixture
def seeded_importer(tmp_db: Path):
    """已导入种子数据的 ImportService。"""
    from hermes_kb.rag import ImportService
    from hermes_kb.seed import SEED_DOCS

    importer = ImportService()
    for doc in SEED_DOCS:
        importer.import_text(
            content=doc["content"],
            title=doc["title"],
            source_type="seed",
            file_type="md",
        )
    return importer
