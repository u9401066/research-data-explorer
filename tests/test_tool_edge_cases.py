"""Tool behavior review: case identity, failed tests, and artifact containment."""

import asyncio
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.use_cases.compare_groups import CompareGroupsUseCase
from rde.domain.models.dataset import Dataset
from rde.domain.models.variable import Variable, VariableType
from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine
from rde.infrastructure.persistence.artifact_store import ArtifactStore


def paired_frame():
    # Deliberately shuffled, nonnumeric visit names, asymmetric missingness.
    frame = (
        pd.DataFrame(
            {
                "case": [1, 2, 3, 4, 5, 6] * 2,
                "visit": ["before"] * 6 + ["after"] * 6,
                "score": [10, 11, 14, 15, np.nan, 30, 8, 7, 9, 14, 20, np.nan],
            }
        )
        .sample(frac=1, random_state=4)
        .reset_index(drop=True)
    )
    dataset = Dataset(
        row_count=len(frame), variables=[Variable("score", "float64", VariableType.CONTINUOUS)]
    )
    return dataset, frame


def test_paired_comparison_joins_subject_not_row_order():
    dataset, frame = paired_frame()
    result = CompareGroupsUseCase(ScipyStatisticalEngine()).execute(
        dataset, frame, ["score"], "visit", is_paired=True, subject_variable="case"
    )
    cases = result.tables["case_sets"]["score"]
    assert cases["n_complete_pairs"] == 4
    assert cases["n_excluded_subjects"] == 2
    for first, second in cases["paired_row_positions"]:
        assert frame.iloc[first]["case"] == frame.iloc[second]["case"]
        assert frame.iloc[first]["visit"] != frame.iloc[second]["visit"]
    expected = ScipyStatisticalEngine().run_test(
        pd.DataFrame({"before": [10, 11, 14, 15], "after": [8, 7, 9, 14]}),
        "Wilcoxon signed-rank test",
        ["before", "after"],
    )
    assert result.tests[0].p_value == pytest.approx(expected["p_value"])
    assert result.tests[0].sample_sizes == (4, 4)


def test_pairing_without_key_or_duplicate_occasion_fails():
    dataset, frame = paired_frame()
    use_case = CompareGroupsUseCase(ScipyStatisticalEngine())
    with pytest.raises(ValueError, match="subject_variable"):
        use_case.execute(dataset, frame, ["score"], "visit", is_paired=True)
    with pytest.raises(ValueError, match="Duplicate subject/occasion"):
        use_case.execute(
            dataset, pd.concat([frame, frame.iloc[:1]]), ["score"], "visit", True, "case"
        )


def test_ordinal_comparison_uses_rank_test_even_if_marked_normal():
    from rde.domain.services.statistical_advisor import StatisticalAdvisor

    recommendation = StatisticalAdvisor().recommend_comparison_test(
        VariableType.ORDINAL, 2, False, True, [60, 60]
    )
    assert recommendation.test_name == "Mann-Whitney U test"


@pytest.mark.parametrize(
    "response", [{"error": "fit failed"}, {}, {"statistic": 0.0, "p_value": float("nan")}]
)
def test_engine_failure_never_becomes_p_one(response):
    dataset, frame = paired_frame()
    engine = Mock()
    engine.run_test.return_value = response
    with pytest.raises(ValueError):
        CompareGroupsUseCase(engine).execute(dataset, frame, ["score"], "visit")


def test_paired_mcp_persists_case_set(tmp_path):
    from test_exploration_branch_loop import _make_phase8_ready_project
    from rde.application.session import get_session
    from rde.interface.mcp.server import create_server

    project, store = _make_phase8_ready_project(tmp_path)
    dataset, frame = paired_frame()
    get_session().register_dataset(dataset, frame)
    project.dataset_ids = [dataset.id]

    async def call():
        return await create_server().call_tool(
            "compare_groups",
            {
                "dataset_id": dataset.id,
                "outcome_variables": ["score"],
                "group_variable": "visit",
                "is_paired": True,
                "subject_variable": "case",
            },
        )

    response = asyncio.run(call())
    assert not response.is_error, response
    assert "Complete subject pairs:** 4 / 6" in response.content[0].text
    artifacts = store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION)
    filename = next(
        name for name in artifacts if name.startswith("compare_groups_") and name.endswith(".json")
    )
    assert (
        store.load(PipelinePhase.EXECUTE_EXPLORATION, filename)["case_sets"]["score"][
            "n_complete_pairs"
        ]
        == 4
    )


@pytest.mark.parametrize(
    "name",
    [
        "../escape.json",
        "..\\escape.json",
        "/tmp/escape.json",
        "C:\\escape.json",
        "C:escape.json",
        "a/../../escape.json",
        "a:stream",
        "",
        ".",
    ],
)
@pytest.mark.parametrize("operation", ["save", "load", "get_path", "exists"])
def test_artifact_paths_cannot_escape_phase(tmp_path, name, operation):
    store = ArtifactStore(tmp_path / "artifacts")
    method = getattr(store, operation)
    with pytest.raises(ValueError):
        method(PipelinePhase.EXECUTE_EXPLORATION, name, {}) if operation == "save" else method(
            PipelinePhase.EXECUTE_EXPLORATION, name
        )


def test_nested_artifact_and_append_only_log_still_work(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    phase = PipelinePhase.EXECUTE_EXPLORATION
    store.save(phase, "branch/a/events.jsonl", {"n": 1})
    store.save(phase, "branch/a/events.jsonl", {"n": 2})
    assert store.load(phase, "branch/a/events.jsonl") == [{"n": 1}, {"n": 2}]


def test_artifact_symlink_escape_is_rejected(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    phase = PipelinePhase.EXECUTE_EXPLORATION
    phase_dir = tmp_path / "artifacts" / phase.value
    phase_dir.mkdir()
    try:
        (phase_dir / "outside").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires OS permission")
    with pytest.raises(ValueError, match="escapes"):
        store.save(phase, "outside/escape.json", {})


def test_plan_coverage_counts_unique_complete_tasks_not_reruns(tmp_path):
    from test_exploration_branch_loop import _make_phase8_ready_project
    from rde.application.session import get_session
    from rde.interface.mcp.tools._shared.project_context import compute_phase6_progress

    project, store = _make_phase8_ready_project(tmp_path)
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        {
            "locked": True,
            "analyses": [
                {"type": "compare_groups", "variables": ["score", "visit"]},
                {"type": "compare_groups", "variables": ["secondary", "visit"]},
            ],
        },
    )
    logger = get_session().get_logger(project.id)
    for _ in range(5):
        logger.log_decision(
            phase=PipelinePhase.EXECUTE_EXPLORATION.value,
            action="compare_groups",
            tool_used="compare_groups",
            parameters={"outcome_variables": ["score"], "group_variable": "visit"},
            rationale="rerun",
            result_summary="valid comparison",
        )
    progress = compute_phase6_progress(project)
    assert progress["executed_analyses"] == 1
    assert progress["coverage"] == 0.5
    assert progress["pending_plan_indices"] == [1]
    assert not progress["ready"]
