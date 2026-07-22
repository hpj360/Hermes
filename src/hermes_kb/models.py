"""SQLModel 数据模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


def _gen_doc_id() -> str:
    return f"doc_{uuid4().hex[:12]}"


def _utcnow() -> datetime:
    """统一的 UTC 当前时间工厂（timezone-aware）。

    替代已废弃的 datetime.utcnow()，避免 Python 3.14+ DeprecationWarning。
    """
    return datetime.now(timezone.utc)


class Document(SQLModel, table=True):
    """文档。"""

    doc_id: str = Field(default_factory=_gen_doc_id, primary_key=True, max_length=64)
    title: str = Field(index=True, max_length=200)
    content: str = Field(default="", sa_column=Column("content", Text))
    source_type: str = Field(default="local", max_length=32)  # local / upload / seed
    file_type: str = Field(default="txt", max_length=16)  # txt / md / pdf
    source_path: str | None = Field(default=None, max_length=512)
    chunk_count: int = Field(default=0)
    category: str = Field(default="", max_length=32, index=True)  # M2-06：分类（单选）
    created_at: datetime = Field(default_factory=_utcnow)


class Chunk(SQLModel, table=True):
    """文档分片。"""

    id: int | None = Field(default=None, primary_key=True)
    doc_id: str = Field(index=True, max_length=64)
    idx: int = Field(default=0)
    text: str = Field(default="", sa_column=Column("text", Text))
    char_start: int = Field(default=0)
    char_end: int = Field(default=0)
    created_at: datetime = Field(default_factory=_utcnow)


class Tag(SQLModel, table=True):
    """M2-06：标签。"""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=32, unique=True)
    color: str = Field(default="#6b7280", max_length=16)  # hex 颜色
    created_at: datetime = Field(default_factory=_utcnow)


class DocumentTag(SQLModel, table=True):
    """M2-06：文档-标签关联（多对多）。"""

    id: int | None = Field(default=None, primary_key=True)
    doc_id: str = Field(index=True, max_length=64)
    tag_id: int = Field(index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class QueryLog(SQLModel, table=True):
    """问答日志。"""

    id: int | None = Field(default=None, primary_key=True)
    query: str = Field(max_length=2000)
    answer: str = Field(default="", sa_column=Column("answer", Text))
    citations: str = Field(
        default="[]", sa_column=Column("citations", Text)
    )  # JSON
    model_used: str = Field(default="mock", max_length=64)
    latency_ms: int = Field(default=0)
    feedback: int = Field(default=0)  # 1=up / -1=down / 0=none
    created_at: datetime = Field(default_factory=_utcnow, index=True)


# M2-06 预设分类
PRESET_CATEGORIES = [
    "烈酒",
    "葡萄酒",
    "啤酒",
    "中国白酒",
    "利口酒",
    "资料",
    "其他",
]


class RecipeStats(SQLModel, table=True):
    """M3：配方使用统计。"""

    doc_id: str = Field(primary_key=True, max_length=64)
    match_count: int = Field(default=0)  # 被匹配命中次数
    view_count: int = Field(default=0)  # 被点击查看次数
    last_matched_at: datetime | None = Field(default=None)
    last_viewed_at: datetime | None = Field(default=None)


class IngredientSubstitute(SQLModel, table=True):
    """M3：材料替代关系（L2 用户自定义 + L1 预置镜像）。"""

    id: int | None = Field(default=None, primary_key=True)
    canonical: str = Field(index=True, max_length=64)  # 原材料标准名
    substitute: str = Field(max_length=64)  # 替代材料名
    source: str = Field(default="preset", max_length=16)  # preset | user
    created_at: datetime = Field(default_factory=_utcnow)
