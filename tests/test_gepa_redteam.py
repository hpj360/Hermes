"""Tests for GEPA red-team denylist strength regression (P3-1)."""

from __future__ import annotations

from hermes.gepa_redteam import (
    DEFAULT_DENYLIST,
    audit_denylist_coverage,
    matches_denylist,
)


def test_matches_denylist_directory_prefix():
    assert matches_denylist("auth/admin.py", DEFAULT_DENYLIST) == "auth/"
    assert matches_denylist("src/auth/login.py", DEFAULT_DENYLIST) == "auth/"


def test_matches_denylist_exact_basename():
    assert matches_denylist(".env", DEFAULT_DENYLIST) == ".env"
    assert matches_denylist("./.env", DEFAULT_DENYLIST) == ".env"


def test_matches_denylist_glob():
    assert matches_denylist("server.key", DEFAULT_DENYLIST) == "*.key"
    assert matches_denylist("certs/private.key", DEFAULT_DENYLIST) == "*.key"


def test_matches_denylist_benign_path_not_blocked():
    assert matches_denylist("CHANGELOG.md", DEFAULT_DENYLIST) is None
    assert matches_denylist("src/main.py", DEFAULT_DENYLIST) is None


def test_matches_denylist_windows_separator():
    # Windows 反斜杠应归一化为 / 后仍命中。
    assert matches_denylist("auth\\admin.py", DEFAULT_DENYLIST) == "auth/"


def test_audit_denylist_coverage_blocks_all_redteam():
    result = audit_denylist_coverage()
    # The default red-team set has one known gap (id_rsa, no extension).
    assert "id_rsa" in result["missed"]
    assert result["coverage"] >= 0.8
    # All must-block paths except the known gap are blocked.
    assert "auth/admin.py" in result["blocked"]
    assert ".env" in result["blocked"]


def test_audit_denylist_coverage_full_with_extended_rules():
    """Adding a rule for extensionless private keys closes the known gap."""
    extended = DEFAULT_DENYLIST + ["id_rsa", "id_ed25519"]
    result = audit_denylist_coverage(denylist=extended)
    assert result["missed"] == []
    assert result["coverage"] == 1.0


def test_audit_denylist_no_false_positive():
    result = audit_denylist_coverage()
    assert result["false_positive"] == []
