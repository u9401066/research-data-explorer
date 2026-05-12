"""Tests for Phase 4 validation, Phase 6 plan adherence, and artifact gate hooks."""

from __future__ import annotations

from pathlib import Path
import re

import yaml

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.domain.models.project import Project
from rde.interface.mcp.tools._shared.project_context import (
    check_plan_adherence,
    compute_phase6_progress,
)


# ── helpers ──────────────────────────────────────────────────────


def _make_project(tmp_path: Path) -> Project:
    project = Project(
        id="test-proj",
        name="test",
        data_dir=tmp_path / "raw",
        output_dir=tmp_path / "output",
    )
    return project


def _write_plan(
    project: Project,
    analyses: list[dict],
    execution_schedule: list[dict] | None = None,
) -> None:
    """Write a minimal analysis_plan.yaml under the project's artifact store."""
    phase_dir = project.artifacts_dir / PipelinePhase.PLAN_REGISTRATION.value
    phase_dir.mkdir(parents=True, exist_ok=True)
    plan = {"project_id": project.id, "analyses": analyses}
    if execution_schedule is not None:
        plan["execution_schedule"] = execution_schedule
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
        ok, reason = check_plan_adherence(project, "compare_groups", {"outcome_variables": ["age"]})
        assert ok is True

    def test_tool_matches_plan_by_synonym(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_plan(project, [{"type": "t_test", "variables": ["bp"]}])
        ok, reason = check_plan_adherence(project, "compare_groups", {"outcome_variables": ["bp"]})
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
        ok, _ = check_plan_adherence(project, "compare_groups", {"outcome_variables": ["anything"]})
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

    def test_advanced_analysis_matches_planned_variables_when_logged(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_plan(
            project,
            [
                {
                    "type": "run_advanced_analysis",
                    "variables": ["success", "operator_id", "trial"],
                }
            ],
        )
        ok, reason = check_plan_adherence(
            project,
            "run_advanced_analysis",
            {
                "analysis_type": "learning_curve_cusum",
                "variables": ["success", "operator_id", "trial"],
                "group_variable": "operator_id",
            },
        )
        assert ok is True
        assert reason is None

    def test_tool_matches_locked_execution_schedule(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_plan(
            project,
            [{"type": "compare_groups", "variables": ["outcome"]}],
            execution_schedule=[
                {
                    "step_id": "apply_cleaning",
                    "tool_name": "apply_cleaning",
                    "analysis_label": "apply_cleaning",
                    "variables": [],
                }
            ],
        )

        ok, reason = check_plan_adherence(project, "apply_cleaning", {"approved_indices": []})

        assert ok is True
        assert reason is None

    def test_group_variable_mismatch_is_a_deviation(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_plan(
            project,
            [
                {
                    "type": "compare_groups",
                    "variables": ["outcome_score"],
                    "group_variable": "treatment_arm",
                }
            ],
        )

        ok, reason = check_plan_adherence(
            project,
            "compare_groups",
            {
                "outcome_variables": ["outcome_score"],
                "group_variable": "wrong_group",
            },
        )

        assert ok is False
        assert reason is not None
        assert "compare_groups" in reason

    def test_advanced_analysis_time_variable_mismatch_is_a_deviation(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_plan(
            project,
            [
                {
                    "type": "survival_analysis",
                    "variables": ["death_28d", "followup_days"],
                    "time_variable": "followup_days",
                }
            ],
        )

        ok, reason = check_plan_adherence(
            project,
            "run_advanced_analysis",
            {
                "analysis_type": "survival_analysis",
                "target_variable": "death_28d",
                "time_variable": "wrong_time",
                "variables": ["death_28d", "wrong_time"],
            },
        )

        assert ok is False
        assert reason is not None
        assert "run_advanced_analysis" in reason

    def test_phase8_progress_counts_only_decisions_matching_locked_plan(
        self, tmp_path: Path
    ) -> None:
        project = _make_project(tmp_path)
        get_session().register_project(project)
        _write_plan(
            project,
            [
                {
                    "type": "compare_groups",
                    "variables": ["age"],
                    "group_variable": "treatment_arm",
                },
                {"type": "analyze_variable", "variables": ["age"]},
            ],
        )
        logger = get_session().get_logger(project.id)
        logger.log_decision(
            phase=PipelinePhase.EXECUTE_EXPLORATION.value,
            action="correlation_matrix",
            tool_used="correlation_matrix",
            parameters={"variables": ["age", "weight"]},
            rationale="off-plan exploratory check",
            result_summary="ok",
        )

        progress = compute_phase6_progress(project)

        assert progress["decision_count"] == 1
        assert progress["matched_decision_count"] == 0
        assert progress["off_plan_decision_count"] == 1
        assert progress["executed_analyses"] == 0
        assert progress["ready"] is False


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

    def test_resolve_projects_dir_is_repo_root_relative(self, tmp_path: Path) -> None:
        from scripts.hooks.artifact_gate import resolve_projects_dir

        repo_root = tmp_path / "repo"
        expected = repo_root / "data" / "projects"

        assert resolve_projects_dir(repo_root) == expected

    def test_pre_commit_pattern_matches_posix_and_windows_project_paths(self) -> None:
        config = Path(__file__).resolve().parent.parent / ".pre-commit-config.yaml"
        data = yaml.safe_load(config.read_text(encoding="utf-8"))

        artifact_gate = next(
            hook
            for repo in data["repos"]
            if repo["repo"] == "local"
            for hook in repo["hooks"]
            if hook["id"] == "rde-artifact-gate"
        )
        pattern = re.compile(artifact_gate["files"])

        assert pattern.search(
            "data/projects/20260414_demo/artifacts/phase_00_project_setup/project.yaml"
        )
        assert pattern.search(
            r"data\projects\20260414_demo\artifacts\phase_00_project_setup\project.yaml"
        )


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
