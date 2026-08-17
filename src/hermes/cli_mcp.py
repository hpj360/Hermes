"""MCP CLI 子命令。

暴露 ``hermes mcp <sub>``：
- list:          列出 mcp.json 中已配置的 servers
- ping <server>: 握手连通性检查
- tools <server>: 列出 server 暴露的工具（name + description）
- call <server> <tool>: 调用工具（--args JSON）

设计（沿用 cli_secrets.py / cli_skill_sync.py 风格）：
- 薄封装：cmd_* 仅调用 mcp_client.py 中的函数，格式化输出，返回退出码。
- --json 标志用于机器消费。
- 退出码：0=success, 1=soft fail（连接/调用失败）, 2=hard error（异常兜底）。
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from hermes.mcp_client import (
    MCPClient,
    default_mcp_config_path,
    load_mcp_config,
)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _find_server(servers: dict[str, dict[str, Any]], name: str) -> dict[str, Any] | None:
    if name not in servers:
        return None
    return servers[name]


def _describe(server_name: str, config: dict[str, Any]) -> dict[str, Any]:
    """生成 server 的人类可读描述（不含敏感 env）。"""
    desc: dict[str, Any] = {"name": server_name}
    if config.get("command"):
        desc["transport"] = "stdio"
        desc["command"] = config["command"]
        if config.get("args"):
            desc["args"] = config["args"]
    elif config.get("url"):
        desc["transport"] = "http"
        desc["url"] = config["url"]
    else:
        desc["transport"] = "unknown"
    return desc


def cmd_mcp_list(args: argparse.Namespace) -> int:
    servers = load_mcp_config(args.config)
    if not servers:
        print(f"No MCP servers configured in {args.config or default_mcp_config_path()}")
        return 0
    view = [_describe(name, cfg) for name, cfg in servers.items()]
    if getattr(args, "json", False):
        _print_json({"config": str(args.config), "servers": view})
        return 0
    print(f"MCP servers ({len(view)}) from {args.config or default_mcp_config_path()}:")
    for v in view:
        transport = v.get("transport", "?")
        target = v.get("command") or v.get("url", "")
        print(f"  - {v['name']:<16} [{transport}] {target}")
    return 0


def cmd_mcp_ping(args: argparse.Namespace) -> int:
    servers = load_mcp_config(args.config)
    config = _find_server(servers, args.server)
    if config is None:
        print(f"Unknown MCP server '{args.server}'")
        return 1
    client = MCPClient(args.server, config, timeout=args.timeout)
    try:
        client.connect()
        result = client.ping()
    except Exception as e:  # noqa: BLE001 — CLI 层软降级
        result = {"success": False, "error": str(e)}
    finally:
        client.close()
    if getattr(args, "json", False):
        _print_json({"server": args.server, **result})
        return 0 if result.get("success") else 1
    if result.get("success"):
        print(f"OK: MCP server '{args.server}' is reachable and initialized")
        return 0
    print(f"FAIL: MCP server '{args.server}' unreachable: {result.get('error')}")
    return 1


def cmd_mcp_tools(args: argparse.Namespace) -> int:
    servers = load_mcp_config(args.config)
    config = _find_server(servers, args.server)
    if config is None:
        print(f"Unknown MCP server '{args.server}'")
        return 1
    client = MCPClient(args.server, config, timeout=args.timeout)
    try:
        client.connect()
        result = client.list_tools()
    except Exception as e:  # noqa: BLE001 — CLI 层软降级
        result = {"success": False, "error": str(e)}
    finally:
        client.close()
    if not result.get("success"):
        print(f"FAIL: cannot list tools from '{args.server}': {result.get('error')}")
        return 1
    tools = (result.get("result") or {}).get("tools", [])
    if getattr(args, "json", False):
        _print_json({"server": args.server, "tools": tools})
        return 0
    print(f"Tools from '{args.server}' ({len(tools)}):")
    for t in tools:
        name = t.get("name", "?")
        desc = (t.get("description") or "").replace("\n", " ")[:80]
        print(f"  - {name:<24} {desc}")
    return 0


def cmd_mcp_call(args: argparse.Namespace) -> int:
    servers = load_mcp_config(args.config)
    config = _find_server(servers, args.server)
    if config is None:
        print(f"Unknown MCP server '{args.server}'")
        return 1
    arguments: dict[str, Any] = {}
    if args.args:
        try:
            arguments = json.loads(args.args)
        except json.JSONDecodeError as e:
            print(f"Invalid --args JSON: {e}")
            return 1
        if not isinstance(arguments, dict):
            print("Invalid --args JSON: must be an object")
            return 1
    client = MCPClient(args.server, config, timeout=args.timeout)
    try:
        client.connect()
        result = client.call_tool(args.tool, arguments)
    except Exception as e:  # noqa: BLE001 — CLI 层软降级
        result = {"success": False, "error": str(e)}
    finally:
        client.close()
    if getattr(args, "json", False):
        _print_json({"server": args.server, "tool": args.tool, **result})
        return 0 if result.get("success") else 1
    if not result.get("success"):
        print(f"FAIL: tool '{args.tool}' error: {result.get('error')}")
        return 1
    # 打印工具返回的文本内容（content 数组里 text 块）。
    content = (result.get("result") or {}).get("content", [])
    printed = False
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "text":
            print(block.get("text", ""))
            printed = True
    if not printed:
        _print_json(result.get("result"))
    return 0


def add_mcp_subparser(sub: argparse._SubParsersAction) -> None:
    p_mcp = sub.add_parser("mcp", help="Query and call MCP servers (stdio/HTTP)")
    p_mcp.add_argument(
        "--config",
        default=None,
        help=f"Path to MCP config (default: {default_mcp_config_path()})",
    )
    p_mcp.add_argument(
        "--timeout", type=float, default=30.0, help="Per-request timeout in seconds (default 30)"
    )
    p_mcp.add_argument("--json", action="store_true", help="Output JSON")
    p_mcp_sub = p_mcp.add_subparsers(dest="mcp_cmd", required=True)

    p_list = p_mcp_sub.add_parser("list", help="List configured MCP servers")
    p_list.set_defaults(func=cmd_mcp_list)

    p_ping = p_mcp_sub.add_parser("ping", help="Check server connectivity")
    p_ping.add_argument("server", help="Server name from mcp.json")
    p_ping.set_defaults(func=cmd_mcp_ping)

    p_tools = p_mcp_sub.add_parser("tools", help="List server tools")
    p_tools.add_argument("server", help="Server name from mcp.json")
    p_tools.set_defaults(func=cmd_mcp_tools)

    p_call = p_mcp_sub.add_parser("call", help="Call a tool on a server")
    p_call.add_argument("server", help="Server name from mcp.json")
    p_call.add_argument("tool", help="Tool name to invoke")
    p_call.add_argument("--args", default=None, help='Tool arguments as JSON object, e.g. \'{"k":"v"}\'')
    p_call.set_defaults(func=cmd_mcp_call)
