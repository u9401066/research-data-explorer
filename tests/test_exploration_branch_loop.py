from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from rde.application.pipeline import PhaseResult, PipelinePhase
from rde.application.session import get_session
from rde.domain.models.project import Project
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.server import create_server


def _textify_tool_result(result: object) -> str:
    content = getattr(result, "content", None)
    if isinstance(content, (list, tuple)):
        blocks = content
    elif isinstance(result, tuple) and result and isinstance(result[0], (list, tuple)):
        blocks = result[0]
    else:
        blocks = result if isinstance(result, (list, tuple)) else [result]
    parts: list[str] = []
    for block in blocks:
        text = getattr(block, "text", None)
        parts.append(text if isinstance(text, str) else str(block))
    return "\n".join(parts)


def _complete_phase(
    store: ArtifactStore,
    phase: PipelinePhase,
    artifacts: dict[str, object],
    *,
    user_confirmed: bool = False,
) -> PhaseResult:
    for filename, data in artifacts.items():
        store.save(phase, filename, data)
    return PhaseResult(
        phase=phase,
        completed_at=datetime.now(),
        success=True,
        artifacts={name: "" for name in artifacts},
        user_confirmed=user_confirmed,
    )


def _make_phase8_ready_project(tmp_path: Path) -> tuple[Project, ArtifactStore]:
    project = Project(
        id=f"branch-proj-{tmp_path.name}",
        name="branch-loop",
        data_dir=tmp_path / "raw",
        output_dir=tmp_path / "output",
        research_question="Does treatment improve outcome after adjustment?",
    )
    project.output_dir.mkdir(parents=True, exist_ok=True)

    store = ArtifactStore(project.artifacts_dir)
    session = get_session()
    session.register_project(project)
    pipeline = session.get_pipeline(project.id)

    schema = {
        "dataset_id": "demo-dataset",
        "row_count": 80,
        "variables": [
            {"name": "treatment", "variable_type": "categorical", "missing_rate": 0.0},
            {"name": "outcome", "variable_type": "continuous", "missing_rate": 0.0},
            {"name": "age", "variable_type": "continuous", "missing_rate": 0.05},
            {"name": "severity", "variable_type": "continuous", "missing_rate": 0.12},
        ],
    }
    plan = {
        "project_id": project.id,
        "locked": True,
        "missing_strategy": "complete_case",
        "analyses": [
            {
                "type": "compare_groups",
                "variables": ["outcome"],
                "group_variable": "treatment",
                "rationale": "Primary outcome comparison.",
            }
        ],
    }

    phase_results = [
        _complete_phase(store, PipelinePhase.PROJECT_SETUP, {"project.yaml": {}}),
        _complete_phase(store, PipelinePhase.DATA_INTAKE, {"intake_report.json": {}}),
        _complete_phase(store, PipelinePhase.SCHEMA_REGISTRY, {"schema.json": schema}),
        _complete_phase(
            store,
            PipelinePhase.CONCEPT_ALIGNMENT,
            {"concept_alignment.md": "", "variable_roles.json": {}},
            user_confirmed=True,
        ),
        _complete_phase(
            store,
            PipelinePhase.CREATIVE_IDEATION,
            {
                "greedy_analysis_candidates.json": {},
                "greedy_analysis_candidates.md": "",
                "greedy_execution_schedule.json": [],
                "greedy_execution_schedule.md": "",
                "greedy_plan_enrichment.json": [],
                "greedy_plan_enrichment.md": "",
                "greedy_statsmodels_base_analysis.py": "",
            },
            user_confirmed=True,
        ),
        _complete_phase(
            store,
            PipelinePhase.PLAN_COMPLETENESS_REVIEW,
            {"analysis_plan_review.json": {}, "analysis_plan_review.md": ""},
            user_confirmed=True,
        ),
        _complete_phase(
            store,
            PipelinePhase.PLAN_REGISTRATION,
            {"analysis_plan.yaml": plan},
            user_confirmed=True,
        ),
        _complete_phase(
            store,
            PipelinePhase.PRE_EXPLORE_CHECK,
            {"readiness_checklist.json": {"all_passed": True}},
        ),
    ]
    for result in phase_results:
        pipeline.mark_completed(result)
    pipeline.plan_locked = True
    project.plan_locked = True
    return project, store


def _branch_id_from_store(store: ArtifactStore) -> str:
    events = store.load(PipelinePhase.EXECUTE_EXPLORATION, "exploration_branches.jsonl")
    assert isinstance(events, list)
    assert events
    return events[0]["branch_id"]


def test_append_only_events_reconstruct_exploration_board(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "Treatment effect is robust to severity adjustment.",
                "reason": "Readiness review showed severity imbalance.",
                "variables": ["outcome", "treatment", "severity"],
            },
        )
        branch_id = _branch_id_from_store(store)
        await server.call_tool(
            "run_branch_experiment",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "experiment_type": "sensitivity",
                "parameters": {"adjust_for": ["severity"]},
                "result_summary": "Adjusted estimate stayed directionally stable.",
                "metrics": {"evidence_score": 74, "stability_score": 82},
            },
        )
        await server.call_tool(
            "discard_branch",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "reason": "Kept as exploratory note for now.",
            },
        )
        result = await server.call_tool("get_exploration_board", {"project_id": project.id})
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    branch_events = store.load(PipelinePhase.EXECUTE_EXPLORATION, "exploration_branches.jsonl")
    experiment_events = store.load(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")
    branch_id = _branch_id_from_store(store)
    assert [event["event_type"] for event in branch_events] == [
        "branch_opened",
        "branch_experiment_recorded",
        "branch_discarded",
    ]
    assert experiment_events[0]["branch_id"] == branch_id
    assert experiment_events[0]["artifacts"]
    assert "discarded" in output
    assert branch_id in output
    assert store.exists(PipelinePhase.EXECUTE_EXPLORATION, "exploration_board.json")


def test_run_branch_experiment_creates_branch_results(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "Missing-data handling does not change conclusions.",
                "reason": "Schema shows non-trivial missingness.",
                "variables": ["outcome", "severity"],
                "risk_level": "medium",
            },
        )
        branch_id = _branch_id_from_store(store)
        result = await server.call_tool(
            "run_branch_experiment",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "experiment_type": "missing_strategy",
                "parameters": {"strategy": "median_impute"},
                "result_summary": "Median imputation preserved the primary direction.",
                "metrics": {"evidence_score": 81, "stability_score": 88},
            },
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    branch_id = _branch_id_from_store(store)
    result_path = store.get_path(
        PipelinePhase.EXECUTE_EXPLORATION,
        f"branch_results/{branch_id}.json",
    )
    payload = store.load(PipelinePhase.EXECUTE_EXPLORATION, f"branch_results/{branch_id}.json")
    result_events = store.load(
        PipelinePhase.EXECUTE_EXPLORATION,
        "branch_experiment_results.jsonl",
    )
    decisions = get_session().get_logger(project.id).read_decisions()
    progress = store.load(PipelinePhase.EXECUTE_EXPLORATION, "phase_08_progress.json")
    assert result_path.exists()
    assert payload["branch_id"] == branch_id
    assert payload["experiments"][0]["metrics"]["evidence_score"] == 81
    assert result_events[0]["experiment"]["artifacts"]
    assert decisions[-1]["parameters"]["scope"] == "branch"
    assert progress["branch_decision_count"] == 1
    assert progress["executed_analyses"] == 0
    assert "branch_results" in output


def test_evaluator_recommends_discard_or_promotion_candidate() -> None:
    from rde.domain.models.exploration_branch import (
        BranchStatus,
        BranchType,
        ExperimentEvent,
        ExplorationBranch,
    )
    from rde.domain.services.exploration_branch_evaluator import ExplorationBranchEvaluator

    evaluator = ExplorationBranchEvaluator()
    crash_branch = ExplorationBranch(
        branch_id="crashed",
        branch_type=BranchType.SENSITIVITY,
        status=BranchStatus.CRASHED,
        hypothesis="This branch crashed.",
    )
    low_branch = ExplorationBranch(
        branch_id="low",
        branch_type=BranchType.MISSING_STRATEGY,
        status=BranchStatus.OPEN,
        hypothesis="Weak missing-data signal.",
    )
    high_branch = ExplorationBranch(
        branch_id="high",
        branch_type=BranchType.ADJUSTED_MODEL,
        status=BranchStatus.OPEN,
        hypothesis="Adjustment confirms a robust signal.",
    )
    high_experiment = ExperimentEvent(
        branch_id="high",
        experiment_id="exp-high",
        experiment_type="adjusted_model",
        result_summary="Large, stable adjusted effect.",
        metrics={
            "evidence_score": 95,
            "stability_score": 90,
            "alignment_score": 85,
            "sample_support": 80,
            "n": 80,
            "p_value": 0.01,
            "effect_size": 0.42,
        },
        artifacts=["phase_08_execute_exploration/branch_results/high/experiments/exp-high.json"],
        status="completed",
    )

    crashed = evaluator.evaluate(crash_branch, [])
    low = evaluator.evaluate(low_branch, [])
    high = evaluator.evaluate(high_branch, [high_experiment])

    assert crashed["promotion_gate"]["can_promote"] is False
    assert crashed["recommendation"] == "discard"
    assert low["overall_score"] < 70
    assert low["recommendation"] == "discard"
    assert high["overall_score"] >= 70
    assert high["recommendation"] == "promote_candidate"
    assert high["promotion_gate"]["can_promote"] is True


def test_promotion_gate_blocks_unconfirmed_and_low_score(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> tuple[str, str]:
        server = create_server()
        await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "Low-evidence branch should not amend the plan.",
                "reason": "YOLO branch generated weak evidence.",
                "variables": ["outcome"],
            },
        )
        branch_id = _branch_id_from_store(store)
        await server.call_tool(
            "run_branch_experiment",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "experiment_type": "visualization",
                "result_summary": "Pattern was noisy and inconsistent.",
                "metrics": {"evidence_score": 25, "stability_score": 30},
            },
        )
        await server.call_tool("evaluate_branch", {"project_id": project.id, "branch_id": branch_id})
        unconfirmed = await server.call_tool(
            "promote_branch_to_plan_amendment",
            {"project_id": project.id, "branch_id": branch_id, "confirm": False},
        )
        low_score = await server.call_tool(
            "promote_branch_to_plan_amendment",
            {"project_id": project.id, "branch_id": branch_id, "confirm": True},
        )
        return _textify_tool_result(unconfirmed), _textify_tool_result(low_score)

    unconfirmed_output, low_score_output = asyncio.run(run_flow())

    assert "confirm=True" in unconfirmed_output or "confirm=true" in unconfirmed_output
    assert "70" in low_score_output or "promote_candidate" in low_score_output
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "plan_amendments.jsonl")


def test_promotion_requires_prior_evaluate_branch_audit_gate(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "Strong branch still needs audit before promotion.",
                "variables": ["outcome", "treatment"],
            },
        )
        branch_id = _branch_id_from_store(store)
        await server.call_tool(
            "run_branch_experiment",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "experiment_type": "sensitivity",
                "result_summary": "Large stable exploratory effect.",
                "metrics": {
                    "evidence_score": 95,
                    "stability_score": 90,
                    "alignment_score": 88,
                    "sample_support": 80,
                },
            },
        )
        result = await server.call_tool(
            "promote_branch_to_plan_amendment",
            {"project_id": project.id, "branch_id": branch_id, "confirm": True},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert "evaluate_branch" in output
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "plan_amendments.jsonl")


def test_promotion_requires_persisted_audit_artifacts(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "Promotion should fail if audit artifacts disappear.",
                "parent_plan_item": "compare_groups:outcome",
                "variables": ["outcome", "treatment", "age"],
            },
        )
        branch_id = _branch_id_from_store(store)
        await server.call_tool(
            "run_branch_experiment",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "experiment_type": "adjusted_model",
                "result_summary": "Adjusted effect remained stable.",
                "metrics": {
                    "evidence_score": 93,
                    "stability_score": 91,
                    "alignment_score": 88,
                    "sample_support": 80,
                    "n": 80,
                    "p_value": 0.01,
                    "effect_size": 0.45,
                    "ci_low": 0.12,
                    "ci_high": 0.79,
                },
            },
        )
        await server.call_tool("evaluate_branch", {"project_id": project.id, "branch_id": branch_id})
        evaluation_events = store.load(PipelinePhase.EXECUTE_EXPLORATION, "branch_evaluations.jsonl")
        gate_path = Path(evaluation_events[-1]["gate_artifact"])
        gate_path.unlink()
        result = await server.call_tool(
            "promote_branch_to_plan_amendment",
            {"project_id": project.id, "branch_id": branch_id, "confirm": True},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert "audit artifacts are missing" in output
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "plan_amendments.jsonl")


def test_promotion_requires_confirmed_locked_plan_even_in_quick_context(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)
    session = get_session()
    pipeline = session.get_pipeline(project.id)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "Quick context branch should not promote without a locked plan.",
                "variables": ["outcome", "treatment"],
            },
        )
        branch_id = _branch_id_from_store(store)
        pipeline.is_quick_explore = True
        pipeline.plan_locked = False
        project.plan_locked = False
        plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
        plan["locked"] = False
        store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
        await server.call_tool(
            "run_branch_experiment",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "experiment_type": "adjusted_model",
                "result_summary": "Strong exploratory signal.",
                "metrics": {
                    "evidence_score": 95,
                    "stability_score": 90,
                    "alignment_score": 88,
                    "sample_support": 80,
                    "n": 80,
                    "p_value": 0.01,
                    "effect_size": 0.45,
                    "ci_low": 0.12,
                    "ci_high": 0.79,
                },
            },
        )
        await server.call_tool("evaluate_branch", {"project_id": project.id, "branch_id": branch_id})
        result = await server.call_tool(
            "promote_branch_to_plan_amendment",
            {"project_id": project.id, "branch_id": branch_id, "confirm": True},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert "confirmed locked plan" in output
    assert "analysis_plan_yaml_not_locked" in output
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "plan_amendments.jsonl")


def test_branch_loop_blocks_quick_explore_without_locked_plan_or_readiness(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)
    session = get_session()
    pipeline = session.get_pipeline(project.id)
    pipeline.is_quick_explore = True
    pipeline.plan_locked = False
    project.plan_locked = False
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    plan["locked"] = False
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    store.save(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json", {"all_passed": False})

    async def run_flow() -> tuple[str, str]:
        server = create_server()
        opened = await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "Quick explore must not open governed branches.",
            },
        )
        started = await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 1, "max_branches": 1},
        )
        return _textify_tool_result(opened), _textify_tool_result(started)

    opened_output, started_output = asyncio.run(run_flow())

    assert "confirmed locked plan" in opened_output
    assert "readiness_checklist_not_all_passed" in opened_output
    assert "confirmed locked plan" in started_output
    assert "analysis_plan_yaml_not_locked" in started_output
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "exploration_branches.jsonl")
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "autoresearch_runs.jsonl")


def test_promotion_requires_successful_readiness_even_after_rehydration_like_state(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "Failed readiness branch should not promote.",
                "variables": ["outcome", "treatment"],
            },
        )
        branch_id = _branch_id_from_store(store)
        await server.call_tool(
            "run_branch_experiment",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "experiment_type": "adjusted_model",
                "result_summary": "Strong exploratory signal.",
                "metrics": {
                    "evidence_score": 95,
                    "stability_score": 90,
                    "alignment_score": 88,
                    "sample_support": 80,
                    "n": 80,
                    "p_value": 0.01,
                    "effect_size": 0.45,
                    "ci_low": 0.12,
                    "ci_high": 0.79,
                },
            },
        )
        await server.call_tool("evaluate_branch", {"project_id": project.id, "branch_id": branch_id})
        store.save(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json", {"all_passed": False})
        result = await server.call_tool(
            "promote_branch_to_plan_amendment",
            {"project_id": project.id, "branch_id": branch_id, "confirm": True},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert "readiness" in output
    assert "readiness_checklist_not_all_passed" in output
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "plan_amendments.jsonl")


def test_promotion_revalidates_live_experiment_evidence_artifacts(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "Promotion should fail if experiment evidence disappears.",
                "parent_plan_item": "compare_groups:outcome",
                "variables": ["outcome", "treatment", "age"],
            },
        )
        branch_id = _branch_id_from_store(store)
        await server.call_tool(
            "run_branch_experiment",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "experiment_type": "adjusted_model",
                "result_summary": "Adjusted effect remained stable.",
                "metrics": {
                    "evidence_score": 93,
                    "stability_score": 91,
                    "alignment_score": 88,
                    "sample_support": 80,
                    "n": 80,
                    "p_value": 0.01,
                    "effect_size": 0.45,
                    "ci_low": 0.12,
                    "ci_high": 0.79,
                },
            },
        )
        await server.call_tool("evaluate_branch", {"project_id": project.id, "branch_id": branch_id})
        experiments = store.load(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")
        artifact = experiments[-1]["artifacts"][0].split(
            f"{PipelinePhase.EXECUTE_EXPLORATION.value}/",
            1,
        )[1]
        store.get_path(PipelinePhase.EXECUTE_EXPLORATION, artifact).unlink()
        result = await server.call_tool(
            "promote_branch_to_plan_amendment",
            {"project_id": project.id, "branch_id": branch_id, "confirm": True},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert "missing_live_evidence_artifact" in output
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "plan_amendments.jsonl")


def test_crashed_branch_cannot_be_reopened_by_later_experiment(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "Crashed branch should stay closed.",
                "variables": ["outcome"],
            },
        )
        branch_id = _branch_id_from_store(store)
        await server.call_tool(
            "run_branch_experiment",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "experiment_type": "sensitivity",
                "result_summary": "Model failed to converge.",
                "status": "crashed",
            },
        )
        result = await server.call_tool(
            "run_branch_experiment",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "experiment_type": "sensitivity",
                "result_summary": "Trying to revive the branch.",
                "metrics": {"n": 80, "p_value": 0.01, "effect_size": 0.5},
            },
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    branch_events = store.load(PipelinePhase.EXECUTE_EXPLORATION, "exploration_branches.jsonl")
    assert "closed" in output
    assert "crashed" in output
    assert branch_events[-1]["event_type"] == "branch_crashed"


def test_promotion_writes_plan_amendment_without_rewriting_locked_plan(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)
    original_plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "Adjusted model should be promoted for sensitivity reporting.",
                "reason": "Exploratory adjustment produced strong, stable evidence.",
                "parent_plan_item": "compare_groups:outcome",
                "variables": ["outcome", "treatment", "age", "severity"],
                "risk_level": "medium",
            },
        )
        branch_id = _branch_id_from_store(store)
        await server.call_tool(
            "run_branch_experiment",
            {
                "project_id": project.id,
                "branch_id": branch_id,
                "experiment_type": "adjusted_model",
                "parameters": {"covariates": ["age", "severity"]},
                "result_summary": "Adjusted effect remained strong and clinically relevant.",
                "metrics": {
                    "evidence_score": 94,
                    "stability_score": 91,
                    "alignment_score": 88,
                    "sample_support": 76,
                    "n": 80,
                    "p_value": 0.008,
                    "effect_size": 0.48,
                    "ci_low": 0.16,
                    "ci_high": 0.82,
                },
            },
        )
        await server.call_tool("evaluate_branch", {"project_id": project.id, "branch_id": branch_id})
        result = await server.call_tool(
            "promote_branch_to_plan_amendment",
            {"project_id": project.id, "branch_id": branch_id, "confirm": True},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    branch_id = _branch_id_from_store(store)
    amendment = store.load(
        PipelinePhase.EXECUTE_EXPLORATION,
        f"plan_amendments/{branch_id}.json",
    )
    branch_events = store.load(PipelinePhase.EXECUTE_EXPLORATION, "exploration_branches.jsonl")
    amendment_events = store.load(PipelinePhase.EXECUTE_EXPLORATION, "plan_amendments.jsonl")
    assert amendment["branch_id"] == branch_id
    assert amendment["promotion_review"]["recommendation"] == "promote_candidate"
    assert amendment_events[0]["branch_id"] == branch_id
    assert store.exists(PipelinePhase.EXECUTE_EXPLORATION, f"plan_amendments/{branch_id}.md")
    assert store.exists(PipelinePhase.EXECUTE_EXPLORATION, "branch_evaluations.jsonl")
    assert store.exists(PipelinePhase.EXECUTE_EXPLORATION, "branch_promotion_gate.json")
    assert store.exists(
        PipelinePhase.EXECUTE_EXPLORATION,
        f"branch_results/{branch_id}_promotion_review.md",
    )
    assert store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") == original_plan
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "plan_amendment.yaml")
    assert branch_events[-1]["event_type"] == "branch_promoted"
    assert "plan_amendments" in output


def test_suggest_branch_experiments_is_bounded_and_does_not_open_branch(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> tuple[str, str]:
        server = create_server()
        first = await server.call_tool(
            "suggest_branch_experiments",
            {"project_id": project.id, "max_suggestions": 3},
        )
        second = await server.call_tool(
            "suggest_branch_experiments",
            {"project_id": project.id, "max_suggestions": 3},
        )
        return _textify_tool_result(first), _textify_tool_result(second)

    first_output, second_output = asyncio.run(run_flow())

    assert first_output == second_output
    assert first_output.count("branch_type") == 3
    assert "sensitivity" in first_output
    assert "missing_strategy" in first_output
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "exploration_branches.jsonl")


def test_start_autoresearch_run_persists_queue_budget_and_status(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> tuple[str, str]:
        server = create_server()
        started = await server.call_tool(
            "start_autoresearch_run",
            {
                "project_id": project.id,
                "max_tasks": 3,
                "max_branches": 3,
                "max_failures": 1,
                "max_minutes": 30,
            },
        )
        status = await server.call_tool(
            "get_autoresearch_status",
            {"project_id": project.id},
        )
        return _textify_tool_result(started), _textify_tool_result(status)

    started_output, status_output = asyncio.run(run_flow())

    runs = store.load(PipelinePhase.EXECUTE_EXPLORATION, "autoresearch_runs.jsonl")
    queue = store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl")
    budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, "budget_state.json")
    progress_events = store.load(PipelinePhase.EXECUTE_EXPLORATION, "progress_events.jsonl")
    assert runs[0]["event_type"] == "autoresearch_run_started"
    assert runs[0]["run_id"]
    assert 1 <= len(queue) <= 3
    assert all(item["status"] == "pending" for item in queue)
    assert all("priority_score" in item for item in queue)
    assert budget["run_id"] == runs[0]["run_id"]
    assert budget["max_tasks"] == 3
    assert progress_events[-1]["event_type"] == "autoresearch_progress"
    assert "work_queue.jsonl" in started_output
    assert "queue_depth" in status_output


def test_start_autoresearch_run_blocks_when_active_run_exists(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 2, "max_branches": 2},
        )
        result = await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 2, "max_branches": 2},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    runs = store.load(PipelinePhase.EXECUTE_EXPLORATION, "autoresearch_runs.jsonl")
    assert [event["event_type"] for event in runs].count("autoresearch_run_started") == 1
    assert "already active" in output


def test_autoresearch_status_projects_latest_task_state(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 1, "max_branches": 1},
        )
        queue = store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl")
        task = dict(queue[0])
        task["status"] = "completed"
        task["completed_at"] = datetime.now().isoformat()
        task["artifacts"] = ["phase_08_execute_exploration/branch_results/example.json"]
        store.save(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl", task)
        store.save(
            PipelinePhase.EXECUTE_EXPLORATION,
            "work_events.jsonl",
            {
                "event_type": "work_item_completed",
                "run_id": task["run_id"],
                "task_id": task["task_id"],
                "status": "completed",
            },
        )
        result = await server.call_tool(
            "get_autoresearch_status",
            {"project_id": project.id},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert "queue_depth: 0" in output
    assert "completed: 1" in output


def test_start_autoresearch_run_persists_empty_queue_artifacts_when_no_suggestions(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)
    store.save(PipelinePhase.SCHEMA_REGISTRY, "schema.json", {"variables": []})
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", {"locked": True, "analyses": []})

    async def run_flow() -> str:
        server = create_server()
        result = await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 3, "max_branches": 3},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert store.exists(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl")
    assert store.exists(PipelinePhase.EXECUTE_EXPLORATION, "work_events.jsonl")
    assert store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl") == []
    runs = store.load(PipelinePhase.EXECUTE_EXPLORATION, "autoresearch_runs.jsonl")
    budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, "budget_state.json")
    assert runs[-1]["event_type"] == "autoresearch_run_completed"
    assert runs[-1]["reason"] == "no_suggestions"
    assert budget["status"] == "completed"
    assert budget["max_tasks"] == 0
    assert budget["remaining_tasks"] == 0
    assert budget["completed_tasks"] == 0
    assert "no branch suggestions" in output.lower()


def test_autoresearch_runner_stops_when_failure_budget_is_exhausted(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 2, "max_branches": 2, "max_failures": 1},
        )
        queue = store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl")
        failed_task = queue[0]
        store.save(
            PipelinePhase.EXECUTE_EXPLORATION,
            "work_events.jsonl",
            {
                "event_type": "work_item_failed",
                "run_id": failed_task["run_id"],
                "task_id": failed_task["task_id"],
                "status": "failed",
                "error": "simulated failure",
            },
        )
        result = await server.call_tool(
            "run_autoresearch_next_task",
            {"project_id": project.id},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    runs = store.load(PipelinePhase.EXECUTE_EXPLORATION, "autoresearch_runs.jsonl")
    budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, "budget_state.json")
    assert "failure budget exhausted" in output.lower()
    assert runs[-1]["event_type"] == "autoresearch_run_failed_budget_exhausted"
    assert budget["status"] == "failed_budget_exhausted"
    assert budget["failed_tasks"] == 1
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")


def test_autoresearch_lifecycle_writes_decision_log(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> None:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 2, "max_branches": 2},
        )
        await server.call_tool(
            "stop_autoresearch_run",
            {"project_id": project.id, "reason": "Pause for audit."},
        )
        await server.call_tool(
            "resume_autoresearch_run",
            {"project_id": project.id, "reason": "Resume after audit."},
        )

    asyncio.run(run_flow())

    decisions = store.load(PipelinePhase.EXECUTE_EXPLORATION, "decision_log.jsonl")
    actions = [entry["action"] for entry in decisions]
    assert actions[-3:] == [
        "start_autoresearch_run",
        "stop_autoresearch_run",
        "resume_autoresearch_run",
    ]
    assert all(entry["parameters"]["scope"] == "branch" for entry in decisions[-3:])


def test_run_autoresearch_next_task_reclaims_expired_lease(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 2, "max_branches": 2},
        )
        queue = store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl")
        leased_task = queue[0]
        store.save(
            PipelinePhase.EXECUTE_EXPLORATION,
            "work_events.jsonl",
            {
                "event_type": "work_item_started",
                "run_id": leased_task["run_id"],
                "task_id": leased_task["task_id"],
                "status": "running",
                "lease_owner": "stale-runner",
                "lease_expires_at": "2000-01-01T00:00:00",
            },
        )
        result = await server.call_tool(
            "run_autoresearch_next_task",
            {"project_id": project.id, "lease_owner": "pytest-reclaimer"},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    events = store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_events.jsonl")
    queue = store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl")
    first_task_id = queue[0]["task_id"]
    assert "task_id: `" + first_task_id + "`" in output
    assert any(event["event_type"] == "work_item_lease_reclaimed" for event in events)
    assert any(
        event["task_id"] == first_task_id and event["status"] == "completed"
        for event in events
    )


def test_autoresearch_status_marks_expired_run(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 1, "max_branches": 1, "max_minutes": 1},
        )
        budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, "budget_state.json")
        budget["deadline_at"] = "2000-01-01T00:00:00"
        store.save(PipelinePhase.EXECUTE_EXPLORATION, "budget_state.json", budget)
        result = await server.call_tool(
            "get_autoresearch_status",
            {"project_id": project.id},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert "status: expired" in output
    assert "deadline_expired" in output


def test_stop_autoresearch_run_writes_stop_decision(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 2, "max_branches": 2},
        )
        result = await server.call_tool(
            "stop_autoresearch_run",
            {"project_id": project.id, "reason": "User paused overnight run."},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    stops = store.load(PipelinePhase.EXECUTE_EXPLORATION, "stop_decisions.jsonl")
    runs = store.load(PipelinePhase.EXECUTE_EXPLORATION, "autoresearch_runs.jsonl")
    budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, "budget_state.json")
    assert stops[-1]["reason"] == "User paused overnight run."
    assert runs[-1]["event_type"] == "autoresearch_run_stopped"
    assert budget["status"] == "stopped"
    assert budget["current_blocker"] == "User paused overnight run."
    assert budget["remaining_tasks"] == budget["queued_tasks"]
    assert budget["updated_at"]
    assert "stopped" in output.lower()


def test_stop_autoresearch_run_is_idempotent_after_stop(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 2, "max_branches": 2},
        )
        await server.call_tool(
            "stop_autoresearch_run",
            {"project_id": project.id, "reason": "First stop."},
        )
        result = await server.call_tool(
            "stop_autoresearch_run",
            {"project_id": project.id, "reason": "Second stop."},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    stops = store.load(PipelinePhase.EXECUTE_EXPLORATION, "stop_decisions.jsonl")
    runs = store.load(PipelinePhase.EXECUTE_EXPLORATION, "autoresearch_runs.jsonl")
    assert len(stops) == 1
    assert [event["event_type"] for event in runs].count("autoresearch_run_stopped") == 1
    assert "No autoresearch run is active" in output


def test_resume_autoresearch_run_reopens_stopped_queue_with_budget(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> tuple[str, str]:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 2, "max_branches": 2, "max_minutes": 30},
        )
        await server.call_tool(
            "stop_autoresearch_run",
            {"project_id": project.id, "reason": "Pause before overnight window."},
        )
        resumed = await server.call_tool(
            "resume_autoresearch_run",
            {"project_id": project.id, "reason": "Continue overnight run."},
        )
        status = await server.call_tool(
            "get_autoresearch_status",
            {"project_id": project.id},
        )
        return _textify_tool_result(resumed), _textify_tool_result(status)

    resumed_output, status_output = asyncio.run(run_flow())

    resumes = store.load(PipelinePhase.EXECUTE_EXPLORATION, "resume_decisions.jsonl")
    runs = store.load(PipelinePhase.EXECUTE_EXPLORATION, "autoresearch_runs.jsonl")
    budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, "budget_state.json")
    assert resumes[-1]["reason"] == "Continue overnight run."
    assert runs[-1]["event_type"] == "autoresearch_run_resumed"
    assert budget["status"] == "running"
    assert budget["current_blocker"] is None
    assert "resumed" in resumed_output.lower()
    assert "status: running" in status_output


def test_resume_autoresearch_run_blocks_when_already_running(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 1, "max_branches": 1},
        )
        result = await server.call_tool(
            "resume_autoresearch_run",
            {"project_id": project.id},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "resume_decisions.jsonl")
    assert "already active" in output


def test_resume_autoresearch_run_blocks_completed_or_failed_budget_runs(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)
    store.save(PipelinePhase.SCHEMA_REGISTRY, "schema.json", {"variables": []})
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", {"locked": True, "analyses": []})

    async def completed_flow() -> str:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 3, "max_branches": 3},
        )
        result = await server.call_tool(
            "resume_autoresearch_run",
            {"project_id": project.id, "reason": "Should not resume completed run."},
        )
        return _textify_tool_result(result)

    completed_output = asyncio.run(completed_flow())

    assert "Cannot resume autoresearch run with status completed" in completed_output
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "resume_decisions.jsonl")

    project2, store2 = _make_phase8_ready_project(tmp_path / "failed-budget")

    async def failed_flow() -> str:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {
                "project_id": project2.id,
                "max_tasks": 2,
                "max_branches": 2,
                "max_failures": 0,
            },
        )
        queue = store2.load(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl")
        failed_task = queue[0]
        store2.save(
            PipelinePhase.EXECUTE_EXPLORATION,
            "work_events.jsonl",
            {
                "event_type": "work_item_failed",
                "run_id": failed_task["run_id"],
                "task_id": failed_task["task_id"],
                "status": "failed",
                "error": "simulated failure",
            },
        )
        await server.call_tool(
            "run_autoresearch_next_task",
            {"project_id": project2.id},
        )
        result = await server.call_tool(
            "resume_autoresearch_run",
            {"project_id": project2.id, "reason": "Should not resume failed budget run."},
        )
        return _textify_tool_result(result)

    failed_output = asyncio.run(failed_flow())

    assert "Cannot resume autoresearch run with status failed_budget_exhausted" in failed_output
    assert not store2.exists(PipelinePhase.EXECUTE_EXPLORATION, "resume_decisions.jsonl")


def test_run_autoresearch_next_task_claims_branch_and_updates_budget(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> tuple[str, str]:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 2, "max_branches": 2},
        )
        tick = await server.call_tool(
            "run_autoresearch_next_task",
            {"project_id": project.id, "lease_owner": "pytest-runner"},
        )
        status = await server.call_tool(
            "get_autoresearch_status",
            {"project_id": project.id},
        )
        return _textify_tool_result(tick), _textify_tool_result(status)

    tick_output, status_output = asyncio.run(run_flow())

    events = store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_events.jsonl")
    queue = store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl")
    branches = store.load(PipelinePhase.EXECUTE_EXPLORATION, "exploration_branches.jsonl")
    experiments = store.load(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")
    budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, "budget_state.json")
    event_types = [event["event_type"] for event in events]
    completed_rows = [item for item in queue if item.get("status") == "completed"]
    assert "work_item_started" in event_types
    assert "work_item_completed" in event_types
    assert completed_rows
    assert completed_rows[-1]["branch_id"]
    assert branches[0]["event_type"] == "branch_opened"
    assert experiments[-1]["status"] == "completed"
    assert experiments[-1]["metrics"]["runner_generated"] is True
    assert budget["completed_tasks"] == 1
    assert budget["remaining_tasks"] == 1
    assert "branch_id" in tick_output
    assert "completed: 1" in status_output


def test_run_autoresearch_queue_drains_until_idle_and_completes_run(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, store = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> tuple[str, str]:
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {"project_id": project.id, "max_tasks": 2, "max_branches": 2},
        )
        drained = await server.call_tool(
            "run_autoresearch_queue",
            {"project_id": project.id, "max_tasks": 5, "lease_owner": "pytest-drain"},
        )
        status = await server.call_tool(
            "get_autoresearch_status",
            {"project_id": project.id},
        )
        return _textify_tool_result(drained), _textify_tool_result(status)

    drained_output, status_output = asyncio.run(run_flow())

    budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, "budget_state.json")
    runs = store.load(PipelinePhase.EXECUTE_EXPLORATION, "autoresearch_runs.jsonl")
    experiments = store.load(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")
    assert budget["status"] == "completed"
    assert budget["completed_tasks"] == 2
    assert budget["remaining_tasks"] == 0
    assert runs[-1]["event_type"] == "autoresearch_run_completed"
    assert len(experiments) == 2
    assert "processed_tasks: 2" in drained_output
    assert "status: completed" in status_output


def test_run_autoresearch_next_task_blocks_without_active_pending_work(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    project, _ = _make_phase8_ready_project(tmp_path)

    async def run_flow() -> str:
        server = create_server()
        result = await server.call_tool(
            "run_autoresearch_next_task",
            {"project_id": project.id},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert "No running autoresearch run" in output


def test_branch_suggestions_cover_common_medical_eda_patterns() -> None:
    from rde.interface.mcp.tools.branch_tools import _build_branch_suggestions

    schema = {
        "variables": [
            {"name": "treatment_group", "variable_type": "categorical", "missing_rate": 0.0},
            {"name": "mortality_event", "variable_type": "binary", "missing_rate": 0.0},
            {"name": "followup_days", "variable_type": "continuous", "missing_rate": 0.0},
            {"name": "risk_score", "variable_type": "continuous", "missing_rate": 0.0},
            {"name": "age", "variable_type": "continuous", "missing_rate": 0.02},
            {"name": "sex", "variable_type": "categorical", "missing_rate": 0.0},
            {"name": "lactate_0h", "variable_type": "continuous", "missing_rate": 0.0},
            {"name": "lactate_24h", "variable_type": "continuous", "missing_rate": 0.0},
        ]
    }
    plan = {
        "analyses": [
            {
                "type": "compare_groups",
                "variables": ["mortality_event"],
                "group_variable": "treatment_group",
            }
        ]
    }

    suggestions = _build_branch_suggestions(schema, plan)
    experiment_types = {item["experiment_type"] for item in suggestions}

    assert {
        "adjusted_model",
        "logistic_regression",
        "propensity_score",
        "survival_analysis",
        "roc_auc",
        "repeated_measures",
        "missing_strategy",
    } <= experiment_types
