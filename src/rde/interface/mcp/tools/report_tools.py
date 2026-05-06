"""Report Tools — Phase 9 (Collect Results) & Phase 10 (Report Assembly).

Collects results from previous phases, assembles the EDA report,
and provides visualization creation.
Enforces H-005 (Report Integrity), H-006 (Output Sanitization).
All tools return markdown strings.
"""

from __future__ import annotations

import re
from typing import Any


MIN_DESCRIPTIVE_FIGURES = 3
MIN_ANALYTICAL_FIGURES = 6
_COMPLETENESS_RANKS = {
    "underpowered": 0,
    "minimum_complete": 1,
    "academic_ready": 2,
    "production_ready": 3,
}


def register_report_tools(server: Any) -> None:
    """Register report and visualization MCP tools."""

    @server.tool()
    def collect_results(project_id: str | None = None, force: bool = False) -> str:
        """彙整 Phase 8 的所有分析結果，標記可發表內容 (Phase 9)。

        掃描已完成的分析，生成 results_summary.json。
        標記統計顯著的結果為 PUBLISHABLE，並建議敏感度分析 (S-012)。

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
            force: 是否強制在未達 Phase 8 覆蓋率時收斂（會記錄偏離）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            ensure_phase_ready,
            ensure_project_context,
            ensure_dataset,
        )
        from rde.interface.mcp.tools._shared.project_context import (
            compute_phase6_progress,
            format_phase6_gate_message,
            mark_phase6_complete_if_ready,
            persist_project,
            project_dataset_ids,
            save_phase6_progress,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("collect_results", {"project_id": project_id, "force": force})

        ok, msg, project = ensure_project_context(project_id)
        if not ok or project is None:
            return fmt_error(msg)

        try:
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult
            from rde.domain.models.project import ProjectStatus
            from rde.infrastructure.persistence.artifact_store import ArtifactStore
            from datetime import datetime

            session = get_session()
            pipeline = session.get_pipeline(project.id)
            logger = session.get_logger(project.id)
            store = ArtifactStore(project.artifacts_dir)

            # Gate Phase 9 on sufficient Phase 8 coverage
            progress = compute_phase6_progress(project)
            progress, progress_path = save_phase6_progress(project, progress)
            if PipelinePhase.EXECUTE_EXPLORATION not in pipeline.completed_phases:
                if progress.get("ready"):
                    mark_phase6_complete_if_ready(project, pipeline, progress, progress_path)
                elif not force:
                    return fmt_error(
                        format_phase6_gate_message(progress),
                        suggestion="請依分析計畫持續進行 Phase 8，或在說明下使用 force=true。",
                    )
                else:
                    logger.log_deviation(
                        phase=PipelinePhase.EXECUTE_EXPLORATION.value,
                        planned_action="完成已鎖定計畫後再收斂",
                        actual_action="force=true 提早收斂 Phase 8",
                        reason="[S-011] 未達計畫覆蓋率即進入 Phase 7",
                        impact_assessment="請在審計時確認未完成的分析是否關鍵",
                    )
                    mark_phase6_complete_if_ready(
                        project, pipeline, progress, progress_path, force=True
                    )

            ok, msg, _, _ = ensure_phase_ready(PipelinePhase.COLLECT_RESULTS, project_id=project.id)
            if not ok:
                return fmt_error(msg)

            # Read all datasets' analysis results
            datasets = project_dataset_ids(project)
            all_results: list[dict] = []
            publishable: list[dict] = []
            unavailable_datasets: list[dict[str, str]] = []

            for ds_id in datasets:
                ok_dataset, dataset_msg, entry = ensure_dataset(ds_id, project=project)
                if not ok_dataset or entry is None:
                    unavailable_datasets.append({"dataset_id": ds_id, "reason": dataset_msg})
                    continue
                for result in entry.analysis_results:
                    result_dict = {
                        "dataset_id": ds_id,
                        "analysis_type": result.analysis_type,
                        "test_count": len(result.tests),
                        "significant_count": len(result.significant_tests),
                        "warnings": result.warnings,
                    }
                    all_results.append(result_dict)

                    # Mark statistically significant results as PUBLISHABLE
                    for t in result.significant_tests:
                        publishable.append(
                            {
                                "dataset_id": ds_id,
                                "test_name": t.test_name,
                                "variables": list(t.variables_involved),
                                "p_value": t.p_value,
                                "effect_size": t.effect_size,
                                "effect_size_name": getattr(t, "effect_size_name", None),
                                "marker": "PUBLISHABLE",
                            }
                        )

            # Read decision + deviation logs
            logger = session.get_logger(project.id)
            decisions = logger.read_decisions()
            deviations = logger.read_deviations()
            executed_analyses = max(len(all_results), len(decisions))

            # Check plan coverage
            plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
            plan_coverage = None
            if plan and isinstance(plan, dict):
                planned_analyses = [
                    entry
                    for entry in plan.get("analyses", plan.get("steps", []))
                    if not isinstance(entry, dict) or entry.get("required", True)
                ]
                plan_coverage = {
                    "planned": len(planned_analyses),
                    "executed": executed_analyses,
                    "coverage": min(1.0, executed_analyses / max(1, len(planned_analyses))),
                }
                progress["planned_analyses"] = plan_coverage["planned"]
                progress["executed_analyses"] = plan_coverage["executed"]
                progress["coverage"] = plan_coverage["coverage"]

            # S-012: Sensitivity analysis suggestion
            sensitivity_hint = None
            if publishable:
                sensitivity_hint = (
                    "[S-012] 有顯著結果，建議進行敏感度分析（如排除極端值或變更 α 值）。"
                )

            deliverables = _summarize_publication_deliverables(project, store)
            report_readiness = _evaluate_report_readiness(
                {"deliverables": deliverables},
                store,
            )

            summary = {
                "total_analyses": executed_analyses,
                "publishable_count": len(publishable),
                "publishable_items": publishable,
                "plan_coverage": plan_coverage,
                "decision_count": len(decisions),
                "deviation_count": len(deviations),
                "unavailable_datasets": unavailable_datasets,
                "phase6_progress": progress,
                "deliverables": deliverables,
                "report_readiness": report_readiness,
            }

            # Save artifact
            store.save(PipelinePhase.COLLECT_RESULTS, "results_summary.json", summary)
            pipeline.mark_completed(
                PhaseResult(
                    phase=PipelinePhase.COLLECT_RESULTS,
                    completed_at=datetime.now(),
                    success=True,
                    artifacts={
                        "results_summary.json": str(
                            store.get_path(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
                        )
                    },
                )
            )
            project.advance_to(ProjectStatus.COLLECT_RESULTS)
            persist_project(project)

            # Format output
            lines = [
                "# 📋 結果彙整 (Phase 7)\n",
                f"- **分析總數:** {executed_analyses}",
                f"- **可發表項目:** {len(publishable)}",
                f"- **決策紀錄:** {len(decisions)} 筆",
                f"- **計畫偏離:** {len(deviations)} 筆",
            ]

            if plan_coverage:
                lines.append(
                    f"- **計畫涵蓋率:** {plan_coverage['coverage']:.0%} "
                    f"({plan_coverage['executed']}/{plan_coverage['planned']})"
                )
            else:
                lines.append(
                    f"- **Phase 8 進度:** 已執行 {progress.get('executed_analyses', 0)} 項 "
                    f"(門檻: {progress.get('required_executions')})"
                )

            lines.append(f"- **Table 1:** {'✅' if deliverables['table_one_present'] else '❌'}")
            lines.append(
                f"- **粗分析圖:** {deliverables['descriptive_figures']}/{deliverables['required_descriptive_figures']}"
            )
            lines.append(
                f"- **細分析圖:** {deliverables['analytical_figures']}/{deliverables['required_analytical_figures']}"
            )
            lines.append(
                f"- **最終報告 readiness:** {report_readiness['current_tier']} → {report_readiness['target_tier']} ({'ready' if report_readiness['ready'] else 'not ready'})"
            )
            if deliverables["missing_components"]:
                lines.append(
                    f"- **最低發表包缺口:** {', '.join(deliverables['missing_components'])}"
                )
            if report_readiness["missing_requirements"]:
                lines.append(
                    f"- **終版報告缺口:** {', '.join(report_readiness['missing_requirements'])}"
                )

            if publishable:
                lines.append("\n## 🟢 可發表結果 (PUBLISHABLE)")
                for p in publishable:
                    es = (
                        f", {p['effect_size_name']}={p['effect_size']:.3f}"
                        if p.get("effect_size")
                        else ""
                    )
                    lines.append(
                        f"- {', '.join(p['variables'])}: {p['test_name']} p={p['p_value']:.4f}{es}"
                    )

            if sensitivity_hint:
                lines.append(f"\n💡 {sensitivity_hint}")

            lines.append("\n**Artifact:** results_summary.json")

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("collect_results", e)
            return fmt_error(f"結果彙整失敗: {e}")

    @server.tool()
    def assemble_report(
        project_id: str | None = None,
        title: str = "EDA Report",
        allow_incomplete: bool = False,
    ) -> str:
        """組裝完整 EDA 報告 (Phase 10)。

        從各 Phase 的 artifacts 組裝報告，含附錄 (decision_log, deviation_log)。
        執行 H-005 (報告完整性) 和 H-006 (輸出清毒)。

        Args:
            project_id: 專案 ID (預設使用當前專案)
            title: 報告標題
            allow_incomplete: 若為 True，允許在未達預設完整度目標時仍組裝報告
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            fmt_success,
            ensure_phase_ready,
        )
        from rde.interface.mcp.tools._shared.project_context import (
            persist_project,
            project_dataset_ids,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call(
            "assemble_report",
            {"project_id": project_id, "title": title, "allow_incomplete": allow_incomplete},
        )

        ok, msg, project, _ = ensure_phase_ready(
            PipelinePhase.REPORT_ASSEMBLY, project_id=project_id
        )
        if not ok:
            return fmt_error(msg)
        assert project is not None

        try:
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult
            from rde.application.use_cases.generate_report import GenerateReportUseCase
            from rde.domain.models.project import ProjectStatus
            from rde.infrastructure.adapters import MarkdownReportRenderer
            from rde.infrastructure.persistence.artifact_store import ArtifactStore
            from datetime import datetime

            session = get_session()
            pipeline = session.get_pipeline(project.id)
            logger = session.get_logger(project.id)
            store = ArtifactStore(project.artifacts_dir)
            results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
            report_readiness = _evaluate_report_readiness(results, store)
            if not allow_incomplete and not report_readiness.get("ready", False):
                return fmt_error(
                    "最終報告完整度未達預設目標，暫不組裝終版報告。",
                    _render_report_readiness_markdown(report_readiness),
                    suggestion="先補齊 methodology / deliverables 缺口，或以 allow_incomplete=true 明示覆蓋。",
                )

            # Collect artifacts for report sections
            artifacts: dict[str, str] = {}

            # Data overview from intake / schema
            intake = store.load(PipelinePhase.DATA_INTAKE, "intake_report.json")
            schema = store.load(PipelinePhase.SCHEMA_REGISTRY, "schema.json")
            if intake:
                artifacts["data_overview"] = _format_data_overview(intake, schema)

            # Data quality from schema / readiness
            readiness = store.load(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json")
            if schema or readiness:
                artifacts["data_quality"] = _format_data_quality(schema, readiness)

            # Variable profiles from schema
            if schema:
                artifacts["variable_profiles"] = _format_variable_profiles(schema)

            table_one = store.load(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md")
            if table_one:
                artifacts["baseline_table"] = _format_baseline_table(table_one)

            # Statistical analyses from results summary
            if results:
                artifacts["statistical_analyses"] = _format_analyses(results)
                artifacts["key_findings"] = _format_findings(results)
            else:
                # Quick explore mode: try to create from session data
                datasets = project_dataset_ids(project)
                if datasets:
                    artifacts["statistical_analyses"] = "[Quick Explore — No formal analysis plan]"
                    artifacts["key_findings"] = "[Quick Explore — Review individual analyses]"

            sensitivity_artifacts = _load_phase6_markdown_bundle(store, "sensitivity_analysis")
            if sensitivity_artifacts:
                artifacts["sensitivity_analysis"] = sensitivity_artifacts

            learning_curve_artifacts = _load_phase6_markdown_bundle(
                store,
                "advanced_analysis_learning_curve_cusum",
            )
            if learning_curve_artifacts:
                artifacts["learning_curve_cusum"] = learning_curve_artifacts

            # Recommendations
            artifacts["recommendations"] = _build_recommendations(results, readiness)

            # Pick first dataset_id for report metadata
            datasets = project_dataset_ids(project)
            dataset_id = datasets[-1] if datasets else "unknown"

            # Generate report via use case
            renderer = MarkdownReportRenderer()
            use_case = GenerateReportUseCase(renderer)

            report = use_case.execute(
                dataset_id=dataset_id,
                project_id=project.id,
                title=title,
                artifacts=artifacts,
            )

            # Add metadata
            report.metadata["pipeline_phases_completed"] = len(pipeline.completed_phases)
            report.metadata["decision_count"] = logger.decision_count
            report.metadata["deviation_count"] = logger.deviation_count

            # Render to markdown
            content = use_case.render(report, "markdown")

            # Add appendices (decision log + deviation log)
            appendix = _build_appendix(logger)
            content += "\n" + appendix

            # Save artifact
            store.save(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md", content)
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
            project.advance_to(ProjectStatus.REPORT_ASSEMBLY)
            persist_project(project)

            word_count = len(content.split())
            return fmt_success(
                f"EDA 報告已組裝 — {word_count} 字",
                f"- **報告標題:** {title}\n"
                f"- **完整度目標:** {report_readiness.get('target_tier')}\n"
                f"- **目前 tier:** {report_readiness.get('current_tier')}\n"
                f"- **章節數:** {len(report.sections)}\n"
                f"- **決策紀錄:** {logger.decision_count} 筆\n"
                f"- **偏離紀錄:** {logger.deviation_count} 筆\n"
                f"- **Artifact:** eda_report.md\n\n"
                f"使用 `read_file` 查看完整報告，或 `run_audit()` 進行審計。",
            )

        except ValueError as e:
            # H-005 or H-006 violation
            return fmt_error(f"報告完整性/清毒失敗: {e}")
        except Exception as e:
            log_tool_error("assemble_report", e)
            return fmt_error(f"報告組裝失敗: {e}")

    @server.tool()
    def create_visualization(
        dataset_id: str,
        plot_type: str,
        variables: list[str],
        output_filename: str | None = None,
        group_var: str | None = None,
    ) -> str:
        """建立資料視覺化圖表。H-009 自動記錄。

        支援類型: histogram, boxplot, scatter, bar, violin, heatmap, line, paired。
        對 histogram / boxplot / scatter / bar / violin / heatmap / line / paired 會自動附加摘要統計；
        若圖表支援比較或關聯檢定，預設會在圖中標註 p 值或相關係數。
        圖表儲存在專案的 figures/ 目錄，報告和 handoff 時自動嵌入。

        Args:
            dataset_id: 資料集 ID
            plot_type: 圖表類型，如 "histogram"、"boxplot"、"scatter"、"violin"、"heatmap"
            variables: 變數列表，如 ["age"]（histogram）或 ["age", "bmi"]（scatter）
            output_filename: 輸出檔名，如 "age_distribution.png"（可選，預設自動生成）
            group_var: 分組變數，如 "treatment_group"（可選，用於組間比對圖）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            fmt_success,
            ensure_minimum_sample_size,
            ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call(
            "create_visualization",
            {
                "plot_type": plot_type,
                "variables": variables,
            },
        )

        ok, msg, project, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert entry is not None
        ok, msg = ensure_minimum_sample_size(entry)
        if not ok:
            return fmt_error(msg)

        valid_types = [
            "histogram",
            "boxplot",
            "scatter",
            "bar",
            "violin",
            "heatmap",
            "line",
            "paired",
        ]
        if plot_type not in valid_types:
            return fmt_error(f"不支援的圖表類型 '{plot_type}'。支援: {', '.join(valid_types)}")

        try:
            from rde.infrastructure.visualization.matplotlib_viz import MatplotlibVisualizer

            # Determine output path
            if output_filename is None:
                var_str = "_".join(variables[:2])
                output_filename = f"{plot_type}_{var_str}.png"

            output_dir = project.output_dir / "figures"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / output_filename

            viz = MatplotlibVisualizer()
            kwargs = {}
            if group_var:
                kwargs["group_var"] = group_var

            result_path = viz.create_plot(
                data=entry.dataframe,
                plot_type=plot_type,
                variables=variables,
                output_path=output_path,
                **kwargs,
            )
            stats_summary = viz.last_annotation_summary
            _upsert_visualization_manifest(
                project,
                plot_type=plot_type,
                variables=variables,
                result_path=result_path,
                group_var=group_var,
                stats_summary=stats_summary,
            )

            from rde.interface.mcp.tools.analysis_tools import _auto_log_decision

            _auto_log_decision(
                "create_visualization",
                {"plot_type": plot_type, "variables": variables, "group_var": group_var},
                "生成視覺化圖表",
                (
                    f"{plot_type}: {result_path} | {stats_summary}"
                    if stats_summary
                    else f"{plot_type}: {result_path}"
                ),
                artifacts=[result_path],
            )

            details = [
                f"- **類型:** {plot_type}",
                f"- **變數:** {', '.join(variables)}",
            ]
            if stats_summary:
                details.append(f"- **統計註記:** {stats_summary}")
            details.append(f"- **路徑:** {result_path}")

            return fmt_success(
                f"圖表已生成: {output_filename}",
                "\n".join(details),
            )

        except Exception as e:
            log_tool_error("create_visualization", e)
            return fmt_error(f"圖表生成失敗: {e}")

    @server.tool()
    def export_report(
        project_id: str | None = None,
        formats: str = "docx",
        title: str = "EDA Report",
        allow_incomplete: bool = False,
    ) -> str:
        """匯出 EDA 報告為 Word (.docx) 或 PDF 格式。

        自動嵌入圖表和統計表格到文件中。
        需先完成 assemble_report (Phase 10)。

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
            formats: 匯出格式，以逗號分隔，如 "docx"、"pdf"、"docx,pdf"（預設: docx）
            title: 報告標題，如 "Sepsis EDA Report"（預設: EDA Report）
            allow_incomplete: 若為 True，允許在未達預設完整度目標時仍匯出報告
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            fmt_success,
            ensure_phase_ready,
        )
        from rde.interface.mcp.tools._shared.project_context import project_dataset_ids
        from rde.application.pipeline import PipelinePhase

        log_tool_call(
            "export_report",
            {"formats": formats, "title": title, "allow_incomplete": allow_incomplete},
        )

        ok, msg, project, _ = ensure_phase_ready(
            PipelinePhase.REPORT_ASSEMBLY, project_id=project_id
        )
        if not ok:
            return fmt_error(msg)
        assert project is not None

        try:
            from rde.application.pipeline import PipelinePhase
            from rde.application.use_cases.generate_report import GenerateReportUseCase
            from rde.application.use_cases.export_report import ExportReportUseCase
            from rde.infrastructure.adapters.markdown_renderer import MarkdownReportRenderer
            from rde.infrastructure.adapters.docx_exporter import DocxExporter
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            store = ArtifactStore(project.artifacts_dir)

            # H-008: Phase 10 report assembly must be done
            if not store.exists(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md"):
                return fmt_error("[H-008] 報告尚未組裝。請先執行 `assemble_report()` (Phase 10)。")

            # Rebuild EDAReport from artifacts (same logic as assemble_report)
            artifacts: dict[str, str] = {}
            intake = store.load(PipelinePhase.DATA_INTAKE, "intake_report.json")
            schema = store.load(PipelinePhase.SCHEMA_REGISTRY, "schema.json")
            readiness = store.load(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json")
            results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
            report_readiness = _evaluate_report_readiness(results, store)
            if not allow_incomplete and not report_readiness.get("ready", False):
                return fmt_error(
                    "最終報告完整度未達預設目標，暫不匯出終版報告。",
                    _render_report_readiness_markdown(report_readiness),
                    suggestion="先補齊 methodology / deliverables 缺口，或以 allow_incomplete=true 明示覆蓋。",
                )

            if intake:
                artifacts["data_overview"] = _format_data_overview(intake, schema)
            if schema or readiness:
                artifacts["data_quality"] = _format_data_quality(schema, readiness)
            if schema:
                artifacts["variable_profiles"] = _format_variable_profiles(schema)
            table_one = store.load(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md")
            if table_one:
                artifacts["baseline_table"] = _format_baseline_table(table_one)
            if results:
                artifacts["statistical_analyses"] = _format_analyses(results)
                artifacts["key_findings"] = _format_findings(results)
            else:
                artifacts["statistical_analyses"] = "[Quick Explore]"
                artifacts["key_findings"] = "[Quick Explore]"
            sensitivity_artifacts = _load_phase6_markdown_bundle(store, "sensitivity_analysis")
            if sensitivity_artifacts:
                artifacts["sensitivity_analysis"] = sensitivity_artifacts
            learning_curve_artifacts = _load_phase6_markdown_bundle(
                store,
                "advanced_analysis_learning_curve_cusum",
            )
            if learning_curve_artifacts:
                artifacts["learning_curve_cusum"] = learning_curve_artifacts
            artifacts["recommendations"] = _build_recommendations(results, readiness)

            datasets = project_dataset_ids(project)
            dataset_id = datasets[-1] if datasets else "unknown"

            renderer = MarkdownReportRenderer()
            gen_uc = GenerateReportUseCase(renderer)
            report = gen_uc.execute(
                dataset_id=dataset_id,
                project_id=project.id,
                title=title,
                artifacts=artifacts,
            )

            # Parse format list
            fmt_list = [f.strip().lower() for f in formats.split(",")]
            valid_fmts = {"docx", "pdf"}
            invalid = [f for f in fmt_list if f not in valid_fmts]
            if invalid:
                return fmt_error(f"不支援的格式: {', '.join(invalid)}。支援: docx, pdf")

            # Export
            figures_dir = project.output_dir / "figures"
            output_dir = project.artifacts_dir / "exports"
            exporter = DocxExporter()
            export_uc = ExportReportUseCase(exporter)

            exported = export_uc.execute(
                report=report,
                output_dir=output_dir,
                formats=fmt_list,
                figures_dir=figures_dir,
            )

            lines = []
            for fmt, path in exported.items():
                label = fmt.upper()
                if path.suffix.lower() == ".html":
                    label = f"{label} (HTML fallback)"
                lines.append(f"- **{label}:** {path}")
            fig_count = sum(len(s.figures) for s in report.sections)

            return fmt_success(
                f"報告已匯出 — {', '.join(f.upper() for f in exported)}",
                f"- **完整度目標:** {report_readiness.get('target_tier')}\n"
                f"- **目前 tier:** {report_readiness.get('current_tier')}\n"
                f"- **嵌入圖表:** {fig_count} 張\n"
                + "\n".join(lines),
            )

        except ImportError as e:
            # weasyprint not installed for PDF
            return fmt_error(str(e))
        except ValueError as e:
            return fmt_error(f"匯出失敗: {e}")
        except Exception as e:
            log_tool_error("export_report", e)
            return fmt_error(f"匯出失敗: {e}")


# ── Helper functions for report assembly ────────────────────────────


def _format_data_overview(
    intake: dict | None,
    schema: dict | None,
) -> str:
    """Format data overview section from intake + schema artifacts."""
    lines = []
    if intake:
        lines.append(f"**檔案:** {intake.get('loaded_file', intake.get('filename', '?'))}")
        rows = intake.get("row_count", intake.get("rows", "?"))
        lines.append(f"**列數:** {rows}")
        lines.append(f"**欄數:** {intake.get('column_count', intake.get('columns', '?'))}")
        if intake.get("size_mb"):
            lines.append(f"**大小:** {intake['size_mb']:.1f} MB")
    if schema:
        var_count = len(schema.get("variables", []))
        lines.append(f"**Schema 變數數:** {var_count}")
    return "\n".join(lines) if lines else "[Data overview not available]"


def _format_data_quality(
    schema: dict | None,
    readiness: dict | None,
) -> str:
    """Format data quality section."""
    lines = []
    if readiness:
        checks = readiness.get("checks", [])
        passed = sum(1 for c in checks if c.get("passed"))
        lines.append(f"**前置檢查:** {passed}/{len(checks)} 通過\n")
        for c in checks:
            icon = "✅" if c.get("passed") else "❌"
            detail = c.get("detail", c.get("message", ""))
            lines.append(f"- {icon} [{c.get('id', '')}] {c.get('name', '?')}: {detail}")

        # Highlight S-005 missing pattern if present
        missing_check = next((c for c in checks if c.get("id") == "S-005"), None)
        if missing_check and "MCAR" not in missing_check.get("detail", ""):
            lines.append(f"\n**⚠️ 缺失模式注意:** {missing_check.get('detail', '')}")

        # Highlight S-007 collinearity if present
        collinear_check = next((c for c in checks if c.get("id") == "S-007"), None)
        if collinear_check and "高相關" in collinear_check.get("detail", ""):
            lines.append(f"\n**⚠️ 共線性注意:** {collinear_check.get('detail', '')}")

    if schema:
        missing = schema.get("missing_summary", {})
        if missing:
            lines.append(f"\n**缺失值摘要:** {missing}")
        # Variable type breakdown
        variables = schema.get("variables", [])
        if variables:
            type_counts: dict[str, int] = {}
            for v in variables:
                vt = v.get("variable_type", v.get("type", "unknown"))
                type_counts[vt] = type_counts.get(vt, 0) + 1
            lines.append(
                "\n**變數類型分佈:** "
                + ", ".join(f"{t}: {n}" for t, n in sorted(type_counts.items()))
            )
    return "\n".join(lines) if lines else "[Data quality information not available]"


def _format_variable_profiles(schema: dict | None) -> str:
    """Format variable profiles from schema."""
    if not schema or "variables" not in schema:
        return "[Variable profiles not available]"
    variables = schema["variables"]
    lines = [f"共 {len(variables)} 個變數:\n"]
    lines.append("| 變數 | 類型 | 缺失率 |")
    lines.append("| --- | --- | --- |")
    for v in variables[:50]:  # Cap at 50 rows
        name = v.get("name", "?")
        vtype = v.get("variable_type", v.get("type", "?"))
        missing = v.get("missing_rate", v.get("missing_pct", 0))
        lines.append(f"| {name} | {vtype} | {missing:.1%} |")
    return "\n".join(lines)


def _format_baseline_table(table_one_markdown: str | None) -> str:
    """Format persisted Table 1 artifact for the report."""
    if not table_one_markdown:
        return "[Table 1 not available]"

    cleaned = table_one_markdown.strip()
    if cleaned.startswith("#"):
        heading_parts = cleaned.split("\n", 1)
        cleaned = heading_parts[1].strip() if len(heading_parts) > 1 else cleaned

    rows = _parse_table_markdown_rows(cleaned)
    notes = _extract_table_markdown_notes(cleaned)

    parts: list[str] = []
    if rows:
        parts.append(_render_markdown_table(rows))
    if notes:
        parts.append("\n".join(notes))

    return "\n\n".join(parts) if parts else cleaned


def _parse_table_markdown_rows(table_markdown: str | None) -> list[list[str]]:
    """Parse pipe tables or fenced tabulate-grid tables into rows."""
    if not table_markdown:
        return []

    cleaned = str(table_markdown).strip()
    fenced = re.search(r"```(?:[\w+-]+)?\n(?P<body>.*?)\n```", cleaned, re.DOTALL)
    candidate = fenced.group("body") if fenced else cleaned

    rows: list[list[str]] = []
    for line in candidate.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or all(cell == "" for cell in cells):
            continue
        rows.append(cells)

    return rows


def _extract_table_markdown_notes(table_markdown: str | None) -> list[str]:
    """Extract bullet notes that follow a persisted Table 1 artifact."""
    if not table_markdown:
        return []

    notes: list[str] = []
    in_fence = False
    for raw_line in str(table_markdown).splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            notes.append(stripped)
    return notes


def _render_markdown_table(rows: list[list[str]]) -> str:
    """Render parsed table rows as a markdown pipe table."""
    if not rows:
        return ""

    n_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (n_cols - len(row)) for row in rows]
    header = normalized[0]
    body = normalized[1:]

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _load_phase6_markdown_bundle(store: Any, prefix: str) -> str | None:
    """Load and concatenate optional Phase 8 markdown artifacts by filename prefix."""
    from rde.application.pipeline import PipelinePhase

    filenames = [
        name
        for name in store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION)
        if name.startswith(prefix) and name.endswith(".md")
    ]
    if not filenames:
        return None

    rendered: list[str] = []
    for name in sorted(filenames):
        content = store.load(PipelinePhase.EXECUTE_EXPLORATION, name)
        if not content:
            continue
        rendered.append(str(content).strip())

    return "\n\n---\n\n".join(rendered) if rendered else None


def _format_analyses(results: dict | None) -> str:
    """Format statistical analyses section."""
    if not results:
        return "[No analysis results collected]"
    lines = [f"**分析總數:** {results.get('total_analyses', 0)}"]
    report_readiness = results.get("report_readiness") or {}
    if report_readiness:
        lines.extend(
            [
                f"**完整度目標:** {report_readiness.get('target_tier', 'unknown')}",
                f"**目前 tier:** {report_readiness.get('current_tier', 'unknown')}",
                f"**最終報告就緒:** {'是' if report_readiness.get('ready') else '否'}",
            ]
        )
        if report_readiness.get("missing_requirements"):
            lines.append(
                f"**完整度缺口:** {', '.join(report_readiness.get('missing_requirements', []))}"
            )
    deliverables = results.get("deliverables") or {}
    if deliverables:
        lines.extend(
            [
                f"**Table 1:** {'已提供' if deliverables.get('table_one_present') else '缺少'}",
                f"**粗分析圖:** {deliverables.get('descriptive_figures', 0)}/{deliverables.get('required_descriptive_figures', MIN_DESCRIPTIVE_FIGURES)}",
                f"**細分析圖:** {deliverables.get('analytical_figures', 0)}/{deliverables.get('required_analytical_figures', MIN_ANALYTICAL_FIGURES)}",
            ]
        )
        missing = deliverables.get("missing_components", [])
        if missing:
            lines.append(f"**最低發表包缺口:** {', '.join(missing)}")
    pub = results.get("publishable_items", [])
    if pub:
        lines.append("\n**可發表結果:**")
        for p in pub:
            lines.append(f"- {p.get('test_name', '?')}: p={p.get('p_value', '?')}")
    return "\n".join(lines)


def _format_findings(results: dict | None) -> str:
    """Format key findings section."""
    if not results:
        return "[No findings to report]"
    pub = results.get("publishable_items", [])
    if not pub:
        return "No statistically significant findings."
    lines = [f"共 {len(pub)} 項顯著發現:\n"]
    for p in pub:
        vars_str = ", ".join(p.get("variables", []))
        details = [f"p={p.get('p_value', '?')}"]
        if p.get("effect_size") is not None:
            es_name = p.get("effect_size_name", "effect size")
            es_val = p["effect_size"]
            # Interpret effect size magnitude
            magnitude = ""
            if abs(es_val) < 0.2:
                magnitude = " (小)"
            elif abs(es_val) < 0.5:
                magnitude = " (中)"
            else:
                magnitude = " (大)"
            details.append(f"{es_name}={es_val:.3f}{magnitude}")
        lines.append(f"- **{vars_str}:** {p.get('test_name', '?')} ({', '.join(details)})")
    return "\n".join(lines)


def _build_recommendations(results: dict | None, readiness: dict | None) -> str:
    """Build recommendations section."""
    lines = []
    if results:
        if results.get("deviation_count", 0) > 0:
            lines.append("- 請檢查偏離紀錄 (deviation_log)，確認方法變更的合理性。")
        if results.get("publishable_count", 0) > 0:
            lines.append("- 建議對顯著結果進行敏感度分析 (S-012)。")
        plan_cov = results.get("plan_coverage", {})
        if plan_cov and plan_cov.get("coverage", 1.0) < 0.8:
            lines.append("- 計畫涵蓋率不足 80%，請檢查是否有遺漏的分析項目。")
        deliverables = results.get("deliverables") or {}
        if deliverables.get("missing_components"):
            lines.append("- 最低發表包尚未滿足，請至少補齊 Table 1、3 張粗分析圖、6 張細分析圖。")
        report_readiness = results.get("report_readiness") or {}
        if report_readiness and not report_readiness.get("ready", False):
            lines.append(
                "- 若要直接產出終版完整報告，請先補齊以下缺口: "
                + ", ".join(report_readiness.get("missing_requirements", []))
            )
    if readiness:
        for c in readiness.get("checks", []):
            if not c.get("passed"):
                lines.append(f"- 注意: {c.get('name', '?')} 檢查未通過。")
    if not lines:
        lines.append("- 所有分析已完成，可進行審計 (Phase 9)。")
    return "\n".join(lines)


def _build_appendix(logger: Any) -> str:
    """Build appendix with decision log and deviation log."""
    lines = [
        "\n---\n",
        "## Appendix A: Decision Log\n",
    ]

    decisions = logger.read_decisions()
    if decisions:
        lines.append("| # | Phase | Action | Rationale | Result |")
        lines.append("| --- | --- | --- | --- | --- |")
        for i, d in enumerate(decisions):
            lines.append(
                f"| {i + 1} | {d.get('phase', '')} | {d.get('action', '')} | "
                f"{d.get('rationale', '')} | {d.get('result_summary', '')} |"
            )
    else:
        lines.append("*No decisions recorded.*\n")

    lines.append("\n## Appendix B: Deviation Log\n")

    deviations = logger.read_deviations()
    if deviations:
        lines.append("| # | Phase | Planned | Actual | Reason | Impact |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for i, d in enumerate(deviations):
            lines.append(
                f"| {i + 1} | {d.get('phase', '')} | {d.get('planned_action', '')} | "
                f"{d.get('actual_action', '')} | {d.get('reason', '')} | "
                f"{d.get('impact_assessment', '')} |"
            )
    else:
        lines.append("*No deviations from plan.*\n")

    lines.append("\n## Appendix C: Reproducibility\n")
    lines.append("- **Pipeline:** RDE 13-Phase Auditable EDA")
    lines.append(f"- **Decision count:** {logger.decision_count}")
    lines.append(f"- **Deviation count:** {logger.deviation_count}")

    return "\n".join(lines)


def _visualization_category(plot_type: str, group_var: str | None) -> str:
    normalized = str(plot_type).strip().lower()
    if normalized == "histogram":
        return "descriptive"
    if normalized == "bar" and not group_var:
        return "descriptive"
    return "analytical"


def _normalize_completion_tier(tier: str | None) -> str:
    normalized = str(tier or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "minimum": "minimum_complete",
        "minimum_complete": "minimum_complete",
        "academic": "academic_ready",
        "academic_ready": "academic_ready",
        "production": "production_ready",
        "production_ready": "production_ready",
        "underpowered": "underpowered",
    }
    return aliases.get(normalized, "underpowered")


def _completion_rank(tier: str | None) -> int:
    return _COMPLETENESS_RANKS.get(_normalize_completion_tier(tier), 0)


def _completion_label(tier: str | None) -> str:
    normalized = _normalize_completion_tier(tier)
    return normalized


def _evaluate_report_readiness(results: dict | None, store: Any) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase
    from rde.domain.policies.heuristics import DEFAULT_HEURISTIC_POLICY

    review = store.load(
        PipelinePhase.PLAN_COMPLETENESS_REVIEW, "analysis_plan_review.json"
    ) or store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan_review.json") or {}
    target_tier = _normalize_completion_tier(
        DEFAULT_HEURISTIC_POLICY.reporting.default_completion_target
    )
    current_tier = _normalize_completion_tier(review.get("completeness_tier"))
    review_status = str(review.get("status", "missing"))
    deliverables = (results or {}).get("deliverables") or {}
    publication_bundle_met = bool(deliverables.get("minimum_publication_bundle_met"))

    missing_requirements: list[str] = []
    if review_status not in {"pass", "repaired"}:
        missing_requirements.append(f"methodology_review={review_status}")
    if _completion_rank(current_tier) < _completion_rank(target_tier):
        missing_requirements.append(
            f"completeness_tier={_completion_label(current_tier)} < target={_completion_label(target_tier)}"
        )
    if not publication_bundle_met:
        missing_requirements.append("publication_bundle")

    return {
        "ready": not missing_requirements,
        "target_tier": target_tier,
        "current_tier": current_tier,
        "review_status": review_status,
        "recommended_analysis_floor": review.get("recommended_analysis_floor"),
        "academic_analysis_target": review.get("academic_analysis_target"),
        "production_analysis_target": review.get("production_analysis_target"),
        "publication_bundle_met": publication_bundle_met,
        "missing_requirements": missing_requirements,
    }


def _render_report_readiness_markdown(readiness: dict[str, Any]) -> str:
    lines = ["# 🧾 Report Readiness\n"]
    lines.append(f"- **target tier:** {readiness.get('target_tier', 'unknown')}")
    lines.append(f"- **current tier:** {readiness.get('current_tier', 'unknown')}")
    lines.append(f"- **methodology review:** {readiness.get('review_status', 'unknown')}")
    lines.append(
        f"- **publication bundle:** {'ready' if readiness.get('publication_bundle_met') else 'missing'}"
    )
    if readiness.get("missing_requirements"):
        lines.append("\n## Missing Requirements")
        for requirement in readiness["missing_requirements"]:
            lines.append(f"- {requirement}")
    return "\n".join(lines)


def _upsert_visualization_manifest(
    project: Any,
    *,
    plot_type: str,
    variables: list[str],
    result_path: str,
    group_var: str | None,
    stats_summary: str | None,
) -> None:
    from rde.application.pipeline import PipelinePhase
    from rde.infrastructure.persistence.artifact_store import ArtifactStore

    store = ArtifactStore(project.artifacts_dir)
    manifest = store.load(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json") or []
    if not isinstance(manifest, list):
        manifest = []

    normalized_vars = [str(value) for value in variables]
    key = (str(plot_type).lower(), tuple(normalized_vars), group_var)
    updated = [
        entry
        for entry in manifest
        if (
            str(entry.get("plot_type", "")).lower(),
            tuple(str(value) for value in entry.get("variables", [])),
            entry.get("group_var"),
        )
        != key
    ]
    updated.append(
        {
            "plot_type": plot_type,
            "variables": normalized_vars,
            "group_var": group_var,
            "output_path": result_path,
            "stats_summary": stats_summary,
            "category": _visualization_category(plot_type, group_var),
        }
    )
    store.save(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json", updated)


def _summarize_publication_deliverables(project: Any, store: Any) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase

    manifest = store.load(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json") or []
    if not isinstance(manifest, list):
        manifest = []

    descriptive = sum(1 for entry in manifest if entry.get("category") == "descriptive")
    analytical = sum(1 for entry in manifest if entry.get("category") == "analytical")
    figure_files = sorted(path.name for path in (project.output_dir / "figures").glob("*.png"))
    missing_components: list[str] = []
    table_one_present = bool(store.exists(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md"))
    if not table_one_present:
        missing_components.append("Table 1")
    if descriptive < MIN_DESCRIPTIVE_FIGURES:
        missing_components.append(f"粗分析圖 {descriptive}/{MIN_DESCRIPTIVE_FIGURES}")
    if analytical < MIN_ANALYTICAL_FIGURES:
        missing_components.append(f"細分析圖 {analytical}/{MIN_ANALYTICAL_FIGURES}")

    return {
        "table_one_present": table_one_present,
        "descriptive_figures": descriptive,
        "analytical_figures": analytical,
        "required_descriptive_figures": MIN_DESCRIPTIVE_FIGURES,
        "required_analytical_figures": MIN_ANALYTICAL_FIGURES,
        "total_figures": len(figure_files),
        "figure_files": figure_files,
        "minimum_publication_bundle_met": not missing_components,
        "missing_components": missing_components,
    }
