"""Skill evaluation framework integration (alibaba/skill-up).

This module integrates the external `skill-up` Go binary as Hermes's
Skill quality evaluator. skill-up is invoked via subprocess — Hermes
never imports Go code, preserving the pure-Python runtime boundary.

Core value:
- Fills the "Skill functional correctness verification" gap (audit_loop
  only checks scaffolding presence, not behavior).
- Provides an objective scorer for GEPA self-evolution (result.json →
  VariantResult), moving GEPA from stub to usable.
- CI-friendly: JUnit XML + semantic exit codes plug into ci-sweeper loop.

Design principles (first-principles):
1. Zero hard dependency: skill-up is optional. If binary is missing, all
   operations degrade gracefully (clear error, no crash).
2. No YAML parsing on Python side — skill-up owns eval.yaml/case.yaml
   parsing. Hermes only manages paths + parses JSON results (stdlib only).
3. Test-friendly: SkillUpClient takes a runner injection point so tests
   mock subprocess without installing the binary.
4. Decoupled from GEPA: gepa_bridge is a thin adapter; eval module itself
   knows nothing about GEPA.
"""

from __future__ import annotations

from hermes.eval.client import SkillUpClient, SkillUpError, SkillUpNotFoundError
from hermes.eval.gepa_bridge import make_evaluator
from hermes.eval.result import CaseResult, EvalResult, parse_result_json
from hermes.eval.runner import EvalRunner, ValidationResult

__all__ = [
    "CaseResult",
    "EvalResult",
    "EvalRunner",
    "SkillUpClient",
    "SkillUpError",
    "SkillUpNotFoundError",
    "ValidationResult",
    "make_evaluator",
    "parse_result_json",
]
