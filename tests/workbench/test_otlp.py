"""Tests for hermes.workbench.otlp (P2-6)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hermes.workbench.memory import Episode
from hermes.workbench.otlp import OtlpExporter


def _episode(trace_id: str = "trace-abc") -> Episode:
    return Episode(
        id="ep-123",
        kind="loop",
        summary="ran a plan",
        details={"trace_id": trace_id},
        created_at=1_700_000_000.5,
    )


def test_exporter_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    exporter = OtlpExporter()
    assert exporter.enabled is False
    assert exporter.export_episodes([_episode()]) is False


def test_exporter_enabled_with_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    assert OtlpExporter().enabled is True


def test_build_payload_structure() -> None:
    exporter = OtlpExporter(endpoint="http://collector:4318")
    payload = exporter.build_payload([_episode()])

    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 1
    span = spans[0]
    assert len(span["traceId"]) == 32  # 16 bytes hex
    assert len(span["spanId"]) == 16  # 8 bytes hex
    assert span["name"] == "loop"


def test_build_payload_uses_episode_id_when_no_trace_id() -> None:
    exporter = OtlpExporter(endpoint="http://collector:4318")
    ep = Episode(id="ep-xyz", kind="note", summary="s", details={}, created_at=1.0)
    payload = exporter.build_payload([ep])
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["traceId"]  # derived from episode id, still present


def test_export_posts_and_returns_true(monkeypatch) -> None:
    exporter = OtlpExporter(endpoint="http://collector:4318")
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=resp):
        assert exporter.export_episodes([_episode()]) is True


def test_export_degrades_on_network_failure(monkeypatch) -> None:
    import urllib.error

    exporter = OtlpExporter(endpoint="http://collector:4318")
    err = urllib.error.URLError("connection refused")
    with patch("urllib.request.urlopen", side_effect=err):
        assert exporter.export_episodes([_episode()]) is False
