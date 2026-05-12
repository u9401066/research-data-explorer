from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rde.application.pipeline import PhaseResult, PipelinePhase
from rde.application.session import get_session
from rde.domain.models.project import Project
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.tools.ux_tools import register_ux_tools


class _ToolCapture:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


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


def _make_project(tmp_path: Path) -> tuple[Project, ArtifactStore]:
    project = Project(
        id=f"ux-proj-{tmp_path.name}",
        name="ux-harness",
        data_dir=tmp_path / "raw",
        output_dir=tmp_path / "output",
        research_question="What should the agent do next?",
    )
    project.output_dir.mkdir(parents=True, exist_ok=True)
    store = ArtifactStore(project.artifacts_dir)
    session = get_session()
    session.register_project(project)
    pipeline = session.get_pipeline(project.id)
    for result in [
        _complete_phase(store, PipelinePhase.PROJECT_SETUP, {"project.yaml": {}}),
        _complete_phase(store, PipelinePhase.DATA_INTAKE, {"intake_report.json": {}}),
        _complete_phase(
            store,
            PipelinePhase.SCHEMA_REGISTRY,
            {"schema.json": {"variables": [{"name": "age", "variable_type": "continuous"}]}},
        ),
    ]:
        pipeline.mark_completed(result)
    return project, store


def test_approval_card_persists_next_confirmation_gate(tmp_path: Path) -> None:
    project, store = _make_project(tmp_path)
    server = _ToolCapture()
    register_ux_tools(server)

    output = server.tools["get_approval_card"](project.id)

    assert "align_concept(confirm=true)" in output
    assert "approval_card.md" in output
    assert store.exists(PipelinePhase.PROJECT_SETUP, "approval_card.md")
    card = store.load(PipelinePhase.PROJECT_SETUP, "approval_card.json")
    assert card["tool"] == "align_concept"
    assert card["requires_user_confirmation"] is True


def test_approval_card_returns_bootstrap_guidance_without_active_project() -> None:
    server = _ToolCapture()
    register_ux_tools(server)

    output = server.tools["get_approval_card"]("missing-project-id")

    assert "Bootstrap Approval Card" in output
    assert "init_project" in output
    assert "Developer: Reload Window" in output


def test_approval_card_points_to_setup_prerequisites_before_phase_three(tmp_path: Path) -> None:
    project = Project(
        id=f"ux-prereq-{tmp_path.name}",
        name="ux-prereq",
        data_dir=tmp_path / "raw",
        output_dir=tmp_path / "output",
        research_question="What should the agent do next?",
    )
    project.output_dir.mkdir(parents=True, exist_ok=True)
    session = get_session()
    session.register_project(project)
    server = _ToolCapture()
    register_ux_tools(server)

    output = server.tools["get_blocker_playbook"](project.id)
    card = ArtifactStore(project.artifacts_dir).load(
        PipelinePhase.PROJECT_SETUP, "blocker_playbook.json"
    )

    assert "run_intake" in output
    assert card["blockers"][0]["tool"] == "run_intake"


def test_approval_card_keeps_phase_four_as_draft_then_confirm(tmp_path: Path) -> None:
    project, store = _make_project(tmp_path)
    session = get_session()
    pipeline = session.get_pipeline(project.id)
    pipeline.mark_completed(
        _complete_phase(
            store,
            PipelinePhase.CONCEPT_ALIGNMENT,
            {"concept_alignment.md": "ok", "variable_roles.json": {"confirmed": True}},
            user_confirmed=True,
        )
    )
    server = _ToolCapture()
    register_ux_tools(server)

    draft_output = server.tools["get_approval_card"](project.id)
    assert "propose_analysis_plan(confirm=false)" in draft_output
    assert "propose_analysis_plan(confirm=true)" not in draft_output

    pipeline.mark_completed(
        _complete_phase(
            store,
            PipelinePhase.CREATIVE_IDEATION,
            {
                "greedy_analysis_candidates.md": "# draft",
                "greedy_analysis_candidates.json": {"confirmed": False},
            },
            user_confirmed=False,
        )
    )

    confirm_output = server.tools["get_approval_card"](project.id)
    assert "propose_analysis_plan(confirm=true)" in confirm_output


def test_artifact_index_recursively_indexes_nested_artifacts(tmp_path: Path) -> None:
    project, store = _make_project(tmp_path)
    store.get_path(
        PipelinePhase.EXECUTE_EXPLORATION,
        "branch_results/br_1/experiments/exp_1.json",
    ).parent.mkdir(parents=True, exist_ok=True)
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "branch_results/br_1/experiments/exp_1.json",
        {"ok": True},
    )
    server = _ToolCapture()
    register_ux_tools(server)

    output = server.tools["build_artifact_index"](project.id)

    index = store.load(PipelinePhase.PROJECT_SETUP, "artifact_index.json")
    paths = {entry["path"] for entry in index["artifacts"]}
    assert index["artifact_root"] == "."
    assert index["artifact_root_policy"] == "relative_to_project_artifacts_dir"
    assert "phase_08_execute_exploration/branch_results/br_1/experiments/exp_1.json" in paths
    assert "artifact_index.json" in output


def test_dashboard_and_blocker_playbook_persist_no_code_status_artifacts(
    tmp_path: Path,
) -> None:
    project, store = _make_project(tmp_path)
    server = _ToolCapture()
    register_ux_tools(server)

    dashboard = server.tools["get_harness_dashboard"](project.id)
    playbook = server.tools["get_blocker_playbook"](project.id)

    assert "Harness Dashboard" in dashboard
    assert "Blocker Playbook" in playbook
    assert "align_concept(confirm=true)" in playbook
    assert store.exists(PipelinePhase.PROJECT_SETUP, "harness_dashboard.json")
    assert store.exists(PipelinePhase.PROJECT_SETUP, "blocker_playbook.md")
