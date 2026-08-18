"""traj-verify: append-only dispatch trajectory log with a reconstruction invariant."""

from .trajectory import (
    TrajectoryDesyncError,
    TrajectoryEvent,
    TrajectoryLogger,
    archive_trajectory,
    assert_reconstructable,
    verify_trajectory,
)

__all__ = [
    "TrajectoryDesyncError",
    "TrajectoryEvent",
    "TrajectoryLogger",
    "archive_trajectory",
    "assert_reconstructable",
    "verify_trajectory",
]

__version__ = "0.1.0"
