"""CleaningPlan / CleaningAction — Entity.

Represents a proposed data cleaning plan that must be confirmed
by the user before execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CleaningActionType(Enum):
    """Type of cleaning action."""

    DROP_ROWS = "drop_rows"
    DROP_COLUMNS = "drop_columns"
    FILL_MISSING = "fill_missing"
    FILL_MEAN = "fill_mean"
    FILL_MEDIAN = "fill_median"
    FILL_MODE = "fill_mode"
    FILL_CONSTANT = "fill_constant"
    REMOVE_DUPLICATES = "remove_duplicates"
    CLIP_OUTLIERS = "clip_outliers"
    REMOVE_OUTLIERS = "remove_outliers"
    TYPE_CAST = "type_cast"
    RENAME_COLUMN = "rename_column"
    ENCODE_CATEGORICAL = "encode_categorical"
    CUSTOM = "custom"


@dataclass
class CleaningAction:
    """A single cleaning operation."""

    action_type: CleaningActionType
    target_variable: str | None  # None for dataset-level actions
    description: str
    rationale: str  # Why this is suggested
    params: dict[str, Any] = field(default_factory=dict)
    approved: bool = False
    applied: bool = False

    def approve(self) -> None:
        self.approved = True

    def mark_applied(self) -> None:
        if not self.approved:
            raise ValueError("Cannot apply unapproved cleaning action.")
        self.applied = True


@dataclass
class CleaningPlan:
    """A set of proposed cleaning actions for a dataset.

    Domain Rule: All actions must be approved before execution.
    """

    dataset_id: str
    actions: list[CleaningAction] = field(default_factory=list)

    def add_action(self, action: CleaningAction) -> None:
        self.actions.append(action)

    def approve_all(self) -> None:
        for action in self.actions:
            action.approve()

    def approve_by_index(self, indices: list[int]) -> None:
        for i in indices:
            if 0 <= i < len(self.actions):
                self.actions[i].approve()

    @property
    def approved_actions(self) -> list[CleaningAction]:
        return [a for a in self.actions if a.approved]

    @property
    def pending_actions(self) -> list[CleaningAction]:
        return [a for a in self.actions if not a.approved]

    @property
    def all_approved(self) -> bool:
        return all(a.approved for a in self.actions)

    @property
    def all_applied(self) -> bool:
        return all(a.applied for a in self.actions if a.approved)
