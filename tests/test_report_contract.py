from datetime import datetime
from pathlib import Path

from rde.domain.models.report import EDAReport, ReportSection
from rde.application.pipeline import PhaseResult, PipelinePhase
from rde.application.session import get_session
from rde.interface.mcp.tools.report_tools import (
    _build_appendix,
    _build_recommendations,
    _evaluate_report_readiness,
    _format_analyses,
    _format_baseline_table,
    _format_data_overview,
    _format_data_quality,
    _format_variable_profiles,
    _summarize_exploration_branches,
    _summarize_publication_deliverables,
)
from rde.interface.mcp.tools.audit_tools import (
    _build_phase10_final_report,
    _build_phase10_export_report,
    _build_phase10_source_markdown,
    _render_phase10_readiness_summary,
    register_audit_tools,
)
from rde.application.use_cases.export_report import ExportReportUseCase
from rde.application.use_cases.generate_report import GenerateReportUseCase
from rde.domain.models.project import Project
from rde.infrastructure.adapters.markdown_renderer import MarkdownReportRenderer
from rde.infrastructure.persistence.artifact_store import ArtifactStore


class _ToolCapture:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _save_production_readiness_context(
    store: ArtifactStore,
    *,
    include_project_manifest: bool = True,
    include_report: bool = True,
) -> None:
    if include_project_manifest:
        store.save(PipelinePhase.PROJECT_SETUP, "project.yaml", {"name": "contract"})
        store.save(
            PipelinePhase.PROJECT_SETUP,
            "approval_card.json",
            {"status": "no_pending_approval"},
        )
        store.save(PipelinePhase.PROJECT_SETUP, "approval_card.md", "# Approval Card\n")
        store.save(PipelinePhase.PROJECT_SETUP, "harness_dashboard.json", {"progress": "100%"})
        store.save(PipelinePhase.PROJECT_SETUP, "artifact_index.json", {"artifacts": []})
        store.save(PipelinePhase.PROJECT_SETUP, "blocker_playbook.json", {"blockers": []})
        store.save(PipelinePhase.PROJECT_SETUP, "blocker_playbook.md", "# Blocker Playbook\n")
    store.save(
        PipelinePhase.PLAN_COMPLETENESS_REVIEW,
        "analysis_plan_review.json",
        {
            "status": "pass",
            "completeness_tier": "production_ready",
            "recommended_analysis_floor": 5,
            "academic_analysis_target": 6,
            "production_analysis_target": 8,
        },
    )
    store.save(PipelinePhase.DATA_INTAKE, "intake_report.json", {"loaded_file": "demo.csv"})
    store.save(PipelinePhase.SCHEMA_REGISTRY, "schema.json", {"variables": [{"name": "age"}]})
    store.save(PipelinePhase.CONCEPT_ALIGNMENT, "concept_alignment.md", "# Concept\n")
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", {"analyses": []})
    store.save(
        PipelinePhase.PRE_EXPLORE_CHECK,
        "readiness_checklist.json",
        {"all_passed": True, "checks": [{"id": "H-003", "passed": True}]},
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "decision_log.jsonl",
        {"phase": "phase_08_execute_exploration", "action": "compare_groups"},
    )
    if include_report:
        store.save(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md", "# EDA Report\n")


def _minimum_bundle() -> dict:
    return {
        "table_one_present": True,
        "descriptive_figures": 3,
        "analytical_figures": 6,
        "required_descriptive_figures": 3,
        "required_analytical_figures": 6,
        "minimum_publication_bundle_met": True,
        "missing_components": [],
    }


def test_summarize_exploration_branches_reads_phase8_branch_ledgers(tmp_path: Path) -> None:
    project = Project(
        id="proj-branch-report",
        name="branch-report",
        data_dir=tmp_path / "rawdata",
        output_dir=tmp_path / "project",
    )
    store = ArtifactStore(project.artifacts_dir)
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "exploration_branches.jsonl",
        {
            "event_type": "branch_opened",
            "branch_id": "br-1",
            "hypothesis": "Effect differs in elderly patients",
            "risk_level": "low",
        },
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "experiment_ledger.jsonl",
        {
            "event_type": "experiment_completed",
            "branch_id": "br-1",
            "status": "completed",
            "experiment_type": "subgroup",
        },
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "exploration_branches.jsonl",
        {
            "event_type": "branch_evaluated",
            "branch_id": "br-1",
            "status": "evaluated",
            "payload": {
                "evaluation": {
                    "recommendation": "promote_candidate",
                    "overall_score": 82,
                },
                "experiment_ids": ["exp-1"],
            },
        },
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "branch_evaluations.jsonl",
        {
            "event_type": "branch_evaluated",
            "branch_id": "br-1",
            "evaluation": {
                "recommendation": "promote_candidate",
                "overall_score": 82,
            },
            "experiment_ids": ["exp-1"],
        },
    )

    summary = _summarize_exploration_branches(store)

    assert summary["total_branches"] == 1
    assert summary["completed_experiments"] == 1
    assert summary["promote_candidates"] == 1
    assert summary["branches"][0]["branch_id"] == "br-1"


def test_summarize_exploration_branches_ignores_stale_branch_result_snapshots(
    tmp_path: Path,
) -> None:
    project = Project(
        id="proj-branch-stale-report",
        name="branch-stale-report",
        data_dir=tmp_path / "rawdata",
        output_dir=tmp_path / "project",
    )
    store = ArtifactStore(project.artifacts_dir)
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "exploration_branches.jsonl",
        {
            "event_type": "branch_opened",
            "branch_id": "br-stale",
            "status": "open",
            "hypothesis": "Snapshot alone should not create a promotion candidate.",
        },
    )
    branch_dir = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "branch_results")
    branch_dir.mkdir(parents=True)
    (branch_dir / "br-stale.json").write_text(
        '{"branch_id":"br-stale","evaluation":{"recommendation":"promote_candidate","overall_score":99}}',
        encoding="utf-8",
    )

    summary = _summarize_exploration_branches(store)

    assert summary["total_branches"] == 1
    assert summary["promote_candidates"] == 0


def test_format_analyses_separates_exploratory_branch_counts() -> None:
    text = _format_analyses(
        {
            "total_analyses": 2,
            "exploration_branches": {
                "total_branches": 2,
                "completed_experiments": 3,
                "promote_candidates": 1,
            },
        }
    )

    assert "Exploratory branches" in text
    assert "2 branches" in text
    assert "promote candidates: 1" in text


def test_build_appendix_includes_exploration_branch_ledger(tmp_path: Path) -> None:
    project = Project(
        id="proj-branch-appendix",
        name="branch-appendix",
        data_dir=tmp_path / "rawdata",
        output_dir=tmp_path / "project",
    )
    get_session().register_project(project)
    store = ArtifactStore(project.artifacts_dir)
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "exploration_branches.jsonl",
        {"event_type": "branch_opened", "branch_id": "br-1", "hypothesis": "Subgroup check"},
    )
    logger = get_session().get_logger(project.id)

    appendix = _build_appendix(logger, store)

    assert "Appendix D: Exploration Branches" in appendix
    assert "br-1" in appendix


def test_format_data_overview_uses_current_intake_keys() -> None:
    intake = {
        "loaded_file": "iris.csv",
        "row_count": 150,
        "column_count": 5,
    }
    schema = {"variables": [{"name": "species"}, {"name": "sepal_length"}]}

    text = _format_data_overview(intake, schema)

    assert "iris.csv" in text
    assert "150" in text
    assert "5" in text
    assert "**Schema 變數數:** 2" in text


def test_formatters_use_current_schema_keys() -> None:
    schema = {
        "variables": [
            {"name": "species", "variable_type": "categorical", "missing_rate": 0.0},
            {"name": "sepal_length", "variable_type": "continuous", "missing_rate": 0.1},
        ]
    }
    readiness = {
        "checks": [
            {"id": "H-003", "name": "最小樣本量", "passed": True, "detail": "n = 150"},
            {"id": "S-005", "name": "缺失模式分析", "passed": True, "detail": "模式: MAR"},
        ]
    }

    quality = _format_data_quality(schema, readiness)
    profiles = _format_variable_profiles(schema)

    assert "categorical: 1" in quality
    assert "continuous: 1" in quality
    assert "species" in profiles
    assert "sepal_length" in profiles
    assert "10.0%" in profiles


class _ExporterSpy:
    def __init__(self) -> None:
        self.figures_dir = None

    def export_docx(self, report, output_path, *, figures_dir=None):
        self.figures_dir = figures_dir
        output_path.write_text("docx", encoding="utf-8")
        return output_path

    def export_pdf(self, report, output_path, *, figures_dir=None):
        self.figures_dir = figures_dir
        output_path.write_text("pdf", encoding="utf-8")
        return output_path


def test_export_use_case_accepts_project_scoped_figures_dir(tmp_path: Path) -> None:
    report = EDAReport(
        id="r1",
        dataset_id="d1",
        project_id="p1",
        title="Demo",
    )
    for idx, section_id in enumerate(
        [
            "data_overview",
            "data_quality",
            "variable_profiles",
            "key_findings",
            "statistical_analyses",
            "recommendations",
        ],
        start=1,
    ):
        report.add_section(
            ReportSection(section_id=section_id, title=section_id, content="ok", order=idx)
        )

    spy = _ExporterSpy()
    use_case = ExportReportUseCase(spy)
    figures_dir = tmp_path / "project" / "figures"
    figures_dir.mkdir(parents=True)

    result = use_case.execute(
        report=report,
        output_dir=tmp_path / "exports",
        formats=["docx"],
        figures_dir=figures_dir,
    )

    assert result["docx"].exists()
    assert spy.figures_dir == figures_dir


def test_generate_report_supports_optional_table_one_and_sensitivity_sections() -> None:
    use_case = GenerateReportUseCase(MarkdownReportRenderer())
    report = use_case.execute(
        dataset_id="d1",
        project_id="p1",
        title="Paper Ready",
        artifacts={
            "data_overview": "overview",
            "data_quality": "quality",
            "variable_profiles": "profiles",
            "baseline_table": _format_baseline_table(
                "# 📊 Table 1\n\n| var | all |\n| --- | --- |\n| age | 10 |"
            ),
            "key_findings": "findings",
            "statistical_analyses": "analysis",
            "learning_curve_cusum": "CUSUM suggests later operators outperform the cohort target.",
            "sensitivity_analysis": "Sensitivity remained directionally consistent.",
            "recommendations": "recommendations",
        },
    )

    rendered = use_case.render(report, "markdown")

    assert "## Table 1 — Baseline Characteristics" in rendered
    assert "## Learning Curve CUSUM" in rendered
    assert "CUSUM suggests later operators outperform the cohort target." in rendered
    assert "## Sensitivity Analysis" in rendered
    assert "Sensitivity remained directionally consistent." in rendered


def test_format_baseline_table_converts_grid_table_to_pipe_table() -> None:
    text = _format_baseline_table(
        "# 📊 Table 1\n\n```\n+-----+-----+\n| col1 | col2 |\n+=====+=====+\n| a | b |\n+-----+-----+\n```\n\n- **分組變數:** surgery_group"
    )

    assert "| col1 | col2 |" in text
    assert "| a | b |" in text
    assert "- **分組變數:** surgery_group" in text


def test_publication_deliverables_summary_marks_missing_bundle(tmp_path: Path) -> None:
    project = type("ProjectStub", (), {})()
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    (project.output_dir / "figures").mkdir(parents=True)

    store = ArtifactStore(project.artifacts_dir)
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "visualization_manifest.json",
        [
            {
                "plot_type": "histogram",
                "variables": ["age"],
                "category": "descriptive",
            },
            {
                "plot_type": "boxplot",
                "variables": ["age"],
                "group_var": "group",
                "category": "analytical",
            },
        ],
    )

    summary = _summarize_publication_deliverables(project, store)

    assert summary["table_one_present"] is False
    assert summary["minimum_publication_bundle_met"] is False
    assert "Table 1" in summary["missing_components"]
    assert any(component.endswith("0/3") for component in summary["missing_components"])
    assert any(component.endswith("0/6") for component in summary["missing_components"])


def test_publication_deliverables_ignore_stale_or_escaped_figure_paths(tmp_path: Path) -> None:
    project = type("ProjectStub", (), {})()
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    figures_dir = project.output_dir / "figures"
    figures_dir.mkdir(parents=True)
    (figures_dir / "valid.png").write_bytes(b"fake")

    store = ArtifactStore(project.artifacts_dir)
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "visualization_manifest.json",
        [
            {"output_path": "figures/valid.png", "category": "descriptive"},
            {"output_path": "figures/missing.png", "category": "descriptive"},
            {"output_path": "../escaped.png", "category": "analytical"},
        ],
    )

    summary = _summarize_publication_deliverables(project, store)

    assert summary["descriptive_figures"] == 1
    assert summary["analytical_figures"] == 0
    assert summary["figure_files"] == ["valid.png"]


def test_build_recommendations_mentions_publication_bundle_gap() -> None:
    text = _build_recommendations(
        {
            "deliverables": {
                "missing_components": ["Table 1", "粗分析圖 2/3", "細分析圖 4/6"],
            },
            "publishable_count": 0,
            "deviation_count": 0,
        },
        None,
    )

    assert "最低發表包" in text


def test_evaluate_report_readiness_blocks_academic_only_plan_from_production_report(
    tmp_path: Path,
) -> None:
    project = type("ProjectStub", (), {})()
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    project.output_dir.mkdir(parents=True)

    store = ArtifactStore(project.artifacts_dir)
    store.save(
        PipelinePhase.PLAN_COMPLETENESS_REVIEW,
        "analysis_plan_review.json",
        {
            "status": "pass",
            "completeness_tier": "academic_ready",
            "recommended_analysis_floor": 5,
            "academic_analysis_target": 6,
            "production_analysis_target": 8,
        },
    )

    readiness = _evaluate_report_readiness(
        {
            "deliverables": {
                "minimum_publication_bundle_met": True,
            }
        },
        store,
    )

    assert readiness["ready"] is False
    assert readiness["target_tier"] == "production_ready"
    assert readiness["current_tier"] == "academic_ready"
    assert any(
        "completeness_tier=academic_ready" in item for item in readiness["missing_requirements"]
    )


def test_evaluate_report_readiness_promotes_execution_evidence_to_production_tier(
    tmp_path: Path,
) -> None:
    project = type("ProjectStub", (), {})()
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    project.output_dir.mkdir(parents=True)

    store = ArtifactStore(project.artifacts_dir)
    _save_production_readiness_context(store, include_report=False)
    store.save(
        PipelinePhase.PLAN_COMPLETENESS_REVIEW,
        "analysis_plan_review.json",
        {
            "status": "pass",
            "completeness_tier": "academic_ready",
            "recommended_analysis_floor": 5,
            "academic_analysis_target": 5,
            "production_analysis_target": 5,
        },
    )

    readiness = _evaluate_report_readiness(
        {
            "total_analyses": 22,
            "decision_count": 24,
            "plan_coverage": {"planned": 17, "executed": 22, "coverage": 1.0},
            "phase6_progress": {"required_coverage": 0.8},
            "deliverables": _minimum_bundle(),
        },
        store,
        require_report_generation=False,
    )

    assert readiness["ready"] is True
    assert readiness["current_tier"] == "production_ready"
    assert "core_goal:report_generation" not in readiness["missing_requirements"]


def test_evaluate_report_readiness_uses_saved_counts_when_called_with_partial_payload(
    tmp_path: Path,
) -> None:
    project = type("ProjectStub", (), {})()
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    project.output_dir.mkdir(parents=True)

    store = ArtifactStore(project.artifacts_dir)
    _save_production_readiness_context(store)
    store.save(
        PipelinePhase.COLLECT_RESULTS,
        "results_summary.json",
        {
            "total_analyses": 2,
            "decision_count": 2,
            "deliverables": _minimum_bundle(),
        },
    )

    readiness = _evaluate_report_readiness(
        {"deliverables": _minimum_bundle()},
        store,
    )

    missing_goals = readiness["core_goal_audit"]["missing_goals"]
    assert "reproducible_exploration" not in missing_goals
    assert "analysis_execution_interpretation" not in missing_goals


def test_report_generation_requires_assembled_report_even_with_publication_bundle(
    tmp_path: Path,
) -> None:
    project = type("ProjectStub", (), {})()
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    project.output_dir.mkdir(parents=True)

    store = ArtifactStore(project.artifacts_dir)
    _save_production_readiness_context(store, include_report=False)

    readiness = _evaluate_report_readiness(
        {
            "total_analyses": 2,
            "decision_count": 2,
            "deliverables": _minimum_bundle(),
        },
        store,
    )

    assert "core_goal:report_generation" in readiness["missing_requirements"]


def test_no_code_and_agent_harness_goals_require_project_evidence(tmp_path: Path) -> None:
    project = type("ProjectStub", (), {})()
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    project.output_dir.mkdir(parents=True)

    store = ArtifactStore(project.artifacts_dir)
    _save_production_readiness_context(store, include_project_manifest=False)

    readiness = _evaluate_report_readiness(
        {
            "total_analyses": 2,
            "decision_count": 2,
            "deliverables": _minimum_bundle(),
        },
        store,
    )

    assert "core_goal:no_code_operation" in readiness["missing_requirements"]
    assert "core_goal:agent_friendly_harness" in readiness["missing_requirements"]


def test_evaluate_report_readiness_accepts_production_ready_plan_with_bundle(tmp_path: Path) -> None:
    project = type("ProjectStub", (), {})()
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    project.output_dir.mkdir(parents=True)

    store = ArtifactStore(project.artifacts_dir)
    store.save(PipelinePhase.PROJECT_SETUP, "project.yaml", {"name": "demo"})
    store.save(
        PipelinePhase.PROJECT_SETUP,
        "approval_card.json",
        {"status": "no_pending_approval"},
    )
    store.save(PipelinePhase.PROJECT_SETUP, "approval_card.md", "# Approval Card\n")
    store.save(PipelinePhase.PROJECT_SETUP, "harness_dashboard.json", {"progress": "100%"})
    store.save(PipelinePhase.PROJECT_SETUP, "artifact_index.json", {"artifacts": []})
    store.save(PipelinePhase.PROJECT_SETUP, "blocker_playbook.json", {"blockers": []})
    store.save(PipelinePhase.PROJECT_SETUP, "blocker_playbook.md", "# Blocker Playbook\n")
    store.save(
        PipelinePhase.PLAN_COMPLETENESS_REVIEW,
        "analysis_plan_review.json",
        {
            "status": "repaired",
            "completeness_tier": "production_ready",
            "recommended_analysis_floor": 5,
            "academic_analysis_target": 6,
            "production_analysis_target": 8,
        },
    )
    store.save(PipelinePhase.DATA_INTAKE, "intake_report.json", {"loaded_file": "demo.csv"})
    store.save(PipelinePhase.SCHEMA_REGISTRY, "schema.json", {"variables": [{"name": "age"}]})
    store.save(
        PipelinePhase.CONCEPT_ALIGNMENT,
        "concept_alignment.md",
        "# Concept\n",
    )
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        {"analyses": [{"type": "generate_table_one"}]},
    )
    store.save(
        PipelinePhase.PRE_EXPLORE_CHECK,
        "readiness_checklist.json",
        {"all_passed": True, "checks": [{"id": "H-003", "passed": True}]},
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "decision_log.jsonl",
        {"phase": "phase_08_execute_exploration", "action": "compare_groups"},
    )
    store.save(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md", "# EDA Report\n")

    readiness = _evaluate_report_readiness(
        {
            "total_analyses": 4,
            "decision_count": 4,
            "deliverables": _minimum_bundle(),
        },
        store,
    )

    assert readiness["ready"] is True
    assert readiness["target_tier"] == "production_ready"
    assert readiness["core_goal_audit"]["ready"] is True
    assert {
        check["id"] for check in readiness["core_goal_audit"]["checks"] if check["passed"]
    } >= {
        "data_understanding",
        "analysis_planning",
        "reproducible_exploration",
        "analysis_execution_interpretation",
        "report_generation",
        "no_code_operation",
        "agent_friendly_harness",
    }


def test_run_audit_recomputes_readiness_instead_of_trusting_stale_results_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("RDE_WORKSPACE", str(tmp_path / "workspace"))
    project = Project(
        id="proj-report-contract-stale-audit",
        name="stale-audit",
        data_dir=tmp_path / "rawdata",
        output_dir=tmp_path / "project",
    )
    project.data_dir.mkdir(parents=True)
    project.output_dir.mkdir(parents=True)
    (project.output_dir / "figures").mkdir()
    store = ArtifactStore(project.artifacts_dir)
    _save_production_readiness_context(store, include_project_manifest=False)
    store.save(
        PipelinePhase.COLLECT_RESULTS,
        "results_summary.json",
        {
            "total_analyses": 2,
            "decision_count": 2,
            "deliverables": _minimum_bundle(),
            "report_readiness": {
                "ready": True,
                "target_tier": "production_ready",
                "current_tier": "production_ready",
                "review_status": "pass",
                "publication_bundle_met": True,
                "core_goal_audit": {
                    "ready": True,
                    "checks": [
                        {"id": "no_code_operation", "passed": True},
                        {"id": "agent_friendly_harness", "passed": True},
                    ],
                    "missing_goals": [],
                },
                "missing_requirements": [],
            },
        },
    )

    session = get_session()
    session.register_project(project)
    pipeline = session.get_pipeline(project.id)
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.REPORT_ASSEMBLY,
            completed_at=datetime.now(),
            success=True,
            artifacts={
                "eda_report.md": str(
                    store.get_path(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
                )
            },
        )
    )

    server = _ToolCapture()
    register_audit_tools(server)

    server.tools["run_audit"](project.id)

    audit = store.load(PipelinePhase.AUDIT_REVIEW, "audit_report.json")
    core_check = next(item for item in audit["checks"] if item["category"] == "core_goal_audit")
    assert core_check["passed"] is False
    assert "no_code_operation" in core_check["missing"]
    assert "agent_friendly_harness" in core_check["missing"]


def test_run_audit_recomputes_plan_adherence_without_branch_inflation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("RDE_WORKSPACE", str(tmp_path / "workspace"))
    project = Project(
        id="proj-report-contract-stale-branch-coverage",
        name="stale-branch-coverage",
        data_dir=tmp_path / "rawdata",
        output_dir=tmp_path / "project",
    )
    project.data_dir.mkdir(parents=True)
    project.output_dir.mkdir(parents=True)
    store = ArtifactStore(project.artifacts_dir)
    _save_production_readiness_context(store, include_project_manifest=False)
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        {
            "locked": True,
            "analyses": [
                {"type": "compare_groups", "variables": ["outcome"], "required": True},
                {"type": "correlation_matrix", "variables": ["age", "bmi"], "required": True},
            ],
        },
    )
    store.save(
        PipelinePhase.COLLECT_RESULTS,
        "results_summary.json",
        {
            "total_analyses": 2,
            "phase6_progress": {
                "executed_analyses": 2,
                "branch_decision_count": 2,
                "coverage": 1.0,
            },
            "deliverables": _minimum_bundle(),
        },
    )

    session = get_session()
    session.register_project(project)
    logger = session.get_logger(project.id)
    for action in ("open_exploration_branch", "run_branch_experiment"):
        logger.log_decision(
            phase=PipelinePhase.EXECUTE_EXPLORATION.value,
            action=action,
            tool_used=action,
            parameters={"scope": "branch"},
            rationale="branch only",
            result_summary="branch only",
        )
    pipeline = session.get_pipeline(project.id)
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.REPORT_ASSEMBLY,
            completed_at=datetime.now(),
            success=True,
            artifacts={"eda_report.md": str(store.get_path(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md"))},
        )
    )

    server = _ToolCapture()
    register_audit_tools(server)
    server.tools["run_audit"](project.id)

    audit = store.load(PipelinePhase.AUDIT_REVIEW, "audit_report.json")
    adherence = next(item for item in audit["checks"] if item["category"] == "plan_adherence")
    assert adherence["passed"] is False
    assert "coverage=0%" in adherence["details"]
    assert "branch_decisions=2" in adherence["details"]


def test_export_final_report_blocks_incomplete_report_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("RDE_WORKSPACE", str(tmp_path / "workspace"))
    project = Project(
        id="proj-incomplete-final-export",
        name="incomplete-final-export",
        data_dir=tmp_path / "rawdata",
        output_dir=tmp_path / "project",
    )
    project.data_dir.mkdir(parents=True)
    project.output_dir.mkdir(parents=True)
    store = ArtifactStore(project.artifacts_dir)
    store.save(PipelinePhase.AUDIT_REVIEW, "audit_report.json", {"grade": "C"})
    store.save(PipelinePhase.AUTO_IMPROVE, "final_report.md", "# Final Report\n")
    store.save(
        PipelinePhase.COLLECT_RESULTS,
        "results_summary.json",
        {
            "total_analyses": 0,
            "decision_count": 0,
            "deliverables": {
                "minimum_publication_bundle_met": False,
                "missing_components": ["table_one"],
            },
        },
    )

    session = get_session()
    session.register_project(project)
    pipeline = session.get_pipeline(project.id)
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.AUDIT_REVIEW,
            completed_at=datetime.now(),
            success=True,
            artifacts={"audit_report.json": ""},
        )
    )
    server = _ToolCapture()
    register_audit_tools(server)

    output = server.tools["export_final_report"](project.id)

    assert "not production-ready" in output
    assert "allow_incomplete=true" in output or "allow_incomplete" in output
    assert not store.exists(PipelinePhase.AUTO_IMPROVE, "final_report_export_manifest.json")


def test_export_final_report_recomputes_readiness_instead_of_trusting_stale_improvement_log(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("RDE_WORKSPACE", str(tmp_path / "workspace"))
    project = Project(
        id="proj-stale-final-export",
        name="stale-final-export",
        data_dir=tmp_path / "rawdata",
        output_dir=tmp_path / "project",
    )
    project.data_dir.mkdir(parents=True)
    project.output_dir.mkdir(parents=True)
    store = ArtifactStore(project.artifacts_dir)
    store.save(PipelinePhase.AUDIT_REVIEW, "audit_report.json", {"grade": "A"})
    store.save(PipelinePhase.AUTO_IMPROVE, "final_report.md", "# Final Report\n")
    store.save(
        PipelinePhase.AUTO_IMPROVE,
        "improvement_log.json",
        {
            "report_readiness": {
                "ready": True,
                "target_tier": "production_ready",
                "current_tier": "production_ready",
                "review_status": "pass",
                "publication_bundle_met": True,
                "missing_requirements": [],
            }
        },
    )
    store.save(
        PipelinePhase.COLLECT_RESULTS,
        "results_summary.json",
        {
            "total_analyses": 0,
            "decision_count": 0,
            "deliverables": {
                "minimum_publication_bundle_met": False,
                "missing_components": ["table_one"],
            },
        },
    )

    session = get_session()
    session.register_project(project)
    pipeline = session.get_pipeline(project.id)
    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.AUDIT_REVIEW,
            completed_at=datetime.now(),
            success=True,
            artifacts={"audit_report.json": ""},
        )
    )
    server = _ToolCapture()
    register_audit_tools(server)

    output = server.tools["export_final_report"](project.id)

    assert "not production-ready" in output
    assert not store.exists(PipelinePhase.AUTO_IMPROVE, "final_report_export_manifest.json")


def test_evaluate_report_readiness_blocks_when_core_goal_artifacts_are_missing(
    tmp_path: Path,
) -> None:
    project = type("ProjectStub", (), {})()
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    project.output_dir.mkdir(parents=True)

    store = ArtifactStore(project.artifacts_dir)
    store.save(
        PipelinePhase.PLAN_COMPLETENESS_REVIEW,
        "analysis_plan_review.json",
        {
            "status": "pass",
            "completeness_tier": "production_ready",
        },
    )

    readiness = _evaluate_report_readiness(
        {
            "total_analyses": 0,
            "decision_count": 0,
            "deliverables": {
                "minimum_publication_bundle_met": True,
            },
        },
        store,
    )

    assert readiness["ready"] is False
    assert readiness["core_goal_audit"]["ready"] is False
    assert any(
        item.startswith("core_goal:data_understanding")
        for item in readiness["missing_requirements"]
    )
    assert any(
        item.startswith("core_goal:analysis_execution_interpretation")
        for item in readiness["missing_requirements"]
    )


def test_build_phase10_export_report_includes_table_and_figures(tmp_path: Path) -> None:
    project = type("ProjectStub", (), {})()
    project.id = "p1"
    project.dataset_ids = ["d1"]
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    (project.output_dir / "figures").mkdir(parents=True)

    for name in ["crbd_by_precedex.png", "age_years_distribution.png"]:
        (project.output_dir / "figures" / name).write_bytes(b"fake")

    store = ArtifactStore(project.artifacts_dir)
    store.save(
        PipelinePhase.AUTO_IMPROVE,
        "final_report.md",
        "# Demo Final Report\n\n## 研究問題\n內容\n\n## Phase 10 Finalization\n- done",
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "table_one.md",
        "# 📊 Table 1\n\n```\n+---+---+\n| A | B |\n+===+===+\n| 1 | 2 |\n+---+---+\n```",
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "visualization_manifest.json",
        [
            {
                "output_path": str(project.output_dir / "figures" / "crbd_by_precedex.png"),
                "stats_summary": "Chi-square; p < 0.001",
            },
            {
                "output_path": str(project.output_dir / "figures" / "age_years_distribution.png"),
                "stats_summary": "n=10",
            },
        ],
    )
    store.save(PipelinePhase.AUDIT_REVIEW, "audit_report.json", {"grade": "A"})
    store.save(PipelinePhase.COLLECT_RESULTS, "results_summary.json", {"deliverables": {}})

    report, asset_summary = _build_phase10_export_report(project, store)

    assert report.title == "Demo Final Report"
    assert any(section.title == "Table 1 — Baseline Characteristics" for section in report.sections)
    stat_section = next(section for section in report.sections if section.section_id == "statistical_analyses")
    assert len(stat_section.figures) == 2
    variable_section = next(section for section in report.sections if section.section_id == "variable_profiles")
    assert variable_section.tables[0]["headers"] == ["A", "B"]
    assert asset_summary["table"]["included"] is True
    assert asset_summary["figures"]["included_count"] == 2


def test_build_phase10_source_markdown_includes_table_gallery_and_relative_paths(
    tmp_path: Path,
) -> None:
    project = type("ProjectStub", (), {})()
    project.id = "p1"
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    project.dataset_ids = ["d1"]
    (project.output_dir / "figures").mkdir(parents=True)

    for name in ["crbd_by_precedex.png", "age_years_distribution.png"]:
        (project.output_dir / "figures" / name).write_bytes(b"fake")

    store = ArtifactStore(project.artifacts_dir)
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "table_one.md",
        "# 📊 Table 1\n\n```\n+---+---+\n| A | B |\n+===+===+\n| 1 | 2 |\n+---+---+\n```",
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "visualization_manifest.json",
        [
            {
                "output_path": str(project.output_dir / "figures" / "crbd_by_precedex.png"),
                "stats_summary": "Chi-square; p < 0.001",
                "category": "analytical",
            },
            {
                "output_path": str(project.output_dir / "figures" / "age_years_distribution.png"),
                "stats_summary": "n=10",
                "category": "descriptive",
            },
        ],
    )
    store.save(PipelinePhase.COLLECT_RESULTS, "results_summary.json", {"deliverables": {}})
    store.save(
        PipelinePhase.AUDIT_REVIEW,
        "audit_report.json",
        {"grade": "A", "total_score": 113, "max_score": 120},
    )

    assembled_report = """# Demo Final Report

## 研究問題
內容

## 資料來源與前處理
處理

## 隊列概況
隊列

## 補充圖表與最低發表包完成狀態
- 摘要

### Figure 2. 年齡分布（描述性）

![Figure 2. 年齡分布（描述性）](../../figures/age_years_distribution.png)

年齡說明
"""

    rendered = _build_phase10_source_markdown(
        project,
        store,
        assembled_report=assembled_report,
        audit={"grade": "A", "total_score": 113, "max_score": 120},
        report_readiness={
            "ready": False,
            "target_tier": "production_ready",
            "current_tier": "academic_ready",
            "review_status": "pass",
            "publication_bundle_met": True,
            "missing_requirements": [
                "completeness_tier=academic_ready < target=production_ready",
            ],
        },
        improvement_log={
            "auto_fixed": [],
            "manual_suggestions": ["建議: 補齊 completeness tier"],
        },
    )

    assert "## Table 1 — Baseline Characteristics" in rendered
    assert "| A | B |" in rendered
    assert "## Figure Gallery" in rendered
    assert "../../figures/crbd_by_precedex.png" in rendered
    assert "### Figure 2. 年齡分布（描述性）" in rendered
    assert "../phase_09_collect_results/results_summary.json" in rendered
    assert str(project.output_dir) not in rendered
    assert rendered.count("- 摘要") == 1


def test_build_recommendations_mentions_report_readiness_gap() -> None:
    text = _build_recommendations(
        {
            "deliverables": {
                "missing_components": [],
            },
            "publishable_count": 0,
            "deviation_count": 0,
            "report_readiness": {
                "ready": False,
                "missing_requirements": [
                    "completeness_tier=academic_ready < target=production_ready",
                    "publication_bundle",
                ],
            },
        },
        None,
    )

    assert "終版完整報告" in text
    assert "production_ready" in text


def test_render_phase10_readiness_summary_explains_missing_production_requirements() -> None:
    text = _render_phase10_readiness_summary(
        {
            "ready": False,
            "target_tier": "production_ready",
            "current_tier": "academic_ready",
            "review_status": "pass",
            "publication_bundle_met": False,
            "missing_requirements": [
                "completeness_tier=academic_ready < target=production_ready",
                "publication_bundle",
            ],
        }
    )

    assert "not production-ready" in text
    assert "academic_ready" in text
    assert "publication_bundle" in text


def test_build_phase10_final_report_appends_readiness_and_improvement_summary() -> None:
    final_report = _build_phase10_final_report(
        "# EDA Report\n\nCore content.",
        audit={"grade": "B", "total_score": 88, "max_score": 120},
        report_readiness={
            "ready": True,
            "target_tier": "production_ready",
            "current_tier": "production_ready",
            "review_status": "repaired",
            "publication_bundle_met": True,
            "missing_requirements": [],
        },
        improvement_log={
            "auto_fixed": ["✅ rebuilt final report"],
            "manual_suggestions": ["建議: review residual issues"],
        },
    )

    assert "# EDA Report" in final_report
    assert "## Phase 10 Finalization" in final_report
    assert "## Production Readiness" in final_report
    assert "production-ready" in final_report
    assert "## Auto-fixed Items" in final_report
    assert "## Remaining Suggestions" in final_report
