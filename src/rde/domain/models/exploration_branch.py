"""Exploration branch domain models for Phase 8 YOLO exploration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BranchStatus(str, Enum):
    """Lifecycle state for an exploratory branch."""

    OPEN = "open"
    EXPERIMENTING = "experimenting"
    EVALUATED = "evaluated"
    PROMOTED = "promoted"
    DISCARDED = "discarded"
    CRASHED = "crashed"


class BranchType(str, Enum):
    """Exploration branch families that Phase 8 can run off-plan."""

    HYPOTHESIS = "hypothesis"
    SENSITIVITY = "sensitivity"
    ADJUSTED_MODEL = "adjusted_model"
    VISUALIZATION = "visualization"
    MISSING_STRATEGY = "missing_strategy"
    SUBGROUP = "subgroup"
    PROPENSITY = "propensity"
    SURVIVAL = "survival"
    ROC = "roc"
    REPEATED_MEASURES = "repeated_measures"
    YOLO = "yolo"


def _now_iso() -> str:
    return datetime.now().isoformat()


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _coerce_branch_status(value: BranchStatus | str | None) -> BranchStatus:
    if isinstance(value, BranchStatus):
        return value
    if value:
        try:
            return BranchStatus(str(value))
        except ValueError:
            return BranchStatus.OPEN
    return BranchStatus.OPEN


def _coerce_branch_type(value: BranchType | str | None) -> BranchType:
    if isinstance(value, BranchType):
        return value
    if value:
        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        try:
            return BranchType(normalized)
        except ValueError:
            return BranchType.YOLO
    return BranchType.HYPOTHESIS


@dataclass
class ExplorationBranch:
    """Current-state projection of an exploratory branch."""

    branch_id: str
    branch_type: BranchType = BranchType.HYPOTHESIS
    status: BranchStatus = BranchStatus.OPEN
    hypothesis: str = ""
    reason: str = ""
    project_id: str | None = None
    parent_plan_item: str | None = None
    variables: list[str] = field(default_factory=list)
    risk_level: str = "low"
    opened_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    experiments_count: int = 0
    last_evaluation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "branch_type": _enum_value(self.branch_type),
            "status": _enum_value(self.status),
            "hypothesis": self.hypothesis,
            "reason": self.reason,
            "project_id": self.project_id,
            "parent_plan_item": self.parent_plan_item,
            "variables": list(self.variables),
            "risk_level": self.risk_level,
            "opened_at": self.opened_at,
            "updated_at": self.updated_at,
            "experiments_count": self.experiments_count,
            "last_evaluation": self.last_evaluation,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExplorationBranch":
        return cls(
            branch_id=str(payload.get("branch_id", "")),
            branch_type=_coerce_branch_type(payload.get("branch_type")),
            status=_coerce_branch_status(payload.get("status")),
            hypothesis=str(payload.get("hypothesis") or ""),
            reason=str(payload.get("reason") or ""),
            project_id=payload.get("project_id"),
            parent_plan_item=payload.get("parent_plan_item"),
            variables=[str(v) for v in payload.get("variables") or []],
            risk_level=str(payload.get("risk_level") or "low"),
            opened_at=str(payload.get("opened_at") or payload.get("timestamp") or _now_iso()),
            updated_at=str(payload.get("updated_at") or payload.get("timestamp") or _now_iso()),
            experiments_count=int(payload.get("experiments_count") or 0),
            last_evaluation=payload.get("last_evaluation"),
        )


@dataclass
class BranchEvent:
    """Append-only branch lifecycle event."""

    branch_id: str
    event_type: str
    event_id: str
    timestamp: str = field(default_factory=_now_iso)
    project_id: str | None = None
    branch_type: BranchType = BranchType.HYPOTHESIS
    status: BranchStatus = BranchStatus.OPEN
    hypothesis: str = ""
    reason: str = ""
    parent_plan_item: str | None = None
    variables: list[str] = field(default_factory=list)
    risk_level: str = "low"
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "project_id": self.project_id,
            "branch_id": self.branch_id,
            "branch_type": _enum_value(self.branch_type),
            "status": _enum_value(self.status),
            "hypothesis": self.hypothesis,
            "reason": self.reason,
            "parent_plan_item": self.parent_plan_item,
            "variables": list(self.variables),
            "risk_level": self.risk_level,
            "payload": dict(self.payload),
        }


@dataclass
class ExperimentEvent:
    """Append-only experiment ledger event for a branch."""

    branch_id: str
    experiment_id: str
    experiment_type: str
    parameters: dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    status: str = "completed"
    timestamp: str = field(default_factory=_now_iso)
    project_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "experiment_id": self.experiment_id,
            "experiment_type": self.experiment_type,
            "parameters": dict(self.parameters),
            "result_summary": self.result_summary,
            "metrics": dict(self.metrics),
            "artifacts": list(self.artifacts),
            "status": self.status,
            "timestamp": self.timestamp,
            "project_id": self.project_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExperimentEvent":
        return cls(
            branch_id=str(payload.get("branch_id", "")),
            experiment_id=str(payload.get("experiment_id", "")),
            experiment_type=str(payload.get("experiment_type", "")),
            parameters=dict(payload.get("parameters") or {}),
            result_summary=str(payload.get("result_summary") or ""),
            metrics=dict(payload.get("metrics") or {}),
            artifacts=[str(v) for v in payload.get("artifacts") or []],
            status=str(payload.get("status") or "completed"),
            timestamp=str(payload.get("timestamp") or _now_iso()),
            project_id=payload.get("project_id"),
        )
