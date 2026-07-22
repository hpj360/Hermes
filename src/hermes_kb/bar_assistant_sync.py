"""bar-assistant 替代材料同步器（B4）。

从 karlomikus/bar-assistant 仓库（MIT License）拉取替代材料关系。
支持传入 mock data 用于测试。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import IngredientSubstitute

_logger = logging.getLogger(__name__)

# bar-assistant 仓库基础 URL（用于真实拉取）
BAR_ASSISTANT_REPO = "karlomikus/bar-assistant"
BAR_ASSISTANT_RAW_BASE = f"https://raw.githubusercontent.com/{BAR_ASSISTANT_REPO}/main"


def sync_bar_assistant_substitutes(
    data: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """从 bar-assistant 同步替代材料关系。

    Args:
        data: 替代关系列表，每项 {"canonical": "...", "substitute": "..."}
              若为 None，尝试从 GitHub 拉取（需网络）

    Returns:
        {"imported": N, "skipped": N, "failed": N}
    """
    if data is None:
        data = _fetch_remote_data()

    if not data:
        return {"imported": 0, "skipped": 0, "failed": 0}

    imported = 0
    skipped = 0
    failed = 0

    for item in data:
        try:
            canonical = item.get("canonical", "").strip()
            substitute = item.get("substitute", "").strip()
            if not canonical or not substitute:
                failed += 1
                continue

            with get_session() as session:
                existing = session.exec(
                    select(IngredientSubstitute).where(
                        IngredientSubstitute.canonical == canonical,
                        IngredientSubstitute.substitute == substitute,
                    )
                ).first()
                if existing:
                    skipped += 1
                    continue
                session.add(IngredientSubstitute(
                    canonical=canonical,
                    substitute=substitute,
                    source="bar_assistant",
                ))
                session.commit()
                imported += 1
        except Exception as e:
            _logger.warning("bar-assistant substitute import failed for %s: %s", item, e)
            failed += 1

    return {"imported": imported, "skipped": skipped, "failed": failed}


def _fetch_remote_data() -> list[dict[str, str]]:
    """从 bar-assistant 仓库拉取替代材料数据。

    实际拉取逻辑：解析仓库的 seed 数据文件。
    若网络不可用或解析失败，返回空列表。
    """
    try:
        # bar-assistant 的成分数据通常在 database/seed 目录
        # 这里尝试拉取成分替代关系
        url = f"{BAR_ASSISTANT_RAW_BASE}/database/seed/ingredients.json"
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        raw = resp.json()

        # 解析为统一格式
        data: list[dict[str, str]] = []
        for ing in raw if isinstance(raw, list) else []:
            canonical = ing.get("name", "")
            # bar-assistant 的 substitute 字段可能是列表或字符串
            subs = ing.get("substitutes", [])
            if isinstance(subs, str):
                subs = [s.strip() for s in subs.split(",") if s.strip()]
            for sub in subs:
                if canonical and sub:
                    data.append({"canonical": canonical, "substitute": sub})
        return data
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError) as e:
        _logger.warning("bar-assistant remote data fetch failed: %s", e)
        return []
