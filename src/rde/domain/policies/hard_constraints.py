"""Hard Constraints — Code-Enforced Policies.

These CANNOT be overridden by the user or Agent.
They protect data integrity, privacy, and system stability.
H-001~H-006: Original constraints
H-007~H-010: Audit trail enforcement (11-Phase Pipeline)
"""

from __future__ import annotations

from pathlib import Path

from rde.domain.models.dataset import Dataset
from rde.domain.models.report import EDAReport
from rde.domain.policies import ConstraintLevel, PolicyResult


class HardConstraints:
    """Collection of hard constraint checks (H-001 through H-010)."""

    @staticmethod
    def h001_file_size_guard(file_size_bytes: int) -> PolicyResult:
        """H-001: Reject files exceeding 500MB."""
        max_size = 500 * 1024 * 1024
        passed = file_size_bytes <= max_size
        size_mb = file_size_bytes / (1024 * 1024)
        return PolicyResult(
            passed=passed,
            constraint_id="H-001",
            level=ConstraintLevel.HARD,
            message=(
                f"File size {size_mb:.1f}MB is within limit."
                if passed
                else f"File size {size_mb:.1f}MB exceeds 500MB limit."
            ),
        )

    @staticmethod
    def h002_format_whitelist(file_format: str) -> PolicyResult:
        """H-002: Only allow supported file formats."""
        passed = file_format in Dataset.ALLOWED_FORMATS
        return PolicyResult(
            passed=passed,
            constraint_id="H-002",
            level=ConstraintLevel.HARD,
            message=(
                f"Format '{file_format}' is supported."
                if passed
                else (
                    f"Format '{file_format}' not supported. "
                    f"Allowed: {', '.join(sorted(Dataset.ALLOWED_FORMATS))}"
                )
            ),
        )

    @staticmethod
    def h003_min_sample_size(n: int, min_n: int = 10) -> PolicyResult:
        """H-003: Reject statistical analysis with n < 10."""
        passed = n >= min_n
        return PolicyResult(
            passed=passed,
            constraint_id="H-003",
            level=ConstraintLevel.HARD,
            message=(
                f"Sample size n={n} meets minimum requirement."
                if passed
                else f"Sample size n={n} is below minimum {min_n} for statistical analysis."
            ),
        )

    @staticmethod
    def h004_pii_detection(pii_variables: list[str]) -> PolicyResult:
        """H-004: Warn when potential PII columns are detected."""
        passed = len(pii_variables) == 0
        return PolicyResult(
            passed=passed,
            constraint_id="H-004",
            level=ConstraintLevel.HARD,
            message=(
                "No PII suspected."
                if passed
                else f"Potential PII detected in: {', '.join(pii_variables)}. "
                "Consider anonymizing before analysis."
            ),
            suggestion="Remove or anonymize PII columns." if not passed else "",
        )

    @staticmethod
    def h005_report_integrity(report: EDAReport) -> PolicyResult:
        """H-005: Report must contain all required sections."""
        errors = report.validate_integrity()
        passed = len(errors) == 0
        return PolicyResult(
            passed=passed,
            constraint_id="H-005",
            level=ConstraintLevel.HARD,
            message="Report integrity check passed." if passed else "; ".join(errors),
        )

    @staticmethod
    def h006_output_sanitization(content: str) -> PolicyResult:
        """H-006: Check for sensitive paths in output."""
        sensitive_patterns = [
            "C:\\Users\\",
            "/home/",
            "/Users/",
            "\\AppData\\",
        ]
        found = [p for p in sensitive_patterns if p in content]
        passed = len(found) == 0
        return PolicyResult(
            passed=passed,
            constraint_id="H-006",
            level=ConstraintLevel.HARD,
            message=(
                "No sensitive paths in output."
                if passed
                else f"Sensitive paths detected: {found}. Must be sanitized before export."
            ),
        )

    # ── Audit Trail Enforcement (11-Phase Pipeline) ──────────────────

    @staticmethod
    def h007_plan_lock_enforcement(plan_locked: bool, phase_index: int) -> PolicyResult:
        """H-007: Phase 6+ requires a locked analysis plan."""
        # Phase 6 (EXECUTE_EXPLORATION) index = 6
        if phase_index >= 6 and not plan_locked:
            return PolicyResult(
                passed=False,
                constraint_id="H-007",
                level=ConstraintLevel.HARD,
                message="Cannot execute exploration without a locked analysis plan.",
                suggestion="Complete Phase 4 (Plan Registration) to lock the plan.",
            )
        return PolicyResult(
            passed=True,
            constraint_id="H-007",
            level=ConstraintLevel.HARD,
            message="Plan lock status verified.",
        )

    @staticmethod
    def h008_artifact_gate(
        phase_name: str, required_artifacts: list[str], existing_artifacts: list[str]
    ) -> PolicyResult:
        """H-008: Previous phase artifacts must exist before advancing."""
        missing = [a for a in required_artifacts if a not in existing_artifacts]
        passed = len(missing) == 0
        return PolicyResult(
            passed=passed,
            constraint_id="H-008",
            level=ConstraintLevel.HARD,
            message=(
                f"All required artifacts present for {phase_name}."
                if passed
                else f"Missing artifacts for {phase_name}: {', '.join(missing)}"
            ),
        )

    @staticmethod
    def h009_decision_logging_required(
        phase_index: int, has_decision_log: bool
    ) -> PolicyResult:
        """H-009: Phase 6 operations must produce decision log entries."""
        # Only enforced during/after Phase 6
        if phase_index >= 6 and not has_decision_log:
            return PolicyResult(
                passed=False,
                constraint_id="H-009",
                level=ConstraintLevel.HARD,
                message="Exploration phase requires decision logging.",
                suggestion="Every analysis operation must be recorded in decision_log.jsonl.",
            )
        return PolicyResult(
            passed=True,
            constraint_id="H-009",
            level=ConstraintLevel.HARD,
            message="Decision logging requirement met.",
        )

    @staticmethod
    def h010_append_only_enforcement(
        log_path: Path, original_line_count: int, current_line_count: int
    ) -> PolicyResult:
        """H-010: Logs are append-only — line count must not decrease."""
        passed = current_line_count >= original_line_count
        return PolicyResult(
            passed=passed,
            constraint_id="H-010",
            level=ConstraintLevel.HARD,
            message=(
                "Log integrity intact (append-only verified)."
                if passed
                else (
                    f"Log tampering detected: {log_path.name} shrank from "
                    f"{original_line_count} to {current_line_count} lines."
                )
            ),
        )
