"""聚合所有 content_team API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from hermes.content_team.api.analytics import router as analytics_router
from hermes.content_team.api.auth import require_api_token
from hermes.content_team.api.content import router as content_router
from hermes.content_team.api.content import (
    topics_content_router as content_topics_router,
)
from hermes.content_team.api.members import router as members_router
from hermes.content_team.api.publish import router as publish_router
from hermes.content_team.api.topics import router as topics_router

api_router = APIRouter(dependencies=[Depends(require_api_token)])
api_router.include_router(topics_router, prefix="/api/topics", tags=["topics"])
api_router.include_router(members_router, prefix="/api/members", tags=["members"])
api_router.include_router(content_router, prefix="/api/content", tags=["content"])
# 基于选题创建内容：POST /api/topics/{id}/content
api_router.include_router(
    content_topics_router, prefix="/api/topics", tags=["content"]
)
# 平台账号与发布任务：/api/accounts, /api/publish
api_router.include_router(publish_router, prefix="/api", tags=["publish"])
# 数据分析与指标采集：/api/analytics
api_router.include_router(
    analytics_router, prefix="/api/analytics", tags=["analytics"]
)
