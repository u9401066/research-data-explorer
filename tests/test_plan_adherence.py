"""Tests for Phase 4 validation, Phase 6 plan adherence, and artifact gate hooks."""

from __future__ import annotations

from pathlib import Path

import yaml
import pytest

from rde.application.pipeline import PipelinePhase
from rde.domain.models.project import Project
from rde.interface.mcp.tools._shared.project_context import check_plan_adherence


# ── helpers ──────────────────────────────────────────────────────


def _make_project(tmp_path: Path) -> Project:
    project = Project(
        id="test-proj",
        name="test",
        data_dir=tmp_path / "raw",
        output_dir=tmp_path / "output",
    )
    return project


def _write_plan(project: Project, analyses: list[dict]) -> None:
    """Write a minimal analysis_plan.yaml under the project's artifact store."""
    phase_dir = project.artifacts_dir / PipelinePhase.PLAN_REGISTRATION.value
    phase_dir.mkdir(parents=True, exist_ok=True)
    plan = {"project_id": project.id, "analyses": analyses}
    (phase_dir / "analysis_plan.yaml").write_text(
        yaml.dump(plan, allow_unicode=True), encoding="utf-8"
    )


# ── check_plan_adherence ─────────────────────────────────────────


class TestCheckPlanAdherence:
    def test_no_plan_returns_in_plan(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        ok, reason = check_plan_adherence(project, "compare_groups", {})
        assert ok is True
        assert reason is None

    def test_empty_analyses_returns_in_plan(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_plan(project, [])
        ok, reason = check_plan_adherence(project, "compare_groups", {})
        assert ok is True

    def test_tool_matches_plan_by_type(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_plan(project, [{"type": "compare_groups", "variables": ["age"]}])
        ok, reason = check_plan_adherence(
            project, "compare_groups", {"outcome_variables": ["age"]}
        )
        assert ok is True

    def test_tool_matches_plan_by_synonym(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_plan(project, [{"type": "t_test", "variables": ["bp"]}])
        ok, reason = check_plan_adherence(
            project, "compare_groups", {"outcome_variables": ["bp"]}
        )
        assert ok is True

    def test_tool_not_in_plan_returns_deviation(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_plan(project, [{"type": "compare_groups", "variables": ["age"]}])
        ok, reason = check_plan_adherence(
            project, "correlation_matrix", {"variables": ["sbp", "dbp"]}
        )
        assert ok is False
        assert reason is not None
        assert "correlation_matrix" in reason

    def test_type_match_without_vars_in_plan_is_enough(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_plan(project, [{"type": "compare_groups"}])
        ok, _ = check_plan_adherence(
            project, "compare_groups", {"outcome_variables": ["anything"]}
        )
        assert ok is True

    def test_advanced_analysis_uses_analysis_type_param(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_plan(project, [{"type": "survival_analysis"}])
        ok, _ = check_plan_adherence(
            project,
            "run_advanced_analysis",
            {"analysis_type": "survival_analysis"},
        )
        assert ok is True


# ── artifact_gate hook ───────────────────────────────────────────


class TestArtifactGateHook:
    def test_phase_keys_match_pipeline_enum(self) -> None:
        from scripts.hooks.artifact_gate import PHASE_ARTIFACTS

        enum_values = {p.value for p in PipelinePhase}
        for key in PHASE_ARTIFACTS:
            assert key in enum_values, f"PHASE_ARTIFACTS key '{key}' not in PipelinePhase enum"

    def test_check_project_detects_skipped_phase(self, tmp_path: Path) -> None:
        from scripts.hooks.artifact_gate import check_project

        artifacts = tmp_path / "artifacts"
        # Create phase 0 and phase 2, skip phase 1
        p0 = artifacts / "phase_00_project_setup"
        p0.mkdir(parents=True)
        (p0 / "project.yaml").write_text("{}")
        p2 = artifacts / "phase_02_schema_registry"
        p2.mkdir(parents=True)
        (p2 / "schema.json").write_text("{}")

        issues = check_project(tmp_path)
        assert any("被跳過" in i for i in issues)

    def test_check_project_no_issues_for_sequential(self, tmp_path: Path) -> None:
        from scripts.hooks.artifact_gate import check_project

        artifacts = tmp_path / "artifacts"
        p0 = artifacts / "phase_00_project_setup"
        p0.mkdir(parents=True)
        (p0 / "project.yaml").write_text("{}")
        p1 = artifacts / "phase_01_data_intake"
        p1.mkdir(parents=True)
        (p1 / "intake_report.json").write_text("{}")

        issues = check_project(tmp_path)
        assert issues == []


# ── agent-control.yaml delegation section ────────────────────────


class TestAgentControlDelegation:
    MANIFEST = Path(__file__).resolve().parent.parent / ".github" / "agent-control.yaml"

    def test_delegation_section_exists(self) -> None:
        data = yaml.safe_load(self.MANIFEST.read_text(encoding="utf-8"))
        assert "delegation" in data
        deleg = data["delegation"]
        assert "local_engine" in deleg
        assert "automl_engine" in deleg

    def test_plan_adherence_section_exists(self) -> None:
        data = yaml.safe_load(self.MANIFEST.read_text(encoding="utf-8"))
        assert "plan_adherence" in data
        pa = data["plan_adherence"]
        assert pa["auto_detection"] is True

    def test_analysis_plan_schema_has_valid_types(self) -> None:
        data = yaml.safe_load(self.MANIFEST.read_text(encoding="utf-8"))
        schema = data.get("analysis_plan_schema", {})
        valid_types = schema.get("valid_types", [])
        assert "compare_groups" in valid_types
        assert "survival_analysis" in valid_types
