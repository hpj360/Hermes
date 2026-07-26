"""Parse skill-up result.json into structured dataclasses.

skill-up writes result.json to ``<skill-name>-workspace/iteration-N/``.
The exact schema is not fully documented — we parse defensively, treating
missing fields as defaults rather than errors. This isolates Hermes from
upstream schema drift.

Conventions:
- status is normalized to lowercase string: "passed" / "failed" / "error"
  / "skipped". Unknown values pass through as-is.
- pass_rate is a float in [0.0, 1.0] (skill-up may emit 0-100; we detect
  and normalize).
- tokens_used is int; missing → 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CaseResult:
    """Result of a single eval case.

    Fields map onto skill-up's per-case report. All fields have safe
    defaults so partial JSON (older skill-up versions) still parses.
    """

    id: str = ""
    name: str = ""
    status: str = "unknown"  # passed / failed / error / skipped / unknown
    pass_rate: float = 0.0  # normalized to [0.0, 1.0]
    tokens_used: int = 0
    duration_ms: int = 0
    error: str | None = None
    output: str = ""

    @property
    def passed(self) -> bool:
        """Convenience: status == "passed"."""
        return self.status == "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "pass_rate": self.pass_rate,
            "tokens_used": self.tokens_used,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "output": self.output,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaseResult":
        """Parse a case dict from result.json. Tolerant of missing fields."""
        # id and name: skill-up may use either; fall back to the other
        case_id = str(data.get("id") or data.get("name") or data.get("case_id") or "")
        name = str(data.get("name") or case_id)

        # status: normalize to lowercase
        status = str(data.get("status") or data.get("result") or "unknown").lower()

        # pass_rate: normalize to [0.0, 1.0]. skill-up may emit 0-100 or 0-1.
        raw_rate = data.get("pass_rate", data.get("passrate", 0.0))
        try:
            rate = float(raw_rate or 0.0)
        except (TypeError, ValueError):
            rate = 0.0
        if rate > 1.0:
            rate = rate / 100.0
        # Clamp to [0, 1]
        rate = max(0.0, min(1.0, rate))

        # tokens_used: int, missing → 0
        try:
            tokens = int(data.get("tokens_used") or data.get("tokens") or 0)
        except (TypeError, ValueError):
            tokens = 0

        # duration_ms: int, missing → 0
        try:
            duration = int(data.get("duration_ms") or data.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0

        error = data.get("error") or data.get("failure") or None
        if error is not None:
            error = str(error)

        output = str(data.get("output") or data.get("agent_output") or "")

        return cls(
            id=case_id,
            name=name,
            status=status,
            pass_rate=rate,
            tokens_used=tokens,
            duration_ms=duration,
            error=error,
            output=output,
        )


@dataclass
class EvalResult:
    """Aggregated result of a full `skill-up run`.

    Wraps the summary + cases list + metadata. Provides aggregate
    properties (total/passed/failed/pass_rate) that fall back to
    recomputing from cases when summary is missing.
    """

    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    cases: list[CaseResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    workspace: str = ""  # path to iteration-N dir
    raw: dict[str, Any] = field(default_factory=dict)  # original JSON

    @property
    def all_passed(self) -> bool:
        """True iff total > 0 and passed == total."""
        return self.total > 0 and self.passed == self.total

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "cases": [c.to_dict() for c in self.cases],
            "metadata": dict(self.metadata),
            "workspace": self.workspace,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], workspace: str = "") -> "EvalResult":
        """Parse result.json dict. Recomputes aggregates if summary missing."""
        summary = data.get("summary") or {}
        cases_raw = data.get("cases") or data.get("results") or []
        cases = [CaseResult.from_dict(c) for c in cases_raw if isinstance(c, dict)]
        metadata = data.get("metadata") or data.get("meta") or {}

        # Aggregate: prefer summary; fall back to recomputing from cases.
        try:
            total = int(summary.get("total", len(cases)))
        except (TypeError, ValueError):
            total = len(cases)
        try:
            passed = int(
                summary.get("passed", sum(1 for c in cases if c.passed))
            )
        except (TypeError, ValueError):
            passed = sum(1 for c in cases if c.passed)
        try:
            failed = int(
                summary.get("failed", total - passed)
            )
        except (TypeError, ValueError):
            failed = total - passed

        raw_rate = summary.get("pass_rate")
        if raw_rate is not None:
            try:
                rate = float(raw_rate)
                if rate > 1.0:
                    rate = rate / 100.0
                rate = max(0.0, min(1.0, rate))
            except (TypeError, ValueError):
                rate = (passed / total) if total > 0 else 0.0
        else:
            rate = (passed / total) if total > 0 else 0.0

        return cls(
            total=total,
            passed=passed,
            failed=failed,
            pass_rate=rate,
            cases=cases,
            metadata=metadata if isinstance(metadata, dict) else {},
            workspace=workspace,
            raw=data,
        )


def parse_result_json(path: str | Path) -> EvalResult:
    """Read and parse a result.json file.

    Args:
        path: Path to result.json (typically in iteration-N/ dir).

    Returns:
        EvalResult with workspace set to parent dir of path.

    Raises:
        FileNotFoundError: path does not exist.
        json.JSONDecodeError: file is not valid JSON.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"result.json not found: {p}")

    text = p.read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)

    workspace = str(p.parent)
    return EvalResult.from_dict(data, workspace=workspace)
