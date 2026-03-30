from __future__ import annotations

# mypy: disable-error-code=import-untyped

from rde.domain.models.dataset import Dataset
from rde.domain.models.variable import Variable, VariableRole, VariableType
from rde.domain.services.autonomous_eda_planner import AutonomousEDAPlanner


def _variable(
    name: str,
    variable_type: VariableType,
    *,
    role: VariableRole = VariableRole.UNASSIGNED,
    n_unique: int = 10,
    n_missing: int = 0,
) -> Variable:
    return Variable(
        name=name,
        dtype="float64",
        variable_type=variable_type,
        role=role,
        n_unique=n_unique,
        n_missing=n_missing,
        extra={"total_count": 100},
    )


def _dataset(*variables: Variable) -> Dataset:
    dataset = Dataset(id="benchmark-ds")
    dataset.mark_loaded(list(variables), row_count=100)
    return dataset


def test_reviewed_blueprint_benchmark_preserves_or_expands_coverage() -> None:
    planner = AutonomousEDAPlanner()
    scenarios = [
        (
            "grouped_binary_outcome",
            _dataset(
                _variable("mortality", VariableType.BINARY, role=VariableRole.OUTCOME, n_unique=2),
                _variable(
                    "treatment_group", VariableType.BINARY, role=VariableRole.GROUP, n_unique=2
                ),
                _variable("age", VariableType.CONTINUOUS, role=VariableRole.COVARIATE),
                _variable("sofa_score", VariableType.CONTINUOUS, role=VariableRole.PREDICTOR),
                _variable("lactate", VariableType.BIOMARKER, role=VariableRole.PREDICTOR),
                _variable("risk_score", VariableType.CONTINUOUS, role=VariableRole.PREDICTOR),
            ),
            5,
        ),
        (
            "repeated_measure_branch",
            _dataset(
                _variable("group", VariableType.BINARY, role=VariableRole.GROUP, n_unique=2),
                _variable("crp_t0", VariableType.CONTINUOUS),
                _variable("crp_t1", VariableType.CONTINUOUS),
                _variable("crp_t2", VariableType.CONTINUOUS),
                _variable("albumin", VariableType.CONTINUOUS),
                _variable("bilirubin", VariableType.CONTINUOUS),
            ),
            4,
        ),
        (
            "learning_curve_branch",
            _dataset(
                _variable("success", VariableType.BINARY, role=VariableRole.OUTCOME, n_unique=2),
                _variable("operator_id", VariableType.ID, n_unique=12),
                _variable("case_order", VariableType.CONTINUOUS),
                _variable("fluoro_time", VariableType.CONTINUOUS),
                _variable("contrast_volume", VariableType.CONTINUOUS),
                _variable("radiation_dose", VariableType.CONTINUOUS),
            ),
            4,
        ),
    ]

    for name, dataset, max_analyses in scenarios:
        proposal = planner.propose(
            dataset,
            research_question=name,
            max_analyses=max_analyses,
            include_advanced=True,
            include_visualizations=True,
        )

        assert proposal.review is not None
        review = proposal.review
        assert review.final_analysis_count >= review.draft_analysis_count
        assert set(review.coverage_after).issuperset(review.coverage_before)
        assert review.soft_analysis_budget >= review.requested_analysis_budget
        assert proposal.execution_schedule
        assert proposal.execution_schedule[0].step_id == "apply_cleaning"
