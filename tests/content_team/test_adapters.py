"""Unit tests for content_team analytics platform adapters (P1-1)."""

from __future__ import annotations

import json

from hermes.content_team.analytics.adapters import (
    MetricsAdapterRegistry,
    MetricsSnapshot,
    PlatformMetricsAdapter,
    WechatOfficialMetricsAdapter,
    _parse_msgid,
    default_metrics_adapter_registry,
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


def test_default_registry_registers_wechat():
    """默认注册表必须含公众号真实适配器，否则真实回采永不接线。"""
    reg = default_metrics_adapter_registry()
    assert reg.get(Platform.WECHAT_OFFICIAL) is not None


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
    # The adapter's token call performs a network request; without a mock it
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


# ---------------------------------------------------------------------------
# _parse_msgid
# ---------------------------------------------------------------------------


def test_parse_msgid_accepts_raw_id():
    assert _parse_msgid("26511012345") == "26511012345"
    assert _parse_msgid("26511012345_1") == "26511012345_1"
    assert _parse_msgid("  1234  ") == "1234"


def test_parse_msgid_accepts_url_mid_param():
    url = "https://mp.weixin.qq.com/s?__biz=MzA1&mid=26511012345&idx=1&sn=abc"
    assert _parse_msgid(url) == "26511012345"


def test_parse_msgid_rejects_unusable():
    assert _parse_msgid(None) is None
    assert _parse_msgid("") is None
    assert _parse_msgid("https://mp.weixin.qq.com/s/mock_abc") is None
    assert _parse_msgid("not-an-id") is None


# ---------------------------------------------------------------------------
# WeChat 真实 datacube 回采（fake executor 契约测试）
# ---------------------------------------------------------------------------


def _token_response():
    return json.dumps({"access_token": "tok-1", "expires_in": 7200}).encode("utf-8")


def _datacube_response():
    return json.dumps(
        {
            "errcode": 0,
            "list": [
                {
                    "ref_date": "2026-08-18",
                    "msgid": "26511012345_1",
                    "title": "t",
                    "int_page_read_count": 100,
                    "share_count": 3,
                },
                {
                    "ref_date": "2026-08-19",
                    "msgid": "26511012345_1",
                    "title": "t",
                    "int_page_read_count": 50,
                    "share_count": 2,
                },
            ],
        }
    ).encode("utf-8")


async def test_wechat_adapter_fetch_real_metrics(monkeypatch):
    """有 appid/secret 且 datacube 返回数据时，应返回真实快照（非模拟）。"""
    monkeypatch.setenv("WECHAT_APPID", "appid")
    monkeypatch.setenv("WECHAT_SECRET", "secret")
    calls: list[str] = []

    def fake_executor(req) -> bytes:  # noqa: ANN001
        calls.append(str(req.full_url))
        if "cgi-bin/token" in str(req.full_url):
            return _token_response()
        return _datacube_response()

    adapter = WechatOfficialMetricsAdapter(request_executor=fake_executor)
    snap = await adapter.fetch_metrics(
        account=None, external_ref="26511012345_1"
    )
    assert snap is not None
    assert snap.views == 150
    assert snap.shares == 5
    assert snap.likes == 0
    assert snap.comments == 0
    assert snap.engagement_rate == -1.0
    # 两次调用：token + datacube
    assert len(calls) == 2
    assert "datacube/getarticletotal" in calls[1]


async def test_wechat_adapter_datacube_error_degrades(monkeypatch):
    """datacube 返回 errcode 时应返回 None（回退模拟）。"""
    monkeypatch.setenv("WECHAT_APPID", "appid")
    monkeypatch.setenv("WECHAT_SECRET", "secret")

    def fake_executor(req) -> bytes:  # noqa: ANN001
        if "cgi-bin/token" in str(req.full_url):
            return _token_response()
        return json.dumps({"errcode": 45009, "errmsg": "reach max api limit"}).encode(
            "utf-8"
        )

    adapter = WechatOfficialMetricsAdapter(request_executor=fake_executor)
    snap = await adapter.fetch_metrics(
        account=None, external_ref="26511012345_1"
    )
    assert snap is None


async def test_wechat_adapter_no_msgid_degrades(monkeypatch):
    """external_ref 不含可识别 msgid 时应返回 None。"""
    monkeypatch.setenv("WECHAT_APPID", "appid")
    monkeypatch.setenv("WECHAT_SECRET", "secret")
    calls: list[str] = []

    def fake_executor(req) -> bytes:  # noqa: ANN001
        calls.append(str(req.full_url))
        return _token_response()

    adapter = WechatOfficialMetricsAdapter(request_executor=fake_executor)
    snap = await adapter.fetch_metrics(
        account=None, external_ref="https://mp.weixin.qq.com/s/not-a-msgid"
    )
    assert snap is None
    # 无 msgid 时不发 datacube 请求（只请求 token 或直接短路）
    assert "datacube/getarticletotal" not in " ".join(calls)
