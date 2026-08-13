"""OTLP (OpenTelemetry Protocol) trace exporter — HTTP/JSON skeleton (P2-6).

Exports workbench episodes (stamped with a ``trace_id`` by ``tracing.Tracer``)
to an OpenTelemetry collector over the OTLP/HTTP JSON endpoint
(``{OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces``).

Zero-runtime-dependency constraint: this uses stdlib ``urllib`` only. When
``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset the exporter is a no-op (``enabled``
is False and every ``export_*`` returns False), so the default path is
unchanged and collector wiring is fully opt-in.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Any

__all__ = ["OtlpExporter"]


def _hex_fragment(text: str, n_bytes: int) -> str:
    """Deterministic hex id of *n_bytes* bytes (OTLP requires 16B/8B hex ids)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[: n_bytes * 2]


class OtlpExporter:
    """Export episodes as OTLP spans to an OpenTelemetry collector."""

    def __init__(
        self,
        endpoint: str | None = None,
        service_name: str = "hermes",
        timeout: float = 10.0,
    ) -> None:
        self._endpoint = (
            endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        ).rstrip("/")
        self._service_name = service_name
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        """True when an OTLP endpoint is configured (otherwise no-op)."""
        return bool(self._endpoint)

    def export_episodes(self, episodes: list[Any]) -> bool:
        """Export a batch of episodes as OTLP spans. Returns success (bool)."""
        if not self.enabled or not episodes:
            return False
        payload = self.build_payload(episodes)
        return self._post(payload)

    def build_payload(self, episodes: list[Any]) -> dict[str, Any]:
        """Build the OTLP/HTTP JSON payload for a batch of episodes."""
        spans: list[dict[str, Any]] = []
        for ep in episodes:
            trace_id = (ep.details or {}).get("trace_id") or ep.id
            created_ns = int(ep.created_at * 1_000_000_000)
            spans.append(
                {
                    "traceId": _hex_fragment(trace_id, 16),
                    "spanId": _hex_fragment(ep.id, 8),
                    "name": ep.kind,
                    "kind": 1,  # INTERNAL
                    "startTimeUnixNano": str(created_ns),
                    "endTimeUnixNano": str(created_ns),
                    "attributes": [
                        {"key": "episode.id", "value": {"stringValue": ep.id}},
                        {"key": "episode.summary", "value": {"stringValue": ep.summary}},
                        {"key": "trace_id", "value": {"stringValue": trace_id}},
                    ],
                }
            )
        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": self._service_name},
                            }
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "hermes.workbench"},
                            "spans": spans,
                        }
                    ],
                }
            ]
        }

    def _post(self, payload: dict[str, Any]) -> bool:
        url = f"{self._endpoint}/v1/traces"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return bool(200 <= resp.status < 300)
        except (urllib.error.URLError, OSError):
            return False
