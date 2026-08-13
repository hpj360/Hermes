"""统一 OAuth token 生命周期管理（P1-3）。

各内容平台的认证方式差异极大（微信公众号 appid/secret 换 access_token、
抖音/小红书/B站各有 OAuth2 流程），但 token 的生命周期语义一致：
检查是否过期 → 过期则刷新 → 更新存储。本模块把这段公共语义抽成一个
:class:`OAuthTokenManager`，把平台差异收敛到可注入的 ``refresh_fn``。

设计原则：
- 过期判断带 skew（提前刷新，避免边界过期导致请求失败）。
- 刷新能力通过 ``refresh_fn`` 注入；无刷新能力（返回 None）时显式降级，
  由调用方决定回退到半自动模式或报错。
- 所有 token 字段沿用 ``PlatformAccount`` 的 auth_token / refresh_token /
  token_expires_at，不引入新的存储结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from hermes.content_team.models.platform import PlatformAccount

__all__ = ["OAuthTokenManager", "TokenRefreshResult"]


@dataclass
class TokenRefreshResult:
    """一次 token 刷新的结果。"""

    token: str
    expires_at: datetime | None = None


# refresh_fn: (account) -> TokenRefreshResult | None（异步）。返回 None 表示
# 该平台不可刷新（缺 refresh_token / 网络失败 / 未实现）。
RefreshFn = Callable[[PlatformAccount], Awaitable[TokenRefreshResult | None]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OAuthTokenManager:
    """统一 token 过期检查与刷新。

    Args:
        refresh_fn: 平台差异的刷新函数，返回新 token 与过期时间；返回 None
            表示不可刷新。可省略，此时 ``ensure_valid_token`` 对过期 token
            直接返回 None（调用方降级）。
        skew_seconds: 提前多少秒视为"即将过期"，默认 300（5 分钟）。
    """

    def __init__(
        self,
        refresh_fn: RefreshFn | None = None,
        *,
        skew_seconds: int = 300,
    ) -> None:
        self._refresh_fn = refresh_fn
        self._skew_seconds = skew_seconds

    def is_expired(self, account: PlatformAccount) -> bool:
        """Return True when the account token is expired or about to expire.

        A token with no ``token_expires_at`` is treated as long-lived (never
        expired) — some platforms issue non-expiring tokens.
        """
        if account.token_expires_at is None:
            return False
        expires_at = account.token_expires_at
        if expires_at.tzinfo is None:
            # Defensive: treat naive timestamps as UTC.
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= _utcnow() + timedelta(seconds=self._skew_seconds)

    async def ensure_valid_token(self, account: PlatformAccount) -> str | None:
        """Return a valid token, refreshing it if expired.

        Returns ``None`` when the token is expired and cannot be refreshed
        (no refresh_fn or the refresh returned None). The caller decides how to
        degrade (semi-auto publish, or surface an auth error).
        """
        if not self.is_expired(account):
            return account.auth_token
        if self._refresh_fn is None:
            return None
        result = await self._refresh_fn(account)
        if result is None:
            return None
        account.auth_token = result.token
        account.token_expires_at = result.expires_at
        return account.auth_token

    def needs_refresh(self, account: PlatformAccount) -> bool:
        """Convenience alias for :meth:`is_expired` (semantic clarity)."""
        return self.is_expired(account)


__all__ += ["RefreshFn"]
