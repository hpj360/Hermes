"""Platform adapter base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from hermes.content_team.models.content import Content
from hermes.content_team.models.platform import PlatformAccount
from hermes.content_team.models.publish import PublishTask


@dataclass
class PublishResult:
    """适配器发布结果。

    - ``success`` 为 True 且 ``error`` 为 None：发布完全成功。
    - ``success`` 为 True 且 ``error`` 非空：半自动模式，需要人工完成发布。
    - ``success`` 为 False：发布失败，``error`` 描述失败原因。
    """

    success: bool
    external_url: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[dict[str, Any]] = field(default=None)


class BaseAdapter(ABC):
    """平台发布适配器基类。

    每个具体平台适配器继承本类并实现 ``publish`` / ``check_status`` /
    ``validate_content`` 三个方法。``platform_name`` 为平台标识字符串。
    """

    platform_name: str = ""

    def __init__(self, account: PlatformAccount) -> None:
        self.account = account

    @abstractmethod
    async def publish(self, content: Content) -> PublishResult:
        """将内容发布到平台，返回 ``PublishResult``。"""

    @abstractmethod
    async def check_status(self, task: PublishTask) -> PublishResult:
        """检查已发布任务在平台端的最新状态。"""

    @abstractmethod
    def validate_content(self, content: Content) -> list[str]:
        """校验内容是否符合平台限制，返回错误信息列表（空列表表示通过）。"""
