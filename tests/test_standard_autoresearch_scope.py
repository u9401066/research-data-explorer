"""Actual MCP gates and restored queues cannot substitute raw-data inference."""

import asyncio
from datetime import datetime, timedelta
import hashlib

import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools import branch_tools


FAMILIES = ["imputation", "stratified", "noninferiority"]
CODE = "CLINICAL_EXPLORATION_UNSUPPORTED"


def call(name, arguments):
    return asyncio.run(create_server().call_tool(name, arguments))


def fixture(tmp_path, family):
    from test_clinical_survival import clinical_project
    from test_clinical_imputation import fixture as mi_fixture
    from test_clinical_stratified import fixture as cmh_fixture
    from test_clinical_noninferiority import means_fixture

    frame, spec = {
        "imputation": mi_fixture,
        "stratified": cmh_fixture,
        "noninferiority": means_fixture,
    }[family]()[:2]
    project, store, dataset, spec = clinical_project(tmp_path, frame=frame, options=spec)
    frame, variables, count, _ = PandasLoader().load(dataset.metadata)
    dataset.mark_loaded(variables, count)
    get_session().get_dataset_entry(dataset.id).dataframe = frame
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    plan.update(
        alpha=0.025 if family == "noninferiority" else 0.05,
        missing_strategy="multiple_imputation" if family == "imputation" else "listwise",
        multiple_comparison_method="none",
    )
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    return project, store, dataset


def proposal():
    return {
        "hypothesis": "Synthetic raw-data alternative",
        "reason": "Verify that the actual locked method governs branch dispatch",
        "variables": ["y", "x"],
        "analysis_contract": {
            "tool": "run_advanced_analysis",
            "analysis_type": "correlation",
            "target_variable": "y",
            "covariates": ["x"],
        },
    }


def start_args(project):
    return {
        "project_id": project.id,
        "max_tasks": 1,
        "agent_proposals": [proposal()],
        "include_builtin_suggestions": False,
    }


def files(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def prohibit_numerical_dispatch(monkeypatch):
    import rde.infrastructure.adapters as adapters
    from rde.interface.mcp.tools._shared import clinical_branch

    def forbidden(*args, **kwargs):
        pytest.fail("A protected clinical queue reached a numerical executor")

    monkeypatch.setattr(adapters, "get_analysis_delegator", forbidden)
    monkeypatch.setattr(clinical_branch, "execute_survival_branch", forbidden)


def historical_queue(project, store, monkeypatch, *, stopped=False, leased=False):
    # Simulate the preceding release, whose public start tool lacked this gate.
    # Actual MCP writes all queue/baseline evidence; no analysis is performed.
    with monkeypatch.context() as old_release:
        old_release.setattr(branch_tools, "_clinical_exploration_blocker", lambda store: None)
        response = call("start_autoresearch_run", start_args(project))
        assert not response.is_error, response.content
    if leased:
        task = store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl")[0]
        store.save(
            PipelinePhase.EXECUTE_EXPLORATION,
            "work_events.jsonl",
            {
                "event_type": "work_item_started",
                "run_id": task["run_id"],
                "task_id": task["task_id"],
                "status": "running",
                "lease_owner": "previous-process",
                "lease_expires_at": (datetime.now() - timedelta(hours=1)).isoformat(),
            },
        )
    if stopped:
        response = call("stop_autoresearch_run", {"project_id": project.id})
        assert not response.is_error, response.content


@pytest.mark.parametrize("family", FAMILIES)
def test_current_locked_family_blocks_all_public_exploration_writes(tmp_path, monkeypatch, family):
    project, store, dataset = fixture(tmp_path, family)
    prohibit_numerical_dispatch(monkeypatch)
    source = dataset.metadata.file_path.read_bytes()
    before = files(project.artifacts_dir)
    operations = [
        ("start_autoresearch_run", start_args(project)),
        ("resume_autoresearch_run", {}),
        ("run_autoresearch_next_task", {}),
        ("run_autoresearch_queue", {"max_tasks": 1}),
        ("open_exploration_branch", {"hypothesis": "Unsupported hypothesis"}),
        ("suggest_branch_experiments", {}),
        ("run_branch_experiment", {"branch_id": "old-branch", "status": "completed"}),
        ("evaluate_branch", {"branch_id": "old-branch"}),
        ("promote_branch_to_plan_amendment", {"branch_id": "old-branch", "confirm": True}),
    ]
    for name, arguments in operations:
        response = call(name, {"project_id": project.id, **arguments})
        assert response.is_error, (name, response.content)
        assert CODE in response.content[0].text and family in response.content[0].text
        assert files(project.artifacts_dir) == before
    assert dataset.metadata.file_path.read_bytes() == source
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "work_queue.jsonl")


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("state", ["pending", "expired-lease", "stopped"])
def test_old_queue_after_session_restart_cannot_resume_lease_or_run(
    tmp_path, monkeypatch, family, state
):
    import rde.application.session as session_module
    from rde.infrastructure.persistence import (
        FileSystemProjectRepository,
        resolve_projects_base_dir,
    )

    project, store, dataset = fixture(tmp_path, family)
    historical_queue(
        project, store, monkeypatch, stopped=state == "stopped", leased=state == "expired-lease"
    )
    FileSystemProjectRepository(resolve_projects_base_dir()).save(project)
    session_module._session = None
    prohibit_numerical_dispatch(monkeypatch)
    before = files(project.artifacts_dir)
    source = dataset.metadata.file_path.read_bytes()
    for name in ["resume_autoresearch_run", "run_autoresearch_next_task", "run_autoresearch_queue"]:
        response = call(name, {"project_id": project.id})
        assert response.is_error and CODE in response.content[0].text
        assert files(project.artifacts_dir) == before
    assert dataset.metadata.file_path.read_bytes() == source
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")
    status = call("get_autoresearch_status", {"project_id": project.id})
    assert not status.is_error and CODE in status.content[0].text
    if state != "stopped":
        stopped = call("stop_autoresearch_run", {"project_id": project.id})
        assert not stopped.is_error, stopped.content
    assert (
        store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")["analyses"][0][
            "execution_arguments"
        ]["clinical_options"]["family"]
        == family
    )


@pytest.mark.parametrize("family", FAMILIES)
def test_direct_worker_and_already_leased_contract_recheck_actual_plan(
    tmp_path, monkeypatch, family
):
    project, store, _ = fixture(tmp_path, family)
    historical_queue(project, store, monkeypatch)
    prohibit_numerical_dispatch(monkeypatch)
    before = files(project.artifacts_dir)
    result = branch_tools._execute_autoresearch_next_task(
        project, store, lease_owner="worker-bypassing-MCP", lease_seconds=1
    )
    assert not result["ok"] and CODE in result["message"]
    for contract in [
        proposal()["analysis_contract"],
        {"tool": "run_clinical_study", "analysis_type": "survival_sensitivity"},
        {},
    ]:
        result = branch_tools._execute_autoresearch_analysis_contract(
            project,
            store,
            {"analysis_contract": contract},
            branch_id="old-leased-branch",
            experiment_id="old-leased-task",
            variables=[],
        )
        assert not result["executed"] and result["status"] == "failed"
        assert result["artifacts"] == [] and CODE in result["error"]
    assert files(project.artifacts_dir) == before
