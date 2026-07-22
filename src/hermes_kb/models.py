"""SQLModel 数据模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, ForeignKey, Text
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
    # B1: 数据源治理字段（向后兼容，均有默认值）
    source: str = Field(default="local", max_length=32, index=True)  # local/iba/thecocktaildb/user/ugc
    source_id: str | None = Field(default=None, max_length=64)
    verified: bool = Field(default=True)
    season: str | None = Field(default=None, max_length=16)  # spring/summer/autumn/winter
    hidden: bool = Field(default=False)
    status: str = Field(default="published", max_length=16)  # draft/pending/published/rejected
    image_url: str | None = Field(default=None, max_length=512)  # B 新增：外部图片 URL
    # B 新增：JSON 字符串（存 ingredients 列表等结构化数据）。
    # 注意：SQLAlchemy 2.0 保留 "metadata" 属性名（Declarative API 硬保留），
    # 故 Python 字段用 `meta`，DB 列名仍为 `metadata`；通过 __init__ 别名 +
    # 类后挂载的 `metadata` property 暴露统一对外接口。
    meta: str = Field(default="{}", sa_column=Column("metadata", Text))
    created_at: datetime = Field(default_factory=_utcnow)

    def __init__(self, **data: object) -> None:
        # 允许 `metadata=` 构造参数，映射到实际字段 `meta`
        if "metadata" in data:
            data["meta"] = data.pop("metadata")
        super().__init__(**data)


# 类创建完成后挂载 `metadata` 只读 property（避开 SQLAlchemy 在类声明期对
# `metadata` 保留名的检查，同时不破坏 `cls.metadata` 在建表阶段返回 MetaData）。
def _get_metadata(self: "Document") -> str:
    return self.meta


Document.metadata = property(_get_metadata)  # type: ignore[assignment]


class Chunk(SQLModel, table=True):
    """文档分片。"""

    id: int | None = Field(default=None, primary_key=True)
    doc_id: str = Field(
        max_length=64,
        sa_column=Column("doc_id", Text, ForeignKey("document.doc_id", ondelete="CASCADE"), index=True),
    )
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
    doc_id: str = Field(
        max_length=64,
        sa_column=Column("doc_id", Text, ForeignKey("document.doc_id", ondelete="CASCADE"), index=True),
    )
    tag_id: int = Field(
        sa_column=Column("tag_id", ForeignKey("tag.id", ondelete="CASCADE"), index=True),
    )
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

    doc_id: str = Field(
        max_length=64,
        sa_column=Column("doc_id", Text, ForeignKey("document.doc_id", ondelete="CASCADE"), primary_key=True),
    )
    match_count: int = Field(default=0)  # 被匹配命中次数（累计）
    view_count: int = Field(default=0)  # 被点击查看次数
    weekly_match_count: int = Field(default=0)  # A4-1: 本周新增匹配数
    last_matched_at: datetime | None = Field(default=None)
    last_viewed_at: datetime | None = Field(default=None)


class IngredientSubstitute(SQLModel, table=True):
    """M3：材料替代关系（L2 用户自定义 + L1 预置镜像）。"""

    id: int | None = Field(default=None, primary_key=True)
    canonical: str = Field(index=True, max_length=64)  # 原材料标准名
    substitute: str = Field(max_length=64)  # 替代材料名
    source: str = Field(default="preset", max_length=16)  # preset | user
    created_at: datetime = Field(default_factory=_utcnow)


class MissingIngredientStats(SQLModel, table=True):
    """M4.1：缺失材料统计（材料维度，反向优化替代表）。"""

    canonical: str = Field(primary_key=True, max_length=64)
    missing_count: int = Field(default=0)
    last_missing_at: datetime | None = Field(default=None)


class RecipeVariant(SQLModel, table=True):
    """M4.3：配方变体关联。"""

    id: int | None = Field(default=None, primary_key=True)
    base_doc_id: str = Field(index=True, max_length=64)  # 原配方
    variant_doc_id: str = Field(index=True, max_length=64)  # 变体配方
    variant_note: str = Field(default="", max_length=200)  # 变体说明
    created_at: datetime = Field(default_factory=_utcnow)
