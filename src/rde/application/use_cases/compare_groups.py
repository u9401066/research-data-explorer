"""CompareGroupsUseCase — Pipeline Step 6.

Orchestrates group comparison with automatic test selection,
applying soft constraints for statistical rigor.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

from rde.domain.models.analysis import AnalysisResult, StatisticalTest, TestCategory
from rde.domain.models.dataset import Dataset
from rde.domain.models.variable import VariableType
from rde.domain.policies.hard_constraints import HardConstraints
from rde.domain.policies.soft_constraints import SoftConstraints
from rde.domain.ports import StatisticalEnginePort
from rde.domain.services.statistical_advisor import StatisticalAdvisor

logger = logging.getLogger(__name__)


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
        subject_variable: str | None = None,
    ) -> AnalysisResult:
        """Run group comparisons with constraint enforcement."""
        # Hard Constraint H-003
        check = HardConstraints.h003_min_sample_size(dataset.row_count)
        if not check.passed:
            raise ValueError(check.message)

        import numpy as np
        import pandas as pd

        df: pd.DataFrame = raw_data
        required = [*outcome_variables, group_variable]
        if not outcome_variables or len(set(outcome_variables)) != len(outcome_variables):
            raise ValueError("Select one or more distinct outcome variables.")
        if is_paired:
            if not subject_variable:
                raise ValueError(
                    "Paired long-form data require subject_variable to preserve case identity. "
                    "For wide-form paired columns use run_repeated_measures instead."
                )
            required.append(subject_variable)
        if len(set(required)) != len(required):
            raise ValueError("Outcome, group, and subject roles must use distinct columns.")
        missing = [name for name in required if name not in df.columns]
        if missing:
            raise ValueError(f"Columns not found: {missing}")
        group_order = df[group_variable].dropna().unique().tolist()
        if len(group_order) < 2:
            raise ValueError("Comparison requires at least two observed groups.")
        if is_paired and len(group_order) != 2:
            raise ValueError(
                "Long-form paired comparison supports exactly two occasions; use run_repeated_measures for 3+."
            )

        tests: list[StatisticalTest] = []
        warnings: list[str] = []
        case_sets: dict[str, Any] = {}

        # Soft Constraint S-002: multiple comparisons
        if len(outcome_variables) > 1:
            mc_check = SoftConstraints.s002_multiple_comparisons(len(outcome_variables))
            if not mc_check.passed:
                warnings.append(f"[S-002] {mc_check.suggestion}")

        for var_name in outcome_variables:
            # Find variable type
            var = next((v for v in dataset.variables if v.name == var_name), None)
            if var is None:
                raise ValueError(f"Variable '{var_name}' not found in the dataset schema.")

            # Count actual groups in the data
            actual_groups = df[group_variable].nunique()
            group_sizes = df.groupby(group_variable)[var_name].count().tolist()
            engine_data = raw_data
            engine_variables = [var_name, group_variable]
            if is_paired:
                if var.variable_type not in (
                    VariableType.CONTINUOUS,
                    VariableType.ORDINAL,
                    VariableType.BIOMARKER,
                ):
                    raise ValueError(
                        "Paired categorical outcomes require McNemar or a specified paired model, not an independent-group test."
                    )
                frame = df[[subject_variable, group_variable, var_name]].copy()
                frame["_rde_row_position"] = np.arange(len(frame))
                identifiable = frame.dropna(subset=[subject_variable, group_variable])
                if identifiable.duplicated([subject_variable, group_variable]).any():
                    raise ValueError(
                        "Duplicate subject/occasion observations: resolve the repeated records explicitly before pairing."
                    )
                identifiable = identifiable.copy()
                identifiable[var_name] = pd.to_numeric(
                    identifiable[var_name], errors="coerce"
                ).replace([np.inf, -np.inf], np.nan)
                wide = identifiable.pivot(
                    index=subject_variable, columns=group_variable, values=var_name
                ).reindex(columns=group_order)
                positions = identifiable.pivot(
                    index=subject_variable, columns=group_variable, values="_rde_row_position"
                ).reindex(columns=group_order)
                complete = wide.notna().all(axis=1)
                if int(complete.sum()) < 3:
                    raise ValueError(
                        "Paired comparison requires at least three complete subject pairs."
                    )
                engine_data = wide.loc[complete].copy()
                engine_variables = ["measurement_1", "measurement_2"]
                engine_data.columns = engine_variables
                group_sizes = [len(engine_data)] * 2
                case_sets[var_name] = {
                    "strategy": "subject-key complete pairs",
                    "subject_variable": subject_variable,
                    "group_order": [str(value) for value in group_order],
                    "n_input_rows": len(df),
                    "n_subjects": len(wide),
                    "n_complete_pairs": len(engine_data),
                    "n_excluded_subjects": int((~complete).sum()),
                    "n_unidentified_rows": len(frame) - len(identifiable),
                    "paired_row_positions": positions.loc[complete].astype(int).values.tolist(),
                }

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
                data=engine_data,
                test_name=recommendation.test_name,
                variables=engine_variables,
            )
            if result.get("error"):
                raise ValueError(f"{var_name}: {result['error']}")
            if not all(
                isinstance(result.get(key), (int, float)) and math.isfinite(result[key])
                for key in ("p_value", "statistic")
            ):
                raise ValueError(f"{var_name}: statistical engine returned no finite test result.")

            test = StatisticalTest(
                test_name=recommendation.test_name,
                category=TestCategory.COMPARISON,
                statistic=result.get("statistic", 0),
                p_value=result.get("p_value", 1),
                effect_size=result.get("effect_size"),
                effect_size_name=result.get("effect_size_name"),
                sample_sizes=tuple(group_sizes),
                variables_involved=(var_name, group_variable),
                interpretation=result.get("interpretation", ""),
            )
            tests.append(test)

            # Soft Constraint S-009: effect size reminder
            es_check = SoftConstraints.s009_effect_size_reminder(test.p_value, test.effect_size)
            if not es_check.passed:
                warnings.append(f"[S-009] {var_name}: {es_check.suggestion}")

            # Soft Constraint S-010: power analysis
            pw_check = SoftConstraints.s010_power_analysis_hint(test.p_value, dataset.row_count)
            if not pw_check.passed:
                warnings.append(f"[S-010] {var_name}: {pw_check.suggestion}")

        return AnalysisResult(
            dataset_id=dataset.id,
            analysis_type="bivariate_comparison",
            created_at=datetime.now(),
            tests=tuple(tests),
            summary=self._build_summary(tests),
            tables={"case_sets": case_sets} if case_sets else {},
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
