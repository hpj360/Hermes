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

__all__ = ["L3_BASE_DENYLIST", "matches_denylist"]


# L3 安全基线 denylist（单一事实源）。
#
# 调用方（loop_patterns 的 L3 pattern 声明、gepa_redteam 的红队回归）
# 一律引用本常量而不再各自手写字面量——此前的多份副本已经漂移出真实
# 缺口：无扩展名私钥（id_rsa）不被 *.key 覆盖，却有 pattern 声称"密钥已
# 保护"。
#
# 三类 pattern（与 matches_denylist 的语义一一对应）：
# - 目录前缀：业务敏感代码目录
# - glob 后缀：密钥/证书容器（二进制/文本容器，标准用途即存放密钥）
# - 精确文件名：SSH 私钥（无扩展名，*.key 覆盖不到）与凭据载体
L3_BASE_DENYLIST: list[str] = [
    # 业务敏感目录
    "auth/",
    "payment/",
    "security/",
    ".ssh/",  # 私钥/known_hosts 的规范存放目录
    # 密钥/证书容器
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    # SSH 私钥（精确名：不用 glob，避免把可公开的 id_rsa.pub 一并拦下）
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    # 凭据载体
    ".env",
    ".npmrc",
    ".netrc",
    ".pgpass",
]


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
