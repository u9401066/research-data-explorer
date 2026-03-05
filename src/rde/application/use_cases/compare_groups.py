"""CompareGroupsUseCase — Pipeline Step 6.

Orchestrates group comparison with automatic test selection,
applying soft constraints for statistical rigor.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

from rde.domain.models.analysis import AnalysisResult, StatisticalTest, TestCategory
from rde.domain.models.dataset import Dataset
from rde.domain.models.variable import VariableType
from rde.domain.policies.hard_constraints import HardConstraints
from rde.domain.policies.soft_constraints import SoftConstraints
from rde.domain.ports import StatisticalEnginePort
from rde.domain.services.statistical_advisor import StatisticalAdvisor


class CompareGroupsUseCase:
    """Compare groups with automatic test selection."""

    def __init__(self, engine: StatisticalEnginePort) -> None:
        self._engine = engine
        self._advisor = StatisticalAdvisor()

    def execute(
        self,
        dataset: Dataset,
        raw_data: Any,
        outcome_variables: list[str],
        group_variable: str,
        is_paired: bool = False,
    ) -> AnalysisResult:
        """Run group comparisons with constraint enforcement."""
        # Hard Constraint H-003
        check = HardConstraints.h003_min_sample_size(dataset.row_count)
        if not check.passed:
            raise ValueError(check.message)

        tests: list[StatisticalTest] = []
        warnings: list[str] = []

        # Soft Constraint S-002: multiple comparisons
        if len(outcome_variables) > 1:
            mc_check = SoftConstraints.s002_multiple_comparisons(len(outcome_variables))
            if not mc_check.passed:
                warnings.append(f"[S-002] {mc_check.suggestion}")

        for var_name in outcome_variables:
            # Find variable type
            var = next((v for v in dataset.variables if v.name == var_name), None)
            if var is None:
                warnings.append(f"Variable '{var_name}' not found in dataset.")
                continue

            # Count actual groups in the data
            import pandas as pd
            df: pd.DataFrame = raw_data
            actual_groups = df[group_variable].nunique()
            group_sizes = df.groupby(group_variable)[var_name].count().tolist()

            # Get test recommendation from domain service
            recommendation = self._advisor.recommend_comparison_test(
                outcome_type=var.variable_type,
                group_count=actual_groups,
                is_paired=is_paired,
                is_normal=None,  # Will be checked by engine
                sample_sizes=group_sizes,
            )

            # Execute via port
            result = self._engine.run_test(
                data=raw_data,
                test_name=recommendation.test_name,
                variables=[var_name, group_variable],
            )

            test = StatisticalTest(
                test_name=recommendation.test_name,
                category=TestCategory.COMPARISON,
                statistic=result.get("statistic", 0),
                p_value=result.get("p_value", 1),
                effect_size=result.get("effect_size"),
                effect_size_name=result.get("effect_size_name"),
                variables_involved=(var_name, group_variable),
                interpretation=result.get("interpretation", ""),
            )
            tests.append(test)

            # Soft Constraint S-009: effect size reminder
            es_check = SoftConstraints.s009_effect_size_reminder(
                test.p_value, test.effect_size
            )
            if not es_check.passed:
                warnings.append(f"[S-009] {var_name}: {es_check.suggestion}")

            # Soft Constraint S-010: power analysis
            pw_check = SoftConstraints.s010_power_analysis_hint(
                test.p_value, dataset.row_count
            )
            if not pw_check.passed:
                warnings.append(f"[S-010] {var_name}: {pw_check.suggestion}")

        return AnalysisResult(
            dataset_id=dataset.id,
            analysis_type="bivariate_comparison",
            created_at=datetime.now(),
            tests=tuple(tests),
            summary=self._build_summary(tests),
            warnings=tuple(warnings),
        )

    def _build_summary(self, tests: list[StatisticalTest]) -> str:
        sig = [t for t in tests if t.is_significant]
        total = len(tests)
        sig_count = len(sig)
        lines = [f"Compared {total} variables: {sig_count} significant."]
        for t in sig:
            lines.append(f"  - {', '.join(t.variables_involved)}: {t.format_result()}")
        return "\n".join(lines)
