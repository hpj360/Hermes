"""wechat-reader / douyin-reader skill 脚本测试。

覆盖纯函数层（不触网）：
- wechat_reader.parse_article：微信文章结构 fixture（#js_content 容器 +
  标题/作者/时间 meta 选择器）→ 共享蒸馏引擎的解析契约
- douyin_reader.resolve_url：分享文本 URL 提取与尾部垃圾字符清理

获取层（get_article / download_video）依赖网络与外部二进制
（yt-dlp/ffmpeg/whisper），不在 CI 覆盖范围。
"""

from __future__ import annotations

import sys
from pathlib import Path

WECHAT_DIR = Path(__file__).resolve().parents[1] / "skills" / "wechat-reader" / "scripts"
DOUYIN_DIR = Path(__file__).resolve().parents[1] / "skills" / "douyin-reader" / "scripts"
for _d in (str(WECHAT_DIR), str(DOUYIN_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from douyin_reader import resolve_url  # noqa: E402
from wechat_reader import parse_article  # noqa: E402


WECHAT_HTML = """
<html><head><title>公众号标题占位</title></head>
<body>
<div class="rich_media_area_primary">
  <h1 class="rich_media_title">深度解析：多智能体系统的工程实践</h1>
  <div id="meta_content">
    <span id="js_name">Hermes 工程笔记</span>
    <em id="publish_time">2026-08-30</em>
  </div>
  <div id="js_content">
    <section><p>第一段正文内容，介绍多智能体系统的核心概念。</p></section>
    <section><p>第二段正文，讨论 builder/checker 协作模式。</p></section>
  </div>
</div>
<script>window.__mooncp = 1;</script>
</body></html>
"""


def test_wechat_parse_article_extracts_full_structure() -> None:
    """微信结构 golden 场景：容器定位 + 三项元数据 + 正文转 Markdown。"""
    article = parse_article(WECHAT_HTML, "https://mp.weixin.qq.com/s/abc123")

    assert article["title"] == "深度解析：多智能体系统的工程实践"
    assert article["author"] == "Hermes 工程笔记"
    assert article["publish_time"] == "2026-08-30"
    assert article["url"] == "https://mp.weixin.qq.com/s/abc123"

    # 正文来自 #js_content 容器，两段都在
    markdown = article["markdown"]
    assert "多智能体系统的核心概念" in markdown
    assert "builder/checker 协作模式" in markdown
    # 脚本噪声不进入正文
    assert "__mooncp" not in markdown


def test_wechat_parse_article_empty_html_degrades_gracefully() -> None:
    """空 HTML 不抛异常，返回空字段（蒸馏引擎的降级契约）。"""
    article = parse_article("<html><body></body></html>", "https://mp.weixin.qq.com/s/none")
    assert article["title"] == ""
    assert article["markdown"] == ""


def test_douyin_resolve_url_extracts_from_share_text() -> None:
    """分享文本（含中文提示）→ 提取纯 URL。"""
    share = "7条评论都在聊这个 https://v.douyin.com/iRNBh5kq/ 复制此链接打开抖音"
    assert resolve_url(share) == "https://v.douyin.com/iRNBh5kq"


def test_douyin_resolve_url_plain_url_passthrough() -> None:
    """已是纯 URL 时仅做尾部清理，原样返回。"""
    assert resolve_url("https://www.douyin.com/video/7301234567890123456/") == (
        "https://www.douyin.com/video/7301234567890123456"
    )
