"""Autoresearch enhances host-agent ideas without manufacturing evidence."""

import asyncio

import pandas as pd
import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.domain.models.dataset import Dataset
from rde.domain.services.research_contracts import combine_research_proposals, contract_fingerprint
from rde.interface.mcp.server import create_server


def proposal(method="risk_estimates", tool="run_advanced_analysis"):
    return {
        "hypothesis": "Describe the absolute and relative event risk with uncertainty.",
        "reason": "A clinically interpretable effect estimate is needed regardless of significance.",
        "variables": ["event", "group"],
        "analysis_contract": {
            "tool": tool,
            "analysis_type": method,
            "target_variable": "event",
            "group_variable": "group",
            "confidence_level": 0.9,
        },
    }


def test_agent_proposals_precede_deduplicate_but_do_not_restrict_hypotheses():
    custom = proposal()
    custom["hypothesis"] = "An entirely new hypothesis outside the built-in catalog"
    combined = combine_research_proposals([custom], [proposal()])
    assert len(combined) == 1
    assert combined[0]["proposal_source"] == "agent"
    assert combined[0]["hypothesis"] == custom["hypothesis"]
    assert contract_fingerprint({"b": 1, "a": 2}) == contract_fingerprint({"a": 2, "b": 1})


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"hypothesis": "idea"},
        {"hypothesis": "idea", "reason": "clinical", "variables": "not-a-list"},
    ],
)
def test_proposal_contract_errors_are_explicit(invalid):
    with pytest.raises(ValueError):
        combine_research_proposals([invalid], [])


def test_agent_clinical_contract_executes_and_preserves_denominators(tmp_path, monkeypatch):
    from test_exploration_branch_loop import _make_phase8_ready_project
    from rde.infrastructure.adapters import get_analysis_delegator

    project, store = _make_phase8_ready_project(tmp_path)
    frame = pd.DataFrame({"event": [0, 1] * 12, "group": [0] * 12 + [1] * 12})
    frame.loc[0, "event"] = None
    dataset = Dataset(row_count=len(frame))
    get_session().register_dataset(dataset, frame)
    project.dataset_ids = [dataset.id]
    monkeypatch.setattr(
        get_analysis_delegator(),
        "_check_automl",
        lambda: pytest.fail("Local clinical contract must not probe a vendor"),
    )

    async def run():
        server = create_server()
        seeded = await server.call_tool(
            "start_autoresearch_run",
            {
                "project_id": project.id,
                "max_tasks": 1,
                "agent_proposals": [proposal()],
                "include_builtin_suggestions": False,
            },
        )
        assert not seeded.is_error
        return await server.call_tool("run_autoresearch_next_task", {"project_id": project.id})

    response = asyncio.run(run())
    assert not response.is_error, response
    event = store.load(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")[-1]
    assert event["status"] == "completed"
    assert event["metrics"]["sample_size"] == 23
    assert event["metrics"]["n_input"] == 24
    assert event["metrics"]["execution_status"] == "completed"
    assert "alignment_score" not in event["metrics"]
    artifact = next(path for path in event["artifacts"] if path.endswith("risk_estimates.json"))
    payload = store.load(PipelinePhase.EXECUTE_EXPLORATION, artifact.split("/", 1)[1])
    assert payload["analysis_result"]["confidence_level"] == 0.9
    assert "backend" not in payload["config"]


def test_unimplemented_executor_is_recorded_not_completed(tmp_path):
    from test_exploration_branch_loop import _make_phase8_ready_project

    project, store = _make_phase8_ready_project(tmp_path)

    async def run():
        server = create_server()
        seeded = await server.call_tool(
            "start_autoresearch_run",
            {
                "project_id": project.id,
                "agent_proposals": [proposal("new_method", "external_review")],
                "include_builtin_suggestions": False,
            },
        )
        assert not seeded.is_error
        return await server.call_tool("run_autoresearch_next_task", {"project_id": project.id})

    assert not asyncio.run(run()).is_error
    event = store.load(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")[-1]
    budget = store.load(PipelinePhase.EXECUTE_EXPLORATION, "budget_state.json")
    assert event["status"] == "recorded"
    assert event["metrics"]["contract_executed"] is False
    assert budget["completed_tasks"] == 0
    assert budget["recorded_tasks"] == 1


def test_design_drift_stops_execution_without_erasing_ideas(tmp_path):
    from test_exploration_branch_loop import _make_phase8_ready_project

    project, store = _make_phase8_ready_project(tmp_path)

    async def run():
        server = create_server()
        await server.call_tool(
            "start_autoresearch_run",
            {
                "project_id": project.id,
                "agent_proposals": [proposal()],
                "include_builtin_suggestions": False,
            },
        )
        schema = store.load(PipelinePhase.SCHEMA_REGISTRY, "schema.json")
        schema["design_revision"] = 2
        store.save(PipelinePhase.SCHEMA_REGISTRY, "schema.json", schema)
        return await server.call_tool("run_autoresearch_next_task", {"project_id": project.id})

    response = asyncio.run(run())
    assert response.is_error
    assert "baseline changed" in response.content[0].text
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")
    assert store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl")[0]["hypothesis"]


def test_null_effect_is_not_lower_quality_than_significant_effect():
    from rde.domain.models.exploration_branch import ExplorationBranch, ExperimentEvent
    from rde.domain.services.exploration_branch_evaluator import ExplorationBranchEvaluator

    evaluator = ExplorationBranchEvaluator()
    branch = ExplorationBranch(branch_id="b", hypothesis="Estimate the effect")

    def evaluate(p, effect):
        return evaluator.evaluate(
            branch,
            [
                ExperimentEvent(
                    branch_id="b",
                    experiment_id="e",
                    experiment_type="model",
                    result_summary="estimate",
                    status="completed",
                    metrics={"n": 100, "p_value": p, "effect_size": effect},
                    artifacts=["evidence.json"],
                )
            ],
        )

    null, positive = evaluate(0.9, 0.001), evaluate(0.001, 5)
    assert null["component_scores"]["evidence"] == positive["component_scores"]["evidence"]
    assert null["promotion_gate"]["can_promote"]
    assert null["promotion_gate"]["score_is_advisory"]
    invalid = evaluate(float("nan"), float("inf"))
    assert not invalid["promotion_gate"]["can_promote"]


def test_mcp_promotion_has_no_hidden_score_threshold(tmp_path):
    from test_exploration_branch_loop import _make_phase8_ready_project, _branch_id_from_store

    project, store = _make_phase8_ready_project(tmp_path)

    async def run():
        server = create_server()
        await server.call_tool(
            "open_exploration_branch",
            {
                "project_id": project.id,
                "hypothesis": "A precise null estimate remains informative",
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
                "result_summary": "Synthetic test evidence: estimate near zero, uncertainty retained.",
                "metrics": {
                    "n": 80,
                    "p_value": 0.9,
                    "effect_size": 0.01,
                    "ci_low": -0.2,
                    "ci_high": 0.22,
                },
            },
        )
        await server.call_tool(
            "evaluate_branch", {"project_id": project.id, "branch_id": branch_id}
        )
        return await server.call_tool(
            "promote_branch_to_plan_amendment",
            {"project_id": project.id, "branch_id": branch_id, "confirm": True},
        )

    result = asyncio.run(run())
    assert not result.is_error, result
    assert store.exists(PipelinePhase.EXECUTE_EXPLORATION, "plan_amendments.jsonl")
