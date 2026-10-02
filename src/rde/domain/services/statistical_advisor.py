"""StatisticalAdvisor — Domain Service.

Encodes the statistical decision rules for choosing
appropriate tests based on variable types, sample size,
and distribution characteristics.

This is pure domain logic — no external dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rde.domain.models.variable import VariableType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TestRecommendation:
    """A recommended statistical test with rationale."""

    test_name: str
    rationale: str
    assumptions: list[str]
    alternative: str | None = None  # Fallback if assumptions fail


class StatisticalAdvisor:
    """Recommends appropriate statistical tests.

    Encodes Soft Constraints S-001 (normality), S-002 (multiple comparisons),
    S-009 (effect size), S-010 (power analysis).
    """

    def recommend_comparison_test(
        self,
        outcome_type: VariableType,
        group_count: int,
        is_paired: bool,
        is_normal: bool | None,
        sample_sizes: list[int],
        is_repeated_measures: bool = False,
        minimum_expected_count: float | None = None,
        contingency_shape: tuple[int, int] | None = None,
    ) -> TestRecommendation:
        """Choose the right comparison test."""
        min_n = min(sample_sizes) if sample_sizes else 0

        # Repeated measures: 3+ timepoints of the same variable
        if is_repeated_measures and group_count >= 3:
            if is_normal and min_n >= 30:
                return TestRecommendation(
                    test_name="Repeated measures ANOVA",
                    rationale=f"{group_count} repeated timepoints, normal distribution.",
                    assumptions=["Normality", "Sphericity (Mauchly's test)"],
                    alternative="Friedman test",
                )
            return TestRecommendation(
                test_name="Friedman test",
                rationale=f"{group_count} repeated timepoints, non-normal or small sample.",
                assumptions=["Complete cases for all timepoints"],
            )

        if outcome_type in (VariableType.CONTINUOUS, VariableType.ORDINAL, VariableType.BIOMARKER):
            if outcome_type == VariableType.ORDINAL:
                is_normal = False  # Ordinal coding never establishes an interval scale.
            if group_count == 2:
                if is_normal and min_n >= 30:
                    if is_paired:
                        return TestRecommendation(
                            test_name="Paired t-test",
                            rationale="Two paired groups, continuous, normal distribution.",
                            assumptions=["Normality of differences", "Paired observations"],
                            alternative="Wilcoxon signed-rank test",
                        )
                    return TestRecommendation(
                        test_name="Independent t-test",
                        rationale="Two independent groups, continuous, normal distribution.",
                        assumptions=["Normality", "Equal variance (Levene's)"],
                        alternative="Mann-Whitney U test",
                    )
                else:
                    if is_paired:
                        return TestRecommendation(
                            test_name="Wilcoxon signed-rank test",
                            rationale="Two paired groups, non-normal or small sample.",
                            assumptions=["Symmetric distribution of differences"],
                        )
                    return TestRecommendation(
                        test_name="Mann-Whitney U test",
                        rationale="Two independent groups, non-normal or small sample.",
                        assumptions=["Similar distribution shapes"],
                    )
            else:  # 3+ groups
                if is_normal and min_n >= 30:
                    return TestRecommendation(
                        test_name="One-way ANOVA",
                        rationale=f"{group_count} groups, continuous, normal.",
                        assumptions=["Normality", "Homoscedasticity"],
                        alternative="Kruskal-Wallis test",
                    )
                return TestRecommendation(
                    test_name="Kruskal-Wallis test",
                    rationale=f"{group_count} groups, non-normal or small sample.",
                    assumptions=["Independent observations"],
                )

        elif outcome_type in (VariableType.CATEGORICAL, VariableType.BINARY):
            if minimum_expected_count is None or contingency_shape is None:
                return TestRecommendation(
                    test_name="Manual review needed",
                    rationale="Categorical selection requires actual expected cell counts; group sizes alone are insufficient.",
                    assumptions=["Independent observations"],
                )
            if minimum_expected_count >= 5:
                return TestRecommendation(
                    test_name="Chi-squared test",
                    rationale="All expected cell counts are at least 5; Pearson test without continuity correction.",
                    assumptions=["Independent observations", "Expected cell count >= 5"],
                    alternative="Fisher's exact test",
                )
            if contingency_shape != (2, 2):
                return TestRecommendation(
                    test_name="Manual review needed",
                    rationale="Sparse tables beyond 2 by 2 require a specified exact or permutation model.",
                    assumptions=["Independent observations"],
                )
            return TestRecommendation(
                test_name="Fisher's exact test",
                rationale="At least one expected cell count below 5 in a 2 by 2 table.",
                assumptions=["Independent observations"],
            )

        return TestRecommendation(
            test_name="Manual review needed",
            rationale=f"Variable type '{outcome_type.value}' requires manual test selection.",
            assumptions=[],
        )

    def recommend_correlation_test(
        self,
        var1_type: VariableType,
        var2_type: VariableType,
        is_normal: bool | None,
    ) -> TestRecommendation:
        """Choose the right correlation test."""
        if var1_type == VariableType.CONTINUOUS and var2_type == VariableType.CONTINUOUS:
            if is_normal:
                return TestRecommendation(
                    test_name="Pearson correlation",
                    rationale="Two continuous variables, normal distribution.",
                    assumptions=["Linearity", "Normality", "No significant outliers"],
                    alternative="Spearman correlation",
                )
            return TestRecommendation(
                test_name="Spearman correlation",
                rationale="Two continuous variables, non-normal or ordinal.",
                assumptions=["Monotonic relationship"],
            )

        if VariableType.ORDINAL in (var1_type, var2_type):
            return TestRecommendation(
                test_name="Spearman correlation",
                rationale="At least one ordinal variable.",
                assumptions=["Monotonic relationship"],
            )

        return TestRecommendation(
            test_name="Point-biserial / Cramér's V",
            rationale="Mixed variable types.",
            assumptions=[],
        )

    def needs_multiple_comparison_correction(self, n_comparisons: int) -> bool:
        """S-002: Flag when multiple comparisons are being performed."""
        return n_comparisons > 1

    def suggest_correction_method(self, n_comparisons: int) -> str:
        if n_comparisons <= 5:
            return "Bonferroni correction"
        return "Benjamini-Hochberg (FDR) correction"
