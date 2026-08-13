"""微信视频号适配器（半自动模式）。

微信视频号（WeChat Channels）尚未对第三方开放内容发布 API——当前仅面向
特定合作伙伴灰度开放，普通开发者无法程序化投稿。因此本适配器采用与 B站
一致的半自动模式：返回视频号助手链接，提示人工完成发布与状态确认。
"""
from __future__ import annotations

from hermes.content_team.models.content import Content
from hermes.content_team.models.publish import PublishStatus, PublishTask
from hermes.content_team.publish.adapters.base import BaseAdapter, PublishResult


class WeChatVideoAdapter(BaseAdapter):
    """微信视频号适配器。

    半自动模式：视频号无公开投稿 API，返回视频号助手链接供人工发布。
    """

    platform_name = "wechat_video"

    # 视频号标题/描述限制（与公众号一致的保守上限）
    TITLE_MAX_LENGTH = 64

    async def publish(self, content: Content) -> PublishResult:
        """半自动模式：返回视频号助手入口，提示人工发布。"""
        return PublishResult(
            success=True,
            external_url="https://channels.weixin.qq.com/platform",
            error="半自动模式：视频号未开放第三方投稿 API，请手动发布",
            raw_response={"mode": "semi_auto", "platform": "wechat_video"},
        )

    async def check_status(self, task: PublishTask) -> PublishResult:
        """半自动模式的状态检查：失败任务透传失败，其余视为人工待确认。"""
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
        """校验内容是否符合视频号限制。"""
        errors: list[str] = []
        if len(content.title) > self.TITLE_MAX_LENGTH:
            errors.append(
                f"标题超过 {self.TITLE_MAX_LENGTH} 字限制"
                f"（当前 {len(content.title)} 字）"
            )
        return errors
