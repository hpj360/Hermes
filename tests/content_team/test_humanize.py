"""de-AI 清理引擎与 humanize API 测试。

覆盖：伪 em dash、客套句、空洞结尾段、交互残留前缀、变更记录可审计性、
API 端点（新版本快照 + 无变更时不建版本）。
"""

from __future__ import annotations

from hermes.content_team.humanize import DeaiResult, deai_text


# ── 引擎单测 ──────────────────────────────────────────────────


class TestDeaiEngine:
    def test_pseudo_dash_replaced(self):
        r = deai_text("这是一个重点 -- 需要关注的问题。")
        assert "--" not in r.text
        assert "，" in r.text
        assert any(c["rule"] == "pseudo-dash→逗号" for c in r.changes)

    def test_pleasantry_removed(self):
        r = deai_text("正文第一句。如需进一步帮助请告诉我。后续内容。")
        assert "如需进一步帮助" not in r.text
        assert "正文第一句" in r.text
        assert "后续内容" in r.text

    def test_hollow_ending_paragraph_removed(self):
        r = deai_text("主体内容。\n\n以上就是本次分享的全部内容。\n希望对你有用。")
        assert "以上就是" not in r.text
        assert "主体内容" in r.text

    def test_chat_prefix_removed(self):
        r = deai_text("当然，这是正文的开始。")
        assert r.text.startswith("这是正文的开始")

    def test_clean_text_unchanged_no_changes(self):
        r = deai_text("干净的人类文本，没有任何 AI 味。")
        assert r.text == "干净的人类文本，没有任何 AI 味。"
        assert r.changes == []
        assert r.total_changes == 0

    def test_changes_are_auditable(self):
        """变更记录含规则名与计数，可审计。"""
        r = deai_text("当然，正文 -- 带符号。如需进一步帮助请告诉我。")
        assert r.total_changes >= 2
        for c in r.changes:
            assert "rule" in c and "count" in c
            assert c["count"] >= 1

    def test_result_dataclass(self):
        r = deai_text("任意文本")
        assert isinstance(r, DeaiResult)
        assert isinstance(r.changes, list)


# ── API 集成 ──────────────────────────────────────────────────


async def test_humanize_endpoint_applies_and_versions(client):
    """POST humanize：清理生效 + 创建新版本快照（清理前文本可回滚）。"""
    resp = await client.post(
        "/api/content",
        json={"title": "AI 味内容", "body": "重点 -- 说明。如需进一步帮助请告诉我。"},
    )
    cid = resp.json()["id"]

    resp = await client.post(f"/api/content/{cid}/humanize")
    assert resp.status_code == 200
    data = resp.json()
    assert "--" not in data["content"]["body"]
    assert "如需进一步帮助" not in data["content"]["body"]
    assert data["total_changes"] >= 2

    # 版本快照保留清理前文本
    versions = await client.get(f"/api/content/{cid}/versions")
    bodies = [v["body"] for v in versions.json()]
    assert any("如需进一步帮助" in b for b in bodies), "清理前文本应保留在版本链"


async def test_humanize_endpoint_clean_text_no_new_version(client):
    """无 AI 味时不建新版本（幂等）。"""
    resp = await client.post(
        "/api/content", json={"title": "干净内容", "body": "人类自然文本。"}
    )
    cid = resp.json()["id"]

    resp = await client.post(f"/api/content/{cid}/humanize")
    assert resp.status_code == 200
    assert resp.json()["total_changes"] == 0

    versions = await client.get(f"/api/content/{cid}/versions")
    assert len(versions.json()) == 1  # 仅创建时的 v1


async def test_humanize_endpoint_404(client):
    resp = await client.post("/api/content/00000000-0000-0000-0000-000000000000/humanize")
    assert resp.status_code == 404
