"""端到端集成：模拟 Open Design 设计生成 → content_team 多平台发布 → 分析回流。

完整链路（战略闭环"设计 → 内容 → 发布 → 分析"）：
  1. 模拟 od MCP server（stdio，暴露真实工具名：list_skills / create_project /
     start_run / get_run / cancel_run）产出设计产物（HTML 落地页）；
  2. 通过 ``hermes.mcp_client.MCPClient`` 消费产物；
  3. 设计产物转 ``Content``；
  4. ``PublishDispatcher`` fan-out 分发到微信公众号 / 抖音 / 小红书 / B站；
  5. ``MetricsCollector`` 按内容回流各平台指标快照。

其中 od MCP 工具名与 get_run 响应字段（studioUrl / previewUrl / agentMessage）
均依据 Open Design MCP PR #3141 与官方文档（真实环境形状）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from hermes.content_team.analytics.collector import MetricsCollector
from hermes.content_team.db import Base
from hermes.content_team.models import (
    Content,
    Platform,
    PlatformAccount,
    PublishStatus,
)
from hermes.content_team.publish.dispatcher import PublishDispatcher
from hermes.mcp_client import MCPClient

# ---------------------------------------------------------------------------
# 模拟 Open Design MCP server（stdio）
# ---------------------------------------------------------------------------

OD_MOCK_SERVER = r"""
import json
import sys

SKILLS = [
    {"id": "saas-landing", "title": "SaaS Landing Page",
     "description": "Single-page landing for a SaaS product"},
    {"id": "pitch-deck", "title": "Pitch Deck",
     "description": "Investor pitch deck"},
    {"id": "dashboard", "title": "Live Dashboard",
     "description": "Data dashboard artifact"},
]

PROJECTS = {}
RUNS = {}
_NEXT = {"proj": 1000, "run": 2000}

TOOLS = [
    {"name": "list_skills", "description": "List available design skills",
     "inputSchema": {"type": "object"}},
    {"name": "create_project", "description": "Create a design project "
     "(skipDiscoveryBrief: true)", "inputSchema": {"type": "object"}},
    {"name": "start_run", "description": "Start a generation run",
     "inputSchema": {"type": "object"}},
    {"name": "get_run", "description": "Poll run status",
     "inputSchema": {"type": "object"}},
    {"name": "cancel_run", "description": "Cancel a running run",
     "inputSchema": {"type": "object"}},
]


def _respond(msg, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"),
                                 "result": result}) + "\n")
    sys.stdout.flush()


def _rpc_error(msg, code, text):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"),
                                 "error": {"code": code, "message": text}}) + "\n")
    sys.stdout.flush()


def main():
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "initialize":
            _respond(msg, {"protocolVersion": "2025-03-26",
                           "capabilities": {"tools": {}},
                           "serverInfo": {"name": "open-design-mock",
                                          "version": "0.9.0"}})
        elif method == "tools/list":
            _respond(msg, {"tools": TOOLS})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "list_skills":
                _respond(msg, {"content": [{"type": "text",
                                            "text": json.dumps({"skills": SKILLS})}],
                               "isError": False})
            elif name == "create_project":
                _NEXT["proj"] += 1
                pid = "proj_%d" % _NEXT["proj"]
                PROJECTS[pid] = {"id": pid, "name": args.get("name", ""),
                                 "skillId": args.get("skillId", ""),
                                 "designSystemId": args.get("designSystemId", "")}
                _respond(msg, {"content": [{"type": "text",
                                            "text": json.dumps({"project": PROJECTS[pid]})}],
                               "isError": False})
            elif name == "start_run":
                _NEXT["run"] += 1
                rid = "run_%d" % _NEXT["run"]
                RUNS[rid] = {"id": rid, "projectId": args.get("projectId", ""),
                             "status": "running", "prompt": args.get("prompt", "")}
                _respond(msg, {"content": [{"type": "text",
                                            "text": json.dumps({"run": RUNS[rid]})}],
                               "isError": False})
            elif name == "get_run":
                rid = args.get("runId", "")
                run = RUNS.get(rid)
                if not run:
                    _rpc_error(msg, -32602, "run not found: %s" % rid)
                    continue
                # 模拟 OD 内部 agent 完成设计：落地页 HTML 产物。
                html = ("<html><head><title>AI 原生数据工作台</title></head>"
                        "<body><h1>AI 原生数据工作台</h1>"
                        "<p>让团队用自然语言完成数据分析与实时洞察。</p></body></html>")
                run["status"] = "completed"
                run["agentMessage"] = ("已完成落地页设计：AI 原生数据工作台，"
                                       "突出自然语言分析、实时洞察、团队协作三大卖点。")
                run["studioUrl"] = ("http://localhost:8080/studio/projects/%s"
                                    % run["projectId"])
                run["previewUrl"] = ("http://localhost:8080/api/projects/%s/raw/index.html"
                                     % run["projectId"])
                # 模拟 OD 项目文件快照（真实环境经文件 API 读取，此处聚合返回）。
                run["artifacts"] = [{"path": "index.html",
                                     "contentType": "text/html", "content": html}]
                _respond(msg, {"content": [{"type": "text",
                                            "text": json.dumps({"run": run})}],
                               "isError": False})
            elif name == "cancel_run":
                rid = args.get("runId", "")
                if rid in RUNS:
                    RUNS[rid]["status"] = "cancelled"
                _respond(msg, {"content": [{"type": "text",
                                            "text": json.dumps({"run": RUNS.get(rid, {
                                                "id": rid, "status": "cancelled"})})}],
                               "isError": False})
            else:
                _respond(msg, {"content": [{"type": "text",
                                            "text": "unknown tool: %s" % name}],
                               "isError": True})
        # notifications（无 id）忽略


if __name__ == "__main__":
    main()
"""


@pytest.fixture
def od_mock_config(tmp_path: Path) -> dict:
    """把模拟 od MCP server 写入临时文件，返回 MCPClient 配置。"""
    server_file = tmp_path / "od_mock_server.py"
    server_file.write_text(OD_MOCK_SERVER, encoding="utf-8")
    return {"command": sys.executable, "args": [str(server_file)]}


@pytest.fixture
def mute_mcp_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离 mcp_client 审计，避免写入真实 .state。"""
    monkeypatch.setattr("hermes.mcp_client._audit_impl", lambda *a, **k: None)


@pytest_asyncio.fixture
async def db_session():
    """内存 SQLite + StaticPool 的 AsyncSession（每个测试独立）。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# 完整链路
# ---------------------------------------------------------------------------


async def test_design_to_publish_analytics_loop(
    db_session, od_mock_config, mute_mcp_audit
) -> None:
    """模拟 OD 设计生成 → Content → 多平台 fan-out → 指标回流。"""

    # ── 1. 消费模拟 OD：发现技能 → 建项目 → 启动 run → 轮询产物 ──
    od = MCPClient("open-design-mock", od_mock_config)
    od.connect()
    try:
        skills_res = od.call_tool("list_skills", {})
        assert skills_res["success"] is True
        skills = json.loads(skills_res["result"]["content"][0]["text"])["skills"]
        assert "saas-landing" in [s["id"] for s in skills]

        proj_res = od.call_tool(
            "create_project",
            {"name": "AI 原生数据工作台落地页", "skillId": "saas-landing",
             "designSystemId": "default"},
        )
        project = json.loads(proj_res["result"]["content"][0]["text"])["project"]
        assert project["skillId"] == "saas-landing"

        run_res = od.call_tool(
            "start_run",
            {"projectId": project["id"],
             "prompt": "为一个数据工作台产品设计高转化落地页"},
        )
        run = json.loads(run_res["result"]["content"][0]["text"])["run"]
        assert run["status"] == "running"

        # 轮询一次即 completed（真实环境为多次 get_run 直到非 running）
        get_res = od.call_tool("get_run", {"runId": run["id"]})
        assert get_res["success"] is True
        run_done = json.loads(get_res["result"]["content"][0]["text"])["run"]
        assert run_done["status"] == "completed"
        assert run_done["studioUrl"].startswith("http://")
        assert run_done["previewUrl"].endswith("index.html")
        assert "agentMessage" in run_done

        # 设计产物：从 HTML 提取标题
        html = run_done["artifacts"][0]["content"]
        match = re.search(r"<h1>(.*?)</h1>", html)
        assert match is not None
        title = match.group(1)
        assert title == "AI 原生数据工作台"
    finally:
        od.close()

    # ── 2. 设计产物 → Content ──
    content = Content(
        title=title, body=run_done["agentMessage"], content_type="webpage"
    )
    db_session.add(content)
    await db_session.flush()

    # ── 3. 注册四个平台账号 ──
    account_ids = []
    for platform in (
        Platform.WECHAT_OFFICIAL,
        Platform.DOUYIN,
        Platform.XIAOHONGSHU,
        Platform.BILIBILI,
    ):
        account = PlatformAccount(
            platform=platform, display_name=f"{platform.value} 测试号"
        )
        db_session.add(account)
        await db_session.flush()
        account_ids.append(account.id)
    await db_session.commit()

    # ── 4. 多平台 fan-out 发布 ──
    dispatcher = PublishDispatcher(db_session)
    tasks = await dispatcher.dispatch(content.id, account_ids)
    assert len(tasks) == 4

    status_by_platform = {t.platform: t.status for t in tasks}
    # 微信公众号：全自动 → SUCCESS；抖音/小红书/B站：半自动 → PARTIAL_SUCCESS
    assert status_by_platform[Platform.WECHAT_OFFICIAL] == PublishStatus.SUCCESS
    assert status_by_platform[Platform.DOUYIN] == PublishStatus.PARTIAL_SUCCESS
    assert status_by_platform[Platform.XIAOHONGSHU] == PublishStatus.PARTIAL_SUCCESS
    assert status_by_platform[Platform.BILIBILI] == PublishStatus.PARTIAL_SUCCESS

    wx_task = next(t for t in tasks if t.platform == Platform.WECHAT_OFFICIAL)
    assert wx_task.external_url.startswith("https://mp.weixin.qq.com/")
    assert wx_task.published_at is not None

    # ── 5. 分析回流：按内容采集各平台指标 ──
    collector = MetricsCollector(db_session)
    metrics = await collector.collect_by_content(content.id)
    assert len(metrics) == 4
    platforms = {m.platform for m in metrics}
    assert platforms == {
        Platform.WECHAT_OFFICIAL,
        Platform.DOUYIN,
        Platform.XIAOHONGSHU,
        Platform.BILIBILI,
    }
    assert all(m.content_id == content.id for m in metrics)
    for m in metrics:
        assert m.views > 0
        assert m.likes > 0
        assert m.comments >= 0
        assert m.shares >= 0
        assert m.engagement_rate >= 0
        assert m.source == "simulation"


async def test_design_loop_soft_degrade_on_missing_run(db_session, od_mock_config, mute_mcp_audit) -> None:
    """get_run 遇到不存在的 runId → MCP 返回协议错误，客户端软降级（不抛异常）。"""
    od = MCPClient("open-design-mock", od_mock_config)
    od.connect()
    try:
        result = od.call_tool("get_run", {"runId": "run_not_exist"})
        assert result["success"] is False
        assert "run not found" in result["error"]
    finally:
        od.close()


async def test_design_loop_tool_names_match_real_od(db_session, od_mock_config, mute_mcp_audit) -> None:
    """暴露的工具名与真实 Open Design MCP 对齐（发现组 + 生成组）。"""
    od = MCPClient("open-design-mock", od_mock_config)
    od.connect()
    try:
        tools_res = od.list_tools()
        assert tools_res["success"] is True
        names = {t["name"] for t in tools_res["result"]["tools"]}
        # 生成组（PR #3141）
        assert {"create_project", "start_run", "get_run", "cancel_run"} <= names
        # 发现组
        assert "list_skills" in names
    finally:
        od.close()
