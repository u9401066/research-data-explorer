"""Decision Logger — Append-only audit trail for the EDA pipeline.

Provides two append-only JSONL logs:
  - decision_log.jsonl: Records every analysis decision during Phase 6
  - deviation_log.jsonl: Records deviations from the registered plan

Both logs are append-only (H-010 enforced).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DecisionEntry:
    """A single analysis decision record."""

    timestamp: str
    phase: str
    action: str
    tool_used: str
    parameters: dict[str, Any]
    rationale: str
    result_summary: str
    artifacts_produced: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DeviationEntry:
    """A record of deviation from the registered analysis plan."""

    timestamp: str
    phase: str
    planned_action: str
    actual_action: str
    reason: str
    impact_assessment: str


class DecisionLogger:
    """Append-only logger for analysis decisions and plan deviations."""

    def __init__(self, project_dir: Path) -> None:
        self._decision_log = project_dir / "decision_log.jsonl"
        self._deviation_log = project_dir / "deviation_log.jsonl"
        self._decision_line_count: int | None = None
        self._deviation_line_count: int | None = None

    def _ensure_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()

    def _append(self, path: Path, data: dict[str, Any]) -> None:
        self._ensure_file(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")

    def _count_lines(self, path: Path) -> int:
        if not path.exists():
            return 0
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)

    def log_decision(
        self,
        phase: str,
        action: str,
        tool_used: str,
        parameters: dict[str, Any],
        rationale: str,
        result_summary: str,
        artifacts: list[str] | None = None,
    ) -> DecisionEntry:
        """Append a decision entry to the decision log."""
        entry = DecisionEntry(
            timestamp=datetime.now().isoformat(),
            phase=phase,
            action=action,
            tool_used=tool_used,
            parameters=parameters,
            rationale=rationale,
            result_summary=result_summary,
            artifacts_produced=artifacts or [],
        )
        self._append(self._decision_log, asdict(entry))
        return entry

    def log_deviation(
        self,
        phase: str,
        planned_action: str,
        actual_action: str,
        reason: str,
        impact_assessment: str,
    ) -> DeviationEntry:
        """Append a deviation entry to the deviation log."""
        entry = DeviationEntry(
            timestamp=datetime.now().isoformat(),
            phase=phase,
            planned_action=planned_action,
            actual_action=actual_action,
            reason=reason,
            impact_assessment=impact_assessment,
        )
        self._append(self._deviation_log, asdict(entry))
        return entry

    def snapshot_line_counts(self) -> tuple[int, int]:
        """Snapshot current line counts for H-010 verification."""
        self._decision_line_count = self._count_lines(self._decision_log)
        self._deviation_line_count = self._count_lines(self._deviation_log)
        return self._decision_line_count, self._deviation_line_count

    def verify_append_only(self) -> tuple[bool, str]:
        """Verify logs haven't been tampered with (H-010)."""
        if self._decision_line_count is None or self._deviation_line_count is None:
            return True, "No baseline snapshot — cannot verify."

        current_decision = self._count_lines(self._decision_log)
        current_deviation = self._count_lines(self._deviation_log)

        baseline_decision = self._decision_line_count
        baseline_deviation = self._deviation_line_count

        if current_decision < baseline_decision:
            return False, (
                f"decision_log.jsonl shrank: {baseline_decision} → {current_decision}"
            )
        if current_deviation < baseline_deviation:
            return False, (
                f"deviation_log.jsonl shrank: {baseline_deviation} → {current_deviation}"
            )
        return True, "Append-only integrity verified."

    def read_decisions(self) -> list[dict[str, Any]]:
        """Read all decision log entries."""
        if not self._decision_log.exists():
            return []
        entries = []
        with open(self._decision_log, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def read_deviations(self) -> list[dict[str, Any]]:
        """Read all deviation log entries."""
        if not self._deviation_log.exists():
            return []
        entries = []
        with open(self._deviation_log, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    @property
    def decision_count(self) -> int:
        return self._count_lines(self._decision_log)

    @property
    def deviation_count(self) -> int:
        return self._count_lines(self._deviation_log)
