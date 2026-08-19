"""traj-verify: append-only dispatch trajectory log with a reconstruction invariant."""

from .compliance import (
    Action,
    AuditContract,
    ComplianceReport,
    RuleVerdict,
    audit_compliance,
)
from .trajectory import (
    TrajectoryDesyncError,
    TrajectoryEvent,
    TrajectoryLogger,
    archive_trajectory,
    assert_reconstructable,
    verify_trajectory,
)

__all__ = [
    "Action",
    "AuditContract",
    "ComplianceReport",
    "RuleVerdict",
    "TrajectoryDesyncError",
    "TrajectoryEvent",
    "TrajectoryLogger",
    "archive_trajectory",
    "assert_reconstructable",
    "audit_compliance",
    "verify_trajectory",
]

__version__ = "0.1.0"
