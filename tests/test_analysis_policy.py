"""Regression: execution must match the approved inferential policy."""

import asyncio
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.use_cases.compare_groups import CompareGroupsUseCase
from rde.domain.models.dataset import Dataset
from rde.domain.models.variable import Variable, VariableType
from rde.domain.services.analysis_policy import correlation_with_cases
from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine


def fixture():
    frame = pd.DataFrame(
        {
            "group": [0] * 10 + [1] * 10,
            "a": list(range(20)),
            "b": [float(i**2) for i in range(20)],
            "c": [float((i * 7) % 19) for i in range(20)],
        }
    )
    frame.loc[0, "a"] = np.nan
    frame.loc[11, "b"] = np.nan
    frame.loc[3, "c"] = np.inf
    dataset = Dataset(
        row_count=20,
        variables=[Variable(c, "float64", VariableType.CONTINUOUS) for c in ["a", "b", "c"]],
    )
    return dataset, frame


@pytest.mark.parametrize(
    "method,expected",
    [
        ("holm", [0.03, 0.08, 0.08]),
        ("bonferroni", [0.03, 0.12, 0.135]),
        ("fdr", [0.03, 0.045, 0.045]),
    ],
)
def test_family_retains_raw_p_and_uses_adjusted_p_at_requested_alpha(method, expected):
    dataset, frame = fixture()
    engine = Mock()
    engine.run_test.side_effect = [{"statistic": 1.0, "p_value": p} for p in [0.01, 0.04, 0.045]]
    result = CompareGroupsUseCase(engine).execute(
        dataset, frame, ["a", "b", "c"], "group", alpha=0.07, multiple_comparison_method=method
    )
    assert [t.p_value for t in result.tests] == [0.01, 0.04, 0.045]
    assert [t.adjusted_p_value for t in result.tests] == pytest.approx(expected)
    assert [t.is_significant for t in result.tests] == [p < 0.07 for p in expected]
    assert result.tables["multiplicity"]["members"] == ["a", "b", "c"]
    assert all(call.kwargs["alpha"] == 0.07 for call in engine.run_test.call_args_list)


def test_different_missing_locations_use_actual_source_positions_and_keep_source():
    dataset, frame = fixture()
    before = frame.copy(deep=True)
    use_case = CompareGroupsUseCase(ScipyStatisticalEngine())
    common = use_case.execute(dataset, frame, ["a", "b", "c"], "group", missing_strategy="listwise")
    own = use_case.execute(dataset, frame, ["a", "b", "c"], "group", missing_strategy="pairwise")
    for name in ["a", "b", "c"]:
        assert common.tables["case_sets"][name]["n_analyzed"] == 17
        assert common.tables["case_sets"][name]["included_row_positions"] == [
            i for i in range(20) if i not in (0, 3, 11)
        ]
        assert own.tables["case_sets"][name]["n_analyzed"] == 19
    assert common.tests[0].sample_sizes == (8, 9)
    assert own.tests[0].sample_sizes == (9, 10)
    pd.testing.assert_frame_equal(frame, before)


def test_correlation_matrix_reports_each_pair_denominator():
    _, frame = fixture()
    pairwise = correlation_with_cases(frame, ["a", "b", "c"], "pairwise")
    listwise = correlation_with_cases(frame, ["a", "b", "c"], "listwise")
    assert pairwise["case_sets"]["a / a"]["n_analyzed"] == 19
    assert pairwise["case_sets"]["a / b"]["n_analyzed"] == 18
    assert listwise["case_sets"]["a / b"]["n_analyzed"] == 17
    assert listwise["matrix"].loc["a", "b"] != pairwise["matrix"].loc["a", "b"]


def test_descriptive_table_never_invokes_tests_when_disabled(monkeypatch):
    _, frame = fixture()
    engine = ScipyStatisticalEngine()
    monkeypatch.setenv("RDE_TABLE_ONE_ENGINE", "local-lite")
    monkeypatch.setenv("RDE_TABLE_ONE_P_VALUES", "1")  # Explicit API policy takes precedence.
    engine._safe_continuous_p_value = Mock(side_effect=AssertionError("baseline tested"))
    engine._safe_categorical_p_value = Mock(side_effect=AssertionError("baseline tested"))
    result = engine.generate_table_one(frame, "group", ["a", "b"], include_p_values=False)
    assert "| p" not in result["table_text"]
    assert all("p" not in row for row in result["table_dict"].values())


def test_real_mcp_inherits_locked_settings_and_persists_actual_policy(tmp_path):
    from test_exploration_branch_loop import _make_phase8_ready_project
    from rde.application.session import get_session
    from rde.interface.mcp.server import create_server

    project, store = _make_phase8_ready_project(tmp_path)
    dataset, frame = fixture()
    get_session().register_dataset(dataset, frame)
    project.dataset_ids = [dataset.id]
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        {
            "alpha": 0.01,
            "missing_strategy": "listwise",
            "multiple_comparison_method": "holm",
            "analyses": [
                {"type": "compare_groups", "variables": ["a", "b", "c"], "group_variable": "group"}
            ],
        },
    )

    async def call():
        return await create_server().call_tool(
            "compare_groups",
            {
                "dataset_id": dataset.id,
                "outcome_variables": ["a", "b", "c"],
                "group_variable": "group",
            },
        )

    response = asyncio.run(call())
    assert not response.is_error
    text = response.content[0].text
    assert "校正 p 值 (holm)" in text and "α=0.01" in text
    assert "17 / 20" in text
    artifacts = store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION)
    artifact = next(
        name for name in artifacts if name.startswith("compare_groups_") and name.endswith(".json")
    )
    record = store.load(PipelinePhase.EXECUTE_EXPLORATION, artifact)
    assert record["policy"] == {
        "alpha": 0.01,
        "missing_strategy": "listwise",
        "multiple_comparison_method": "holm",
    }
    assert len(record["tests"]) == 3
    assert record["tests"][0]["sample_sizes"] == [8, 9]


def test_regression_records_complete_cases_even_with_pairwise_request():
    from rde.infrastructure.adapters.analysis_delegator import AnalysisDelegator

    rng = np.random.default_rng(92)
    frame = pd.DataFrame(
        {
            "x": rng.normal(size=50),
            "y": rng.normal(size=50),
            "binary": rng.binomial(1, 0.5, size=50),
        }
    )
    frame.loc[2, "x"] = np.nan
    frame.loc[7, "x"] = np.inf
    before = frame.copy()
    engine = AnalysisDelegator()
    engine._automl_available = False
    for method, target in [("multiple_regression", "y"), ("logistic_regression", "binary")]:
        result = engine.run_analysis(
            frame,
            method,
            {
                "target": target,
                "covariates": ["x"],
                "missing_strategy": "pairwise",
                "confidence_level": 0.99,
            },
        )["result"]
        assert result["nobs"] == result["case_set"]["n_analyzed"] == 48
        assert result["case_set"]["n_excluded"] == 2
        assert result["case_set"]["included_row_positions"] == [
            i for i in range(50) if i not in (2, 7)
        ]
        assert "no pairwise" in result["case_set"]["strategy"]
        assert result["confidence_level"] == 0.99
    pd.testing.assert_frame_equal(frame, before)


def test_figure_policy_matches_matrix_and_omits_unapproved_tests(tmp_path, monkeypatch):
    from rde.infrastructure.visualization.matplotlib_viz import MatplotlibVisualizer
    from rde.interface.mcp.tools.report_tools import _candidate_p_text

    _, frame = fixture()
    viz = MatplotlibVisualizer()
    viz._mann_whitney_lite = Mock(side_effect=AssertionError("unapproved test"))
    viz.create_plot(
        frame, "boxplot", ["a"], tmp_path / "box.png", group_var="group", include_tests=False
    )
    assert "Descriptive only" in viz.last_annotation_summary
    assert "p=" not in viz.last_annotation_summary
    viz.create_plot(
        frame, "heatmap", ["a", "b", "c"], tmp_path / "common.png", missing_strategy="listwise"
    )
    assert "listwise; cell n=17..17" in viz.last_annotation_summary
    viz.create_plot(
        frame, "heatmap", ["a", "b", "c"], tmp_path / "pairwise.png", missing_strategy="pairwise"
    )
    assert "pairwise; cell n=18..19" in viz.last_annotation_summary
    caption = _candidate_p_text(
        {"p_value": 0.03, "raw_p_value": 0.01, "p_value_kind": "holm", "alpha": 0.01}
    )
    assert "p (holm)=0.03; raw p=0.01; alpha=0.01" == caption


@pytest.mark.parametrize(
    "policy",
    [
        {"alpha": 1.0},
        {"missing_strategy": "impute_median"},
        {"multiple_comparison_method": "made_up"},
    ],
)
def test_invalid_registered_policy_never_locks_plan(tmp_path, policy):
    from test_exploration_branch_loop import _make_phase8_ready_project
    from rde.interface.mcp.server import create_server
    from rde.application.session import get_session

    project, store = _make_phase8_ready_project(tmp_path)
    get_session().get_pipeline(project.id).plan_locked = False
    before = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")

    async def call():
        return await create_server().call_tool(
            "register_analysis_plan",
            {"project_id": project.id, "analyses": [], "confirm": True, **policy},
        )

    response = asyncio.run(call())
    assert response.is_error
    assert not get_session().get_pipeline(project.id).plan_locked
    assert store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") == before


def test_report_retains_nonsignificant_endpoint_receipts_after_session_results_are_gone(tmp_path):
    from rde.infrastructure.persistence.artifact_store import ArtifactStore
    from rde.interface.mcp.tools.report_tools import (
        _persisted_comparisons,
        _format_analyses,
        _formal_statistical_summary,
    )
    from rde.domain.models.project import Project

    project = Project(
        id="full-results",
        name="full-results",
        data_dir=tmp_path / "raw",
        output_dir=tmp_path / "output",
    )
    store = ArtifactStore(project.artifacts_dir)
    record = {
        "group_variable": "arm",
        "outcome_variables": ["outcome_null", "outcome_signal"],
        "policy": {"alpha": 0.01, "missing_strategy": "listwise"},
        "multiplicity": {"members": ["outcome_null", "outcome_signal"], "method": "holm"},
        "tests": [
            {
                "variables": ["outcome_null", "arm"],
                "test_name": "Mann-Whitney",
                "p_value": 0.8,
                "adjusted_p_value": 0.8,
                "alpha": 0.01,
                "significant": False,
            },
            {
                "variables": ["outcome_signal", "arm"],
                "test_name": "Mann-Whitney",
                "p_value": 0.001,
                "adjusted_p_value": 0.002,
                "alpha": 0.01,
                "significant": True,
            },
        ],
        "case_sets": {
            "outcome_null": {"n_analyzed": 18, "n_excluded": 2},
            "outcome_signal": {"n_analyzed": 18, "n_excluded": 2},
        },
    }
    store.save(PipelinePhase.EXECUTE_EXPLORATION, "compare_groups_arm_outcomes.json", record)
    restored = ArtifactStore(project.artifacts_dir)
    summary = {
        "total_analyses": 1,
        "comparisons": _persisted_comparisons(restored),
        "publishable_items": [],
    }
    assert len(summary["comparisons"]) == 1
    for output in [
        _format_analyses(summary),
        _formal_statistical_summary(project, restored, summary),
    ]:
        assert "outcome_null" in output and "未達門檻" in output
        assert "outcome_signal" in output and "0.002" in output
        assert "0.8" in output and "18" in output
        assert "compare_groups_arm_outcomes.json" in output
