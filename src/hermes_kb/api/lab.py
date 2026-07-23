"""鸡尾酒实验室端点（M3 / M4 / B6）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from hermes_kb.api.deps import get_importer, require_age_gate
from hermes_kb.rag import ImportService
from hermes_kb.daily_recipe import daily_recipe
from hermes_kb.ingredients import canonicalize
from hermes_kb.lab_dashboard import get_lab_dashboard
from hermes_kb.missing_stats import batch_increment_missing, get_top_missing
from hermes_kb.recipe_crud import (
    approve_recipe,
    create_recipe,
    reject_recipe,
    submit_recipe,
    update_recipe,
)
from hermes_kb.recipe_filter import filter_recipes, hide_recipe, verify_recipe
from hermes_kb.recipe_match import match_recipes
from hermes_kb.recipe_stats import (
    batch_increment_match_counts,
    get_hot_recipes,
    increment_view_count,
)
from hermes_kb.recipe_variants import create_variant_link, get_variants
from hermes_kb.substitutes import add_user_substitute

router = APIRouter(prefix="/api/lab", tags=["lab"])


# B6：外部数据源同步请求
class SyncRequest(BaseModel):
    source: str = Field(..., description="数据源：thecocktaildb / iba_dataset / bar_assistant")
    limit: int = Field(default=50, ge=1, le=500)


@router.get("/match", dependencies=[Depends(require_age_gate)])
async def lab_match(
    ingredients: str = "",
    background_tasks: BackgroundTasks = None,
) -> dict[str, Any]:
    """材料 → 配方匹配。ingredients 为逗号分隔的材料名。

    A3-3: 统计写入移到 BackgroundTasks，主响应不阻塞。match_recipes
    返回的 _pending_stats 内部字段在此 pop 掉，不暴露给客户端。
    """
    if not ingredients or not ingredients.strip():
        return {"full_match": [], "partial_match": []}

    raw_names = [s.strip() for s in ingredients.split(",") if s.strip()]
    user_ingredients = {canonicalize(n) for n in raw_names}

    result = match_recipes(user_ingredients)

    # A3-3: 统计写入移到 BackgroundTasks（批量、单次事务）
    pending = result.pop("_pending_stats", {}) or {}
    matched_doc_ids = pending.get("matched_doc_ids") or []
    missing_ingredients = pending.get("missing_ingredients") or []
    if matched_doc_ids:
        background_tasks.add_task(
            batch_increment_match_counts, matched_doc_ids
        )
    if missing_ingredients:
        background_tasks.add_task(
            batch_increment_missing, missing_ingredients
        )

    return result


@router.get("/hot", dependencies=[Depends(require_age_gate)])
async def lab_hot(limit: int = 3, days: int = 30) -> dict[str, Any]:
    """热门配方（按 match_count 降序）。"""
    limit = max(1, min(limit, 50))
    days = max(1, min(days, 365))
    items = get_hot_recipes(limit=limit, days=days)
    return {"items": items}


@router.post("/view/{doc_id}", dependencies=[Depends(require_age_gate)])
async def lab_view(doc_id: str) -> dict[str, Any]:
    """查看配方详情时调用，view_count +1。"""
    increment_view_count(doc_id)
    return {"doc_id": doc_id, "status": "ok"}


# M4.1：实验室自动运营层
@router.get("/daily", dependencies=[Depends(require_age_gate)])
async def lab_daily() -> dict[str, Any]:
    """每日推荐配方。"""
    result = daily_recipe()
    return result or {"title": None, "reason": "empty"}


@router.get("/missing-stats", dependencies=[Depends(require_age_gate)])
async def lab_missing_stats(limit: int = 10) -> dict[str, Any]:
    """缺失材料排行。"""
    limit = max(1, min(limit, 50))
    return {"items": get_top_missing(limit=limit)}


@router.post("/substitute", dependencies=[Depends(require_age_gate)])
async def lab_save_substitute(req: dict[str, Any]) -> dict[str, Any]:
    """保存用户自定义替代关系。"""
    canonical = (req.get("canonical") or "").strip()
    substitute = (req.get("substitute") or "").strip()
    if not canonical or not substitute:
        raise HTTPException(status_code=400, detail="canonical 和 substitute 必填")
    add_user_substitute(canonical, substitute)
    return {"canonical": canonical, "substitute": substitute, "status": "ok"}


@router.get("/dashboard", dependencies=[Depends(require_age_gate)])
async def lab_dashboard_endpoint() -> dict[str, Any]:
    """实验室运营看板聚合指标。"""
    return get_lab_dashboard()


# B6: 外部数据源同步 + 配方治理
@router.post("/sync", dependencies=[Depends(require_age_gate)])
async def lab_sync(
    req: SyncRequest,
    importer: ImportService = Depends(get_importer),
) -> dict[str, Any]:
    """同步外部数据源配方/替代材料。

    source 取值：
    - thecocktaildb: 全量拉取 TheCocktailDB 配方
    - iba_dataset: 拉取 IBA 官方金标准配方（100 款）
    - bar_assistant: 同步 bar-assistant 替代材料关系
    """
    # 注意：以下三个 import 保持函数内 lazy 形式——测试通过 monkeypatch 源模块
    # （hermes_kb.thecocktaildb_sync / iba_dataset_importer / bar_assistant_sync）
    # 注入 fake 实现，若改为顶层 import 则 patch 源模块不会生效。
    if req.source == "thecocktaildb":
        from hermes_kb.thecocktaildb_sync import sync_thecocktaildb

        result = sync_thecocktaildb(limit=req.limit, importer=importer)
    elif req.source == "iba_dataset":
        from hermes_kb.iba_dataset_importer import sync_iba_dataset

        result = sync_iba_dataset(importer=importer)
    elif req.source == "bar_assistant":
        from hermes_kb.bar_assistant_sync import sync_bar_assistant_substitutes

        result = sync_bar_assistant_substitutes()
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source: {req.source}. Supported: thecocktaildb / iba_dataset / bar_assistant",
        )
    return {"source": req.source, **result}


@router.get("/recipes", dependencies=[Depends(require_age_gate)])
async def lab_recipes_list(
    source: str | None = None,
    verified: bool | None = None,
    hidden: bool | None = None,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """配方列表（支持按 source/verified/hidden/status 筛选）。"""
    limit = max(1, min(limit, 500))
    items = filter_recipes(
        source=source, verified=verified, hidden=hidden, status=status, limit=limit
    )
    return {"items": items}


@router.post("/recipes/{doc_id}/verify", dependencies=[Depends(require_age_gate)])
async def lab_verify_recipe(doc_id: str) -> dict[str, Any]:
    """审核通过配方（verified=True, status=published）。"""
    if not verify_recipe(doc_id):
        raise HTTPException(status_code=404, detail=f"Recipe not found: {doc_id}")
    return {"doc_id": doc_id, "status": "ok"}


@router.post("/recipes/{doc_id}/hide", dependencies=[Depends(require_age_gate)])
async def lab_hide_recipe(doc_id: str, hidden: bool = True) -> dict[str, Any]:
    """隐藏/取消隐藏配方。"""
    if not hide_recipe(doc_id, hidden=hidden):
        raise HTTPException(status_code=404, detail=f"Recipe not found: {doc_id}")
    return {"doc_id": doc_id, "hidden": hidden}


# M4.3：UGC 调酒研究室
@router.post("/recipes", dependencies=[Depends(require_age_gate)])
async def lab_create_recipe(
    req: dict[str, Any],
    importer: ImportService = Depends(get_importer),
) -> dict[str, Any]:
    """创建 UGC 配方（draft 状态）。"""
    title = (req.get("title") or "").strip()
    content = req.get("content") or ""
    if not title or not content.strip():
        raise HTTPException(status_code=400, detail="title 和 content 必填")
    ingredients = req.get("ingredients") or []
    result = create_recipe(
        title=title,
        ingredients=ingredients,
        content=content,
        base_spirit=req.get("base_spirit", ""),
        difficulty=req.get("difficulty", "easy"),
        season=req.get("season"),
        importer=importer,
    )
    return result


@router.put("/recipes/{doc_id}", dependencies=[Depends(require_age_gate)])
async def lab_update_recipe(doc_id: str, req: dict[str, Any]) -> dict[str, Any]:
    """编辑 UGC 配方（仅 draft 状态）。"""
    try:
        ok = update_recipe(
            doc_id,
            title=req.get("title"),
            ingredients=req.get("ingredients"),
            content=req.get("content"),
            season=req.get("season"),
        )
    except ValueError as e:
        # P2-2: ingredients 不支持更新，显式拒绝而非静默丢弃
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=400, detail="仅 draft 状态可编辑")
    return {"doc_id": doc_id, "status": "ok"}


@router.post("/recipes/{doc_id}/submit", dependencies=[Depends(require_age_gate)])
async def lab_submit_recipe(doc_id: str) -> dict[str, Any]:
    """提交审核（draft → pending）。"""
    ok = submit_recipe(doc_id)
    if not ok:
        raise HTTPException(status_code=400, detail="仅 draft 状态可提交")
    return {"doc_id": doc_id, "status": "pending"}


@router.post("/recipes/{doc_id}/approve", dependencies=[Depends(require_age_gate)])
async def lab_approve_recipe(doc_id: str) -> dict[str, Any]:
    """审核通过（pending → published）。"""
    ok = approve_recipe(doc_id)
    if not ok:
        raise HTTPException(status_code=400, detail="仅 pending 状态可审核")
    return {"doc_id": doc_id, "status": "ok"}


@router.post("/recipes/{doc_id}/reject", dependencies=[Depends(require_age_gate)])
async def lab_reject_recipe(doc_id: str, req: dict[str, Any]) -> dict[str, Any]:
    """审核驳回（pending → rejected）。"""
    reason = req.get("reason", "")
    ok = reject_recipe(doc_id, reason=reason)
    if not ok:
        raise HTTPException(status_code=400, detail="仅 pending 状态可驳回")
    return {"doc_id": doc_id, "status": "rejected", "reason": reason}


@router.get("/recipes/{doc_id}/variants", dependencies=[Depends(require_age_gate)])
async def lab_recipe_variants(doc_id: str) -> dict[str, Any]:
    """查看配方的变体列表。"""
    items = get_variants(doc_id)
    return {"items": items, "count": len(items)}


@router.post("/recipes/{doc_id}/variant", dependencies=[Depends(require_age_gate)])
async def lab_create_variant(doc_id: str, req: dict[str, Any]) -> dict[str, Any]:
    """创建变体（基于 doc_id 配方创作新配方并关联）。"""
    variant_doc_id = req.get("variant_doc_id")
    variant_note = req.get("variant_note", "")
    if not variant_doc_id:
        raise HTTPException(status_code=400, detail="variant_doc_id 必填")
    ok = create_variant_link(doc_id, variant_doc_id, variant_note)
    if not ok:
        raise HTTPException(status_code=400, detail="关联已存在或配方不存在")
    return {"base_doc_id": doc_id, "variant_doc_id": variant_doc_id, "status": "ok"}
