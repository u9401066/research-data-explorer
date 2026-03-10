"""Report Tools — Phase 7 (Collect Results) & Phase 8 (Report Assembly).

Collects results from previous phases, assembles the EDA report,
and provides visualization creation.
Enforces H-005 (Report Integrity), H-006 (Output Sanitization).
All tools return markdown strings.
"""

from __future__ import annotations

from typing import Any


def register_report_tools(server: Any) -> None:
    """Register report and visualization MCP tools."""

    @server.tool()
    def collect_results(project_id: str | None = None) -> str:
        """彙整 Phase 6 的所有分析結果，標記可發表內容 (Phase 7)。

        掃描已完成的分析，生成 results_summary.json。
        標記統計顯著的結果為 PUBLISHABLE，並建議敏感度分析 (S-012)。

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_error,
            fmt_error, fmt_success, ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("collect_results", {"project_id": project_id})

        ok, msg, project, _ = ensure_phase_ready(PipelinePhase.COLLECT_RESULTS, project_id=project_id)
        if not ok:
            return fmt_error(msg)

        try:
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult
            from rde.infrastructure.persistence.artifact_store import ArtifactStore
            from datetime import datetime

            session = get_session()
            pipeline = session.get_pipeline(project.id)
            logger = session.get_logger(project.id)

            # H-008: Check that Phase 6 analysis has been done
            store = ArtifactStore(project.artifacts_dir)
            decisions = logger.read_decisions()
            datasets = session.list_datasets()

            has_analysis = any(
                session.get_dataset_entry(did).analysis_results
                for did in datasets
            ) if datasets else False

            if not decisions and not has_analysis:
                return fmt_error(
                    "[H-008] Phase 6 尚未完成。必須先執行分析 (Phase 6) 才能收集結果。"
                )

            # Read all datasets' analysis results
            datasets = session.list_datasets()
            all_results: list[dict] = []
            publishable: list[dict] = []

            for ds_id in datasets:
                entry = session.get_dataset_entry(ds_id)
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
                        publishable.append({
                            "dataset_id": ds_id,
                            "test_name": t.test_name,
                            "variables": list(t.variables_involved),
                            "p_value": t.p_value,
                            "effect_size": t.effect_size,
                            "effect_size_name": getattr(t, "effect_size_name", None),
                            "marker": "PUBLISHABLE",
                        })

            # Read decision + deviation logs
            logger = session.get_logger(project.id)
            decisions = logger.read_decisions()
            deviations = logger.read_deviations()

            # Check plan coverage
            plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
            plan_coverage = None
            if plan and isinstance(plan, dict):
                planned_analyses = plan.get("analyses", plan.get("steps", []))
                plan_coverage = {
                    "planned": len(planned_analyses),
                    "executed": len(all_results),
                    "coverage": min(1.0, len(all_results) / max(1, len(planned_analyses))),
                }

            # S-012: Sensitivity analysis suggestion
            sensitivity_hint = None
            if publishable:
                sensitivity_hint = (
                    "[S-012] 有顯著結果，建議進行敏感度分析（如排除極端值或變更 α 值）。"
                )

            summary = {
                "total_analyses": len(all_results),
                "publishable_count": len(publishable),
                "publishable_items": publishable,
                "plan_coverage": plan_coverage,
                "decision_count": len(decisions),
                "deviation_count": len(deviations),
            }

            # Save artifact
            store.save(PipelinePhase.COLLECT_RESULTS, "results_summary.json", summary)
            pipeline.mark_completed(PhaseResult(
                phase=PipelinePhase.COLLECT_RESULTS,
                completed_at=datetime.now(),
                success=True,
                artifacts={"results_summary.json": str(store.get_path(PipelinePhase.COLLECT_RESULTS, "results_summary.json"))},
            ))

            # Format output
            lines = [
                "# 📋 結果彙整 (Phase 7)\n",
                f"- **分析總數:** {len(all_results)}",
                f"- **可發表項目:** {len(publishable)}",
                f"- **決策紀錄:** {len(decisions)} 筆",
                f"- **計畫偏離:** {len(deviations)} 筆",
            ]

            if plan_coverage:
                lines.append(
                    f"- **計畫涵蓋率:** {plan_coverage['coverage']:.0%} "
                    f"({plan_coverage['executed']}/{plan_coverage['planned']})"
                )

            if publishable:
                lines.append("\n## 🟢 可發表結果 (PUBLISHABLE)")
                for p in publishable:
                    es = f", {p['effect_size_name']}={p['effect_size']:.3f}" if p.get("effect_size") else ""
                    lines.append(
                        f"- {', '.join(p['variables'])}: "
                        f"{p['test_name']} p={p['p_value']:.4f}{es}"
                    )

            if sensitivity_hint:
                lines.append(f"\n💡 {sensitivity_hint}")

            lines.append(f"\n**Artifact:** results_summary.json")

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("collect_results", e)
            return fmt_error(f"結果彙整失敗: {e}")

    @server.tool()
    def assemble_report(
        project_id: str | None = None,
        title: str = "EDA Report",
    ) -> str:
        """組裝完整 EDA 報告 (Phase 8)。

        從各 Phase 的 artifacts 組裝報告，含附錄 (decision_log, deviation_log)。
        執行 H-005 (報告完整性) 和 H-006 (輸出清毒)。

        Args:
            project_id: 專案 ID (預設使用當前專案)
            title: 報告標題
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_error,
            fmt_error, fmt_success, ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("assemble_report", {"project_id": project_id, "title": title})

        ok, msg, project, _ = ensure_phase_ready(PipelinePhase.REPORT_ASSEMBLY, project_id=project_id)
        if not ok:
            return fmt_error(msg)

        try:
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult
            from rde.application.use_cases.generate_report import GenerateReportUseCase
            from rde.infrastructure.adapters import MarkdownReportRenderer
            from rde.infrastructure.persistence.artifact_store import ArtifactStore
            from datetime import datetime

            session = get_session()
            pipeline = session.get_pipeline(project.id)
            logger = session.get_logger(project.id)
            store = ArtifactStore(project.artifacts_dir)

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

            # Statistical analyses from results summary
            results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
            if results:
                artifacts["statistical_analyses"] = _format_analyses(results)
                artifacts["key_findings"] = _format_findings(results)
            else:
                # Quick explore mode: try to create from session data
                datasets = session.list_datasets()
                if datasets:
                    artifacts["statistical_analyses"] = "[Quick Explore — No formal analysis plan]"
                    artifacts["key_findings"] = "[Quick Explore — Review individual analyses]"

            # Recommendations
            artifacts["recommendations"] = _build_recommendations(results, readiness)

            # Pick first dataset_id for report metadata
            datasets = session.list_datasets()
            dataset_id = datasets[0] if datasets else "unknown"

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
            pipeline.mark_completed(PhaseResult(
                phase=PipelinePhase.REPORT_ASSEMBLY,
                completed_at=datetime.now(),
                success=True,
                artifacts={"eda_report.md": str(store.get_path(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md"))},
            ))

            word_count = len(content.split())
            return fmt_success(
                f"EDA 報告已組裝 — {word_count} 字",
                f"- **報告標題:** {title}\n"
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
        圖表儲存在專案的 figures/ 目錄，報告和 handoff 時自動嵌入。

        Args:
            dataset_id: 資料集 ID
            plot_type: 圖表類型，如 "histogram"、"boxplot"、"scatter"、"violin"、"heatmap"
            variables: 變數列表，如 ["age"]（histogram）或 ["age", "bmi"]（scatter）
            output_filename: 輸出檔名，如 "age_distribution.png"（可選，預設自動生成）
            group_var: 分組變數，如 "treatment_group"（可選，用於組間比對圖）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_error, log_tool_result,
            fmt_error, fmt_success, ensure_minimum_sample_size, ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("create_visualization", {
            "plot_type": plot_type, "variables": variables,
        })

        ok, msg, project, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)
        ok, msg = ensure_minimum_sample_size(entry)
        if not ok:
            return fmt_error(msg)

        valid_types = ["histogram", "boxplot", "scatter", "bar", "violin", "heatmap", "line", "paired"]
        if plot_type not in valid_types:
            return fmt_error(
                f"不支援的圖表類型 '{plot_type}'。"
                f"支援: {', '.join(valid_types)}"
            )

        try:
            from rde.infrastructure.visualization.matplotlib_viz import MatplotlibVisualizer
            # Determine output path
            if output_filename is None:
                var_str = "_".join(variables[:2])
                output_filename = f"{plot_type}_{var_str}.png"

            output_dir = project.output_dir / "figures"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(output_dir / output_filename)

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

            from rde.interface.mcp.tools.analysis_tools import _auto_log_decision

            _auto_log_decision(
                "create_visualization",
                {"plot_type": plot_type, "variables": variables, "group_var": group_var},
                "生成視覺化圖表",
                f"{plot_type}: {result_path}",
                artifacts=[result_path],
            )

            return fmt_success(
                f"圖表已生成: {output_filename}",
                f"- **類型:** {plot_type}\n"
                f"- **變數:** {', '.join(variables)}\n"
                f"- **路徑:** {result_path}",
            )

        except Exception as e:
            log_tool_error("create_visualization", e)
            return fmt_error(f"圖表生成失敗: {e}")

    @server.tool()
    def export_report(
        project_id: str | None = None,
        formats: str = "docx",
        title: str = "EDA Report",
    ) -> str:
        """匯出 EDA 報告為 Word (.docx) 或 PDF 格式。

        自動嵌入圖表和統計表格到文件中。
        需先完成 assemble_report (Phase 8)。

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
            formats: 匯出格式，以逗號分隔，如 "docx"、"pdf"、"docx,pdf"（預設: docx）
            title: 報告標題，如 "Sepsis EDA Report"（預設: EDA Report）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_error,
            fmt_error, fmt_success, ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("export_report", {"formats": formats, "title": title})

        ok, msg, project, _ = ensure_phase_ready(PipelinePhase.REPORT_ASSEMBLY, project_id=project_id)
        if not ok:
            return fmt_error(msg)

        try:
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase
            from rde.application.use_cases.generate_report import GenerateReportUseCase
            from rde.application.use_cases.export_report import ExportReportUseCase
            from rde.infrastructure.adapters import MarkdownReportRenderer, DocxExporter
            from rde.infrastructure.persistence.artifact_store import ArtifactStore
            from pathlib import Path

            session = get_session()
            store = ArtifactStore(project.artifacts_dir)

            # H-008: Phase 8 must be done
            if not store.exists(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md"):
                return fmt_error(
                    "[H-008] 報告尚未組裝。請先執行 `assemble_report()` (Phase 8)。"
                )

            # Rebuild EDAReport from artifacts (same logic as assemble_report)
            artifacts: dict[str, str] = {}
            intake = store.load(PipelinePhase.DATA_INTAKE, "intake_report.json")
            schema = store.load(PipelinePhase.SCHEMA_REGISTRY, "schema.json")
            readiness = store.load(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json")
            results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")

            if intake:
                artifacts["data_overview"] = _format_data_overview(intake, schema)
            if schema or readiness:
                artifacts["data_quality"] = _format_data_quality(schema, readiness)
            if schema:
                artifacts["variable_profiles"] = _format_variable_profiles(schema)
            if results:
                artifacts["statistical_analyses"] = _format_analyses(results)
                artifacts["key_findings"] = _format_findings(results)
            else:
                artifacts["statistical_analyses"] = "[Quick Explore]"
                artifacts["key_findings"] = "[Quick Explore]"
            artifacts["recommendations"] = _build_recommendations(results, readiness)

            datasets = session.list_datasets()
            dataset_id = datasets[0] if datasets else "unknown"

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
                return fmt_error(
                    f"不支援的格式: {', '.join(invalid)}。支援: docx, pdf"
                )

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

            lines = [f"- **{fmt.upper()}:** {path}" for fmt, path in exported.items()]
            fig_count = sum(len(s.figures) for s in report.sections)

            return fmt_success(
                f"報告已匯出 — {', '.join(f.upper() for f in exported)}",
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
        rows = intake.get('row_count', intake.get('rows', '?'))
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
            lines.append(f"\n**變數類型分佈:** " + ", ".join(
                f"{t}: {n}" for t, n in sorted(type_counts.items())
            ))
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


def _format_analyses(results: dict | None) -> str:
    """Format statistical analyses section."""
    if not results:
        return "[No analysis results collected]"
    lines = [f"**分析總數:** {results.get('total_analyses', 0)}"]
    pub = results.get("publishable_items", [])
    if pub:
        lines.append(f"\n**可發表結果:**")
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
    lines.append("- **Pipeline:** RDE 11-Phase Auditable EDA")
    lines.append(f"- **Decision count:** {logger.decision_count}")
    lines.append(f"- **Deviation count:** {logger.deviation_count}")

    return "\n".join(lines)
