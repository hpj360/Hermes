"""各平台发布适配器集合。"""
from __future__ import annotations

from hermes.content_team.publish.adapters.base import BaseAdapter, PublishResult
from hermes.content_team.publish.adapters.bilibili import BilibiliAdapter
from hermes.content_team.publish.adapters.douyin import DouyinAdapter
from hermes.content_team.publish.adapters.wechat import WeChatOfficialAdapter
from hermes.content_team.publish.adapters.xiaohongshu import XiaohongshuAdapter

__all__ = [
    "BaseAdapter",
    "BilibiliAdapter",
    "DouyinAdapter",
    "PublishResult",
    "WeChatOfficialAdapter",
    "XiaohongshuAdapter",
]
