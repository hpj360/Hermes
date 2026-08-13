"""抖音适配器（半自动模式）。"""
from __future__ import annotations

from hermes.content_team.models.content import Content
from hermes.content_team.models.publish import PublishStatus, PublishTask
from hermes.content_team.publish.adapters.base import BaseAdapter, PublishResult


class DouyinAdapter(BaseAdapter):
    """抖音适配器。

    抖音创作者平台无完全开放的自动发布 API，采用半自动模式：
    返回创作者中心链接，由人工完成最终发布动作。
    """

    platform_name = "douyin"

    TITLE_MAX_LENGTH = 55

    async def publish(self, content: Content) -> PublishResult:
        """半自动模式：返回抖音创作者中心链接，提示人工发布。"""
        return PublishResult(
            success=True,
            external_url="https://creator.douyin.com/",
            error="半自动模式：请手动发布",
            raw_response={"mode": "semi_auto", "platform": "douyin"},
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
        """校验内容是否符合抖音标题限制。"""
        errors: list[str] = []
        if len(content.title) > self.TITLE_MAX_LENGTH:
            errors.append(
                f"标题超过 {self.TITLE_MAX_LENGTH} 字限制"
                f"（当前 {len(content.title)} 字）"
            )
        return errors
