"""content_team crypto + API auth + at-rest encryption tests."""

from __future__ import annotations

import pytest

from hermes.content_team.crypto import decrypt, encrypt, get_secret
from hermes.content_team.models.platform import EncryptedText, PlatformAccount


class TestCrypto:
    def test_encrypt_decrypt_roundtrip(self) -> None:
        blob = encrypt("my-secret", "wx_token_abc123")
        assert blob != "wx_token_abc123"
        assert decrypt("my-secret", blob) == "wx_token_abc123"

    def test_wrong_key_fails(self) -> None:
        blob = encrypt("key-a", "value")
        assert decrypt("key-b", blob) is None

    def test_corrupt_blob_returns_none(self) -> None:
        blob = encrypt("key", "value")
        corrupted = blob[:-4] + "AAAA"
        assert decrypt("key", corrupted) is None

    def test_empty_and_none(self) -> None:
        assert decrypt("key", "") is None
        blob = encrypt("key", "")
        assert decrypt("key", blob) == ""

    def test_unicode(self) -> None:
        blob = encrypt("key", "小红书 token 中文")
        assert decrypt("key", blob) == "小红书 token 中文"


class TestEncryptedText:
    def test_bind_encrypts_when_secret_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "hermes.content_team.crypto.get_secret", lambda: "test-secret"
        )
        tc = EncryptedText()
        bound = tc.process_bind_param("tok-123", None)
        assert isinstance(bound, str)
        assert bound != "tok-123"
        # round-trip through decrypt
        from hermes.content_team.crypto import decrypt as _dec

        assert _dec("test-secret", bound) == "tok-123"

    def test_bind_passthrough_without_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "hermes.content_team.crypto.get_secret", lambda: None
        )
        tc = EncryptedText()
        assert tc.process_bind_param("plain", None) == "plain"

    def test_result_legacy_plaintext_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "hermes.content_team.crypto.get_secret", lambda: "test-secret"
        )
        tc = EncryptedText()
        # Legacy plaintext value cannot be decrypted → returned as-is.
        assert tc.process_result_value("legacy-plain", None) == "legacy-plain"

    def test_result_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "hermes.content_team.crypto.get_secret", lambda: "test-secret"
        )
        tc = EncryptedText()
        bound = tc.process_bind_param("enc-me", None)
        assert tc.process_result_value(bound, None) == "enc-me"

    def test_get_secret_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeSettings:
            hermes_secret_key = "from-settings"

        monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
        assert get_secret() == "from-settings"


class TestRequireApiToken:
    def test_no_token_dev_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from hermes.content_team.api.auth import require_api_token

        class FakeSettings:
            hermes_api_token = None
            openclaw_gateway_token = ""

        monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
        # dev mode: no token configured → allowed without header
        assert require_api_token(None) is None

    def test_valid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from hermes.content_team.api.auth import require_api_token

        class FakeSettings:
            hermes_api_token = "ct-secret"
            openclaw_gateway_token = None

        monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
        assert require_api_token("Bearer ct-secret") is None

    def test_invalid_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi import HTTPException

        from hermes.content_team.api.auth import require_api_token

        class FakeSettings:
            hermes_api_token = "ct-secret"
            openclaw_gateway_token = None

        monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
        with pytest.raises(HTTPException) as exc:
            require_api_token(None)
        assert exc.value.status_code == 401
        with pytest.raises(HTTPException):
            require_api_token("Bearer wrong")


def test_platform_account_columns_are_encrypted_text() -> None:
    """auth_token/refresh_token use the EncryptedText type at rest."""
    col = PlatformAccount.__table__.c.auth_token
    assert isinstance(col.type, EncryptedText)
    refresh = PlatformAccount.__table__.c.refresh_token
    assert isinstance(refresh.type, EncryptedText)
