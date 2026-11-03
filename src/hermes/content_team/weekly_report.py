"""C1 自动周报：聚合周期复盘数据 → 飞书卡片文本（静默优先）。

纵向业务闭环的第一段自动输出：无活动不发（silent-first），有活动发一条；
发送失败进飞书死信表（复用 workbench Notifier 的 DeadLetterStore），不在
调度 worker 线程里崩溃（U9 通知策略的 weekly 版本）。

数据源是 ``api.analytics.get_retrospective``（同一套查询逻辑，保证端点与
周报一致）；通知层依赖仅指向 ``workbench.feishu_notify.Notifier``（依赖方向
保持 content_team → workbench 单向）。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from hermes.content_team.observability import log_event

__all__ = [
    "WeeklyReport",
    "build_weekly_report",
    "send_weekly_report",
]


@dataclass
class WeeklyReport:
    """本周复盘报告（生成后由 send_weekly_report 负责投递）。"""

    days: int
    start_date: date
    end_date: date
    views: int = 0
    views_prev: int = 0
    interactions: int = 0
    interactions_prev: int = 0
    followers_gained: int = 0
    followers_gained_prev: int = 0
    top_contents: list[dict[str, Any]] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)

    def is_silent(self) -> bool:
        """整个窗口无任何活动 → 静默（与 DailyBrief 同语义）。"""
        return (
            self.views == 0
            and self.interactions == 0
            and not self.top_contents
            and not self.source_counts
        )

    def _delta(self, cur: int, prev: int) -> str:
        if prev <= 0:
            return f"{cur}（上期无数据）"
        pct = (cur - prev) / prev * 100
        sign = "+" if pct >= 0 else ""
        return f"{cur}（{sign}{pct:.0f}% vs 上期）"

    def render_text(self) -> str:
        lines = [
            f"Hermes 本周复盘（近 {self.days} 天："
            f"{self.start_date.isoformat()} ~ {self.end_date.isoformat()}）",
            f"· 曝光: {self._delta(self.views, self.views_prev)}",
            f"· 互动(赞评传): {self._delta(self.interactions, self.interactions_prev)}",
            f"· 涨粉: {self._delta(self.followers_gained, self.followers_gained_prev)}",
        ]
        if self.top_contents:
            lines.append("· Top 内容:")
            for item in self.top_contents[:3]:
                lines.append(
                    f"  - {item['title']}（互动 {item['interactions']}）"
                )
        if self.source_counts:
            parts = [
                f"{src} {cnt}" for src, cnt in sorted(self.source_counts.items())
            ]
            lines.append(f"· 数据来源: {' / '.join(parts)}")
            if "simulation" in self.source_counts and not any(
                s in ("manual", "adapter") for s in self.source_counts
            ):
                lines.append("· ⚠️ 本期仅模拟数据——真实平台数据请人工导出后回填")
        return "\n".join(lines)


async def build_weekly_report(
    session: Any,
    days: int = 7,
    end_date: date | None = None,
) -> WeeklyReport:
    """用同一套复盘查询逻辑构建周报（排除 HTTPException 分支：days 已约束）。"""
    from datetime import datetime, timezone

    from hermes.content_team.api.analytics import get_retrospective

    end = end_date or datetime.now(timezone.utc).date()
    retro = await get_retrospective(
        days=days if days > 0 else 7, end_date=end, db=session
    )
    report = WeeklyReport(
        days=retro.days,
        start_date=retro.start_date,
        end_date=retro.end_date,
        views=retro.period.total_views,
        views_prev=retro.previous_period.total_views,
        interactions=(
            retro.period.total_likes
            + retro.period.total_comments
            + retro.period.total_shares
        ),
        interactions_prev=(
            retro.previous_period.total_likes
            + retro.previous_period.total_comments
            + retro.previous_period.total_shares
        ),
        followers_gained=retro.period.total_followers_gained,
        followers_gained_prev=retro.previous_period.total_followers_gained,
        top_contents=[
            {"title": performance.title, "interactions": performance.interactions}
            for performance in retro.top_contents
        ],
        source_counts=dict(retro.source_counts),
    )
    return report


async def send_weekly_report(notifier: Any, report: WeeklyReport) -> bool:
    """发送周报（静默优先）；失败记入死信（kind="weekly"）不抛异常。"""
    if report.is_silent():
        log_event("weekly_report_skipped", "本周无活动，周报静默不发")
        return False
    try:
        notifier.client.send_text(
            notifier.receive_id, report.render_text(), notifier.receive_id_type
        )
        return True
    except Exception as exc:  # noqa: BLE001 — 通知是尽力而为通道
        notifier.dead_letter.record("weekly", notifier.receive_id, "weekly report", str(exc))
        log_event("weekly_report_dead_letter", "周报发送失败进死信", error=str(exc))
        return False


def run_weekly_report_for_payload(days: int) -> dict[str, Any]:
    """同步入口：调度 worker 里由 runtime 分发调用（自行建会话/事件循环）。"""

    async def _impl() -> dict[str, Any]:
        from hermes.content_team.db import AsyncSessionLocal
        from hermes.workbench.feishu_notify import Notifier

        async with AsyncSessionLocal() as session:
            report = await build_weekly_report(session, days=days)

        if report.is_silent():
            return {"ok": True, "sent": False, "silent": True}
        from hermes.config import get_settings

        settings = get_settings()
        if not settings.feishu_report_chat_id:
            return {
                "ok": True,
                "sent": False,
                "reason": "FEISHU_REPORT_CHAT_ID unset; preview only",
                "preview": report.render_text(),
            }
        notifier = Notifier.from_settings(
            settings.hermes_state_dir, settings.feishu_report_chat_id
        )
        if notifier is None:
            return {
                "ok": True,
                "sent": False,
                "reason": "feishu app not configured; preview only",
                "preview": report.render_text(),
            }
        sent = await send_weekly_report(notifier, report)
        return {"ok": True, "sent": sent, "silent": False}

    return asyncio.run(_impl())
