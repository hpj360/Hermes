"""Unit tests for content_team analytics platform adapters (P1-1)."""

from __future__ import annotations

from hermes.content_team.analytics.adapters import (
    MetricsAdapterRegistry,
    MetricsSnapshot,
    PlatformMetricsAdapter,
    WechatOfficialMetricsAdapter,
)
from hermes.content_team.models.platform import Platform


def test_metrics_snapshot_defaults():
    snap = MetricsSnapshot()
    assert snap.views == 0
    assert snap.likes == 0
    assert snap.engagement_rate == -1.0  # -1 = "not provided"


def test_registry_register_and_get():
    class _Fake(PlatformMetricsAdapter):
        platform = Platform.DOUYIN

        async def fetch_metrics(self, account, external_ref):
            return MetricsSnapshot(views=10)

    reg = MetricsAdapterRegistry()
    reg.register(_Fake())
    assert len(reg) == 1
    assert reg.get(Platform.DOUYIN) is not None
    assert reg.get(Platform.BILIBILI) is None


def test_registry_overwrite_same_platform():
    class _A(PlatformMetricsAdapter):
        platform = Platform.XIAOHONGSHU

        async def fetch_metrics(self, account, external_ref):
            return MetricsSnapshot(views=1)

    class _B(PlatformMetricsAdapter):
        platform = Platform.XIAOHONGSHU

        async def fetch_metrics(self, account, external_ref):
            return MetricsSnapshot(views=2)

    reg = MetricsAdapterRegistry()
    reg.register(_A())
    reg.register(_B())
    assert len(reg) == 1


async def test_wechat_adapter_degrades_without_credentials(monkeypatch):
    monkeypatch.delenv("WECHAT_APPID", raising=False)
    monkeypatch.delenv("WECHAT_SECRET", raising=False)
    adapter = WechatOfficialMetricsAdapter()
    result = await adapter.fetch_metrics(account=None, external_ref=None)
    assert result is None


async def test_wechat_adapter_missing_token_degrades(monkeypatch):
    """Even with appid/secret, a failed token call must degrade to None."""
    monkeypatch.setenv("WECHAT_APPID", "appid")
    monkeypatch.setenv("WECHAT_SECRET", "secret")
    adapter = WechatOfficialMetricsAdapter()
    # The adapter's _access_token performs a network call; without a mock it
    # will fail and return None (fallback), which is the correct degradation.
    result = await adapter.fetch_metrics(account=None, external_ref=None)
    assert result is None


async def test_fake_adapter_returns_snapshot():
    class _Fake(PlatformMetricsAdapter):
        platform = Platform.WECHAT_OFFICIAL

        async def fetch_metrics(self, account, external_ref):
            return MetricsSnapshot(views=100, likes=20, comments=5, shares=3)

    adapter = _Fake()
    snap = await adapter.fetch_metrics(account=None, external_ref="url")
    assert snap is not None
    assert snap.views == 100
    assert snap.likes == 20
