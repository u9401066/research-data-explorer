"""QualityAssessor — Domain Service.

Evaluates data quality and produces a QualityReport.
Pure domain logic (scoring rules, threshold checks).
"""

from __future__ import annotations

from datetime import datetime

from rde.domain.models.profile import DataProfile
from rde.domain.models.quality import (
    IssueCategory,
    QualityIssue,
    QualityReport,
    Severity,
)


class QualityAssessor:
    """Assesses data quality from a DataProfile.

    Implements Hooks S-005 (missing pattern), S-006 (outlier strategy).
    """

    MISSING_THRESHOLD_WARNING = 0.05
    MISSING_THRESHOLD_CRITICAL = 0.50
    DUPLICATE_THRESHOLD = 0.01

    def assess(self, profile: DataProfile) -> QualityReport:
        """Produce a QualityReport from profiling results."""
        issues: list[QualityIssue] = []

        # Completeness checks
        completeness_score = self._check_completeness(profile, issues)

        # Uniqueness checks
        uniqueness_penalty = self._check_uniqueness(profile, issues)

        # Validity checks (via warnings from profiling engine)
        validity_score = self._check_validity(profile, issues)

        # PII checks
        self._check_pii(profile, issues)

        # Overall score
        overall = (
            completeness_score * 0.4
            + (100 - uniqueness_penalty) * 0.2
            + validity_score * 0.4
        )

        return QualityReport(
            dataset_id=profile.dataset_id,
            created_at=datetime.now(),
            issues=tuple(issues),
            overall_score=round(overall, 1),
            completeness_score=round(completeness_score, 1),
            consistency_score=100.0,  # Placeholder — needs cross-field checks
            validity_score=round(validity_score, 1),
        )

    def _check_completeness(
        self, profile: DataProfile, issues: list[QualityIssue]
    ) -> float:
        if not profile.variable_profiles:
            return 100.0

        total_penalty = 0.0
        for vp in profile.variable_profiles:
            if vp.missing_rate > self.MISSING_THRESHOLD_CRITICAL:
                issues.append(
                    QualityIssue(
                        category=IssueCategory.COMPLETENESS,
                        severity=Severity.CRITICAL,
                        variable_name=vp.variable_name,
                        description=(
                            f"Missing rate {vp.missing_rate:.1%} exceeds 50%."
                        ),
                        affected_rows=vp.missing_count,
                        suggestion="Consider dropping this variable or using imputation.",
                    )
                )
                total_penalty += 20
            elif vp.missing_rate > self.MISSING_THRESHOLD_WARNING:
                issues.append(
                    QualityIssue(
                        category=IssueCategory.COMPLETENESS,
                        severity=Severity.WARNING,
                        variable_name=vp.variable_name,
                        description=f"Missing rate {vp.missing_rate:.1%}.",
                        affected_rows=vp.missing_count,
                        suggestion="Review missing pattern (MCAR/MAR/MNAR).",
                    )
                )
                total_penalty += 5

        return max(0, 100 - total_penalty)

    def _check_uniqueness(
        self, profile: DataProfile, issues: list[QualityIssue]
    ) -> float:
        dup_rate = profile.duplicate_row_count / max(profile.row_count, 1)
        if dup_rate > self.DUPLICATE_THRESHOLD:
            issues.append(
                QualityIssue(
                    category=IssueCategory.UNIQUENESS,
                    severity=Severity.WARNING,
                    variable_name=None,
                    description=f"{profile.duplicate_row_count} duplicate rows ({dup_rate:.1%}).",
                    affected_rows=profile.duplicate_row_count,
                    suggestion="Review and consider removing duplicates.",
                )
            )
            return min(dup_rate * 100, 30)
        return 0.0

    def _check_validity(
        self, profile: DataProfile, issues: list[QualityIssue]
    ) -> float:
        penalty = len(profile.warnings) * 5
        for warning in profile.warnings:
            issues.append(
                QualityIssue(
                    category=IssueCategory.VALIDITY,
                    severity=Severity.INFO,
                    variable_name=None,
                    description=warning,
                )
            )
        return max(0, 100 - penalty)

    def _check_pii(
        self, profile: DataProfile, issues: list[QualityIssue]
    ) -> None:
        """Flag variables that were marked as PII suspects during profiling."""
        # This depends on variable metadata set by VariableClassifier
        # Here we check profile warnings for PII-related flags
        for warning in profile.warnings:
            if "pii" in warning.lower() or "personally identifiable" in warning.lower():
                issues.append(
                    QualityIssue(
                        category=IssueCategory.PII,
                        severity=Severity.CRITICAL,
                        variable_name=None,
                        description=warning,
                        suggestion="Remove or anonymize PII before analysis.",
                    )
                )
