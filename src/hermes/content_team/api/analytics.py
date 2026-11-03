"""数据分析 API：指标查询、聚合摘要、手动采集与复盘。

端点：
- ``GET /api/analytics``                - 列表查询（支持 content_id/platform/日期范围过滤）
- ``GET /api/analytics/summary``        - 全局聚合摘要（支持日期范围过滤）
- ``GET /api/analytics/content/{id}``   - 单内容跨平台指标
- ``GET /api/analytics/content/{id}/summary`` - 单内容聚合摘要
- ``POST /api/analytics/collect``       - 手动触发批量采集
- ``POST /api/analytics/collect/{task_id}`` - 手动采集单个发布任务
- ``POST /api/analytics/manual``        - 人工回填指标快照（source="manual"，同键覆盖）
- ``GET  /api/analytics/retrospective`` - 周期复盘（对比上一周期 + Top 内容 + 来源构成）
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from typing_extensions import TypeVarTuple, Unpack

from hermes.content_team.analytics.collector import MetricsCollector
from hermes.content_team.db import get_db
from hermes.content_team.models.content import Content
from hermes.content_team.models.metrics import ContentMetric
from hermes.content_team.models.platform import Platform

# SQLAlchemy 的 Select 是变长泛型（列类型元组），过滤器不应改变列结构，
# 因此用 TypeVarTuple 原样透传，而不是把结果窄化成单一 Select[Any]。
_Ts = TypeVarTuple("_Ts")

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class MetricResponse(BaseModel):
    """单条指标快照响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content_id: UUID
    publish_task_id: UUID | None = None
    platform: Platform
    date: date
    views: int
    likes: int
    comments: int
    shares: int
    followers_gained: int
    followers_lost: int
    engagement_rate: float
    source: str = "simulation"
    created_at: datetime


class PlatformBreakdown(BaseModel):
    """单平台的聚合指标。"""

    views: int
    likes: int
    comments: int
    shares: int
    followers_gained: int
    followers_lost: int
    engagement_rate: float
    count: int


class MetricsSummary(BaseModel):
    """指标聚合摘要。"""

    content_id: UUID | None = None
    total_views: int
    total_likes: int
    total_comments: int
    total_shares: int
    total_followers_gained: int
    avg_engagement_rate: float
    by_platform: dict[str, PlatformBreakdown]


class MetricsFilter(BaseModel):
    """指标过滤条件（所有字段可选）。"""

    content_id: UUID | None = None
    platform: Platform | None = None
    start_date: date | None = None
    end_date: date | None = None


class ManualMetricRequest(BaseModel):
    """人工指标回填请求体（半自动数据回采：人工导出平台数据后录入）。"""

    content_id: UUID
    platform: Platform
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    followers_gained: int = Field(default=0, ge=0)
    followers_lost: int = Field(default=0, ge=0)
    publish_task_id: UUID | None = None
    snapshot_date: date | None = None  # 缺省为今日（UTC）；避名与 date 类型同名遮蔽


class ContentPerformance(BaseModel):
    """复盘用的单内容表现。"""

    content_id: UUID
    title: str
    views: int
    likes: int
    comments: int
    shares: int
    interactions: int
    engagement_rate: float


class RetrospectiveResponse(BaseModel):
    """周期复盘响应体。"""

    days: int
    start_date: date
    end_date: date
    period: MetricsSummary
    previous_period: MetricsSummary
    top_contents: list[ContentPerformance]
    source_counts: dict[str, int]


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _apply_filters(
    stmt: Select[Unpack[_Ts]],
    content_id: UUID | None,
    platform: Platform | None,
    start_date: date | None,
    end_date: date | None,
) -> Select[Unpack[_Ts]]:
    """在查询语句上叠加过滤条件。"""
    if content_id is not None:
        stmt = stmt.where(ContentMetric.content_id == content_id)
    if platform is not None:
        stmt = stmt.where(ContentMetric.platform == platform)
    if start_date is not None:
        stmt = stmt.where(ContentMetric.date >= start_date)
    if end_date is not None:
        stmt = stmt.where(ContentMetric.date <= end_date)
    return stmt


async def _build_summary(
    db: AsyncSession,
    *,
    content_id: UUID | None,
    platform: Platform | None,
    start_date: date | None,
    end_date: date | None,
) -> MetricsSummary:
    """根据过滤条件构建聚合摘要。"""
    # 总体聚合
    total_stmt = _apply_filters(
        select(
            func.coalesce(func.sum(ContentMetric.views), 0).label("total_views"),
            func.coalesce(func.sum(ContentMetric.likes), 0).label("total_likes"),
            func.coalesce(func.sum(ContentMetric.comments), 0).label(
                "total_comments"
            ),
            func.coalesce(func.sum(ContentMetric.shares), 0).label("total_shares"),
            func.coalesce(func.sum(ContentMetric.followers_gained), 0).label(
                "total_followers_gained"
            ),
            func.coalesce(func.avg(ContentMetric.engagement_rate), 0.0).label(
                "avg_engagement_rate"
            ),
        ),
        content_id,
        platform,
        start_date,
        end_date,
    )
    total_result = await db.execute(total_stmt)
    total_row = total_result.one()

    # 按平台聚合
    platform_stmt = _apply_filters(
        select(
            ContentMetric.platform,
            func.coalesce(func.sum(ContentMetric.views), 0).label("views"),
            func.coalesce(func.sum(ContentMetric.likes), 0).label("likes"),
            func.coalesce(func.sum(ContentMetric.comments), 0).label("comments"),
            func.coalesce(func.sum(ContentMetric.shares), 0).label("shares"),
            func.coalesce(func.sum(ContentMetric.followers_gained), 0).label(
                "followers_gained"
            ),
            func.coalesce(func.sum(ContentMetric.followers_lost), 0).label(
                "followers_lost"
            ),
            func.coalesce(func.avg(ContentMetric.engagement_rate), 0.0).label(
                "engagement_rate"
            ),
            func.count(ContentMetric.id).label("count"),
        ).group_by(ContentMetric.platform),
        content_id,
        platform,
        start_date,
        end_date,
    )
    platform_result = await db.execute(platform_stmt)
    by_platform: dict[str, PlatformBreakdown] = {}
    for row in platform_result.all():
        by_platform[row.platform.value] = PlatformBreakdown(
            views=row.views,
            likes=row.likes,
            comments=row.comments,
            shares=row.shares,
            followers_gained=row.followers_gained,
            followers_lost=row.followers_lost,
            engagement_rate=row.engagement_rate,
            count=int(getattr(row, "count")),
        )

    return MetricsSummary(
        content_id=content_id,
        total_views=total_row.total_views,
        total_likes=total_row.total_likes,
        total_comments=total_row.total_comments,
        total_shares=total_row.total_shares,
        total_followers_gained=total_row.total_followers_gained,
        avg_engagement_rate=total_row.avg_engagement_rate,
        by_platform=by_platform,
    )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.get("", response_model=list[MetricResponse])
async def list_metrics(
    content_id: UUID | None = None,
    platform: Platform | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[ContentMetric]:
    """列出指标快照，支持按内容/平台/日期范围过滤。"""
    stmt = _apply_filters(
        select(ContentMetric), content_id, platform, start_date, end_date
    ).order_by(ContentMetric.date.desc(), ContentMetric.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/summary", response_model=MetricsSummary)
async def get_metrics_summary(
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> MetricsSummary:
    """获取全局聚合摘要（可按日期范围过滤）。"""
    return await _build_summary(
        db,
        content_id=None,
        platform=None,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/content/{content_id}", response_model=list[MetricResponse])
async def get_content_metrics(
    content_id: UUID, db: AsyncSession = Depends(get_db)
) -> list[ContentMetric]:
    """获取指定内容在所有平台上的指标快照。"""
    stmt = (
        select(ContentMetric)
        .where(ContentMetric.content_id == content_id)
        .order_by(ContentMetric.date.desc(), ContentMetric.platform.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/content/{content_id}/summary", response_model=MetricsSummary)
async def get_content_summary(
    content_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> MetricsSummary:
    """获取指定内容的聚合摘要。"""
    return await _build_summary(
        db,
        content_id=content_id,
        platform=None,
        start_date=start_date,
        end_date=end_date,
    )


@router.post("/collect", response_model=dict)
async def trigger_collect_all(
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """手动触发批量指标采集，返回采集统计。"""
    collector = MetricsCollector(db_session=db)
    collected = await collector.collect_all()
    return {"collected": collected}


@router.post("/collect/{publish_task_id}", response_model=MetricResponse)
async def trigger_collect_single(
    publish_task_id: UUID, db: AsyncSession = Depends(get_db)
) -> ContentMetric:
    """手动采集单个发布任务的指标快照。"""
    collector = MetricsCollector(db_session=db)
    metric = await collector.collect_single(publish_task_id)
    if metric is None:
        raise HTTPException(
            status_code=404,
            detail="Publish task not found or metric snapshot already exists",
        )
    return metric


# ---------------------------------------------------------------------------
# 数据回路（数据驱动闭环 · Phase 3）：人工回填 + 周期复盘
# ---------------------------------------------------------------------------


@router.post("/manual", response_model=MetricResponse)
async def backfill_manual_metric(
    payload: ManualMetricRequest,
    db: AsyncSession = Depends(get_db),
) -> ContentMetric:
    """人工回填指标快照（数据回路 · 半自动回采）。

    平台无自动回采 API（如小红书/抖音）时，人工从平台后台导出数据后录入。
    ``source`` 标注为 ``manual``，与 adapter/simulation 数据显式区分。
    同一 (content_id, platform, date) 已有快照时覆盖更新（人工修正语义）。
    """
    content = await db.get(Content, payload.content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    snapshot_date = payload.snapshot_date or datetime.now(timezone.utc).date()
    engagement_rate = ContentMetric.compute_engagement_rate(
        payload.views, payload.likes, payload.comments, payload.shares
    )

    stmt = select(ContentMetric).where(
        ContentMetric.content_id == payload.content_id,
        ContentMetric.platform == payload.platform,
        ContentMetric.date == snapshot_date,
    )
    result = await db.execute(stmt)
    metric = result.scalar_one_or_none()

    if metric is None:
        metric = ContentMetric(
            content_id=payload.content_id,
            publish_task_id=payload.publish_task_id,
            platform=payload.platform,
            date=snapshot_date,
            views=payload.views,
            likes=payload.likes,
            comments=payload.comments,
            shares=payload.shares,
            followers_gained=payload.followers_gained,
            followers_lost=payload.followers_lost,
            engagement_rate=engagement_rate,
            source="manual",
        )
        db.add(metric)
    else:
        metric.views = payload.views
        metric.likes = payload.likes
        metric.comments = payload.comments
        metric.shares = payload.shares
        metric.followers_gained = payload.followers_gained
        metric.followers_lost = payload.followers_lost
        metric.engagement_rate = engagement_rate
        metric.source = "manual"
        if payload.publish_task_id is not None:
            metric.publish_task_id = payload.publish_task_id

    await db.commit()
    await db.refresh(metric)
    return metric

@router.get("/retrospective", response_model=RetrospectiveResponse)
async def get_retrospective(
    days: int = 7,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> RetrospectiveResponse:
    """周期复盘：本期 vs 上一期对比 + Top 内容 + 数据来源构成。

    - ``days``：复盘窗口长度（默认 7 天）
    - ``end_date``：窗口截止日（默认今日 UTC）
    - ``top_contents``：按总互动量（赞+评+传）降序取前 5
    - ``source_counts``：窗口内各来源（adapter/manual/simulation）快照数，
      供复盘时显式区分真实/人工/模拟数据
    """
    if days <= 0 or days > 90:
        raise HTTPException(status_code=400, detail="days 须在 1-90 之间")

    end = end_date or datetime.now(timezone.utc).date()
    start = date.fromordinal(end.toordinal() - days + 1)
    prev_end = date.fromordinal(start.toordinal() - 1)
    prev_start = date.fromordinal(prev_end.toordinal() - days + 1)

    period = await _build_summary(
        db, content_id=None, platform=None, start_date=start, end_date=end
    )
    previous = await _build_summary(
        db,
        content_id=None,
        platform=None,
        start_date=prev_start,
        end_date=prev_end,
    )

    # Top 内容（按互动量降序）
    interactions = (
        ContentMetric.likes + ContentMetric.comments + ContentMetric.shares
    )
    top_stmt = (
        select(
            Content.id.label("content_id"),
            Content.title.label("title"),
            func.coalesce(func.sum(ContentMetric.views), 0).label("views"),
            func.coalesce(func.sum(ContentMetric.likes), 0).label("likes"),
            func.coalesce(func.sum(ContentMetric.comments), 0).label("comments"),
            func.coalesce(func.sum(ContentMetric.shares), 0).label("shares"),
            func.coalesce(func.sum(interactions), 0).label("interactions"),
            func.coalesce(func.avg(ContentMetric.engagement_rate), 0.0).label(
                "engagement_rate"
            ),
        )
        .join(Content, Content.id == ContentMetric.content_id)
        .where(ContentMetric.date >= start, ContentMetric.date <= end)
        .group_by(Content.id, Content.title)
        .order_by(func.sum(interactions).desc())
        .limit(5)
    )
    top_result = await db.execute(top_stmt)
    top_contents = [
        ContentPerformance(
            content_id=row.content_id,
            title=row.title,
            views=row.views,
            likes=row.likes,
            comments=row.comments,
            shares=row.shares,
            interactions=int(row.interactions),
            engagement_rate=row.engagement_rate,
        )
        for row in top_result.all()
    ]

    # 数据来源构成
    src_stmt = (
        select(ContentMetric.source, func.count(ContentMetric.id))
        .where(ContentMetric.date >= start, ContentMetric.date <= end)
        .group_by(ContentMetric.source)
    )
    src_result = await db.execute(src_stmt)
    source_counts = {src: int(cnt) for src, cnt in src_result.all()}

    return RetrospectiveResponse(
        days=days,
        start_date=start,
        end_date=end,
        period=period,
        previous_period=previous,
        top_contents=top_contents,
        source_counts=source_counts,
    )


# ---------------------------------------------------------------------------
# OpenViking「会话沉淀为记忆」吸收（降格为半自动候选）
# ---------------------------------------------------------------------------


class RetrospectiveDistillRequest(BaseModel):
    """复盘沉淀请求体（同 retrospective 查询窗口）。"""

    days: int = 7
    end_date: date | None = None


class RetrospectiveDistillResponse(BaseModel):
    """复盘沉淀候选：md 草稿文本（不入库，人工确认后写入 knowledge/）。"""

    suggested_filename: str
    markdown: str
    verdicts: list[str]
    note: str


def _fmt_pct(cur: float, prev: float) -> str:
    """百分比变化文本（prev=0 时显示绝对差）。"""
    if prev == 0:
        return f"+{int(cur)}" if cur else "0"
    pct = (cur - prev) / prev * 100
    return f"{pct:+.1f}%"


def _distill_verdicts(retro: "RetrospectiveResponse") -> list[str]:
    """确定性启发式提炼（与 review-playbook 规则表一一对应）。"""
    v: list[str] = []
    period, prev = retro.period, retro.previous_period
    likes_delta = period.total_likes - prev.total_likes
    likes_delta_pct = (
        likes_delta / prev.total_likes if prev.total_likes else None
    )
    interactions = (
        period.total_likes + period.total_comments + period.total_shares
    )

    if likes_delta_pct is not None and likes_delta_pct > 0.1 and retro.top_contents:
        top = retro.top_contents[0]
        v.append(
            f"本期点赞↑{likes_delta_pct:.0%} 且 Top1 集中于「{top.title}」："
            "该篇结构疑似有效，回填 viral-structures 验证区"
        )
    if likes_delta_pct is not None and likes_delta_pct < -0.1:
        v.append(
            "本期点赞↓超过10%：优先检查 Top 内容的结构差异与掉量共性，"
            "而非铺新内容"
        )

    sim_total = sum(retro.source_counts.values())
    manual = retro.source_counts.get("manual", 0)
    adapter = retro.source_counts.get("adapter", 0)
    if sim_total and manual / sim_total > 0.8:
        v.append(
            f"来源以人工回填为主（manual {manual}/{sim_total}）："
            "回填覆盖优先于内容优化"
        )
    if sim_total and adapter / sim_total > 0.8:
        v.append(
            f"来源以真实回采为主（adapter {adapter}/{sim_total}）："
            "本周期数据可直接用于选题权重"
        )
    if interactions == 0:
        v.append("本期无任何互动数据：结论是「复盘无依据」，先修数据回路")

    if not v:
        v.append("本周期无可提炼信号（指标平稳或样本不足）")
    return v


@router.post(
    "/retrospective/distill", response_model=RetrospectiveDistillResponse
)
async def distill_retrospective(
    payload: RetrospectiveDistillRequest,
    db: AsyncSession = Depends(get_db),
) -> RetrospectiveDistillResponse:
    """把复盘数据生成知识条目候选 md（OpenViking 会话沉淀吸收，半自动）。

    确定性规则生成（不调 LLM），产物为候选文本 **不入库**：
    人确认后写入 ``knowledge/content-ops/``（半自动原则）。
    """
    from datetime import datetime, timezone as _tz

    # 复用同一查询逻辑
    end = payload.end_date or datetime.now(_tz.utc).date()
    start = date.fromordinal(end.toordinal() - payload.days + 1)

    retro = await get_retrospective(
        days=payload.days, end_date=payload.end_date, db=db
    )
    period, prev = retro.period, retro.previous_period
    verdicts = _distill_verdicts(retro)

    fname = f"review-{start.isoformat()}_{end.isoformat()}.candidate.md"
    md = (
        "---\n"
        f"title: 复盘沉淀 {start}~{end}\n"
        "summary: （人工确认后改写为一句可检索的 L0 摘要）\n"
        "overview: |\n"
        "  （人工确认后提炼 2-4 行 L1 概览：本周期发生了什么/启示）\n"
        "type: case-study\n"
        "---\n\n"
        f"# 复盘沉淀 {start}~{end}\n\n"
        f"- 本期浏览 {period.total_views}（vs 上期 {prev.total_views}，"
        f"{_fmt_pct(period.total_views, prev.total_views)}）\n"
        f"- 本期点赞 {period.total_likes}（{prev.total_likes}，"
        f"{_fmt_pct(period.total_likes, prev.total_likes)}）\n"
        f"- 来源构成 {retro.source_counts or '无数据'}\n\n"
        "## Top5 互动\n\n"
        + (
            "\n".join(
                f"- {t.title}：互动{t.interactions}（浏览{t.views}）"
                for t in retro.top_contents
            )
            or "（无）"
        )
        + "\n\n## 规则提炼候选\n\n"
        + "\n".join(f"- {v}" for v in verdicts)
        + "\n"
    )
    return RetrospectiveDistillResponse(
        suggested_filename=fname,
        markdown=md,
        verdicts=verdicts,
        note=(
            "候选由确定性规则生成（非 LLM），未写入知识库；"
            "人工确认/删改成明显结论后落入 knowledge/content-ops/。"
        ),
    )
