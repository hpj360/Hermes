"""B站适配器（半自动模式）。"""
from __future__ import annotations

from hermes.content_team.models.content import Content
from hermes.content_team.models.publish import PublishStatus, PublishTask
from hermes.content_team.publish.adapters.base import BaseAdapter, PublishResult


class BilibiliAdapter(BaseAdapter):
    """B站适配器。

    B站投稿 API 需要较复杂的认证流程，当前采用半自动模式。
    """

    platform_name = "bilibili"

    TITLE_MAX_LENGTH = 80

    async def publish(self, content: Content) -> PublishResult:
        """半自动模式：返回B站创作中心链接，提示人工发布。"""
        return PublishResult(
            success=True,
            external_url="https://member.bilibili.com/platform/upload/text/edit",
            error="半自动模式：请手动发布",
            raw_response={"mode": "semi_auto", "platform": "bilibili"},
        )

    async def check_status(self, task: PublishTask) -> PublishResult:
        """模拟状态检查。"""
        if task.status == PublishStatus.FAILED:
            return PublishResult(
                success=False,
                external_url=task.external_url,
                error=task.error_message or "发布失败",
            )
        return PublishResult(
            success=True,
            external_url=task.external_url,
            error=None,
        )

    def validate_content(self, content: Content) -> list[str]:
        """校验内容是否符合B站标题限制。"""
        errors: list[str] = []
        if len(content.title) > self.TITLE_MAX_LENGTH:
            errors.append(
                f"标题超过 {self.TITLE_MAX_LENGTH} 字限制"
                f"（当前 {len(content.title)} 字）"
            )
        return errors
