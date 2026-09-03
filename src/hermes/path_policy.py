"""L3 路径 denylist 匹配语义——单一事实源。

此前该逻辑在 ``orchestrator._matches_denylist`` 与
``gepa_redteam.matches_denylist`` 各有一份副本：红队回归测的是副本，
一旦 orchestrator 语义变更，回归依然全绿（假阴性）。本模块把匹配
语义下沉为唯一实现，两个调用方都委托到这里，漂移即不可能。

语义（与 LOOP_PATTERNS 中 denylist 的声明对齐）：
- ``"auth/"``  → 目录前缀匹配（路径以 auth/ 开头或包含 /auth/）
- ``".env"``   → 精确文件名匹配（basename 等于 .env）
- ``"*.key"``  → glob 后缀匹配（fnmatch）
- ``"CHANGELOG.md"`` → 精确文件名匹配
"""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

__all__ = ["matches_denylist"]


def matches_denylist(path: str, denylist: list[str]) -> str | None:
    """检查文件路径是否命中 denylist pattern。

    返回命中的 pattern（便于审计日志），未命中返回 None。
    """
    if not path or not denylist:
        return None
    # 规范化：统一用 / 分隔，去除前导 ./（注意不能用 lstrip——它是字符类剥离，
    # 会把 ".env" 错误地剥成 "env"）。只剥离字面量 "./" 前缀。
    clean = path.replace("\\", "/")
    if clean.startswith("./"):
        clean = clean[2:]
    pure = PurePosixPath(clean)
    basename = pure.name
    full = str(pure)

    for pattern in denylist:
        if not pattern:
            continue
        # 目录前缀：pattern 以 / 结尾（如 "auth/"）
        if pattern.endswith("/"):
            prefix = pattern.rstrip("/")
            if full == prefix or full.startswith(prefix + "/") or f"/{prefix}/" in f"/{full}":
                return pattern
            continue
        # glob：pattern 含 * 或 ?（如 "*.key"）
        if "*" in pattern or "?" in pattern:
            if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(full, pattern):
                return pattern
            continue
        # 精确匹配：basename 或 full 等于 pattern（如 ".env", "CHANGELOG.md"）
        if basename == pattern or full == pattern:
            return pattern
    return None
