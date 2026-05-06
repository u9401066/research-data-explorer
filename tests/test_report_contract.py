from pathlib import Path

from rde.domain.models.report import EDAReport, ReportSection
from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.tools.report_tools import (
    _build_recommendations,
    _evaluate_report_readiness,
    _format_baseline_table,
    _format_data_overview,
    _format_data_quality,
    _format_variable_profiles,
    _summarize_publication_deliverables,
)
from rde.interface.mcp.tools.audit_tools import (
    _build_phase10_final_report,
    _build_phase10_export_report,
    _build_phase10_source_markdown,
    _render_phase10_readiness_summary,
)
from rde.application.use_cases.export_report import ExportReportUseCase
from rde.application.use_cases.generate_report import GenerateReportUseCase
from rde.infrastructure.adapters.markdown_renderer import MarkdownReportRenderer
from rde.infrastructure.persistence.artifact_store import ArtifactStore


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
    assert "粗分析圖 1/3" in summary["missing_components"]
    assert "細分析圖 1/6" in summary["missing_components"]


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


def test_evaluate_report_readiness_accepts_production_ready_plan_with_bundle(tmp_path: Path) -> None:
    project = type("ProjectStub", (), {})()
    project.output_dir = tmp_path / "project"
    project.artifacts_dir = project.output_dir / "artifacts"
    project.output_dir.mkdir(parents=True)

    store = ArtifactStore(project.artifacts_dir)
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

    readiness = _evaluate_report_readiness(
        {
            "total_analyses": 4,
            "decision_count": 4,
            "deliverables": {
                "minimum_publication_bundle_met": True,
            }
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
