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
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from hermes.content_team.models.platform import Platform

__all__ = [
    "MetricsAdapterRegistry",
    "MetricsSnapshot",
    "PlatformMetricsAdapter",
    "WechatOfficialMetricsAdapter",
]


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


class WechatOfficialMetricsAdapter(PlatformMetricsAdapter):
    """Reference implementation for the WeChat Official Account data API.

    WeChat's data-stats API requires an ``access_token`` obtained via the
    appid/appsecret credential flow. This adapter is a stdlib-only HTTP client
    skeleton: it reads ``WECHAT_APPID`` / ``WECHAT_SECRET`` from the
    environment and degrades to ``None`` (triggering simulation fallback) when
    credentials are missing or the API call fails.

    The exact endpoint/response mapping for article-level statistics varies by
    WeChat account tier; the ``_request`` helper and field mapping are the
    extension points for a live integration.
    """

    platform = Platform.WECHAT_OFFICIAL
    API_BASE = "https://api.weixin.qq.com"

    def _access_token(self) -> str | None:
        appid = os.environ.get("WECHAT_APPID", "").strip()
        secret = os.environ.get("WECHAT_SECRET", "").strip()
        if not appid or not secret:
            return None
        url = (
            f"{self.API_BASE}/cgi-bin/token"
            f"?grant_type=client_credential&appid={appid}&secret={secret}"
        )
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None
        token = data.get("access_token")
        return token if isinstance(token, str) else None

    async def fetch_metrics(
        self, account: Any, external_ref: str | None
    ) -> MetricsSnapshot | None:
        token = self._access_token()
        if token is None:
            return None
        # Real integration would POST to /datacube/getarticletotal with the
        # article's msgid; here we return None to fall back to simulation until
        # the account-specific field mapping is wired with real credentials.
        return None
