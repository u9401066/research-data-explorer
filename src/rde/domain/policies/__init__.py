"""Domain Policies — Hard and Soft Constraints.

Hard Constraints (Code-Enforced): Automatically prevent invalid operations.
Soft Constraints (Agent-Driven): Guidance returned to the Agent for user communication.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConstraintLevel(Enum):
    HARD = "hard"  # Code-enforced, cannot be overridden
    SOFT = "soft"  # Agent-driven, user can decide


@dataclass(frozen=True)
class PolicyResult:
    """Result of a policy check."""

    passed: bool
    constraint_id: str
    level: ConstraintLevel
    message: str
    suggestion: str = ""
