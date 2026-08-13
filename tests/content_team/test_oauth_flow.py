"""Unit tests for content_team OAuth token lifecycle (P1-3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hermes.content_team.auth import OAuthTokenManager, TokenRefreshResult
from hermes.content_team.models.platform import Platform, PlatformAccount


def _account(
    *,
    auth_token: str | None = "token-a",
    expires_at: datetime | None = None,
) -> PlatformAccount:
    return PlatformAccount(
        platform=Platform.WECHAT_OFFICIAL,
        display_name="测试号",
        auth_token=auth_token,
        token_expires_at=expires_at,
    )


def test_long_lived_token_not_expired():
    mgr = OAuthTokenManager()
    account = _account(expires_at=None)
    assert mgr.is_expired(account) is False


def test_expired_token_detected():
    mgr = OAuthTokenManager()
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    account = _account(expires_at=past)
    assert mgr.is_expired(account) is True


def test_skew_treats_near_expiry_as_expired():
    mgr = OAuthTokenManager(skew_seconds=300)
    near = datetime.now(timezone.utc) + timedelta(seconds=120)
    account = _account(expires_at=near)
    # 120s < 300s skew → considered expired (refresh early).
    assert mgr.is_expired(account) is True


async def test_valid_token_returned_without_refresh():
    mgr = OAuthTokenManager()
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    account = _account(expires_at=future)
    assert await mgr.ensure_valid_token(account) == "token-a"


async def test_expired_without_refresh_fn_returns_none():
    mgr = OAuthTokenManager()
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    account = _account(expires_at=past)
    assert await mgr.ensure_valid_token(account) is None


async def test_expired_token_refreshes():
    refreshed: list[str] = []

    async def _refresh(account):
        refreshed.append(account.display_name)
        return TokenRefreshResult(
            token="token-b",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )

    mgr = OAuthTokenManager(refresh_fn=_refresh)
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    account = _account(expires_at=past)
    result = await mgr.ensure_valid_token(account)
    assert result == "token-b"
    assert account.auth_token == "token-b"
    assert account.token_expires_at is not None
    assert len(refreshed) == 1


async def test_refresh_failure_returns_none():
    async def _refresh(account):
        return None

    mgr = OAuthTokenManager(refresh_fn=_refresh)
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    account = _account(expires_at=past)
    assert await mgr.ensure_valid_token(account) is None
    assert account.auth_token == "token-a"  # unchanged on failure
