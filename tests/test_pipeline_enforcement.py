import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from rde.application.decision_logger import DecisionLogger
from rde.application.pipeline import PhaseResult, PipelinePhase, PipelineState
from rde.application.session import get_session
from rde.domain.models.project import Project
from rde.domain.models.project import ProjectStatus
from rde.domain.policies.hard_constraints import HardConstraints
from rde.interface.mcp.tools.discovery_tools import _pii_gate_message
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


def test_later_phase_attempts_surface_unconfirmed_alignment_before_missing_prerequisites() -> None:
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


def test_decision_logger_writes_into_phase08_artifact_dir(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    logger = DecisionLogger(artifacts_dir)

    logger.log_decision(
        phase=PipelinePhase.EXECUTE_EXPLORATION.value,
        action="compare_groups",
        tool_used="compare_groups",
        parameters={"outcome": ["x"]},
        rationale="test",
        result_summary="ok",
    )

    expected = artifacts_dir / PipelinePhase.EXECUTE_EXPLORATION.value / "decision_log.jsonl"
    assert expected.exists()
    assert logger.read_decisions()[0]["action"] == "compare_groups"
    assert logger.read_decisions()[0]["phase"] == PipelinePhase.EXECUTE_EXPLORATION.value


def test_audit_hard_constraints_follow_13_phase_indices() -> None:
    plan_registration_without_lock = HardConstraints.h007_plan_lock_enforcement(
        plan_locked=False,
        phase_index=6,
    )
    execution_without_lock = HardConstraints.h007_plan_lock_enforcement(
        plan_locked=False,
        phase_index=8,
    )
    readiness_without_decision_log = HardConstraints.h009_decision_logging_required(
        phase_index=7,
        has_decision_log=False,
    )
    execution_without_decision_log = HardConstraints.h009_decision_logging_required(
        phase_index=8,
        has_decision_log=False,
    )

    assert plan_registration_without_lock.passed is True
    assert execution_without_lock.passed is False
    assert readiness_without_decision_log.passed is True
    assert execution_without_decision_log.passed is False


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


def test_plan_registration_completion_requires_user_confirmation_to_lock_plan() -> None:
    pipeline = PipelineState(project_id="proj-1")

    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.PLAN_REGISTRATION,
            completed_at=datetime.now(),
            success=True,
            artifacts={"analysis_plan.yaml": ""},
            user_confirmed=False,
        )
    )

    assert pipeline.plan_locked is False
    assert pipeline.plan_locked_at is None

    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.PLAN_REGISTRATION,
            completed_at=datetime.now(),
            success=True,
            artifacts={"analysis_plan.yaml": ""},
            user_confirmed=True,
        )
    )

    assert pipeline.plan_locked is True
    assert pipeline.plan_locked_at is not None


def test_project_advance_to_plan_registration_does_not_lock_without_confirmed_tool(
    tmp_path: Path,
) -> None:
    project = Project(
        id="proj-plan-lock",
        name="demo",
        data_dir=tmp_path / "raw",
        output_dir=tmp_path / "output",
    )

    project.advance_to(ProjectStatus.PLAN_REGISTRATION)

    assert project.plan_locked is False


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


def test_build_schema_requires_phase1_intake_artifact_for_project_context(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    raw_dir = tmp_path / "rawdata"
    raw_dir.mkdir()
    csv_path = raw_dir / "demo.csv"
    csv_path.write_text(
        "group,value\n"
        "a,1\n"
        "a,2\n"
        "b,3\n"
        "b,4\n"
        "b,5\n"
        "a,6\n"
        "a,7\n"
        "b,8\n"
        "a,9\n"
        "b,10\n",
        encoding="utf-8",
    )

    async def run_flow() -> str:
        server = create_server()
        session = get_session()
        await server.call_tool(
            "init_project",
            {
                "name": "schema-without-intake",
                "data_dir": str(raw_dir),
                "research_question": "Do groups differ?",
            },
        )
        project = session.get_project()
        await server.call_tool("load_dataset", {"file_path": str(csv_path)})
        dataset_id = session.list_datasets()[0]
        result = await server.call_tool(
            "build_schema",
            {"dataset_id": dataset_id, "project_id": project.id},
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert "phase_01_data_intake" in output or "Missing artifacts" in output
    assert "Schema" not in output


def test_register_analysis_plan_requires_confirmed_phase4_ideation(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    raw_dir = tmp_path / "rawdata"
    raw_dir.mkdir()
    csv_path = raw_dir / "demo.csv"
    csv_path.write_text(
        "group,value\n"
        "a,1\n"
        "a,2\n"
        "b,3\n"
        "b,4\n"
        "b,5\n"
        "a,6\n"
        "a,7\n"
        "b,8\n"
        "a,9\n"
        "b,10\n",
        encoding="utf-8",
    )

    async def run_flow() -> str:
        server = create_server()
        session = get_session()
        await server.call_tool(
            "init_project",
            {
                "name": "unconfirmed-phase4",
                "data_dir": str(raw_dir),
                "research_question": "Do groups differ in value?",
            },
        )
        project = session.get_project()
        await server.call_tool("run_intake", {"directory": str(raw_dir), "project_id": project.id})
        dataset_id = session.list_datasets()[0]
        await server.call_tool(
            "build_schema",
            {"dataset_id": dataset_id, "project_id": project.id},
        )
        await server.call_tool(
            "align_concept",
            {
                "project_id": project.id,
                "research_question": "Do groups differ in value?",
                "variable_roles": {"group": "group", "outcome": "value"},
                "confirm": True,
            },
        )
        await server.call_tool(
            "propose_analysis_plan",
            {"project_id": project.id, "dataset_id": dataset_id, "max_analyses": 2},
        )
        result = await server.call_tool(
            "register_analysis_plan",
            {
                "project_id": project.id,
                "analyses": [
                    {
                        "type": "compare_groups",
                        "variables": ["value"],
                        "group_variable": "group",
                    }
                ],
                "confirm": True,
            },
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert "requires explicit user confirmation" in output
    assert "Phase 4" in output or "phase_04_creative_ideation" in output


def test_register_analysis_plan_does_not_auto_create_phase4(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    raw_dir = tmp_path / "rawdata"
    raw_dir.mkdir()
    csv_path = raw_dir / "demo.csv"
    csv_path.write_text(
        "group,value\n"
        "a,1\n"
        "a,2\n"
        "b,3\n"
        "b,4\n"
        "b,5\n"
        "a,6\n"
        "a,7\n"
        "b,8\n"
        "a,9\n"
        "b,10\n",
        encoding="utf-8",
    )

    async def run_flow() -> str:
        server = create_server()
        session = get_session()
        await server.call_tool(
            "init_project",
            {
                "name": "missing-phase4",
                "data_dir": str(raw_dir),
                "research_question": "Do groups differ in value?",
            },
        )
        project = session.get_project()
        await server.call_tool("run_intake", {"directory": str(raw_dir), "project_id": project.id})
        dataset_id = session.list_datasets()[0]
        await server.call_tool(
            "build_schema",
            {"dataset_id": dataset_id, "project_id": project.id},
        )
        await server.call_tool(
            "align_concept",
            {
                "project_id": project.id,
                "research_question": "Do groups differ in value?",
                "variable_roles": {"group": "group", "outcome": "value"},
                "confirm": True,
            },
        )
        result = await server.call_tool(
            "register_analysis_plan",
            {
                "project_id": project.id,
                "analyses": [
                    {
                        "type": "compare_groups",
                        "variables": ["value"],
                        "group_variable": "group",
                    }
                ],
                "confirm": True,
            },
        )
        return _textify_tool_result(result)

    output = asyncio.run(run_flow())

    assert "phase_04_creative_ideation" in output or "propose_analysis_plan" in output
    assert "analysis_plan.yaml" not in output
