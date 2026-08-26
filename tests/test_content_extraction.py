"""content-extraction 共享蒸馏引擎测试。

覆盖：噪声剥离、容器定位（平台特异+通用候选）、元数据提取、
Markdown 转换、压缩统计、无 bs4 降级、微信结构 golden 场景。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1] / "skills" / "content-extraction" / "scripts"
sys.path.insert(0, str(ENGINE_DIR))

from distill import (  # noqa: E402
    GENERIC_CONTENT_SELECTORS,
    NOISE_TAGS,
    DistilledContent,
    distill,
    locate_content,
    strip_noise,
)

pytestmark = pytest.mark.usefixtures("clean_engine_path")


@pytest.fixture()
def clean_engine_path(monkeypatch):
    """确保测试从干净 sys.path 导入引擎。"""
    yield


# ── 测试夹具 HTML ──────────────────────────────────────────────

NOISY_PAGE = f"""
<html><head><title>Test Page</title>
<meta property="og:title" content="OG Title">
<meta name="author" content="Alice"></head>
<body>
<nav><a href="/">Home</a><a href="/about">About</a></nav>
<header><h1>Site Banner</h1></header>
<aside><div class="ad">Advertisement text {'x' * 200}</div></aside>
<main>
  <article>
    <h2>Real Heading</h2>
    <p>First paragraph with <strong>bold</strong> and <em>italic</em> text.</p>
    <p>Second paragraph with <a href="https://example.com">a link</a>.</p>
    <ul><li>item one</li><li>item two</li></ul>
    <pre><code>def hello():
    return "world"</code></pre>
  </article>
</main>
<footer><p>Footer copyright info</p></footer>
<script>console.log("tracking")</script>
<style>.a {{ color: red; }}</style>
</body></html>
"""

WECHAT_PAGE = """
<html><head>
<script>var msg_title = 'JS fallback title';</script></head>
<body>
<div id="js_name">公众号作者</div>
<div id="publish_time">2026-08-19</div>
<h1 class="rich_media_title">微信文章标题</h1>
<div id="js_content">
  <section><p>第一段正文内容，这里写足够长的真实正文，确保总文本量超过容器检测的最小阈值，避免空壳容器被拒绝的规则误伤正常短文。</p></section>
  <section><p>第二段正文内容 with <strong>加粗</strong>，同样补充长度。</p></section>
  <script>evil()</script>
</div>
<div class="rich_media_tool">工具栏噪声</div>
</body></html>
"""


# ── 噪声剥离 ──────────────────────────────────────────────────

class TestStripNoise:
    def test_removes_all_noise_tags(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(NOISY_PAGE, "html.parser")
        strip_noise(soup)
        for tag in NOISE_TAGS:
            assert not soup.find_all(tag)

    def test_keeps_main_content(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(NOISY_PAGE, "html.parser")
        strip_noise(soup)
        assert soup.find("article") is not None
        assert "First paragraph" in soup.get_text()


# ── 容器定位 ──────────────────────────────────────────────────

class TestLocateContent:
    def test_generic_main_selector(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(NOISY_PAGE, "html.parser")
        content = locate_content(soup)
        assert content is not None
        assert "Real Heading" in content.get_text()

    def test_extra_selectors_take_priority(self):
        from bs4 import BeautifulSoup

        html = '<div id="custom"><p>' + "custom content " * 10 + "</p></div><main><p>" + "main content " * 10 + "</p></main>"
        soup = BeautifulSoup(html, "html.parser")
        content = locate_content(soup, extra_selectors=["#custom"])
        assert content is not None
        assert "custom content" in content.get_text()

    def test_rejects_thin_containers(self):
        """文本过少的容器（空壳）跳过，选下一个候选。"""
        from bs4 import BeautifulSoup

        html = '<main><p>short</p></main><article><p>' + "real " * 30 + "</p></article>"
        soup = BeautifulSoup(html, "html.parser")
        content = locate_content(soup)
        assert content is not None
        assert "real" in content.get_text()

    def test_generic_selectors_cover_wechat(self):
        """通用候选包含微信容器（js_content），无平台参数也能定位。"""
        assert "#js_content" in GENERIC_CONTENT_SELECTORS
        assert ".rich_media_content" in GENERIC_CONTENT_SELECTORS


# ── 元数据 ────────────────────────────────────────────────────

class TestExtractMetadata:
    def test_og_title_and_meta_author(self):
        result = distill(NOISY_PAGE, "https://example.com/a")
        assert result.title == "OG Title"
        assert result.author == "Alice"

    def test_wechat_meta_via_extra_selectors(self):
        result = distill(
            WECHAT_PAGE,
            "https://mp.weixin.qq.com/s/xxx",
            content_selectors=["#js_content"],
            meta_selectors={
                "title": ["h1.rich_media_title"],
                "author": ["#js_name"],
                "publish_time": ["#publish_time"],
            },
        )
        assert result.title == "微信文章标题"
        assert result.author == "公众号作者"
        assert result.publish_time == "2026-08-19"


# ── Markdown 转换 ─────────────────────────────────────────────

class TestHtmlToMarkdown:
    def test_structure_conversion(self):
        result = distill(NOISY_PAGE, "url")
        md = result.markdown
        assert "## Real Heading" in md
        assert "**bold**" in md
        assert "*italic*" in md
        assert "[a link](https://example.com)" in md
        assert "- item one" in md
        assert "- item two" in md
        assert "```" in md  # pre → 围栏代码块

    def test_noise_excluded_from_markdown(self):
        result = distill(NOISY_PAGE, "url")
        md = result.markdown
        assert "Site Banner" not in md
        assert "Footer copyright" not in md
        assert "Home" not in md
        assert "tracking" not in md

    def test_wechat_structure_golden(self):
        """微信文章结构 golden：容器命中、正文保留、容器外噪声排除。"""
        result = distill(
            WECHAT_PAGE,
            "https://mp.weixin.qq.com/s/xxx",
            content_selectors=["#js_content"],
            meta_selectors={"title": ["h1.rich_media_title"]},
        )
        assert result.stats["container_found"] is True
        assert "第一段正文内容" in result.markdown
        assert "**加粗**" in result.markdown
        assert "工具栏噪声" not in result.markdown
        assert "evil()" not in result.markdown


# ── 压缩统计 ──────────────────────────────────────────────────

class TestStats:
    def test_reduction_ratio_computed(self):
        result = distill(NOISY_PAGE, "url")
        s = result.stats
        assert s["raw_chars"] == len(NOISY_PAGE)
        assert s["distilled_chars"] == len(result.markdown)
        assert 0.0 <= s["reduction_ratio"] <= 1.0
        assert s["container_found"] is True

    def test_noisy_page_actually_shrinks(self):
        """噪声页蒸馏后应显著缩小（Defuddle 价值的量化证据）。"""
        result = distill(NOISY_PAGE, "url")
        assert result.stats["reduction_ratio"] > 0.3


# ── 降级路径 ──────────────────────────────────────────────────

class TestFallback:
    def test_empty_html(self):
        result = distill("", "url")
        assert result.markdown == ""
        assert result.stats["raw_chars"] == 0

    def test_regex_fallback_without_bs4(self, monkeypatch):
        """bs4 缺失时走正则降级，不崩、有标记。"""
        import distill as distill_mod

        monkeypatch.setattr(distill_mod, "_HAS_BS4", False)
        result = distill_mod.distill("<html><body><p>hello world</p></body></html>", "url")
        assert "hello world" in result.content_text
        assert result.stats["mode"] == "regex-fallback"

    def test_plain_page_without_known_container(self):
        """无任何已知容器时降级为 body 全文（仍剥噪声）。"""
        html = "<html><body><p>" + "plain " * 100 + "</p><nav>nav stuff</nav></body></html>"
        result = distill(html, "url")
        assert result.stats["container_found"] is False
        assert "plain" in result.markdown
        assert "nav stuff" not in result.markdown


# ── 契约 ──────────────────────────────────────────────────────

class TestContract:
    def test_to_dict_fields(self):
        result = distill(NOISY_PAGE, "https://example.com/a")
        d = result.to_dict()
        assert set(d.keys()) == {
            "url", "title", "author", "publish_time",
            "markdown", "content_text", "stats",
        }
        assert isinstance(result, DistilledContent)

    def test_deterministic_output(self):
        """同输入同输出（纯函数属性）。"""
        r1 = distill(WECHAT_PAGE, "u", content_selectors=["#js_content"])
        r2 = distill(WECHAT_PAGE, "u", content_selectors=["#js_content"])
        assert r1.markdown == r2.markdown
        assert r1.stats == r2.stats


# ── wechat-reader 接入验证 ────────────────────────────────────

class TestWechatReaderIntegration:
    def test_reader_script_imports_engine(self):
        """wechat_reader 脚本能寻址并导入共享引擎。"""
        reader_dir = (
            Path(__file__).resolve().parents[1]
            / "skills" / "wechat-reader" / "scripts"
        )
        assert (reader_dir / "wechat_reader.py").exists()
        source = (reader_dir / "wechat_reader.py").read_text(encoding="utf-8")
        assert "from distill import distill" in source
        assert "content-extraction" in source

    def test_reader_parse_article_delegates(self):
        """parse_article 委托引擎且输出契约一致。"""
        sys.path.insert(0, str(ENGINE_DIR))
        reader_path = (
            Path(__file__).resolve().parents[1]
            / "skills" / "wechat-reader" / "scripts"
        )
        sys.path.insert(0, str(reader_path))
        try:
            import wechat_reader  # noqa: S108

            result = wechat_reader.parse_article(WECHAT_PAGE, "https://mp.weixin.qq.com/s/xxx")
            assert result["title"] == "微信文章标题"
            assert result["author"] == "公众号作者"
            assert "第一段正文内容" in result["markdown"]
            assert "stats" in result
        finally:
            sys.path.remove(str(reader_path))
            sys.modules.pop("wechat_reader", None)


# ── F2: 报告渲染器 ────────────────────────────────────────────

from report import emit, render_report  # noqa: E402


class TestRenderReport:
    def test_full_report_structure(self):
        r = render_report(
            title="标题",
            meta={"来源": "微信公众号", "作者": "Alice"},
            body="正文内容",
            stats={"raw_chars": 10000, "distilled_chars": 2000, "reduction_ratio": 0.8},
        )
        assert r.startswith("# 标题\n")
        assert "> 来源: 微信公众号 | 作者: Alice" in r
        assert "---" in r
        assert "正文内容" in r
        assert "*提取统计*: 原始 10,000 字符 → 蒸馏 2,000 字符 · 压缩 80.0%" in r

    def test_empty_meta_values_skipped(self):
        r = render_report(
            title="t",
            meta={"作者": "", "时间": "2024-01-01"},
            body="b",
        )
        assert "作者" not in r
        assert "时间: 2024-01-01" in r

    def test_no_title_no_stats_minimal(self):
        r = render_report(title="", meta={}, body="仅正文")
        assert not r.startswith("#")
        assert "提取统计" not in r
        assert "仅正文" in r

    def test_fallback_stats_mode(self):
        r = render_report(title="t", meta={}, body="b", stats={"mode": "regex-fallback"})
        assert "mode=regex-fallback" in r


class TestEmit:
    def test_emit_json_stdout(self, capsys):
        code = emit({"a": 1}, "report-text", fmt="json")
        out = capsys.readouterr().out
        assert code == 0
        assert '"a": 1' in out

    def test_emit_report_stdout(self, capsys):
        code = emit({"a": 1}, "# 报告\n正文", fmt="report")
        out = capsys.readouterr().out
        assert code == 0
        assert out.startswith("# 报告")

    def test_emit_writes_file(self, tmp_path, capsys):
        target = tmp_path / "out.md"
        code = emit({"a": 1}, "# 报告", fmt="report", output=str(target))
        assert code == 0
        assert target.read_text(encoding="utf-8").startswith("# 报告")
        assert "已写入" in capsys.readouterr().err


# ── F3: reader 统一输出契约接入验证 ───────────────────────────


class TestReaderOutputContract:
    """三个 Python reader 均接入 render_report + emit 统一契约。"""

    READERS = [
        ("wechat-reader", "scripts/wechat_reader.py"),
        ("douyin-reader", "scripts/douyin_reader.py"),
        ("youtube-watcher", "scripts/get_transcript.py"),
    ]

    def test_all_readers_use_shared_contract(self):
        for skill, script in self.READERS:
            path = Path(__file__).resolve().parents[1] / "skills" / skill / script
            assert path.exists(), f"{skill}/{script} 不存在"
            source = path.read_text(encoding="utf-8")
            assert "from report import" in source, f"{skill} 未接入报告引擎"
            assert "render_report(" in source, f"{skill} 未使用统一报告渲染"
            assert "emit(" in source, f"{skill} 未使用统一输出契约"

    def test_all_readers_support_json_and_output_file(self):
        for skill, script in self.READERS:
            path = Path(__file__).resolve().parents[1] / "skills" / skill / script
            source = path.read_text(encoding="utf-8")
            assert "--json" in source, f"{skill} 缺 --json 机器模式"
            assert '"-o"' in source or "'-o'" in source, f"{skill} 缺 -o 文件输出"
