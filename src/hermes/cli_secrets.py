"""Secrets CLI 子命令。

暴露 `hermes secrets <sub>`：
- list: 列出所有 SecretSource 及其可用性
- show <key>: 显示某个密钥的值（掩码显示，只露前 4 后 4 字符）
- check: 检查当前 SecretSource 是否可用 + 已配置的密钥列表

设计（沿用 cli_eval.py / cli_skill_sync.py 风格）：
- 薄封装：cmd_* 仅调用 secrets.py 中的函数，格式化输出，返回退出码。
- --json 标志用于机器消费。
- 退出码：0=success, 1=soft fail, 2=hard error（抛出的异常由 main 兜底为 2）。
- 不在此处放业务逻辑——全部逻辑在 secrets.py。
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from hermes.config import Settings
from hermes.secrets import (
    DEFAULT_SECRET_SOURCE,
    get_secret_source,
    list_available_sources,
)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _mask(value: str) -> str:
    """掩码显示：长度 > 8 时露前 4 后 4，否则全掩码（避免短密钥泄露）。"""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _known_secret_keys() -> list[str]:
    """从 Settings 字段推导已知密钥类环境变量名。

    筛选字段名包含 key/token/secret/password 的项，取其 alias（即 .env 变量名）。
    """
    keys: list[str] = []
    for field_name, field_info in Settings.model_fields.items():
        alias = field_info.alias or field_name
        name_lower = field_name.lower()
        if any(kw in name_lower for kw in ("key", "token", "secret", "password")):
            keys.append(alias)
    return sorted(set(keys))


# ── Command handlers ────────────────────────────────────────────────


def cmd_secrets_list(args: argparse.Namespace) -> int:
    """列出所有 SecretSource 及其可用性。"""
    sources = list_available_sources()
    configured = os.environ.get(
        "HERMES_SECRET_SOURCE", DEFAULT_SECRET_SOURCE
    ).strip().lower()

    if args.json:
        _print_json({"configured": configured, "sources": sources})
        return 0

    print(f"SecretSources (configured: {configured}):")
    for s in sources:
        mark = "✓" if s["available"] else "✗"
        cur = " *" if s["name"] == configured else ""
        print(f"  {mark} {s['name']:<14} {s['source_name']}{cur}")
    return 0


def cmd_secrets_show(args: argparse.Namespace) -> int:
    """显示某个密钥的值（掩码显示，只露前 4 后 4 字符）。"""
    source = get_secret_source()
    value = source.get_secret(args.key)

    if value is None:
        if args.json:
            _print_json({"key": args.key, "set": False, "value_masked": None})
        else:
            print(f"{args.key}: (unset)")
        return 1

    if args.json:
        _print_json({"key": args.key, "set": True, "value_masked": _mask(value)})
    else:
        print(f"{args.key}: {_mask(value)}")
    return 0


def cmd_secrets_check(args: argparse.Namespace) -> int:
    """检查当前 SecretSource 是否可用 + 已配置的密钥列表。"""
    source = get_secret_source()
    available = source.is_available()
    keys = _known_secret_keys()

    configured_keys: list[str] = []
    missing_keys: list[str] = []
    for k in keys:
        if source.get_secret(k):
            configured_keys.append(k)
        else:
            missing_keys.append(k)

    if args.json:
        _print_json(
            {
                "source": source.source_name(),
                "available": available,
                "configured_keys": configured_keys,
                "missing_keys": missing_keys,
            }
        )
        return 0 if available else 1

    status = "available" if available else "unavailable"
    print(f"SecretSource: {source.source_name()} ({status})")
    print(f"Configured keys ({len(configured_keys)}):")
    for k in configured_keys:
        print(f"  ✓ {k}")
    print(f"Missing keys ({len(missing_keys)}):")
    for k in missing_keys:
        print(f"  · {k}")
    return 0 if available else 1


# ── Subparser registration ──────────────────────────────────────────


def add_secrets_subparser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `hermes secrets <sub>` commands on the top-level subparsers."""
    p = sub.add_parser(
        "secrets", help="Manage pluggable secret sources (env_file/env_var/...)"
    )
    ss = p.add_subparsers(dest="secrets_cmd", required=True)

    # list
    p_list = ss.add_parser("list", help="List all SecretSources and availability")
    p_list.add_argument("--json", action="store_true", help="Output JSON")
    p_list.set_defaults(func=cmd_secrets_list)

    # show
    p_show = ss.add_parser("show", help="Show a secret value (masked: first/last 4 chars)")
    p_show.add_argument("key", help="Secret key / env var name")
    p_show.add_argument("--json", action="store_true", help="Output JSON")
    p_show.set_defaults(func=cmd_secrets_show)

    # check
    p_check = ss.add_parser("check", help="Check current source + configured keys")
    p_check.add_argument("--json", action="store_true", help="Output JSON")
    p_check.set_defaults(func=cmd_secrets_check)
