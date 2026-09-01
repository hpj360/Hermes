"""Platform metrics adapters for content_team analytics (P1-1).

Defines the boundary between "real platform data API" and the deterministic
simulation fallback used when no credentials are configured. ``MetricsCollector``
injects an optional :class:`MetricsAdapterRegistry`; when a real adapter for a
platform is registered AND returns a snapshot, the real metrics win; otherwise
the collector falls back to simulated metrics (preserving the pre-P1-1 behavior).

Adapters are stdlib-only (``urllib``), matching the zero-runtime-dependency
constraint of the core layer. A real adapter returns ``None`` on any failure
(no credentials, network error, unsupported platform) so the collector can
degrade gracefully.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast

from hermes.content_team.auth.oauth_flow import (
    OAuthTokenManager,
    TokenRefreshResult,
)
from hermes.content_team.models.platform import Platform

__all__ = [
    "MetricsAdapterRegistry",
    "MetricsSnapshot",
    "PlatformMetricsAdapter",
    "WechatOfficialMetricsAdapter",
    "default_metrics_adapter_registry",
]

# 微信公众号数据统计（数据更新通常 T+1，最多可查近 3 天摘要；总量接口可查更宽）
_WECHAT_TOKEN_PATH = "https://api.weixin.qq.com/cgi-bin/token"
_WECHAT_DATASTATS_TOTAL = "https://api.weixin.qq.com/datacube/getarticletotal"
# 回采窗口：公众号 datacube 仅保留近期数据，默认回采近 7 天
_WECHAT_LOOKBACK_DAYS = 7


@dataclass
class MetricsSnapshot:
    """A structured metrics snapshot fetched from a real platform API.

    Mirrors the ``ContentMetric`` numeric fields. ``engagement_rate`` defaults
    to -1.0 meaning "not provided by the platform"; the collector recomputes it
    from views/likes/comments/shares when negative.
    """

    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    followers_gained: int = 0
    followers_lost: int = 0
    engagement_rate: float = -1.0


class PlatformMetricsAdapter:
    """Abstract base for a per-platform metrics fetch adapter."""

    platform: Platform

    async def fetch_metrics(
        self, account: Any, external_ref: str | None
    ) -> MetricsSnapshot | None:
        """Fetch metrics for a published piece of content.

        Args:
            account: the ``PlatformAccount`` (duck-typed: has platform,
                account_id, auth_token).
            external_ref: external identifier of the published item (e.g. the
                platform-side content id or URL from ``PublishTask.external_url``).

        Returns a :class:`MetricsSnapshot`, or ``None`` to signal "unavailable"
        (no credentials / unsupported / network failure) so the caller can fall
        back to simulation.
        """
        raise NotImplementedError


class MetricsAdapterRegistry:
    """Registry mapping :class:`Platform` → :class:`PlatformMetricsAdapter`."""

    def __init__(self) -> None:
        self._adapters: dict[Platform, PlatformMetricsAdapter] = {}

    def register(self, adapter: PlatformMetricsAdapter) -> None:
        """Register an adapter for its declared platform (overwrites existing)."""
        self._adapters[adapter.platform] = adapter

    def get(self, platform: Platform) -> PlatformMetricsAdapter | None:
        """Return the adapter for *platform*, or None if unregistered."""
        return self._adapters.get(platform)

    def __len__(self) -> int:
        return len(self._adapters)


def default_metrics_adapter_registry() -> MetricsAdapterRegistry:
    """Build the default registry: WeChat Official is wired by default.

    The adapter degrades to ``None`` (simulation fallback) whenever credentials
    are missing, so registering it unconditionally is safe and enables real
    collection the moment ``WECHAT_APPID``/``WECHAT_SECRET`` are configured.
    """
    reg = MetricsAdapterRegistry()
    reg.register(WechatOfficialMetricsAdapter())
    return reg


def _default_request_executor(req: Any) -> bytes:  # pragma: no cover - thin wrapper
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        # req 为 Any 导致 resp 推导为 Any；按 urlopen 契约 cast 为 bytes
        return cast(bytes, resp.read())


def _parse_msgid(external_ref: str | None) -> str | None:
    """Extract a WeChat article msgid from an external reference.

    Supports:
    - a raw msgid, e.g. ``"26511012345"`` or ``"26511012345_1"``
    - a WeChat article URL carrying a ``mid`` query param (the URL form the
      publish flow stores in ``PublishTask.external_url``).

    Returns ``None`` when no usable id is found (caller falls back to sim).
    """
    if not external_ref:
        return None
    ref = str(external_ref).strip()
    if re.fullmatch(r"\d+(?:_\d+)?", ref):
        return ref
    parsed = urllib.parse.urlparse(ref)
    if parsed.scheme in ("http", "https"):
        mid = urllib.parse.parse_qs(parsed.query).get("mid")
        if mid and re.fullmatch(r"\d+(?:_\d+)?", mid[0]):
            return mid[0]
    return None


class WechatOfficialMetricsAdapter(PlatformMetricsAdapter):
    """WeChat Official Account data-stats adapter.

    Credentials are resolved in order: the account's ``auth_token`` (already a
    valid access token) → ``WECHAT_APPID``/``WECHAT_SECRET`` (exchanged for an
    access token, cached via :class:`OAuthTokenManager`). Any failure degrades
    to ``None`` so the collector falls back to simulation with a log event.

    ``request_executor`` is injectable for contract tests (mirrors the Feishu
    client pattern).
    """

    platform = Platform.WECHAT_OFFICIAL

    def __init__(
        self, request_executor: Any | None = None
    ) -> None:
        self._executor = request_executor or _default_request_executor
        self._oauth = OAuthTokenManager(refresh_fn=self._refresh_access_token)

    # ------------------------------------------------------------------
    # 凭据与 token
    # ------------------------------------------------------------------

    def _credentials(self, account: Any) -> tuple[str, str]:
        appid = os.environ.get("WECHAT_APPID", "").strip()
        secret = os.environ.get("WECHAT_SECRET", "").strip()
        if not appid and account is not None and getattr(account, "metadata_", None):
            try:
                meta = json.loads(account.metadata_)
                appid = str(meta.get("appid", "")).strip()
                secret = str(meta.get("secret", "")).strip()
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
        return appid, secret

    async def _refresh_access_token(
        self, account: Any | None = None
    ) -> TokenRefreshResult | None:
        """Exchange appid/secret for a fresh access token; None on any failure."""
        appid, secret = self._credentials(account)
        if not appid or not secret:
            return None
        url = (
            f"{_WECHAT_TOKEN_PATH}?grant_type=client_credential"
            f"&appid={urllib.parse.quote(appid)}&secret={urllib.parse.quote(secret)}"
        )
        req = urllib.request.Request(url)
        try:
            data = json.loads(self._executor(req))
        except Exception:  # noqa: BLE001 — network/parse failure must degrade
            return None
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            return None
        try:
            expires_in = max(60, int(data.get("expires_in", 7200)))
        except (TypeError, ValueError):
            expires_in = 7200
        return TokenRefreshResult(
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        )

    async def _resolve_token(self, account: Any) -> str | None:
        """Return a valid access token, refreshing when needed."""
        if account is not None and getattr(account, "auth_token", None):
            token = await self._oauth.ensure_valid_token(account)
            if token:
                return token
        result = await self._refresh_access_token(account)
        return result.token if result else None

    # ------------------------------------------------------------------
    # 数据回采
    # ------------------------------------------------------------------

    async def fetch_metrics(
        self, account: Any, external_ref: str | None
    ) -> MetricsSnapshot | None:
        """Fetch real article stats via the WeChat datacube API.

        Calls ``/datacube/getarticletotal`` for the article identified by
        *external_ref* across a rolling 7-day window, summing the daily rows.
        Returns ``None`` on missing credentials, missing msgid, or any API
        failure so the collector degrades gracefully.
        """
        token = await self._resolve_token(account)
        if not token:
            return None
        msgid = _parse_msgid(external_ref)
        if msgid is None:
            return None

        today = date.today()
        begin = today - timedelta(days=_WECHAT_LOOKBACK_DAYS)
        payload = {
            "begin_date": begin.isoformat(),
            "end_date": today.isoformat(),
            "msgid": msgid,
        }
        url = f"{_WECHAT_DATASTATS_TOTAL}?access_token={urllib.parse.quote(token)}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST"
        )
        req.add_header("Content-Type", "application/json")
        try:
            data = json.loads(self._executor(req))
        except Exception:  # noqa: BLE001 — network/parse failure must degrade
            return None
        if data.get("errcode", 0) != 0:
            return None
        rows = data.get("list") or []
        if not rows:
            return None

        def _sum(key: str) -> int:
            return sum(int(r.get(key, 0) or 0) for r in rows)

        # 公众号 getarticletotal 不返回点赞/评论数（datacube 无对应字段），
        # 如实留 0，避免把收藏数伪装成点赞。
        return MetricsSnapshot(
            views=_sum("int_page_read_count"),
            likes=0,
            comments=0,
            shares=_sum("share_count"),
            followers_gained=0,
            followers_lost=0,
            engagement_rate=-1.0,  # collector recomputes from the 4 fields
        )
