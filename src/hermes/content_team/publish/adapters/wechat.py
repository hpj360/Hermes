"""微信公众号适配器（全自动模拟模式）。"""
from __future__ import annotations

from hermes.content_team.models.content import Content
from hermes.content_team.models.publish import PublishStatus, PublishTask
from hermes.content_team.publish.adapters.base import BaseAdapter, PublishResult


class WeChatOfficialAdapter(BaseAdapter):
    """微信公众号适配器。

    模拟调用微信公众号 API 完成自动发布。实际接入时需替换 ``publish``
    中的 HTTP 调用为真实接口。
    """

    platform_name = "wechat_official"

    # 平台内容限制
    TITLE_MAX_LENGTH = 64
    BODY_MAX_LENGTH = 20000

    async def publish(self, content: Content) -> PublishResult:
        """模拟调用微信公众号 API 发布内容，返回成功结果。"""
        # 模拟 API 调用：生成 mock 链接
        return PublishResult(
            success=True,
            external_url=f"https://mp.weixin.qq.com/s/mock_{content.id}",
            error=None,
            raw_response={"mock": True, "platform": "wechat_official"},
        )

    async def check_status(self, task: PublishTask) -> PublishResult:
        """模拟状态检查：已成功任务返回成功，其余视为进行中。"""
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
        """校验内容是否符合微信公众号限制。"""
        errors: list[str] = []
        if len(content.title) > self.TITLE_MAX_LENGTH:
            errors.append(
                f"标题超过 {self.TITLE_MAX_LENGTH} 字限制"
                f"（当前 {len(content.title)} 字）"
            )
        if len(content.body) > self.BODY_MAX_LENGTH:
            errors.append(
                f"正文超过 {self.BODY_MAX_LENGTH} 字限制"
                f"（当前 {len(content.body)} 字）"
            )
        return errors
