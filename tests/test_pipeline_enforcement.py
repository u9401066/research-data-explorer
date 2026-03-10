from datetime import datetime
from pathlib import Path

from rde.application.decision_logger import DecisionLogger
from rde.application.pipeline import PhaseResult, PipelinePhase, PipelineState
from rde.domain.models.project import Project
from rde.interface.mcp.tools.discovery_tools import _pii_gate_message


def test_phase_four_requires_confirmed_alignment() -> None:
    pipeline = PipelineState(project_id="proj-1")
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.PROJECT_SETUP,
            completed_at=datetime.now(),
            success=True,
            artifacts={"project.yaml": ""},
        )
    )
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.DATA_INTAKE,
            completed_at=datetime.now(),
            success=True,
            artifacts={"intake_report.json": ""},
        )
    )
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.SCHEMA_REGISTRY,
            completed_at=datetime.now(),
            success=True,
            artifacts={"schema.json": ""},
        )
    )
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.CONCEPT_ALIGNMENT,
            completed_at=datetime.now(),
            success=True,
            artifacts={"concept_alignment.md": "", "variable_roles.json": ""},
            user_confirmed=False,
        )
    )

    can_execute, reason = pipeline.can_execute(PipelinePhase.PLAN_REGISTRATION)

    assert can_execute is False
    assert "requires explicit user confirmation" in reason


def test_decision_logger_writes_into_phase06_artifact_dir(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    logger = DecisionLogger(artifacts_dir)

    logger.log_decision(
        phase="phase_06",
        action="compare_groups",
        tool_used="compare_groups",
        parameters={"outcome": ["x"]},
        rationale="test",
        result_summary="ok",
    )

    expected = artifacts_dir / PipelinePhase.EXECUTE_EXPLORATION.value / "decision_log.jsonl"
    assert expected.exists()
    assert logger.read_decisions()[0]["action"] == "compare_groups"


def test_failed_prerequisite_blocks_next_phase() -> None:
    pipeline = PipelineState(project_id="proj-1")
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.PROJECT_SETUP,
            completed_at=datetime.now(),
            success=True,
            artifacts={"project.yaml": ""},
        )
    )
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.DATA_INTAKE,
            completed_at=datetime.now(),
            success=True,
            artifacts={"intake_report.json": ""},
        )
    )
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.SCHEMA_REGISTRY,
            completed_at=datetime.now(),
            success=True,
            artifacts={"schema.json": ""},
        )
    )
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.CONCEPT_ALIGNMENT,
            completed_at=datetime.now(),
            success=True,
            artifacts={"concept_alignment.md": "", "variable_roles.json": ""},
            user_confirmed=True,
        )
    )
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.PLAN_REGISTRATION,
            completed_at=datetime.now(),
            success=True,
            artifacts={"analysis_plan.yaml": ""},
            user_confirmed=True,
        )
    )
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.PRE_EXPLORE_CHECK,
            completed_at=datetime.now(),
            success=False,
            artifacts={"readiness_checklist.json": ""},
        )
    )

    can_execute, reason = pipeline.can_execute(PipelinePhase.EXECUTE_EXPLORATION)

    assert can_execute is False
    assert "did not complete successfully" in reason


def test_project_log_paths_match_phase06_artifact_location(tmp_path: Path) -> None:
    project = Project(
        id="proj-1",
        name="demo",
        data_dir=tmp_path / "raw",
        output_dir=tmp_path / "output",
    )

    assert project.decision_log_path == (
        project.artifacts_dir / PipelinePhase.EXECUTE_EXPLORATION.value / "decision_log.jsonl"
    )
    assert project.deviation_log_path == (
        project.artifacts_dir / PipelinePhase.EXECUTE_EXPLORATION.value / "deviation_log.jsonl"
    )


def test_pii_gate_blocks_by_default_and_allows_explicit_override() -> None:
    blocked = _pii_gate_message(["patient_name"], allow_pii=False, context="")
    allowed = _pii_gate_message(["patient_name"], allow_pii=True, context="")

    assert blocked[0] is False
    assert "H-004" in blocked[1]
    assert "allow_pii=true" in blocked[3]
    assert allowed[0] is True
    assert "allow_pii=true" in allowed[3]