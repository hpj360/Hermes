"""Tests for hermes.secrets (SecretSource abstraction) and the `hermes secrets` CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes.cli_secrets import _mask, _known_secret_keys
from hermes.main import main
from hermes.secrets import (
    BitwardenSecretSource,
    EnvFileSecretSource,
    EnvVarSecretSource,
    OnePasswordSecretSource,
    SECRET_SOURCES,
    get_secret_source,
    list_available_sources,
)


# ── EnvFileSecretSource ─────────────────────────────────────────────


def test_env_file_source_reads_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """EnvFileSecretSource 能从指定 .env 文件读取密钥。"""
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_FILE_SECRET=from-file-value\n", encoding="utf-8")
    # 确保进程环境变量中没有该 key，从而验证是从文件读取
    monkeypatch.delenv("TEST_FILE_SECRET", raising=False)

    source = EnvFileSecretSource(env_file=env_file)
    assert source.get_secret("TEST_FILE_SECRET") == "from-file-value"


def test_env_file_source_reads_from_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """EnvFileSecretSource 优先从进程环境变量读取（向后兼容 bootstrap_env 注入）。"""
    monkeypatch.setenv("TEST_ENVVAR_SECRET", "from-environ")
    env_file = tmp_path / ".env"  # 不存在也无所谓：环境变量优先
    source = EnvFileSecretSource(env_file=env_file)
    assert source.get_secret("TEST_ENVVAR_SECRET") == "from-environ"


def test_env_file_source_is_available(tmp_path: Path) -> None:
    """EnvFileSecretSource 始终可用。"""
    source = EnvFileSecretSource(env_file=tmp_path / ".env")
    assert source.is_available() is True
    assert source.source_name() == "env_file"


def test_env_file_source_returns_default_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """未命中时返回传入的 default。"""
    monkeypatch.delenv("DEFINITELY_NOT_SET_KEY", raising=False)
    source = EnvFileSecretSource(env_file=tmp_path / ".env")
    assert source.get_secret("DEFINITELY_NOT_SET_KEY", default="fallback") == "fallback"
    assert source.get_secret("DEFINITELY_NOT_SET_KEY") is None


# ── EnvVarSecretSource ──────────────────────────────────────────────


def test_env_var_source_reads_from_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """EnvVarSecretSource 从进程环境变量读取。"""
    monkeypatch.setenv("TEST_ENVVAR_ONLY", "env-value-123")
    source = EnvVarSecretSource()
    assert source.get_secret("TEST_ENVVAR_ONLY") == "env-value-123"
    assert source.is_available() is True
    assert source.source_name() == "env_var"


# ── BitwardenSecretSource / OnePasswordSecretSource ─────────────────


def test_bitwarden_source_not_available() -> None:
    """占位实现：BitwardenSecretSource 不可用。"""
    source = BitwardenSecretSource()
    assert source.is_available() is False
    assert source.source_name() == "bitwarden"


def test_bitwarden_source_raises_not_implemented() -> None:
    """占位实现：get_secret 抛 NotImplementedError。"""
    source = BitwardenSecretSource()
    with pytest.raises(NotImplementedError):
        source.get_secret("ANY_KEY")


def test_onepassword_source_not_available() -> None:
    """占位实现：OnePasswordSecretSource 不可用。"""
    source = OnePasswordSecretSource()
    assert source.is_available() is False
    assert source.source_name() == "onepassword"


def test_onepassword_source_raises_not_implemented() -> None:
    """占位实现：get_secret 抛 NotImplementedError。"""
    source = OnePasswordSecretSource()
    with pytest.raises(NotImplementedError):
        source.get_secret("ANY_KEY")


# ── Factory functions ───────────────────────────────────────────────


def test_get_secret_source_default_is_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置 HERMES_SECRET_SOURCE 时默认返回 EnvFileSecretSource。"""
    monkeypatch.delenv("HERMES_SECRET_SOURCE", raising=False)
    source = get_secret_source()
    assert isinstance(source, EnvFileSecretSource)
    assert source.source_name() == "env_file"


def test_get_secret_source_respects_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """HERMES_SECRET_SOURCE=env_var 时返回 EnvVarSecretSource。"""
    monkeypatch.setenv("HERMES_SECRET_SOURCE", "env_var")
    source = get_secret_source()
    assert isinstance(source, EnvVarSecretSource)
    assert source.source_name() == "env_var"


def test_get_secret_source_fallback_on_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """选择不可用的 source 时 fallback 到 env_file 并打印 warning。"""
    monkeypatch.setenv("HERMES_SECRET_SOURCE", "bitwarden")
    source = get_secret_source()
    assert isinstance(source, EnvFileSecretSource)
    assert source.source_name() == "env_file"
    err = capsys.readouterr().err
    assert "bitwarden" in err
    assert "env_file" in err


def test_get_secret_source_unknown_name_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知 SecretSource 名称时 fallback 到 env_file。"""
    monkeypatch.setenv("HERMES_SECRET_SOURCE", "totally-unknown")
    source = get_secret_source()
    assert isinstance(source, EnvFileSecretSource)


def test_list_available_sources() -> None:
    """list_available_sources 返回全部 4 个 source 及可用性状态。"""
    sources = list_available_sources()
    names = {s["name"] for s in sources}
    assert names == set(SECRET_SOURCES.keys())
    by_name = {s["name"]: s for s in sources}
    assert by_name["env_file"]["available"] is True
    assert by_name["env_var"]["available"] is True
    assert by_name["bitwarden"]["available"] is False
    assert by_name["onepassword"]["available"] is False


# ── CLI subcommands ─────────────────────────────────────────────────


def test_cli_secrets_list(
    tmp_state_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`hermes secrets list` 注册成功并返回 0。"""
    monkeypatch.delenv("HERMES_SECRET_SOURCE", raising=False)
    rc = main(["secrets", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "env_file" in out
    assert "bitwarden" in out
    assert "onepassword" in out


def test_cli_secrets_show_masks_value(
    tmp_state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`hermes secrets show <key>` 掩码显示，只露前 4 后 4 字符。"""
    monkeypatch.delenv("HERMES_SECRET_SOURCE", raising=False)
    monkeypatch.setenv("HERMES_TEST_SHOW_KEY", "abcdefghijklmnop")  # 长度 16 > 8
    rc = main(["secrets", "show", "HERMES_TEST_SHOW_KEY"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "abcd...mnop" in out
    # 明文不得出现在输出中
    assert "abcdefghijklmnop" not in out


def test_cli_secrets_show_unset_returns_soft_fail(
    tmp_state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`hermes secrets show` 对未设置的 key 返回 1（soft fail）。"""
    monkeypatch.delenv("HERMES_SECRET_SOURCE", raising=False)
    monkeypatch.delenv("HERMES_TEST_UNSET_KEY", raising=False)
    rc = main(["secrets", "show", "HERMES_TEST_UNSET_KEY"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "unset" in out


def test_cli_secrets_check(
    tmp_state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`hermes secrets check` 显示当前 source 与已配置密钥列表。"""
    monkeypatch.delenv("HERMES_SECRET_SOURCE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-check-test-12345")
    rc = main(["secrets", "check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SecretSource" in out
    assert "env_file" in out
    assert "OPENAI_API_KEY" in out


# ── CLI helper unit tests ───────────────────────────────────────────


def test_mask_long_value_reveals_first_and_last_four() -> None:
    """长密钥掩码后只露前 4 后 4。"""
    assert _mask("abcdefghijklmnop") == "abcd...mnop"


def test_mask_short_value_fully_masked() -> None:
    """短密钥（<=8）全掩码，不泄露内容。"""
    assert _mask("short") == "*****"
    assert _mask("12345678") == "********"


def test_known_secret_keys_includes_api_keys() -> None:
    """_known_secret_keys 包含已知 API key 类变量名。"""
    keys = _known_secret_keys()
    assert "OPENAI_API_KEY" in keys
    assert "ANTHROPIC_API_KEY" in keys
    assert "GITHUB_TOKEN" in keys
    # 端口/路径类配置不应被纳入
    assert "OPENCLAW_GATEWAY_PORT" not in keys
