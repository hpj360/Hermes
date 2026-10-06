"""Tests for agent_evolve.redteam: denylist matching semantics and coverage audit."""

from __future__ import annotations

from agent_evolve.redteam import (
    DEFAULT_DENYLIST,
    REDTEAM_PATHS,
    audit_denylist_coverage,
    matches_denylist,
)


class TestMatchesDenylist:
    def test_directory_prefix(self):
        assert matches_denylist("auth/login.py", DEFAULT_DENYLIST) == "auth/"

    def test_nested_directory_prefix(self):
        assert matches_denylist("src/auth/login.py", DEFAULT_DENYLIST) == "auth/"

    def test_exact_directory_name(self):
        assert matches_denylist("auth", DEFAULT_DENYLIST) == "auth/"

    def test_glob_suffix(self):
        assert matches_denylist("server.key", DEFAULT_DENYLIST) == "*.key"

    def test_exact_filename(self):
        assert matches_denylist(".env", DEFAULT_DENYLIST) == ".env"

    def test_benign_path_passes(self):
        assert matches_denylist("src/main.py", DEFAULT_DENYLIST) is None

    def test_backslash_normalized(self):
        assert matches_denylist("auth\\login.py", DEFAULT_DENYLIST) == "auth/"

    def test_key_container_and_extensionless_key(self):
        assert matches_denylist("certs/ca.pem", DEFAULT_DENYLIST) == "*.pem"
        assert matches_denylist("id_rsa", DEFAULT_DENYLIST) == "id_rsa"
        assert matches_denylist(".ssh/id_ed25519", DEFAULT_DENYLIST) == ".ssh/"

    def test_public_key_not_blocked(self):
        assert matches_denylist("id_rsa.pub", DEFAULT_DENYLIST) is None

    def test_dot_slash_prefix_stripped(self):
        assert matches_denylist("./.env", DEFAULT_DENYLIST) == ".env"

    def test_empty_inputs(self):
        assert matches_denylist("", DEFAULT_DENYLIST) is None
        assert matches_denylist("auth/x", []) is None


class TestAuditCoverage:
    def test_default_denylist_blocks_all(self):
        report = audit_denylist_coverage()
        assert report["coverage"] == 1.0
        assert report["missed"] == []
        assert report["false_positive"] == []

    def test_weakened_denylist_exposes_gap(self):
        # The pre-extension baseline misses extensionless private keys: the
        # audit must surface that regression, not silently pass.
        weakened = ["auth/", "payment/", "security/", ".env", "*.key"]
        report = audit_denylist_coverage(denylist=weakened)
        assert "id_rsa" in report["missed"]
        assert report["coverage"] < 1.0

    def test_custom_redteam_set(self):
        report = audit_denylist_coverage(
            redteam_paths=[("auth/x.py", True), ("README.md", False)]
        )
        assert report["blocked"] == ["auth/x.py"]
        assert report["coverage"] == 1.0

    def test_empty_redteam_set_full_coverage(self):
        report = audit_denylist_coverage(redteam_paths=[])
        assert report["coverage"] == 1.0

    def test_redteam_paths_wellformed(self):
        for path, expected in REDTEAM_PATHS:
            assert isinstance(path, str) and path
            assert isinstance(expected, bool)
