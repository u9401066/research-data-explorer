from __future__ import annotations

# mypy: disable-error-code=import-untyped

from rde.domain.models.dataset import Dataset
from rde.domain.models.variable import Variable, VariableRole, VariableType
from rde.domain.services.autonomous_eda_planner import (
    AnalysisCandidate,
    AutonomousEDAPlanner,
    RankedCandidate,
)


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
    dataset = Dataset(id="ds-autonomous")
    dataset.mark_loaded(list(variables), row_count=100)
    return dataset


def _selected_labels(proposal) -> list[str]:
    labels: list[str] = []
    for ranked in proposal.selected:
        candidate = ranked.candidate
        labels.append(candidate.analysis_type or candidate.type)
    return labels


def _candidate(
    candidate_type: str,
    variables: tuple[str, ...],
    *,
    analysis_type: str | None = None,
    group_variable: str | None = None,
    target_variable: str | None = None,
    coverage_tags: tuple[str, ...],
    base_score: float,
) -> AnalysisCandidate:
    return AnalysisCandidate(
        type=candidate_type,
        variables=variables,
        rationale=f"candidate {analysis_type or candidate_type}",
        coverage_tags=coverage_tags,
        base_score=base_score,
        analysis_type=analysis_type,
        group_variable=group_variable,
        target_variable=target_variable,
    )


def test_binary_outcome_group_plan_includes_core_greedy_candidates() -> None:
    planner = AutonomousEDAPlanner()
    dataset = _dataset(
        _variable("mortality", VariableType.BINARY, role=VariableRole.OUTCOME, n_unique=2),
        _variable("treatment_group", VariableType.BINARY, role=VariableRole.GROUP, n_unique=2),
        _variable("age", VariableType.CONTINUOUS, role=VariableRole.COVARIATE),
        _variable("sofa_score", VariableType.CONTINUOUS, role=VariableRole.PREDICTOR),
        _variable("lactate", VariableType.BIOMARKER, role=VariableRole.PREDICTOR),
        _variable("sex", VariableType.CATEGORICAL, role=VariableRole.COVARIATE, n_unique=2),
    )

    proposal = planner.propose(
        dataset,
        research_question="哪些因子和 mortality 有關？",
        max_analyses=6,
        include_advanced=True,
        include_visualizations=True,
    )

    labels = _selected_labels(proposal)
    assert "analyze_variable" in labels
    assert "generate_table_one" in labels
    assert "compare_groups" in labels
    assert "logistic_regression" in labels
    assert len(proposal.selected) <= 6

    blueprint_types = [entry["type"] for entry in proposal.plan_blueprint]
    assert "visualization" in blueprint_types
    assert any(
        entry.get("analysis_type") == "logistic_regression"
        for entry in proposal.plan_blueprint
        if entry["type"] == "run_advanced_analysis"
    )
    descriptive_figures = sum(
        1
        for entry in proposal.plan_blueprint
        if entry["type"] == "visualization"
        and (
            entry.get("plot_type") == "histogram"
            or (entry.get("plot_type") == "bar" and not entry.get("group_variable"))
        )
    )
    analytical_figures = sum(
        1
        for entry in proposal.plan_blueprint
        if entry["type"] == "visualization"
        and not (
            entry.get("plot_type") == "histogram"
            or (entry.get("plot_type") == "bar" and not entry.get("group_variable"))
        )
    )
    assert descriptive_figures >= 3
    assert analytical_figures >= 6


def test_proposal_exposes_review_metadata_for_methodology_checks() -> None:
    planner = AutonomousEDAPlanner()
    dataset = _dataset(
        _variable("mortality", VariableType.BINARY, role=VariableRole.OUTCOME, n_unique=2),
        _variable("treatment_group", VariableType.BINARY, role=VariableRole.GROUP, n_unique=2),
        _variable("age", VariableType.CONTINUOUS, role=VariableRole.COVARIATE),
        _variable("sofa_score", VariableType.CONTINUOUS, role=VariableRole.PREDICTOR),
        _variable("lactate", VariableType.BIOMARKER, role=VariableRole.PREDICTOR),
        _variable("risk_score", VariableType.CONTINUOUS, role=VariableRole.PREDICTOR),
        _variable("sex", VariableType.CATEGORICAL, role=VariableRole.COVARIATE, n_unique=2),
    )

    proposal = planner.propose(dataset, max_analyses=6, include_advanced=True)

    assert proposal.review is not None
    assert proposal.review.status in {"pass", "repaired"}
    assert proposal.review.recommended_analysis_floor >= 5
    check_names = {check.name for check in proposal.review.checks}
    assert "foundational_overview" in check_names
    assert "cohort_snapshot" in check_names
    assert "group_difference" in check_names
    assert "association_structure" in check_names
    assert "adjusted_model" in check_names


def test_review_registered_plan_flags_under_scoped_plan() -> None:
    planner = AutonomousEDAPlanner()
    dataset = _dataset(
        _variable("mortality", VariableType.BINARY, role=VariableRole.OUTCOME, n_unique=2),
        _variable("treatment_group", VariableType.BINARY, role=VariableRole.GROUP, n_unique=2),
        _variable("age", VariableType.CONTINUOUS, role=VariableRole.COVARIATE),
        _variable("sofa_score", VariableType.CONTINUOUS, role=VariableRole.PREDICTOR),
        _variable("lactate", VariableType.BIOMARKER, role=VariableRole.PREDICTOR),
        _variable("risk_score", VariableType.CONTINUOUS, role=VariableRole.PREDICTOR),
        _variable("sex", VariableType.CATEGORICAL, role=VariableRole.COVARIATE, n_unique=2),
    )

    review = planner.review_registered_plan(
        dataset,
        [
            {
                "type": "generate_table_one",
                "variables": ["age", "sex"],
                "group_variable": "treatment_group",
            },
            {
                "type": "compare_groups",
                "variables": ["mortality"],
                "group_variable": "treatment_group",
            },
        ],
        include_advanced=True,
        max_analyses=2,
    )

    assert review.status == "needs_override"
    missing = {check.name for check in review.checks if check.status == "missing"}
    assert "foundational_overview" in missing
    assert "association_structure" in missing
    assert "adjusted_model" in missing
    assert "descriptive_figure_bundle" in missing
    assert "detailed_figure_bundle" in missing


def test_internal_review_expands_budget_before_dropping_optional_branch() -> None:
    planner = AutonomousEDAPlanner()
    overview = _candidate(
        "analyze_variable",
        ("mortality", "risk_score"),
        coverage_tags=("overview", "distribution", "quality"),
        base_score=9.4,
    )
    table_one = _candidate(
        "generate_table_one",
        ("mortality", "risk_score", "sex"),
        group_variable="treatment_group",
        coverage_tags=("overview", "comparison", "cohort_balance"),
        base_score=8.9,
    )
    compare = _candidate(
        "compare_groups",
        ("mortality", "risk_score"),
        group_variable="treatment_group",
        coverage_tags=("comparison", "effect_size", "hypothesis_screen"),
        base_score=8.7,
    )
    correlation = _candidate(
        "correlation_matrix",
        ("marker_a", "marker_b"),
        coverage_tags=("association", "collinearity", "screening"),
        base_score=7.8,
    )
    logistic = _candidate(
        "run_advanced_analysis",
        ("mortality", "risk_score", "sex"),
        analysis_type="logistic_regression",
        target_variable="mortality",
        coverage_tags=("modeling", "multivariable", "risk_estimation"),
        base_score=7.7,
    )
    roc = _candidate(
        "run_advanced_analysis",
        ("mortality", "risk_score"),
        analysis_type="roc_auc",
        target_variable="mortality",
        coverage_tags=("modeling", "discrimination", "thresholding"),
        base_score=7.2,
    )

    selected, review = planner._review_and_repair(
        draft_selected=(
            RankedCandidate(overview, 10.0),
            RankedCandidate(table_one, 9.5),
            RankedCandidate(compare, 9.3),
            RankedCandidate(logistic, 9.0),
            RankedCandidate(roc, 8.8),
        ),
        candidate_pool=[overview, table_one, compare, correlation, logistic, roc],
        max_analyses=5,
        variable_missing={
            "mortality": 0.0,
            "risk_score": 0.0,
            "sex": 0.0,
            "marker_a": 0.95,
            "marker_b": 0.95,
        },
        groups=[
            _variable("treatment_group", VariableType.BINARY, role=VariableRole.GROUP, n_unique=2)
        ],
        continuous=[
            _variable("marker_a", VariableType.CONTINUOUS, n_missing=95),
            _variable("marker_b", VariableType.CONTINUOUS, n_missing=95),
        ],
        model_family="logistic_regression",
        repeated_cluster=None,
        has_cusum=False,
    )

    final_labels = [item.candidate.family() for item in selected]
    assert "correlation_matrix" in final_labels
    assert "roc_auc" in final_labels
    assert len(selected) == 6
    assert review.requested_analysis_budget == 5
    assert review.soft_analysis_budget == 6
    assert any(action.candidate_label == "correlation_matrix" for action in review.repair_actions)
    assert any(action.action == "expand_required_family" for action in review.repair_actions)
    assert all(action.replaced_label is None for action in review.repair_actions)


def test_proposal_exposes_phase_six_execution_schedule() -> None:
    planner = AutonomousEDAPlanner()
    dataset = _dataset(
        _variable("mortality", VariableType.BINARY, role=VariableRole.OUTCOME, n_unique=2),
        _variable("treatment_group", VariableType.BINARY, role=VariableRole.GROUP, n_unique=2),
        _variable("age", VariableType.CONTINUOUS, role=VariableRole.COVARIATE),
        _variable("sofa_score", VariableType.CONTINUOUS, role=VariableRole.PREDICTOR),
        _variable("lactate", VariableType.BIOMARKER, role=VariableRole.PREDICTOR),
        _variable("risk_score", VariableType.CONTINUOUS, role=VariableRole.PREDICTOR),
    )

    proposal = planner.propose(
        dataset,
        max_analyses=5,
        include_advanced=True,
        include_visualizations=True,
    )

    schedule = list(proposal.execution_schedule)
    assert schedule
    assert schedule[0].step_id == "apply_cleaning"
    assert schedule[0].tool_name == "apply_cleaning"
    compare_index = next(
        index for index, step in enumerate(schedule) if step.analysis_label == "compare_groups"
    )
    model_index = next(
        index for index, step in enumerate(schedule) if step.analysis_label == "logistic_regression"
    )
    assert compare_index < model_index
    assert any(step.analysis_label == "visualization_bundle" for step in schedule)


def test_repeated_measure_cluster_generates_repeated_measures_candidate() -> None:
    planner = AutonomousEDAPlanner()
    dataset = _dataset(
        _variable("crp_t0", VariableType.CONTINUOUS),
        _variable("crp_t1", VariableType.CONTINUOUS),
        _variable("crp_t2", VariableType.CONTINUOUS),
        _variable("group", VariableType.BINARY, role=VariableRole.GROUP, n_unique=2),
    )

    proposal = planner.propose(dataset, max_analyses=5)

    repeated = [
        ranked for ranked in proposal.selected if ranked.candidate.type == "run_repeated_measures"
    ]
    assert repeated, "expected repeated-measures candidate to be selected"
    assert repeated[0].candidate.variables == ("crp_t0", "crp_t1", "crp_t2")
    assert any(viz.plot_type == "paired" for viz in repeated[0].candidate.visualizations)


def test_learning_curve_signature_generates_cusum_candidate() -> None:
    planner = AutonomousEDAPlanner()
    dataset = _dataset(
        _variable("success", VariableType.BINARY, role=VariableRole.OUTCOME, n_unique=2),
        _variable("operator_id", VariableType.ID, n_unique=12),
        _variable("case_order", VariableType.CONTINUOUS),
        _variable("fluoro_time", VariableType.CONTINUOUS),
    )

    proposal = planner.propose(dataset, max_analyses=6, include_advanced=True)

    cusum = [
        ranked
        for ranked in proposal.selected
        if ranked.candidate.analysis_type == "learning_curve_cusum"
    ]
    assert cusum, "expected learning-curve CUSUM candidate to be selected"

    blueprint = next(
        entry
        for entry in proposal.plan_blueprint
        if entry["type"] == "run_advanced_analysis"
        and entry.get("analysis_type") == "learning_curve_cusum"
    )
    assert blueprint["target_variable"] == "success"
    assert blueprint["group_variable"] == "operator_id"
    assert blueprint["covariates"] == ["case_order"]
