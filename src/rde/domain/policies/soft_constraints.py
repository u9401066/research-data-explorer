"""Soft Constraints — Agent-Driven Policies.

These are advisory. The Agent communicates them to the user,
who can decide whether to follow the advice.
S-001~S-010: Original statistical advisories
S-011~S-012: Audit trail advisories (11-Phase Pipeline)
"""

from __future__ import annotations

from rde.domain.models.variable import VariableType
from rde.domain.policies import ConstraintLevel, PolicyResult


class SoftConstraints:
    """Collection of soft constraint checks (S-001 through S-012)."""

    @staticmethod
    def s001_normality_check(
        is_normal: bool | None, p_value: float | None
    ) -> PolicyResult:
        """S-001: Check normality before parametric tests."""
        if is_normal is None:
            return PolicyResult(
                passed=False,
                constraint_id="S-001",
                level=ConstraintLevel.SOFT,
                message="Normality not yet tested. Run normality check first.",
                suggestion="Use Shapiro-Wilk test (n<50) or Kolmogorov-Smirnov (n≥50).",
            )
        if not is_normal:
            return PolicyResult(
                passed=False,
                constraint_id="S-001",
                level=ConstraintLevel.SOFT,
                message=f"Data is not normally distributed (p={p_value:.4f}).",
                suggestion="Consider non-parametric alternatives.",
            )
        return PolicyResult(
            passed=True,
            constraint_id="S-001",
            level=ConstraintLevel.SOFT,
            message="Normality assumption met.",
        )

    @staticmethod
    def s002_multiple_comparisons(n_comparisons: int) -> PolicyResult:
        """S-002: Warn about multiple comparison correction."""
        if n_comparisons <= 1:
            return PolicyResult(
                passed=True,
                constraint_id="S-002",
                level=ConstraintLevel.SOFT,
                message="Single comparison — no correction needed.",
            )
        method = "Bonferroni" if n_comparisons <= 5 else "Benjamini-Hochberg (FDR)"
        return PolicyResult(
            passed=False,
            constraint_id="S-002",
            level=ConstraintLevel.SOFT,
            message=f"{n_comparisons} comparisons detected.",
            suggestion=f"Apply {method} correction to control false positive rate.",
        )

    @staticmethod
    def s003_visualization_advisor(
        var_type: VariableType, n_groups: int = 0
    ) -> PolicyResult:
        """S-003: Suggest appropriate visualization."""
        suggestions = {
            VariableType.CONTINUOUS: "Histogram + boxplot (or violin plot if comparing groups).",
            VariableType.CATEGORICAL: "Bar chart (or grouped bar chart for comparisons).",
            VariableType.BINARY: "Stacked bar chart or proportion plot.",
            VariableType.ORDINAL: "Ordered bar chart or heatmap.",
            VariableType.DATETIME: "Time series line plot.",
        }
        suggestion = suggestions.get(var_type, "Consult user for appropriate chart type.")
        return PolicyResult(
            passed=True,
            constraint_id="S-003",
            level=ConstraintLevel.SOFT,
            message=f"Recommended visualization for {var_type.value}.",
            suggestion=suggestion,
        )

    @staticmethod
    def s004_transform_suggestion(skewness: float | None) -> PolicyResult:
        """S-004: Suggest transformation for skewed distribution."""
        if skewness is None:
            return PolicyResult(
                passed=True,
                constraint_id="S-004",
                level=ConstraintLevel.SOFT,
                message="Skewness not computed.",
            )
        if abs(skewness) > 1.0:
            return PolicyResult(
                passed=False,
                constraint_id="S-004",
                level=ConstraintLevel.SOFT,
                message=f"High skewness ({skewness:.2f}).",
                suggestion="Consider log or square-root transformation.",
            )
        return PolicyResult(
            passed=True,
            constraint_id="S-004",
            level=ConstraintLevel.SOFT,
            message=f"Skewness ({skewness:.2f}) within acceptable range.",
        )

    @staticmethod
    def s007_collinearity_warning(max_vif: float) -> PolicyResult:
        """S-007: Warn about multicollinearity."""
        if max_vif > 10:
            return PolicyResult(
                passed=False,
                constraint_id="S-007",
                level=ConstraintLevel.SOFT,
                message=f"VIF = {max_vif:.1f} indicates multicollinearity.",
                suggestion="Consider removing or combining collinear variables.",
            )
        return PolicyResult(
            passed=True,
            constraint_id="S-007",
            level=ConstraintLevel.SOFT,
            message=f"VIF = {max_vif:.1f} — no multicollinearity concern.",
        )

    @staticmethod
    def s008_sample_balance(group_sizes: list[int]) -> PolicyResult:
        """S-008: Check group size balance."""
        if not group_sizes or len(group_sizes) < 2:
            return PolicyResult(
                passed=True,
                constraint_id="S-008",
                level=ConstraintLevel.SOFT,
                message="Not applicable — fewer than 2 groups.",
            )
        ratio = max(group_sizes) / max(min(group_sizes), 1)
        if ratio > 3:
            return PolicyResult(
                passed=False,
                constraint_id="S-008",
                level=ConstraintLevel.SOFT,
                message=f"Group size ratio {ratio:.1f}:1 is highly imbalanced.",
                suggestion="Consider stratified analysis or weighted methods.",
            )
        return PolicyResult(
            passed=True,
            constraint_id="S-008",
            level=ConstraintLevel.SOFT,
            message=f"Group size ratio {ratio:.1f}:1 is acceptable.",
        )

    @staticmethod
    def s009_effect_size_reminder(
        p_value: float, effect_size: float | None
    ) -> PolicyResult:
        """S-009: Remind that statistical significance ≠ clinical importance."""
        if p_value < 0.05 and effect_size is not None and abs(effect_size) < 0.2:
            return PolicyResult(
                passed=False,
                constraint_id="S-009",
                level=ConstraintLevel.SOFT,
                message="Statistically significant but small effect size.",
                suggestion=(
                    "Effect size is small — consider clinical/practical significance."
                ),
            )
        return PolicyResult(
            passed=True,
            constraint_id="S-009",
            level=ConstraintLevel.SOFT,
            message="Effect size noted.",
        )

    @staticmethod
    def s010_power_analysis_hint(p_value: float, n: int) -> PolicyResult:
        """S-010: Suggest power analysis for non-significant results."""
        if p_value >= 0.05 and n < 100:
            return PolicyResult(
                passed=False,
                constraint_id="S-010",
                level=ConstraintLevel.SOFT,
                message=f"Non-significant result (p={p_value:.4f}) with small sample (n={n}).",
                suggestion="Consider post-hoc power analysis — may be underpowered.",
            )
        return PolicyResult(
            passed=True,
            constraint_id="S-010",
            level=ConstraintLevel.SOFT,
            message="Power consideration noted.",
        )

    # ── Audit Trail Advisories (11-Phase Pipeline) ───────────────────

    @staticmethod
    def s011_plan_deviation_alert(
        planned_action: str, actual_action: str
    ) -> PolicyResult:
        """S-011: Alert when execution deviates from the registered plan."""
        if planned_action != actual_action:
            return PolicyResult(
                passed=False,
                constraint_id="S-011",
                level=ConstraintLevel.SOFT,
                message=(
                    f"Deviation detected: planned '{planned_action}', "
                    f"actual '{actual_action}'."
                ),
                suggestion=(
                    "Record this deviation in deviation_log.jsonl with justification. "
                    "This is normal in exploratory analysis but must be documented."
                ),
            )
        return PolicyResult(
            passed=True,
            constraint_id="S-011",
            level=ConstraintLevel.SOFT,
            message="Action matches the registered plan.",
        )

    @staticmethod
    def s012_sensitivity_reminder(
        has_sensitive_variables: bool, analysis_type: str
    ) -> PolicyResult:
        """S-012: Remind about sensitivity analysis for key findings."""
        if has_sensitive_variables:
            return PolicyResult(
                passed=False,
                constraint_id="S-012",
                level=ConstraintLevel.SOFT,
                message=f"Sensitive variables present in {analysis_type}.",
                suggestion=(
                    "Consider running sensitivity analysis (e.g., with/without outliers, "
                    "different imputation methods) to confirm robustness of findings."
                ),
            )
        return PolicyResult(
            passed=True,
            constraint_id="S-012",
            level=ConstraintLevel.SOFT,
            message="Sensitivity analysis consideration noted.",
        )
