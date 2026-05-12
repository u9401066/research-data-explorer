"""Report Tools — Phase 9 (Collect Results) & Phase 10 (Report Assembly).

Collects results from previous phases, assembles the EDA report,
and provides visualization creation.
Enforces H-005 (Report Integrity), H-006 (Output Sanitization).
All tools return markdown strings.
"""

from __future__ import annotations

from datetime import datetime
import re
from pathlib import Path
from typing import Any

from rde.application.pipeline import PipelinePhase


MIN_DESCRIPTIVE_FIGURES = 3
MIN_ANALYTICAL_FIGURES = 6
_COMPLETENESS_RANKS = {
    "underpowered": 0,
    "minimum_complete": 1,
    "academic_ready": 2,
    "production_ready": 3,
}


def _safe_visualization_filename(filename: str) -> str:
    candidate = str(filename).strip()
    path = Path(candidate)
    if (
        not candidate
        or path.is_absolute()
        or path.name != candidate
        or ".." in path.parts
        or "/" in candidate
        or "\\" in candidate
    ):
        raise ValueError("output_filename must be a simple filename inside the project figures directory.")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._-") or "figure"
    suffix = path.suffix.lower() if path.suffix else ".png"
    if suffix != ".png":
        suffix = ".png"
    return f"{stem[:96]}{suffix}"


def _project_figure_path(project: Any, path_value: object) -> Any | None:
    from rde.domain.services.report_asset_contract import project_figure_path

    return project_figure_path(project, path_value)


def _figure_manifest_output_path(project: Any, path_value: object) -> str | None:
    from rde.domain.services.report_asset_contract import figure_manifest_output_path

    return figure_manifest_output_path(project, path_value)


def _sanitize_project_report_output(content: str, project: Any) -> str:
    replacements = {
        str(project.output_dir): "[PROJECT]/",
        project.output_dir.as_posix(): "[PROJECT]/",
        str(project.artifacts_dir): "[ARTIFACTS]/",
        project.artifacts_dir.as_posix(): "[ARTIFACTS]/",
        str(project.data_dir): "[DATA]/",
        project.data_dir.as_posix(): "[DATA]/",
    }
    sanitized = content
    for raw, replacement in replacements.items():
        if raw:
            sanitized = sanitized.replace(raw, replacement)
    sanitized = re.sub(r"[A-Z]:\\Users\\[^\\]+\\", r"[PATH]\\", sanitized)
    sanitized = re.sub(r"/home/[^/]+/", "[PATH]/", sanitized)
    sanitized = re.sub(r"/Users/[^/]+/", "[PATH]/", sanitized)
    return sanitized


def _extract_report_h1(markdown: str, fallback: str = "EDA Report") -> str:
    match = re.search(r"^#\s+(.+?)\s*$", str(markdown or ""), re.MULTILINE)
    return match.group(1).strip() if match else fallback


def _split_assembled_markdown(markdown: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Split an assembled Phase 10 markdown report into H2 sections."""
    text = str(markdown or "").strip()
    title = _extract_report_h1(text)
    body = re.sub(r"^#\s+.+?$", "", text, count=1, flags=re.MULTILINE).strip()
    pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(body))
    if not matches:
        return title, body, []

    preamble = body[: matches[0].start()].strip()
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((match.group(1).strip(), body[start:end].strip()))
    return title, preamble, sections


def _extract_markdown_preamble_metadata(preamble: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in str(preamble or "").splitlines():
        match = re.match(r"^\*\*(Dataset|Project|Generated):\*\*\s*(.+?)\s*$", line.strip())
        if match:
            metadata[match.group(1).lower()] = match.group(2).strip()
    return metadata


def _parse_generated_at(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _section_id_from_heading(heading: str, used: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")
    canonical = {
        "data_overview": "data_overview",
        "data_quality": "data_quality",
        "variable_profiles": "variable_profiles",
        "key_findings": "key_findings",
        "statistical_analyses": "statistical_analyses",
        "interpretation_and_literature_context": "interpretation_discussion",
        "interpretation_discussion": "interpretation_discussion",
        "discussion": "interpretation_discussion",
        "recommendations": "recommendations",
        "table_1_baseline_characteristics": "baseline_table",
        "learning_curve_cusum": "learning_curve_cusum",
        "sensitivity_analysis": "sensitivity_analysis",
        "figure_gallery": "figure_gallery",
        "metadata": "metadata",
    }
    base = canonical.get(slug, slug or "section")
    section_id = base
    suffix = 2
    while section_id in used:
        section_id = f"{base}_{suffix}"
        suffix += 1
    used.add(section_id)
    return section_id


def _build_report_from_assembled_markdown(
    project: Any,
    markdown: str,
    *,
    title: str = "",
) -> Any:
    """Build an exportable EDAReport directly from phase_10/eda_report.md.

    Phase 10 assembly is the canonical report artifact. Export must preserve
    its sections (advanced analyses, figure gallery, appendices) instead of
    rebuilding a second report from partial upstream artifacts.
    """
    from rde.domain.models.report import EDAReport, REQUIRED_SECTIONS, ReportSection

    inferred_title, preamble, sections = _split_assembled_markdown(markdown)
    preamble_metadata = _extract_markdown_preamble_metadata(preamble)
    dataset_ids = getattr(project, "dataset_ids", None) or []
    dataset_id = preamble_metadata.get("dataset") or (dataset_ids[-1] if dataset_ids else "unknown")
    generated_at = _parse_generated_at(preamble_metadata.get("generated")) or datetime.now()
    report = EDAReport(
        id=f"{project.id}_phase10_assembled_report",
        dataset_id=dataset_id,
        project_id=getattr(project, "id", preamble_metadata.get("project", "unknown")),
        title=title.strip() if title.strip() and title.strip() != "EDA Report" else inferred_title,
        created_at=generated_at,
    )

    used: set[str] = set()
    for order, (heading, content) in enumerate(sections, 1):
        report.add_section(
            ReportSection(
                section_id=_section_id_from_heading(heading, used),
                title=heading,
                content=content,
                order=order,
            )
        )

    present = {section.section_id for section in report.sections}
    for offset, required in enumerate(REQUIRED_SECTIONS, len(report.sections) + 1):
        if required in present:
            continue
        report.add_section(
            ReportSection(
                section_id=required,
                title=required.replace("_", " ").title(),
                content="(Auto-generated integrity placeholder; source markdown lacks this section.)",
                order=offset,
            )
        )

    return report


def _count_report_figure_references(report: Any) -> int:
    """Count figure placements attached to or referenced by a report."""
    count = 0
    for section in getattr(report, "sections", []):
        count += len(getattr(section, "figures", []))
        count += len(
            re.findall(
                r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)",
                getattr(section, "content", ""),
            )
        )
    return count


def _build_formal_research_report(
    project: Any,
    store: Any,
    assembled_markdown: str,
    *,
    title: str = "",
) -> Any:
    """Build a publication-facing report for DOCX/PDF export.

    The Phase 10 markdown remains the auditable internal report. This export
    report removes pipeline internals from the main body and keeps only the
    research-facing narrative, tables, figures, interpretation, and limitations.
    """
    from rde.domain.models.report import EDAReport, ReportSection

    inferred_title, preamble, _ = _split_assembled_markdown(assembled_markdown)
    metadata = _extract_markdown_preamble_metadata(preamble)
    dataset_ids = getattr(project, "dataset_ids", None) or []
    dataset_id = metadata.get("dataset") or (dataset_ids[-1] if dataset_ids else "unknown")
    generated_at = _parse_generated_at(metadata.get("generated")) or datetime.now()
    schema = store.load(PipelinePhase.SCHEMA_REGISTRY, "schema.json")
    intake = store.load(PipelinePhase.DATA_INTAKE, "intake_report.json")
    concept_alignment = store.load(PipelinePhase.CONCEPT_ALIGNMENT, "concept_alignment.md")
    variable_roles = store.load(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json")
    readiness = store.load(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json")
    results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    table_one = store.load(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md")
    pubmed_context = store.load(PipelinePhase.REPORT_ASSEMBLY, "pubmed_literature_context.md")
    table_rows = _parse_table_markdown_rows(table_one)
    table_payload = (
        {"headers": table_rows[0], "rows": table_rows[1:]}
        if len(table_rows) >= 2
        else None
    )

    report = EDAReport(
        id=f"{project.id}_formal_research_report",
        dataset_id=dataset_id,
        project_id=getattr(project, "id", metadata.get("project", "unknown")),
        title=title.strip() if title.strip() and title.strip() != "EDA Report" else inferred_title,
        created_at=generated_at,
    )
    report.metadata["_export_profile"] = "formal_research_report"

    report.add_section(
        ReportSection(
            section_id="data_overview",
            title="摘要",
            content=_formal_abstract(
                project,
                intake,
                schema,
                results,
                concept_alignment=concept_alignment,
                variable_roles=variable_roles if isinstance(variable_roles, dict) else None,
            ),
            order=1,
        )
    )
    report.add_section(
        ReportSection(
            section_id="data_quality",
            title="資料來源與品質摘要",
            content=_formal_data_quality(schema, readiness, intake=intake),
            order=2,
        )
    )
    report.add_section(
        ReportSection(
            section_id="variable_profiles",
            title="研究變項",
            content=_formal_variable_summary(
                schema,
                variable_roles=variable_roles if isinstance(variable_roles, dict) else None,
            ),
            order=3,
        )
    )
    report.add_section(
        ReportSection(
            section_id="baseline_table",
            title="Table 1. Baseline Characteristics",
            content=_interpret_table_one(table_one, schema),
            tables=[table_payload] if table_payload else [],
            order=4,
        )
    )
    report.add_section(
        ReportSection(
            section_id="key_findings",
            title="主要結果",
            content=_formal_key_findings(results),
            order=5,
        )
    )
    report.add_section(
        ReportSection(
            section_id="statistical_analyses",
            title="統計分析摘要",
            content=_formal_statistical_summary(project, store, results),
            order=6,
        )
    )
    report.add_section(
        ReportSection(
            section_id="interpretation_discussion",
            title="討論與文獻對照",
            content=_build_interpretation_discussion(
                project,
                store,
                results=results if isinstance(results, dict) else None,
                readiness=readiness if isinstance(readiness, dict) else None,
                schema=schema if isinstance(schema, dict) else None,
                table_one=table_one,
                pubmed_context=str(pubmed_context or ""),
                include_artifact_refs=False,
                include_figure_details=False,
            ),
            order=7,
        )
    )
    report.add_section(
        ReportSection(
            section_id="recommendations",
            title="結論與後續建議",
            content=_formal_conclusions(
                results,
                readiness,
                pubmed_context=str(pubmed_context or ""),
                schema=schema if isinstance(schema, dict) else None,
                variable_roles=variable_roles if isinstance(variable_roles, dict) else None,
            ),
            order=8,
        )
    )
    report.add_section(
        ReportSection(
            section_id="figures",
            title="Figures",
            content=_formal_figure_gallery(project, store),
            order=9,
        )
    )
    return report


def register_report_tools(server: Any) -> None:
    """Register report and visualization MCP tools."""

    @server.tool()
    def collect_results(project_id: str | None = None, force: bool = False) -> str:
        """彙整 Phase 8 的所有分析結果，標記統計顯著候選內容 (Phase 9)。

        掃描已完成的分析，生成 results_summary.json。
        標記統計顯著候選結果，並建議敏感度分析 (S-012)。

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
                        reason="[S-011] 未達計畫覆蓋率即進入 Phase 9",
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

                    # Significant tests are candidates until audit confirms context.
                    for t in result.significant_tests:
                        publishable.append(
                            {
                                "dataset_id": ds_id,
                                "test_name": t.test_name,
                                "variables": list(t.variables_involved),
                                "p_value": t.p_value,
                                "effect_size": t.effect_size,
                                "effect_size_name": getattr(t, "effect_size_name", None),
                                "marker": "STATISTICALLY_SIGNIFICANT_CANDIDATE",
                                "review_status": "audit_required",
                            }
                        )

            # Read decision + deviation logs
            logger = session.get_logger(project.id)
            decisions = logger.read_decisions()
            deviations = logger.read_deviations()
            branch_decision_count = int(progress.get("branch_decision_count") or 0)
            primary_decision_count = int(progress.get("primary_decision_count") or 0)
            executed_analyses = max(
                len(all_results),
                int(progress.get("executed_analyses") or primary_decision_count),
            )

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
            exploration_branches = _summarize_exploration_branches(store)
            summary = {
                "total_analyses": executed_analyses,
                "publishable_count": len(publishable),
                "publishable_items": publishable,
                "candidate_count": len(publishable),
                "candidate_findings": publishable,
                "plan_coverage": plan_coverage,
                "decision_count": len(decisions),
                "primary_decision_count": primary_decision_count,
                "branch_exploration_count": branch_decision_count,
                "deviation_count": len(deviations),
                "unavailable_datasets": unavailable_datasets,
                "phase6_progress": progress,
                "deliverables": deliverables,
                "exploration_branches": exploration_branches,
            }
            report_readiness = _evaluate_report_readiness(
                summary,
                store,
                require_report_generation=False,
            )
            summary["report_readiness"] = report_readiness

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
                "# 📋 結果彙整 (Phase 9)\n",
                f"- **分析總數:** {executed_analyses}",
                f"- **統計顯著候選結果:** {len(publishable)}",
                f"- **決策紀錄:** {len(decisions)} 筆",
                f"- **計畫偏離:** {len(deviations)} 筆",
            ]

            if branch_decision_count:
                lines.append(
                    f"- **Branch-scoped exploratory decisions:** {branch_decision_count}"
                )

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

            if exploration_branches["total_branches"]:
                lines.append(
                    "- **Exploratory branches:** "
                    f"{exploration_branches['total_branches']} branches, "
                    f"{exploration_branches['completed_experiments']} experiments, "
                    f"promote candidates: {exploration_branches['promote_candidates']}"
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
                lines.append("\n## Statistically Significant Candidate Findings (Audit Required)")
                for p in publishable:
                    es = (
                        f", {p['effect_size_name']}={p['effect_size']:.3f}"
                        if p.get("effect_size")
                        else ""
                    )
                    lines.append(
                        f"- {', '.join(p['variables'])}: {p['test_name']} p={p['p_value']:.4f}{es}"
                    )
                lines.append(
                    "\nThese are candidates only; audit must confirm effect size, "
                    "multiplicity, plan adherence, and clinical relevance."
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
            report_readiness = _evaluate_report_readiness(
                results,
                store,
                require_report_generation=False,
            )
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

            advanced_artifacts = _load_phase6_markdown_bundle(
                store,
                "advanced_analysis_",
                exclude_prefixes=("advanced_analysis_learning_curve_cusum",),
            )
            if advanced_artifacts:
                artifacts["statistical_analyses"] = (
                    artifacts.get("statistical_analyses", "")
                    + "\n\n## Advanced Analyses\n\n"
                    + advanced_artifacts
                )

            pubmed_context = store.load(
                PipelinePhase.REPORT_ASSEMBLY,
                "pubmed_literature_context.md",
            )
            artifacts["interpretation_discussion"] = _build_interpretation_discussion(
                project,
                store,
                results=results,
                readiness=readiness,
                schema=schema,
                table_one=table_one,
                pubmed_context=str(pubmed_context or ""),
            )

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
            figure_harness = _build_figure_interpretation_harness(project, store)
            if figure_harness:
                store.save(
                    PipelinePhase.REPORT_ASSEMBLY,
                    "figure_interpretation_harness.json",
                    {
                        "generated_at": datetime.now().isoformat(),
                        "entry_count": len(figure_harness),
                        "entries": figure_harness,
                    },
                )

            figure_gallery = _format_figure_gallery(project, store)
            if figure_gallery:
                content += "\n---\n\n" + figure_gallery + "\n"

            # Add appendices (decision log + deviation log)
            appendix = _build_appendix(logger, store)
            content += "\n" + appendix
            content = _sanitize_project_report_output(content, project)

            # Save artifact
            store.save(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md", content)
            final_report_readiness = _evaluate_report_readiness(results, store)
            store.save(
                PipelinePhase.REPORT_ASSEMBLY,
                "report_readiness.json",
                final_report_readiness,
            )
            store.save(
                PipelinePhase.REPORT_ASSEMBLY,
                "semantic_report_quality.json",
                final_report_readiness.get("semantic_report_quality", {}),
            )
            store.save(
                PipelinePhase.REPORT_ASSEMBLY,
                "claim_provenance_manifest.json",
                _build_claim_provenance_manifest(project, store, report_source="phase_10_report"),
            )
            if isinstance(results, dict):
                results["report_readiness"] = final_report_readiness
                store.save(PipelinePhase.COLLECT_RESULTS, "results_summary.json", results)
                report_readiness = final_report_readiness
            pipeline.mark_completed(
                PhaseResult(
                    phase=PipelinePhase.REPORT_ASSEMBLY,
                    completed_at=datetime.now(),
                    success=True,
                    artifacts={
                        "eda_report.md": str(
                            store.get_path(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
                        ),
                        "report_readiness.json": str(
                            store.get_path(PipelinePhase.REPORT_ASSEMBLY, "report_readiness.json")
                        ),
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
            output_filename = _safe_visualization_filename(output_filename)

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
            relative_result_path = _figure_manifest_output_path(project, result_path) or result_path

            from rde.interface.mcp.tools.analysis_tools import _auto_log_decision

            _auto_log_decision(
                "create_visualization",
                {"plot_type": plot_type, "variables": variables, "group_var": group_var},
                "生成視覺化圖表",
                (
                    f"{plot_type}: {relative_result_path} | {stats_summary}"
                    if stats_summary
                    else f"{plot_type}: {relative_result_path}"
                ),
                artifacts=[relative_result_path],
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
            from rde.application.use_cases.export_report import ExportReportUseCase
            from rde.infrastructure.adapters.docx_exporter import DocxExporter
            from rde.infrastructure.adapters.markdown_renderer import MarkdownReportRenderer
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            store = ArtifactStore(project.artifacts_dir)

            # H-008: Phase 10 report assembly must be done
            if not store.exists(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md"):
                return fmt_error("[H-008] 報告尚未組裝。請先執行 `assemble_report()` (Phase 10)。")

            results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
            report_readiness = _evaluate_report_readiness(results, store)
            if not allow_incomplete and not report_readiness.get("ready", False):
                return fmt_error(
                    "最終報告完整度未達預設目標，暫不匯出終版報告。",
                    _render_report_readiness_markdown(report_readiness),
                    suggestion="先補齊 methodology / deliverables 缺口，或以 allow_incomplete=true 明示覆蓋。",
                )

            assembled_markdown = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
            if not assembled_markdown:
                return fmt_error("[H-008] phase_10_report_assembly/eda_report.md 為空，無法匯出。")
            report = _build_formal_research_report(
                project,
                store,
                str(assembled_markdown),
                title=title,
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
            output_dir.mkdir(parents=True, exist_ok=True)
            formal_source = MarkdownReportRenderer().render_markdown(report)
            formal_source_path = output_dir / "eda_report_formal_source.md"
            formal_source_path.write_text(
                _sanitize_project_report_output(formal_source, project),
                encoding="utf-8",
            )
            provenance_manifest = _build_claim_provenance_manifest(
                project,
                store,
                report_source="formal_research_export",
            )
            provenance_path = output_dir / "claim_provenance_manifest.json"
            provenance_path.write_text(
                __import__("json").dumps(
                    provenance_manifest,
                    indent=2,
                    ensure_ascii=True,
                    default=str,
                ),
                encoding="utf-8",
            )
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
            fig_count = _count_report_figure_references(report)

            return fmt_success(
                f"報告已匯出 — {', '.join(f.upper() for f in exported)}",
                f"- **完整度目標:** {report_readiness.get('target_tier')}\n"
                f"- **目前 tier:** {report_readiness.get('current_tier')}\n"
                f"- **匯出樣式:** formal research report\n"
                f"- **嵌入圖表:** {fig_count} 張\n"
                f"- **Formal source:** {formal_source_path}\n"
                f"- **Claim provenance:** {provenance_path}\n"
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


def _raw_coverage_from_intake(intake: dict | None) -> dict[str, Any]:
    """Normalize current and legacy intake reports into raw coverage evidence."""
    if not isinstance(intake, dict):
        return {
            "status": "missing_intake",
            "requires_review": True,
            "loaded_files": [],
            "unloaded_loadable_files": [],
            "selected_sheets": [],
            "unselected_data_candidate_sheets": [],
        }
    embedded = intake.get("raw_data_coverage")
    if isinstance(embedded, dict):
        return embedded

    loaded_file = str(intake.get("loaded_file") or intake.get("filename") or "")
    total_files = int(intake.get("total_files") or 0)
    loadable = int(intake.get("loadable") or 0)
    unloaded_count = max(loadable - 1, 0) if loaded_file else loadable
    unloaded_files = [f"unrecorded_loadable_file_{idx}" for idx in range(1, unloaded_count + 1)]

    normalization = intake.get("normalization") if isinstance(intake, dict) else {}
    normalization = normalization if isinstance(normalization, dict) else {}
    selected_sheet = str(normalization.get("selected_sheet_name") or "")
    sheet_assessments = normalization.get("sheet_assessments") or []
    selected_sheets: list[dict[str, Any]] = []
    unselected_candidates: list[dict[str, Any]] = []
    for item in sheet_assessments:
        if not isinstance(item, dict):
            continue
        payload = {
            "file_name": loaded_file,
            "sheet_name": str(item.get("sheet_name", "")),
            "classification": str(item.get("classification", "")),
            "score": item.get("score"),
            "row_count": item.get("row_count"),
            "column_count": item.get("column_count"),
            "reasons": item.get("reasons") or [],
        }
        if item.get("selected"):
            selected_sheets.append(payload)
        elif str(item.get("classification", "")) == "data_candidate":
            unselected_candidates.append(payload)
    if selected_sheet and not selected_sheets:
        selected_sheets.append(
            {
                "file_name": loaded_file,
                "sheet_name": selected_sheet,
                "classification": "selected",
                "score": None,
                "row_count": None,
                "column_count": None,
                "reasons": [],
            }
        )

    requires_review = bool(unloaded_files or unselected_candidates)
    return {
        "status": "partial_raw_coverage" if requires_review else "complete_raw_coverage",
        "loaded_files": [loaded_file] if loaded_file else [],
        "loadable_file_count": loadable or total_files,
        "unloaded_loadable_files": unloaded_files,
        "selected_sheets": selected_sheets,
        "unselected_data_candidate_sheets": unselected_candidates,
        "requires_review": requires_review,
        "legacy_inferred": True,
    }


def _format_data_overview(
    intake: dict | None,
    schema: dict | None,
) -> str:
    """Format data overview section from intake + schema artifacts."""
    lines = []
    if intake:
        lines.append(f"**檔案:** {intake.get('loaded_file', intake.get('filename', '?'))}")
        normalization = intake.get("normalization") if isinstance(intake, dict) else {}
        if isinstance(normalization, dict) and normalization.get("selected_sheet_name"):
            lines.append(f"**載入分頁:** {normalization.get('selected_sheet_name')}")
            if normalization.get("sheet_selection_mode"):
                lines.append(f"**分頁選擇模式:** {normalization.get('sheet_selection_mode')}")
        if intake.get("total_files") is not None:
            lines.append(
                f"**Raw 檔案掃描:** {intake.get('loadable', '?')} / {intake.get('total_files')} 可載入"
            )
        rows = intake.get("row_count", intake.get("rows", "?"))
        lines.append(f"**列數:** {rows}")
        lines.append(f"**欄數:** {intake.get('column_count', intake.get('columns', '?'))}")
        if intake.get("size_mb"):
            lines.append(f"**大小:** {intake['size_mb']:.1f} MB")
        coverage = _raw_coverage_from_intake(intake)
        if coverage.get("requires_review"):
            unloaded = coverage.get("unloaded_loadable_files") or []
            unselected = coverage.get("unselected_data_candidate_sheets") or []
            lines.append(
                "\n**Raw coverage 注意:** "
                f"目前報告只代表已載入資料表；另有 {len(unloaded)} 個可載入檔案、"
                f"{len(unselected)} 個 data-like 分頁尚未納入或缺少排除理由。"
            )
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


def _load_phase6_markdown_bundle(
    store: Any,
    prefix: str,
    *,
    exclude_prefixes: tuple[str, ...] = (),
) -> str | None:
    """Load and concatenate optional Phase 8 markdown artifacts by filename prefix."""
    from rde.application.pipeline import PipelinePhase

    filenames = [
        name
        for name in store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION)
        if name.startswith(prefix) and name.endswith(".md")
        and not any(name.startswith(excluded) for excluded in exclude_prefixes)
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
    exploration_branches = results.get("exploration_branches") or {}
    if exploration_branches and exploration_branches.get("total_branches", 0):
        lines.append(
            "**Exploratory branches:** "
            f"{exploration_branches.get('total_branches', 0)} branches, "
            f"{exploration_branches.get('completed_experiments', 0)} experiments, "
            f"promote candidates: {exploration_branches.get('promote_candidates', 0)}"
        )
        lines.append(
            "**Exploratory branch caveat:** branch findings are branch-scoped candidates, "
            "not primary conclusions unless promoted through the audit gate."
        )
        for branch in exploration_branches.get("branches", [])[:5]:
            lines.append(
                f"- `{branch.get('branch_id', '')}` {branch.get('status', '')}: "
                f"{branch.get('hypothesis', '')} "
                f"(experiments={branch.get('experiment_count', 0)}, "
                f"recommendation={branch.get('recommendation') or 'pending'}, "
                f"evidence_artifacts={len(branch.get('evidence_artifacts') or [])}, "
                f"blockers={branch.get('blockers') or []})"
            )
    core_goal_audit = report_readiness.get("core_goal_audit") or {}
    if core_goal_audit:
        lines.append(
            f"**core goal audit:** {'ready' if core_goal_audit.get('ready') else 'missing'}"
        )
    pub = results.get("publishable_items", [])
    if pub:
        lines.append("\n**Candidate signals (audit required):**")
        for p in pub:
            lines.append(f"- {p.get('test_name', '?')}: p={p.get('p_value', '?')}")
    return "\n".join(lines)


def _format_figure_gallery(project: Any, store: Any) -> str:
    manifest = store.load(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json") or []
    if not isinstance(manifest, list):
        return ""
    lines = ["## Figure Gallery"]
    included = 0
    for entry in manifest:
        if not isinstance(entry, dict):
            continue
        figure_path = _project_figure_path(project, entry.get("output_path"))
        if figure_path is None or not figure_path.exists():
            continue
        relative = figure_path.relative_to(project.artifacts_dir.parent).as_posix()
        variables = ", ".join(str(value) for value in entry.get("variables", []))
        figure_no = included + 1
        title = f"Figure {figure_no}. {entry.get('plot_type', 'figure')} {variables}".strip()
        lines.append(f"\n### {title}")
        lines.append(f"![{title}](../../{relative})")
        if entry.get("stats_summary"):
            lines.append(str(entry["stats_summary"]))
        included += 1
    return "\n".join(lines) if included else ""


def _extract_research_question(concept_alignment: str | None) -> str:
    text = str(concept_alignment or "").strip()
    if not text:
        return ""
    for raw_line in text.splitlines():
        line = raw_line.strip().strip("-").strip()
        if not line or line.startswith("#"):
            continue
        lowered = line.lower()
        if "research question" in lowered or "研究問題" in line:
            candidate = re.sub(
                r"^(?:\*\*)?(?:research question|研究問題)(?:\*\*)?\s*[:：-]?\s*",
                "",
                line,
                flags=re.IGNORECASE,
            ).strip()
            if candidate:
                return candidate[:280]
        if 12 <= len(line) <= 280:
            return line
    return ""


def _flatten_variable_roles(variable_roles: dict | None) -> dict[str, str]:
    roles: dict[str, str] = {}
    if not isinstance(variable_roles, dict):
        return roles
    for key, raw in variable_roles.items():
        key_text = str(key)
        if isinstance(raw, list):
            for value in raw:
                roles[str(value)] = key_text
        elif isinstance(raw, dict):
            for nested_key, nested_value in raw.items():
                roles[str(nested_key)] = str(nested_value or key_text)
        elif raw:
            raw_text = str(raw)
            if key_text.lower() in {"outcome", "target", "endpoint", "group", "exposure", "treatment", "covariate", "confounder", "adjuster", "predictor"}:
                roles[raw_text] = key_text
            else:
                roles[key_text] = raw_text
    return roles


def _role_matches(role: str, tokens: tuple[str, ...]) -> bool:
    role_text = str(role or "").lower()
    return any(token in role_text for token in tokens)


def _select_focus_variables(
    schema: dict | None,
    variable_roles: dict | None,
    results: dict | None,
    *,
    limit: int,
) -> list[str]:
    selected: list[str] = []
    for name in _flatten_variable_roles(variable_roles):
        if name and name not in selected:
            selected.append(name)
    if isinstance(results, dict):
        for item in results.get("publishable_items") or results.get("candidate_findings") or []:
            if not isinstance(item, dict):
                continue
            for name in item.get("variables") or []:
                value = str(name)
                if value and value not in selected:
                    selected.append(value)
    variables = (schema or {}).get("variables", []) if isinstance(schema, dict) else []
    for var in variables:
        if not isinstance(var, dict):
            continue
        name = str(var.get("name") or "")
        if not name or name in selected:
            continue
        var_type = str(var.get("variable_type") or var.get("type") or "").lower()
        if var_type not in {"id", "identifier", "text"}:
            selected.append(name)
        if len(selected) >= limit:
            break
    return selected[:limit]


def _formal_abstract(
    project: Any,
    intake: dict | None,
    schema: dict | None,
    results: dict | None,
    *,
    concept_alignment: str | None = None,
    variable_roles: dict | None = None,
) -> str:
    loaded_file = (intake or {}).get("loaded_file", "study dataset")
    normalization = (intake or {}).get("normalization") if isinstance(intake, dict) else {}
    loaded_sheet = (
        normalization.get("selected_sheet_name")
        if isinstance(normalization, dict)
        else None
    )
    dataset_label = f"`{loaded_file}`"
    if loaded_sheet:
        dataset_label += f" 的 `{loaded_sheet}` 分頁"
    row_count = (schema or {}).get("row_count", "unknown")
    column_count = (schema or {}).get("column_count", "unknown")
    total_analyses = (results or {}).get("total_analyses", 0)
    research_question = _extract_research_question(concept_alignment)
    focus_variables = _select_focus_variables(schema, variable_roles, results, limit=8)
    focus_text = "、".join(focus_variables) if focus_variables else "Phase 3/6 所定義的研究變項"
    question_text = (
        f"研究問題聚焦於：{research_question}"
        if research_question
        else "本報告依據概念對齊、schema registry 與鎖定分析計畫整理探索性研究證據。"
    )
    lines = [
        f"本報告整理 {dataset_label} 的探索性分析結果。資料集包含 {row_count} 筆觀察值與 {column_count} 個欄位。",
        question_text,
        f"主要解讀圍繞 {focus_text}，並依變項角色、資料品質與前置檢查結果限制推論範圍。",
        (
            f"RDE 共彙整 {total_analyses} 項分析與圖表證據。所有結果應視為早期探索與假說生成，"
            "除非後續以預先鎖定的 endpoint、樣本數與校正策略完成驗證。"
        ),
    ]
    coverage = _raw_coverage_from_intake(intake)
    if coverage.get("requires_review"):
        lines.append(
            "Raw data coverage 尚未完整關帳：本報告不可解讀為已分析所有原始 Excel 檔與所有 data-like 分頁。"
        )
    lines.append("正式解讀以正文為主，審計與 pipeline 細節保留於 RDE artifacts。")
    return "\n".join(lines)


def _formal_data_quality(
    schema: dict | None,
    readiness: dict | None,
    *,
    intake: dict | None = None,
) -> str:
    lines: list[str] = []
    coverage = _raw_coverage_from_intake(intake)
    if coverage.get("requires_review"):
        unloaded_files = coverage.get("unloaded_loadable_files") or []
        unselected_sheets = coverage.get("unselected_data_candidate_sheets") or []
        selected = coverage.get("selected_sheets") or []
        selected_text = ""
        if selected:
            first = selected[0]
            selected_text = f"目前載入範圍為 {first.get('file_name')} / {first.get('sheet_name')}。"
        lines.append(
            "Raw data coverage 尚未完整關帳。"
            + selected_text
            + f" 仍有 {len(unloaded_files)} 個可載入檔案與 "
            + f"{len(unselected_sheets)} 個 data-like 分頁尚未納入或缺少排除理由；"
            + "因此本報告不得宣稱已完整分析所有原始 Excel 分頁。"
        )
    checks = (readiness or {}).get("checks", []) if isinstance(readiness, dict) else []
    passed = sum(1 for check in checks if isinstance(check, dict) and check.get("passed"))
    if checks:
        lines.append(f"前置檢查共有 {passed}/{len(checks)} 項通過。")
    if isinstance(schema, dict):
        type_counts = schema.get("type_counts") or {}
        if type_counts:
            lines.append(
                "變項型態包含 "
                + "、".join(f"{key}: {value}" for key, value in type_counts.items())
                + "。"
            )
    if isinstance(readiness, dict):
        for check in checks:
            if not isinstance(check, dict) or check.get("passed"):
                continue
            lines.append(f"需注意：{check.get('name', check.get('id', 'quality check'))} 未通過。")
    lines.append(
        "整體而言，資料適合進行探索性描述與假說生成；但 sparse group、缺失模式與共線性仍限制正式推論。"
    )
    return "\n".join(lines)


def _formal_variable_summary(schema: dict | None, *, variable_roles: dict | None = None) -> str:
    variables = (schema or {}).get("variables", []) if isinstance(schema, dict) else []
    if not variables:
        return "未取得 schema registry，因此無法產生研究變項摘要。"
    role_map = _flatten_variable_roles(variable_roles)
    outcomes = [name for name, role in role_map.items() if _role_matches(role, ("outcome", "target", "endpoint", "dependent"))]
    groups = [name for name, role in role_map.items() if _role_matches(role, ("group", "exposure", "treatment", "arm"))]
    covariates = [name for name, role in role_map.items() if _role_matches(role, ("covariate", "confounder", "adjuster", "baseline", "predictor"))]
    type_counts: dict[str, int] = {}
    for var in variables:
        vtype = str(var.get("variable_type") or var.get("type") or "unknown")
        type_counts[vtype] = type_counts.get(vtype, 0) + 1
    lines = [f"Schema registry 共列出 {len(variables)} 個變項。"]
    if type_counts:
        lines.append("變項型態分布：" + "、".join(f"{key}: {value}" for key, value in sorted(type_counts.items())) + "。")
    if outcomes:
        lines.append("主要 outcome / endpoint 變項：" + "、".join(outcomes[:12]) + "。")
    if groups:
        lines.append("主要 group / exposure 變項：" + "、".join(groups[:12]) + "。")
    if covariates:
        lines.append("主要 covariate / adjuster 變項：" + "、".join(covariates[:12]) + "。")
    lines.append(
        "分類與連續變項的角色由 Phase 2 schema 與後續修正共同決定；數字編碼但具類別意義的變項不應以連續尺度解讀。"
    )
    return "\n".join(lines)


def _formal_key_findings(results: dict | None) -> str:
    if not isinstance(results, dict):
        return "目前沒有可彙整的正式結果。"
    publishable = results.get("publishable_items") or []
    if not publishable:
        return (
            "本輪分析未產生可直接視為審計通過的 confirmatory finding。"
            "部分 scatter/correlation 圖呈現候選關聯，但需經多重比較、endpoint 定義與樣本擴充後再確認。"
        )
    lines = ["審計候選結果如下，仍需正式方法學確認："]
    for item in publishable:
        variables = ", ".join(item.get("variables", []))
        lines.append(f"- {variables}: {item.get('test_name', 'test')}，p={item.get('p_value', 'NA')}")
    return "\n".join(lines)


def _formal_statistical_summary(project: Any, store: Any, results: dict | None) -> str:
    lines: list[str] = []
    if isinstance(results, dict):
        deliverables = results.get("deliverables") or {}
        lines.append(
            f"本次分析包含 {results.get('total_analyses', 0)} 項彙整分析；"
            f"描述性圖表 {deliverables.get('descriptive_figures', 0)} 張，"
            f"分析性圖表 {deliverables.get('analytical_figures', 0)} 張。"
        )
    model_text = _interpret_advanced_models(store, include_artifact_refs=False)
    if model_text:
        lines.append("調整模型摘要：")
        lines.append(model_text)
    entries = _resolved_visualization_manifest_entries(project, store)
    p_candidates = []
    for entry in entries:
        p_text, p_value = _extract_p_value(str(entry.get("summary") or entry.get("stats_summary") or ""))
        if p_value is not None and p_value < 0.05:
            p_candidates.append(
                f"{entry.get('plot_type', 'figure')} ({', '.join(str(v) for v in entry.get('variables', []))}; {p_text})"
            )
    if p_candidates:
        lines.append(
            "候選關聯訊號包含：" + "；".join(p_candidates[:8]) + "。這些訊號需以 multiplicity-aware 方式解讀。"
        )
    return "\n".join(lines) if lines else "尚無統計分析摘要可供正式報告使用。"


def _formal_conclusions(
    results: dict | None,
    readiness: dict | None,
    *,
    pubmed_context: str,
    schema: dict | None = None,
    variable_roles: dict | None = None,
) -> str:
    focus_variables = _select_focus_variables(schema, variable_roles, results, limit=5)
    focus_text = "、".join(focus_variables) if focus_variables else "主要研究變項"
    lines = [
        f"本輪分析支持以 {focus_text} 作為後續研究設計與假說精煉的核心線索。",
        "目前結果最適合用於研究規劃、資料品質改善、endpoint 定義與樣本擴充；不應直接視為確認性結論。",
        "若組別稀疏、缺失率偏高或共線性存在，非顯著結果不可解讀為沒有差異或沒有實質意義。",
    ]
    if isinstance(readiness, dict) and readiness.get("missing_requirements"):
        lines.append("正式發表前仍需補齊：" + "、".join(readiness.get("missing_requirements", [])) + "。")
    if pubmed_context.strip():
        lines.append(
            "後續討論應明確連結 PubMed context，並區分既有文獻支持、資料內探索訊號與仍需驗證的推論。"
        )
    return "\n".join(f"- {line}" for line in lines)


def _formal_figure_gallery(project: Any, store: Any) -> str:
    entries = _resolved_visualization_manifest_entries(project, store)
    if not entries:
        return "本報告未產生可嵌入的圖表。"
    lines: list[str] = []
    figure_no = 0
    for entry in entries:
        if not entry.get("exists"):
            continue
        figure_no += 1
        figure_path = Path(str(entry["output_path"]))
        relative = f"../../figures/{figure_path.name}"
        plot_type = str(entry.get("plot_type") or "figure")
        variables = [str(value) for value in entry.get("variables", [])]
        variables_text = ", ".join(variables) if variables else "unspecified variables"
        stats_summary = str(entry.get("summary") or entry.get("stats_summary") or "").strip()
        group_var = str(entry.get("group_var") or "").strip()
        title = f"Figure {figure_no}. {plot_type} — {variables_text}"
        harness = _figure_interpretation_harness_entry(
            figure_no=figure_no,
            plot_type=plot_type,
            variables=variables,
            stats_summary=stats_summary,
            group_var=group_var,
        )
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"![{title}]({relative})")
        lines.append("")
        lines.append("**圖說與解讀 / 圖表證據評讀（harness）：**")
        lines.extend(_render_figure_harness_bullets(harness))
        lines.append("")
    return "\n".join(lines).strip()


def _build_interpretation_discussion(
    project: Any,
    store: Any,
    *,
    results: dict | None,
    readiness: dict | None,
    schema: dict | None,
    table_one: str | None,
    pubmed_context: str = "",
    include_artifact_refs: bool = True,
    include_figure_details: bool = True,
) -> str:
    """Build narrative interpretation, recommendations, and literature context."""

    lines = ["## Interpretation Narrative\n"]
    lines.append(
        "This section is generated from the Phase 8/9 artifacts and is intended to "
        "turn tables and figures into reviewable scientific interpretation. It "
        "does not promote exploratory findings to confirmatory conclusions unless "
        "the audit gate supports that promotion."
    )

    table_text = _interpret_table_one(table_one, schema)
    if table_text:
        lines.append("\n### Table 1 Interpretation")
        lines.append(table_text)

    figure_text = _interpret_figure_manifest(project, store) if include_figure_details else ""
    if figure_text:
        lines.append("\n### Figure-by-Figure Interpretation and Suggested Action")
        lines.append(figure_text)

    model_text = _interpret_advanced_models(store, include_artifact_refs=include_artifact_refs)
    if model_text:
        lines.append("\n### Multivariable and Propensity Model Interpretation")
        lines.append(model_text)

    literature_text = _interpret_pubmed_context(pubmed_context)
    if literature_text:
        lines.append("\n### Literature Context and Discussion")
        lines.append(literature_text)

    lines.append("\n### Study-Level Recommendations")
    lines.extend(
        _build_interpretation_recommendations(
            results=results,
            readiness=readiness,
            pubmed_context=pubmed_context,
        )
    )
    return "\n".join(lines).strip()


def _interpret_table_one(table_one: str | None, schema: dict | None) -> str:
    if not table_one:
        return "Table 1 is not available, so baseline comparability cannot be interpreted."

    rows = _parse_table_markdown_rows(table_one)
    notes = _extract_table_markdown_notes(table_one)
    header = rows[0] if rows else []
    group_columns = [
        value
        for value in header
        if value not in {"Variable", "Overall", "p", "---"} and not re.fullmatch(r"-+", value)
    ]
    variable_rows = [
        row
        for row in rows[1:]
        if row and row[0] not in {"", "---"} and not re.fullmatch(r"-+", row[0])
    ]
    nan_cells = sum(1 for row in variable_rows for cell in row if "(nan)" in cell)
    variable_count = len(variable_rows)
    row_count = schema.get("row_count") if isinstance(schema, dict) else None

    lines: list[str] = []
    if row_count:
        lines.append(f"- The analysis cohort contains {row_count} rows in the schema registry.")
    if group_columns:
        lines.append(
            "- Table 1 compares baseline and analysis variables across "
            f"{len(group_columns)} observed strata/groups ({', '.join(group_columns)})."
        )
    if variable_count:
        lines.append(f"- Table 1 includes {variable_count} interpretable variable rows.")
    if nan_cells:
        lines.append(
            "- Several group cells have undefined standard deviations (`nan`), which is a practical "
            "signal that some groups contain a single observation. Group-level comparisons should "
            "therefore be treated as descriptive unless sparse levels are collapsed or new samples "
            "are added."
        )
    if notes:
        lines.append("- Source table notes: " + "; ".join(note.lstrip("- ").strip() for note in notes[:3]))
    lines.append(
        "- Recommendation: report medians/IQRs alongside means/SDs, preserve the sparse-code warning, "
        "and avoid interpreting non-significant sparse-group contrasts as evidence of equivalence."
    )
    return "\n".join(lines)


def _interpret_figure_manifest(project: Any, store: Any) -> str:
    manifest = store.load(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json") or []
    if not isinstance(manifest, list):
        return ""

    lines: list[str] = []
    figure_no = 0
    for entry in manifest:
        if not isinstance(entry, dict):
            continue
        figure_path = _project_figure_path(project, entry.get("output_path"))
        if figure_path is None or not figure_path.exists():
            continue
        figure_no += 1
        plot_type = str(entry.get("plot_type") or "figure")
        variables = [str(value) for value in entry.get("variables", [])]
        variables_text = ", ".join(variables) if variables else "unspecified variables"
        stats_summary = str(entry.get("stats_summary") or "").strip()
        group_var = str(entry.get("group_var") or "").strip()
        title = f"Figure {figure_no}. {plot_type} — {variables_text}"
        lines.append(f"#### {title}")
        harness = _figure_interpretation_harness_entry(
            figure_no=figure_no,
            plot_type=plot_type,
            variables=variables,
            stats_summary=stats_summary,
            group_var=group_var,
        )
        lines.extend(_render_figure_harness_bullets(harness))
    return "\n".join(lines)


def _interpret_single_figure(
    *,
    plot_type: str,
    variables: list[str],
    stats_summary: str,
    group_var: str,
) -> tuple[str, str]:
    harness = _figure_interpretation_harness_entry(
        figure_no=0,
        plot_type=plot_type,
        variables=variables,
        stats_summary=stats_summary,
        group_var=group_var,
    )
    return str(harness["visual_read"]), str(harness["next_analysis"])


def _figure_interpretation_harness_entry(
    *,
    figure_no: int,
    plot_type: str,
    variables: list[str],
    stats_summary: str,
    group_var: str,
) -> dict[str, Any]:
    primary = variables[0] if variables else "the displayed variable"
    p_text, p_value = _extract_p_value(stats_summary)
    sparse_groups = _extract_sparse_group_notes(stats_summary)
    plot = plot_type.lower()
    variables_text = ", ".join(variables) if variables else "unspecified variables"

    if plot == "histogram":
        distribution = _describe_distribution(stats_summary)
        evidence_role = "Distribution and assumption check"
        visual_read = (
            f"{primary} is shown as a univariate distribution. {distribution} "
            "Use this panel to judge skewness, outliers, and whether parametric summaries are fragile."
        )
        statistical_support = stats_summary or "No formal inferential statistic is attached to this descriptive figure."
        validity_caveat = "Distributional shape should affect summary choice and downstream parametric assumptions."
        reportable_claim = (
            f"{primary} can be described as an exploratory distributional profile, not as an association or effect estimate."
        )
        next_analysis = (
            "For manuscript reporting, pair this with median/IQR and consider log or rank-based "
            "analysis if the distribution is skewed."
        )
    elif plot in {"boxplot", "violin", "bar"}:
        comparator = f" across {group_var}" if group_var else ""
        if p_value is None:
            signal = "The figure is descriptive; no usable inferential p-value is available."
        elif p_value < 0.05:
            signal = f"The displayed contrast is an exploratory candidate signal ({p_text})."
        else:
            signal = f"The figure does not show strong statistical evidence of a group difference ({p_text})."
        sparse = (
            f" Sparse cells are present ({'; '.join(sparse_groups)}), so visual differences may be unstable."
            if sparse_groups
            else ""
        )
        evidence_role = "Group contrast screening"
        visual_read = f"{primary} is compared{comparator}. {signal}{sparse}"
        statistical_support = stats_summary or "No test annotation is available; treat the figure as descriptive."
        validity_caveat = (
            "Sparse cells and unbalanced strata can make apparent group differences unstable."
            if sparse_groups
            else "Group contrasts remain exploratory unless the grouping and endpoint were prespecified."
        )
        reportable_claim = (
            f"{primary} shows an exploratory group-contrast pattern for {group_var or 'the displayed grouping'}, "
            "but this figure alone does not establish equivalence or causal effect."
        )
        next_analysis = (
            "Collapse sparse groups or prespecify a scientifically meaningful binary contrast "
            "before using this figure as evidence."
        )
    elif plot == "scatter":
        if p_value is None:
            signal = "This is a model/association diagnostic without a directly reported p-value."
        elif p_value < 0.05:
            signal = f"The association is a candidate signal ({p_text}) and needs multiplicity-aware review."
        else:
            signal = f"The observed association is weak or statistically uncertain ({p_text})."
        evidence_role = "Crude association screening"
        visual_read = f"The scatter plot evaluates the relationship among {variables_text}. {signal}"
        statistical_support = stats_summary or "No correlation/model statistic is attached to this scatter plot."
        validity_caveat = (
            "Crude associations can be driven by leverage points, scale, missingness, or confounding."
        )
        reportable_claim = (
            f"The figure supports only a hypothesis-generating association review for {variables_text}."
        )
        next_analysis = (
            "Use this to guide adjusted modeling rather than as a standalone conclusion; inspect leverage "
            "points because the cohort is small."
        )
    elif plot == "heatmap":
        evidence_role = "Covariate structure and collinearity check"
        visual_read = (
            "The heatmap summarizes covariate structure and potential collinearity before modeling. "
            f"It should be read with the readiness warning: {stats_summary or 'correlation structure review'}."
        )
        statistical_support = stats_summary or "No pairwise statistic summary is attached to this heatmap."
        validity_caveat = "Correlation structure is not an effect estimate and should not be treated as endpoint evidence."
        reportable_claim = "The heatmap supports model-building caution, especially around redundant covariates."
        next_analysis = (
            "Avoid putting highly redundant anthropometric variables into the same small-sample model "
            "unless the model is explicitly sensitivity-oriented."
        )
    elif "propensity" in plot:
        evidence_role = "Propensity/balance diagnostic"
        visual_read = (
            "The propensity figure is a balance/overlap diagnostic for the derived treatment contrast, "
            "not a causal estimate by itself."
        )
        statistical_support = stats_summary or "No balance metric summary is attached to this propensity figure."
        validity_caveat = "Propensity diagnostics require common support, balance thresholds, and exposure-definition provenance."
        reportable_claim = "The figure can support balance assessment only, not a treatment-effect conclusion."
        next_analysis = (
            "Report the derived exposure definition, inspect overlap, and use the weighted/matched balance "
            "table before presenting any adjusted treatment contrast."
        )
    else:
        evidence_role = "Exploratory visual evidence"
        visual_read = (
            f"The figure displays {variables[0] if variables else 'an analysis artifact'} for exploratory review."
        )
        statistical_support = stats_summary or "No statistical annotation is attached to this figure."
        validity_caveat = "The evidentiary role is unclear until it is linked to a prespecified question."
        reportable_claim = f"The figure is supporting context for {variables_text}."
        next_analysis = "Treat as supporting context and link it to a specific model or table before publication."

    return {
        "figure_no": figure_no,
        "plot_type": plot_type,
        "variables": variables,
        "group_var": group_var,
        "evidence_role": evidence_role,
        "visual_read": visual_read,
        "statistical_support": statistical_support,
        "validity_caveat": validity_caveat,
        "reportable_claim": reportable_claim,
        "next_analysis": next_analysis,
        "p_value_text": p_text,
        "p_value": p_value,
        "sparse_groups": sparse_groups,
    }


def _render_figure_harness_bullets(harness: dict[str, Any]) -> list[str]:
    return [
        f"- **Evidence role:** {harness['evidence_role']}",
        f"- **Visual read:** {harness['visual_read']}",
        f"- **Statistical support:** {harness['statistical_support']}",
        f"- **Validity caveat:** {harness['validity_caveat']}",
        f"- **Reportable claim:** {harness['reportable_claim']}",
        f"- **Next analysis:** {harness['next_analysis']}",
    ]


def _build_figure_interpretation_harness(project: Any, store: Any) -> list[dict[str, Any]]:
    entries = _resolved_visualization_manifest_entries(project, store)
    harness_entries: list[dict[str, Any]] = []
    figure_no = 0
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("exists"):
            continue
        figure_no += 1
        harness = _figure_interpretation_harness_entry(
            figure_no=figure_no,
            plot_type=str(entry.get("plot_type") or "figure"),
            variables=[str(value) for value in entry.get("variables", [])],
            stats_summary=str(entry.get("summary") or entry.get("stats_summary") or "").strip(),
            group_var=str(entry.get("group_var") or "").strip(),
        )
        harness["output_path"] = entry.get("output_path")
        harness["category"] = entry.get("category")
        harness_entries.append(harness)
    return harness_entries


def _extract_p_value(stats_summary: str) -> tuple[str, float | None]:
    match = re.search(r"\bp\s*([<=>]=?)\s*([0-9]*\.?[0-9]+(?:e[-+]?\d+)?)", stats_summary, re.I)
    if not match:
        return "p not reported", None
    operator = match.group(1)
    raw = match.group(2)
    try:
        value = float(raw)
    except ValueError:
        return f"p {operator} {raw}", None
    return f"p {operator} {raw}", value


def _extract_sparse_group_notes(stats_summary: str) -> list[str]:
    sparse: list[str] = []
    for group, count in re.findall(r"([^,;]+?)\s+n=(\d+)", stats_summary):
        try:
            n = int(count)
        except ValueError:
            continue
        if n <= 2:
            sparse.append(f"{group.strip()} n={n}")
    return sparse[:5]


def _describe_distribution(stats_summary: str) -> str:
    mean_match = re.search(r"mean=([-+]?\d*\.?\d+)", stats_summary)
    median_match = re.search(r"median=([-+]?\d*\.?\d+)", stats_summary)
    sd_match = re.search(r"SD=([-+]?\d*\.?\d+)", stats_summary)
    if not (mean_match and median_match):
        return stats_summary or "Summary statistics were not available."
    mean = float(mean_match.group(1))
    median = float(median_match.group(1))
    sd_text = f", SD={sd_match.group(1)}" if sd_match else ""
    if median and abs(mean - median) / max(abs(median), 1e-9) > 0.2:
        shape = "Mean and median differ materially, suggesting skew or influential observations."
    else:
        shape = "Mean and median are broadly aligned."
    return f"mean={mean:.2f}, median={median:.2f}{sd_text}. {shape}"


def _interpret_advanced_models(store: Any, *, include_artifact_refs: bool = True) -> str:
    artifacts = [
        name
        for name in store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION)
        if name.startswith("advanced_analysis_") and name.endswith(".json")
    ]
    if not artifacts:
        return ""

    lines: list[str] = []
    for name in sorted(artifacts):
        payload = store.load(PipelinePhase.EXECUTE_EXPLORATION, name)
        if not isinstance(payload, dict):
            continue
        result = payload.get("result")
        if not isinstance(result, dict):
            continue
        target = result.get("target") or payload.get("config", {}).get("target") or "target"
        analysis_type = result.get("analysis_type") or payload.get("analysis_type") or "advanced analysis"
        p_values = result.get("p_values") if isinstance(result.get("p_values"), dict) else {}
        significant_terms = [
            f"{term} (p={float(p):.3g})"
            for term, p in p_values.items()
            if term != "const" and _is_numeric_less_than(p, 0.05)
        ]
        r_squared = result.get("adj_r_squared", result.get("r_squared"))
        fit_text = (
            f"; adjusted R²={float(r_squared):.3f}"
            if isinstance(r_squared, (int, float))
            else ""
        )
        if significant_terms:
            interpretation = (
                f"`{analysis_type}` for `{target}` has candidate adjusted terms: "
                + ", ".join(significant_terms)
                + fit_text
                + "."
            )
        else:
            interpretation = (
                f"`{analysis_type}` for `{target}` did not identify covariates with p<0.05"
                f"{fit_text}; interpret coefficient direction as hypothesis-generating only."
            )
        artifact_text = f" Artifact: `{name}`." if include_artifact_refs else ""
        lines.append(f"- {interpretation}{artifact_text}")
    return "\n".join(lines)


def _is_numeric_less_than(value: Any, threshold: float) -> bool:
    try:
        return float(value) < threshold
    except (TypeError, ValueError):
        return False


def _interpret_pubmed_context(pubmed_context: str) -> str:
    if not pubmed_context.strip():
        return (
            "No PubMed literature context artifact was found for this report. "
            "Recommendation: run or refresh the PubMed Search MCP context before final manuscript drafting."
        )

    key_context = _extract_markdown_section(pubmed_context, "Key Context For This RDE Report")
    interpretation = _extract_markdown_section(pubmed_context, "How It Should Affect Interpretation")
    references = _extract_markdown_section(pubmed_context, "PubMed MCP Seed References")
    lines = [
        "- The PubMed context artifact is available and should be treated as the external evidence frame "
        "for interpreting dataset-derived exploratory signals.",
    ]
    if key_context:
        lines.append("\n#### External Evidence Frame")
        lines.append(key_context.strip())
    if interpretation:
        lines.append("\n#### Consequences for This Dataset")
        lines.append(interpretation.strip())
    if references:
        pmid_count = len(re.findall(r"^\|\s*\d+", references, flags=re.MULTILINE))
        if pmid_count:
            lines.append(f"\n- Seed reference table contains {pmid_count} PubMed-backed context items.")
    return "\n".join(lines)


def _extract_markdown_section(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(markdown)
    if not match:
        return ""
    next_match = re.search(r"^##\s+", markdown[match.end() :], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(markdown)
    return markdown[match.end() : end].strip()


def _build_interpretation_recommendations(
    *,
    results: dict | None,
    readiness: dict | None,
    pubmed_context: str,
) -> list[str]:
    lines = [
        "- Keep the current findings labeled as exploratory until endpoint definitions, sampling-time rules, "
        "and sparse-group strategies are locked in the analysis plan.",
        "- For the next RDE cycle, require each retained figure to have three linked elements: visual pattern, "
        "statistical caveat, and action/recommendation.",
    ]
    deliverables = (results or {}).get("deliverables") if isinstance(results, dict) else {}
    if isinstance(deliverables, dict) and deliverables.get("minimum_publication_bundle_met"):
        lines.append(
            "- The minimum figure/table bundle is present, but manuscript readiness still depends on whether "
            "the interpretation text is clinically coherent and traceable to artifacts."
        )
    missing = (readiness or {}).get("missing_requirements") if isinstance(readiness, dict) else []
    if missing:
        lines.append("- Remaining readiness gaps should be resolved before confirmatory claims: " + ", ".join(missing))
    if pubmed_context.strip():
        lines.append(
            "- In the discussion, explicitly separate literature-supported background, dataset-derived "
            "exploratory signals, and claims that still require endpoint-linked validation."
        )
    return lines


def _format_findings(results: dict | None) -> str:
    """Format key findings section."""
    if not results:
        return "[No findings to report]"
    pub = results.get("publishable_items", [])
    if not pub:
        return "No audit-ready candidate signals."
    lines = [f"共 {len(pub)} 項候選訊號（需審計後才可視為正式結論）:\n"]
    lines.append("Audit required before treating these candidates as publishable conclusions.")
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
        lines.append("- 所有分析已完成，可進行審計 (Phase 11)。")
    return "\n".join(lines)


def _build_appendix(logger: Any, store: Any | None = None) -> str:
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

    if store is not None:
        branches = _summarize_exploration_branches(store)
        lines.append("\n## Appendix D: Exploration Branches\n")
        if branches["total_branches"]:
            lines.append(
                "| Branch | Status | Hypothesis | Experiments | Recommendation | Score | Blockers | Evidence Artifacts |"
            )
            lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
            for branch in branches["branches"]:
                lines.append(
                    f"| {branch.get('branch_id', '')} | {branch.get('status', '')} | "
                    f"{branch.get('hypothesis', '')} | {branch.get('experiment_count', 0)} | "
                    f"{branch.get('recommendation', '')} | {branch.get('overall_score', '')} | "
                    f"{branch.get('blockers', [])} | {len(branch.get('evidence_artifacts') or [])} |"
                )
            lines.append(
                "\nExploratory branches are audit candidates only; they are not treated as "
                "primary conclusions until a branch promotion gate succeeds."
            )
        else:
            lines.append("*No exploration branches recorded.*\n")

    return "\n".join(lines)


def _summarize_exploration_branches(store: Any) -> dict[str, Any]:
    """Summarize Phase 8 autonomous branch artifacts for reports and audit context."""
    branches_raw = store.load(PipelinePhase.EXECUTE_EXPLORATION, "exploration_branches.jsonl")
    experiments_raw = store.load(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")
    evaluations_raw = store.load(PipelinePhase.EXECUTE_EXPLORATION, "branch_evaluations.jsonl")
    branch_events = branches_raw if isinstance(branches_raw, list) else []
    experiment_events = experiments_raw if isinstance(experiments_raw, list) else []
    evaluation_events = evaluations_raw if isinstance(evaluations_raw, list) else []

    branches: dict[str, dict[str, Any]] = {}
    for event in branch_events:
        if not isinstance(event, dict):
            continue
        branch_id = str(event.get("branch_id") or "")
        if not branch_id:
            continue
        branch = branches.setdefault(
            branch_id,
            {
                "branch_id": branch_id,
                "status": "",
                "hypothesis": "",
                "risk_level": "",
                "experiment_count": 0,
                "experiment_types": [],
                "evidence_artifacts": [],
                "metrics_preview": [],
                "recommendation": "",
                "overall_score": None,
                "blockers": [],
                "component_scores": {},
                "review_artifact": "",
                "gate_artifact": "",
            },
        )
        if event.get("status"):
            branch["status"] = str(event["status"])
        if event.get("hypothesis"):
            branch["hypothesis"] = str(event["hypothesis"])
        if event.get("risk_level"):
            branch["risk_level"] = str(event["risk_level"])
        payload = event.get("payload")
        if (
            event.get("event_type") == "branch_evaluated"
            and isinstance(payload, dict)
            and isinstance(payload.get("evaluation"), dict)
        ):
            evaluation = payload["evaluation"]
            branch["recommendation"] = str(evaluation.get("recommendation") or "")
            branch["overall_score"] = evaluation.get("overall_score")
            gate = evaluation.get("promotion_gate")
            if isinstance(gate, dict):
                branch["blockers"] = gate.get("blockers") or []
            branch["component_scores"] = evaluation.get("component_scores") or {}

    for event in evaluation_events:
        if not isinstance(event, dict):
            continue
        branch_id = str(event.get("branch_id") or "")
        evaluation = event.get("evaluation")
        if not branch_id or not isinstance(evaluation, dict):
            continue
        branch = branches.setdefault(
            branch_id,
            {
                "branch_id": branch_id,
                "status": "",
                "hypothesis": "",
                "risk_level": "",
                "experiment_count": 0,
                "experiment_types": [],
                "evidence_artifacts": [],
                "metrics_preview": [],
                "recommendation": "",
                "overall_score": None,
                "blockers": [],
                "component_scores": {},
                "review_artifact": "",
                "gate_artifact": "",
            },
        )
        branch["recommendation"] = str(evaluation.get("recommendation") or "")
        branch["overall_score"] = evaluation.get("overall_score")
        gate = evaluation.get("promotion_gate")
        if isinstance(gate, dict):
            branch["blockers"] = gate.get("blockers") or []
        branch["component_scores"] = evaluation.get("component_scores") or {}
        branch["review_artifact"] = str(event.get("review_artifact") or branch["review_artifact"])
        branch["gate_artifact"] = str(event.get("gate_artifact") or branch["gate_artifact"])

    completed_experiments = 0
    crashed_experiments = 0
    for event in experiment_events:
        if not isinstance(event, dict):
            continue
        branch_id = str(event.get("branch_id") or "")
        if branch_id in branches:
            branch = branches[branch_id]
            branch["experiment_count"] += 1
            experiment_type = str(event.get("experiment_type") or "")
            if experiment_type:
                branch["experiment_types"].append(experiment_type)
            artifacts = event.get("artifacts")
            if isinstance(artifacts, list):
                branch["evidence_artifacts"].extend(str(artifact) for artifact in artifacts)
            metrics = event.get("metrics")
            if isinstance(metrics, dict):
                preview = _branch_metric_preview(metrics)
                if preview:
                    branch["metrics_preview"].append(preview)
        status = str(event.get("status") or "").lower()
        if status == "completed":
            completed_experiments += 1
        if status in {"crashed", "failed", "error"}:
            crashed_experiments += 1

    # Branch result files can carry the latest evaluation even when the evaluation
    # event is not loaded from the ledger, so use them as supplemental evidence.
    branch_results_dir = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "branch_results")
    if branch_results_dir.exists():
        for result_path in sorted(branch_results_dir.glob("*.json")):
            try:
                import json

                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            branch_id = str(payload.get("branch_id") or result_path.stem)
            branch = branches.setdefault(
                branch_id,
                {
                    "branch_id": branch_id,
                    "status": "",
                    "hypothesis": "",
                    "risk_level": "",
                "experiment_count": 0,
                "experiment_types": [],
                "evidence_artifacts": [],
                "metrics_preview": [],
                "recommendation": "",
                "overall_score": None,
                "blockers": [],
                "component_scores": {},
                "review_artifact": "",
                "gate_artifact": "",
            },
        )
            branch_payload = payload.get("branch")
            if isinstance(branch_payload, dict):
                branch["status"] = str(branch_payload.get("status") or branch["status"])
                branch["hypothesis"] = str(
                    branch_payload.get("hypothesis") or branch["hypothesis"]
                )
                branch["risk_level"] = str(
                    branch_payload.get("risk_level") or branch["risk_level"]
                )
            experiments = payload.get("experiments")
            if isinstance(experiments, list):
                branch["experiment_count"] = max(branch["experiment_count"], len(experiments))
                for experiment in experiments:
                    if not isinstance(experiment, dict):
                        continue
                    experiment_type = str(experiment.get("experiment_type") or "")
                    if experiment_type:
                        branch["experiment_types"].append(experiment_type)
                    artifacts = experiment.get("artifacts")
                    if isinstance(artifacts, list):
                        branch["evidence_artifacts"].extend(str(artifact) for artifact in artifacts)
                    metrics = experiment.get("metrics")
                    if isinstance(metrics, dict):
                        preview = _branch_metric_preview(metrics)
                        if preview:
                            branch["metrics_preview"].append(preview)

    branch_list = sorted(branches.values(), key=lambda item: item["branch_id"])
    for branch in branch_list:
        branch["experiment_types"] = sorted(set(branch.get("experiment_types") or []))
        branch["evidence_artifacts"] = sorted(set(branch.get("evidence_artifacts") or []))
    return {
        "total_branches": len(branch_list),
        "completed_experiments": completed_experiments,
        "crashed_experiments": crashed_experiments,
        "promote_candidates": sum(
            1
            for branch in branch_list
            if branch.get("recommendation") == "promote_candidate"
            and branch.get("status") == "evaluated"
        ),
        "promoted_branches": sum(1 for branch in branch_list if branch.get("status") == "promoted"),
        "discarded_branches": sum(
            1 for branch in branch_list if branch.get("status") == "discarded"
        ),
        "branches": branch_list,
    }


def _branch_metric_preview(metrics: dict[str, Any]) -> dict[str, Any]:
    preview_keys = [
        "n",
        "nobs",
        "sample_size",
        "p_value",
        "effect_size",
        "odds_ratio",
        "hazard_ratio",
        "auc",
        "roc_auc",
        "c_index",
        "standardized_mean_difference",
        "ci_low",
        "ci_high",
        "common_support",
    ]
    return {key: metrics[key] for key in preview_keys if key in metrics}


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


def _evaluate_report_readiness(
    results: dict | None,
    store: Any,
    *,
    require_report_generation: bool = True,
) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase
    from rde.domain.policies.heuristics import DEFAULT_HEURISTIC_POLICY

    normalized_results = dict(results or {})
    persisted_results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    if isinstance(persisted_results, dict):
        for key in (
            "total_analyses",
            "decision_count",
            "deviation_count",
            "publishable_count",
            "publishable_items",
            "plan_coverage",
            "deliverables",
        ):
            if key not in normalized_results and key in persisted_results:
                normalized_results[key] = persisted_results[key]
    review = store.load(
        PipelinePhase.PLAN_COMPLETENESS_REVIEW, "analysis_plan_review.json"
    ) or store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan_review.json") or {}
    target_tier = _normalize_completion_tier(
        DEFAULT_HEURISTIC_POLICY.reporting.default_completion_target
    )
    current_tier = _normalize_completion_tier(review.get("completeness_tier"))
    review_status = str(review.get("status", "missing"))
    deliverables = normalized_results.get("deliverables") or {}
    publication_bundle_met = bool(deliverables.get("minimum_publication_bundle_met"))
    current_tier = _execution_adjusted_completion_tier(
        normalized_results,
        review,
        current_tier=current_tier,
        publication_bundle_met=publication_bundle_met,
    )

    missing_requirements: list[str] = []
    if review_status not in {"pass", "repaired"}:
        missing_requirements.append(f"methodology_review={review_status}")
    if _completion_rank(current_tier) < _completion_rank(target_tier):
        missing_requirements.append(
            f"completeness_tier={_completion_label(current_tier)} < target={_completion_label(target_tier)}"
        )
    if not publication_bundle_met:
        missing_requirements.append("publication_bundle")

    data_quality = _evaluate_data_quality_evidence(store)
    for requirement in data_quality.get("missing_requirements", []):
        missing_requirements.append(f"data_quality:{requirement}")

    analysis_depth = _evaluate_analysis_depth(normalized_results, store)
    for requirement in analysis_depth.get("missing_requirements", []):
        missing_requirements.append(f"analysis_depth:{requirement}")

    semantic_quality = _evaluate_semantic_report_quality(
        normalized_results,
        store,
        require_report_generation=require_report_generation,
    )
    for requirement in semantic_quality.get("missing_requirements", []):
        missing_requirements.append(f"semantic_quality:{requirement}")

    core_goal_audit = _evaluate_core_goal_audit(
        normalized_results,
        store,
        current_tier=current_tier,
        target_tier=target_tier,
        review_status=review_status,
        publication_bundle_met=publication_bundle_met,
        data_quality=data_quality,
        analysis_depth=analysis_depth,
        semantic_quality=semantic_quality,
        require_report_generation=require_report_generation,
    )
    for goal in core_goal_audit["missing_goals"]:
        missing_requirements.append(f"core_goal:{goal}")

    return {
        "ready": not missing_requirements,
        "target_tier": target_tier,
        "current_tier": current_tier,
        "review_status": review_status,
        "recommended_analysis_floor": review.get("recommended_analysis_floor"),
        "academic_analysis_target": review.get("academic_analysis_target"),
        "production_analysis_target": review.get("production_analysis_target"),
        "publication_bundle_met": publication_bundle_met,
        "data_quality": data_quality,
        "analysis_depth": analysis_depth,
        "semantic_report_quality": semantic_quality,
        "core_goal_audit": core_goal_audit,
        "missing_requirements": missing_requirements,
    }


def _evaluate_data_quality_evidence(store: Any) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase

    quality_report = store.load(PipelinePhase.SCHEMA_REGISTRY, "quality_report.json") or {}
    profile_summary = store.load(PipelinePhase.SCHEMA_REGISTRY, "profile_summary.json") or {}
    raw_coverage = _evaluate_raw_data_coverage(store)
    has_schema = store.exists(PipelinePhase.SCHEMA_REGISTRY, "schema.json")
    has_profile = store.exists(PipelinePhase.SCHEMA_REGISTRY, "profile_summary.json")
    has_quality = store.exists(PipelinePhase.SCHEMA_REGISTRY, "quality_report.json")
    critical_issues = int((quality_report or {}).get("critical_issue_count") or 0)
    analysis_ready = (quality_report or {}).get("is_analysis_ready")
    if analysis_ready is None:
        analysis_ready = has_quality and critical_issues == 0

    checks = [
        {
            "id": "schema_registry",
            "title": "Schema registry",
            "passed": has_schema,
            "evidence": ["phase_02_schema_registry/schema.json"],
        },
        {
            "id": "profile_summary",
            "title": "Data profile artifact",
            "passed": has_profile,
            "evidence": ["phase_02_schema_registry/profile_summary.json"],
        },
        {
            "id": "quality_report",
            "title": "Data quality assessment artifact",
            "passed": has_quality,
            "evidence": ["phase_02_schema_registry/quality_report.json"],
        },
        {
            "id": "critical_quality_issues",
            "title": "No unresolved critical quality issues",
            "passed": bool(analysis_ready),
            "evidence": ["phase_02_schema_registry/quality_report.json"],
        },
        {
            "id": "raw_file_coverage",
            "title": "Raw file coverage reviewed",
            "passed": not bool(raw_coverage.get("unloaded_loadable_files")),
            "evidence": ["phase_01_data_intake/intake_report.json"],
            "detail": raw_coverage.get("file_coverage_detail"),
        },
        {
            "id": "raw_sheet_coverage",
            "title": "Excel sheet coverage reviewed",
            "passed": not bool(raw_coverage.get("unselected_data_candidate_sheets")),
            "evidence": ["phase_01_data_intake/raw_data_coverage.json"],
            "detail": raw_coverage.get("sheet_coverage_detail"),
        },
    ]
    missing = [str(check["id"]) for check in checks if not check["passed"]]
    return {
        "ready": not missing,
        "checks": checks,
        "missing_requirements": missing,
        "profile_engine": (profile_summary or {}).get("engine"),
        "overall_missing_rate": (profile_summary or {}).get("overall_missing_rate"),
        "quality_score": (quality_report or {}).get("overall_score"),
        "critical_issue_count": critical_issues,
        "raw_data_coverage": raw_coverage,
    }


def _evaluate_raw_data_coverage(store: Any) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase

    intake = store.load(PipelinePhase.DATA_INTAKE, "intake_report.json") or {}
    coverage_artifact = store.load(PipelinePhase.DATA_INTAKE, "raw_data_coverage.json")
    coverage = coverage_artifact if isinstance(coverage_artifact, dict) else _raw_coverage_from_intake(intake)
    unloaded_files = [str(item) for item in coverage.get("unloaded_loadable_files") or []]
    unselected_sheets = [
        item
        for item in coverage.get("unselected_data_candidate_sheets") or []
        if isinstance(item, dict)
    ]
    file_detail = (
        "All loadable files are represented in the loaded analysis dataset."
        if not unloaded_files
        else f"{len(unloaded_files)} loadable raw file(s) were not loaded or explicitly excluded."
    )
    sheet_detail = (
        "No unselected Excel sheet was classified as data_candidate."
        if not unselected_sheets
        else f"{len(unselected_sheets)} data-candidate sheet(s) were not loaded or explicitly excluded."
    )
    return {
        **coverage,
        "ready": not unloaded_files and not unselected_sheets,
        "coverage_artifact_present": isinstance(coverage_artifact, dict),
        "unloaded_loadable_files": unloaded_files,
        "unselected_data_candidate_sheets": unselected_sheets,
        "file_coverage_detail": file_detail,
        "sheet_coverage_detail": sheet_detail,
    }


def _evaluate_analysis_depth(results: dict[str, Any], store: Any) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase

    schema = store.load(PipelinePhase.SCHEMA_REGISTRY, "schema.json") or {}
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
    roles = store.load(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json") or {}
    decisions = _as_list(store.load(PipelinePhase.EXECUTE_EXPLORATION, "decision_log.jsonl"))
    experiments = _as_list(store.load(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl"))
    manifest = _as_list(store.load(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json"))
    registry = store.load(PipelinePhase.EXECUTE_EXPLORATION, "derived_variable_registry.json") or {}
    derived_entries = registry.get("derived_variables") if isinstance(registry, dict) else []
    derived_entries = derived_entries if isinstance(derived_entries, list) else []

    variables = schema.get("variables") if isinstance(schema, dict) else []
    variables = variables if isinstance(variables, list) else []
    analyses = plan.get("analyses") if isinstance(plan, dict) else []
    analyses = analyses if isinstance(analyses, list) else []
    if not variables and not analyses:
        return {
            "ready": True,
            "assessable": False,
            "checks": [],
            "missing_requirements": [],
            "summary": "No schema/plan depth contract available.",
        }

    variable_index = {
        str(item.get("name")): item
        for item in variables
        if isinstance(item, dict) and item.get("name")
    }
    numeric = [
        name
        for name, item in variable_index.items()
        if str(item.get("variable_type", "")).lower() in {"continuous", "numeric", "integer"}
    ]
    categorical = [
        name
        for name, item in variable_index.items()
        if str(item.get("variable_type", "")).lower()
        in {"binary", "boolean", "categorical", "factor", "ordinal"}
    ]
    role_outcomes = _readiness_role_values(roles, ("outcome", "target", "dependent", "endpoint"))
    role_groups = _readiness_role_values(roles, ("group", "treatment", "exposure"))
    role_covariates = _readiness_role_values(
        roles,
        ("covariate", "confounder", "adjuster", "baseline", "predictor"),
    )
    substantive_analyses = [
        analysis
        for analysis in analyses
        if isinstance(analysis, dict)
        and str(analysis.get("type") or analysis.get("analysis_type") or "").lower()
        not in {"generate_table_one", "table_one", "descriptive", "summary"}
    ]
    plan_outcomes = list(
        dict.fromkeys(
            value
            for analysis in substantive_analyses
            for value in _readiness_analysis_outcomes(analysis)
        )
    )
    plan_groups = [
        str(analysis[key])
        for analysis in substantive_analyses
        for key in ("group_variable", "group_var")
        if analysis.get(key)
    ]
    outcome_vars = list(dict.fromkeys(role_outcomes + plan_outcomes))
    group_vars = list(dict.fromkeys(role_groups + plan_groups))
    if not outcome_vars:
        outcome_vars = [
            name
            for name in numeric + categorical
            if any(
                token in name.lower()
                for token in (
                    "outcome",
                    "event",
                    "death",
                    "mortality",
                    "aki",
                    "renal",
                    "creatinine",
                    "ngal",
                    "cystatin",
                )
            )
        ]
    if not group_vars:
        group_vars = [
            name
            for name in categorical
            if any(token in name.lower() for token in ("group", "treat", "arm", "exposure"))
        ]
    covariates = [
        name
        for name in list(dict.fromkeys(role_covariates + numeric + categorical))
        if name not in set(outcome_vars + group_vars)
    ]
    actions = {str(item.get("action") or item.get("tool_used") or "") for item in decisions}
    experiment_types = {
        str(item.get("experiment_type") or "")
        for item in experiments
        if str(item.get("status") or "completed") == "completed"
    }
    advanced_analysis_types = {
        str((item.get("parameters") or {}).get("analysis_type") or "")
        for item in decisions
        if str(item.get("action") or item.get("tool_used") or "") == "run_advanced_analysis"
    }
    completed_contract_types = {
        str((item.get("metrics") or {}).get("analysis_type") or item.get("experiment_type") or "")
        for item in experiments
        if (item.get("metrics") or {}).get("contract_executed") is True
    }
    has_analytical_figure = any(
        isinstance(item, dict) and str(item.get("category") or "") == "analytical"
        for item in manifest
    )
    total_analyses = int(results.get("total_analyses") or 0)
    has_results = total_analyses > 0 or bool(results.get("publishable_items"))

    checks: list[dict[str, Any]] = []

    def add_check(
        check_id: str,
        title: str,
        required: bool,
        passed: bool,
        evidence: list[str],
    ) -> None:
        checks.append(
            {
                "id": check_id,
                "title": title,
                "required": required,
                "passed": (not required) or passed,
                "evidence": evidence,
            }
        )

    add_check(
        "univariate",
        "Univariate descriptive analysis",
        True,
        bool(
            {"analyze_variable", "generate_table_one"} & actions
            or "univariate_scan" in experiment_types
            or store.exists(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md")
            or has_results
        ),
        ["decision_log.jsonl", "table_one.md", "results_summary.json"],
    )
    add_check(
        "bivariate",
        "Bivariate/crude association analysis",
        bool(group_vars or len(outcome_vars) >= 2 or substantive_analyses),
        bool(
            {"compare_groups", "correlation_matrix"} & actions
            or "bivariate_scan" in experiment_types
            or has_analytical_figure
        ),
        ["decision_log.jsonl", "visualization_manifest.json"],
    )
    multivariable_required = bool(outcome_vars and covariates)
    add_check(
        "multivariable",
        "Covariate-adjusted model",
        multivariable_required,
        bool(
            advanced_analysis_types
            & {"multiple_regression", "logistic_regression", "glm", "linear_regression"}
            or completed_contract_types
            & {"multiple_regression", "logistic_regression", "glm", "linear_regression"}
            or {"adjusted_model", "logistic_regression"} & experiment_types
        ),
        ["decision_log.jsonl", "experiment_ledger.jsonl"],
    )
    propensity_required = bool(group_vars and covariates)
    add_check(
        "propensity_score",
        "Propensity/balance analysis",
        propensity_required,
        bool(
            "propensity_score" in advanced_analysis_types
            or "propensity_score" in completed_contract_types
            or "propensity_score" in experiment_types
        ),
        ["decision_log.jsonl", "experiment_ledger.jsonl"],
    )
    multilevel_group = any(
        (count := _readiness_unique_count(variable_index.get(name))) is not None and count >= 3
        for name in group_vars
    )
    add_check(
        "derived_variable_provenance",
        "Derived variable provenance",
        bool(multilevel_group and propensity_required),
        bool(derived_entries),
        ["derived_variable_registry.json"],
    )
    add_check(
        "sensitivity_or_branch_review",
        "Sensitivity or autonomous branch review",
        bool(outcome_vars and substantive_analyses),
        bool(
            "sensitivity" in experiment_types
            or store.exists(PipelinePhase.EXECUTE_EXPLORATION, "branch_evaluations.jsonl")
            or store.exists(PipelinePhase.EXECUTE_EXPLORATION, "deviation_log.jsonl")
        ),
        ["experiment_ledger.jsonl", "branch_evaluations.jsonl", "deviation_log.jsonl"],
    )

    missing = [str(check["id"]) for check in checks if check["required"] and not check["passed"]]
    return {
        "ready": not missing,
        "assessable": True,
        "checks": checks,
        "missing_requirements": missing,
        "outcome_variables": outcome_vars,
        "group_variables": group_vars,
        "covariates": covariates[:10],
        "summary": f"{len(checks) - len(missing)}/{len(checks)} depth checks passed",
    }


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _readiness_role_values(roles: dict[str, Any], role_names: tuple[str, ...]) -> list[str]:
    if not isinstance(roles, dict):
        return []
    values: list[str] = []
    for key, raw in roles.items():
        normalized_key = str(key).lower()
        key_matches = any(role_name in normalized_key for role_name in role_names)
        if key_matches:
            if isinstance(raw, list):
                values.extend(str(item) for item in raw)
            elif isinstance(raw, dict):
                values.extend(str(item) for item in raw.values() if item)
            elif raw:
                values.append(str(raw))
        if isinstance(raw, dict):
            for variable_name, role_value in raw.items():
                role_text = str(role_value).strip().lower()
                if any(role_name in role_text for role_name in role_names):
                    values.append(str(variable_name))
        if (
            isinstance(raw, str)
            and not key_matches
            and len(raw) <= 40
            and any(role_name in raw.lower() for role_name in role_names)
        ):
            values.append(str(key))
    return list(dict.fromkeys(values))


def _readiness_analysis_outcomes(analysis: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("variables", "outcome_variables", "targets"):
        raw = analysis.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
        elif raw:
            values.append(str(raw))
    for key in ("target_variable", "outcome", "dependent_variable"):
        if analysis.get(key):
            values.append(str(analysis[key]))
    return list(dict.fromkeys(values))


def _readiness_unique_count(variable: Any) -> int | None:
    if not isinstance(variable, dict):
        return None
    raw = variable.get("n_unique")
    if raw is None:
        raw = variable.get("unique_count")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _evaluate_semantic_report_quality(
    results: dict[str, Any],
    store: Any,
    *,
    require_report_generation: bool,
) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase

    report_text = str(store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md") or "")
    if not report_text.strip() and not require_report_generation:
        return {
            "ready": True,
            "assessable": False,
            "checks": [],
            "missing_requirements": [],
            "summary": "Report narrative is not required before Phase 10 assembly.",
        }

    lower = report_text.lower()
    figure_harness = store.load(PipelinePhase.REPORT_ASSEMBLY, "figure_interpretation_harness.json")
    figure_entries = (
        figure_harness.get("entries")
        if isinstance(figure_harness, dict)
        else []
    )
    figure_entries = figure_entries if isinstance(figure_entries, list) else []
    has_visualization_manifest = store.exists(
        PipelinePhase.EXECUTE_EXPLORATION,
        "visualization_manifest.json",
    )
    required_figure_fields = (
        "evidence_role",
        "visual_read",
        "statistical_support",
        "validity_caveat",
        "reportable_claim",
        "next_analysis",
    )
    figure_harness_complete = bool(figure_entries) and all(
        isinstance(entry, dict)
        and all(str(entry.get(field) or "").strip() for field in required_figure_fields)
        for entry in figure_entries
    )
    has_results = int(results.get("total_analyses") or 0) > 0 or bool(
        results.get("publishable_items")
    )
    checks = [
        {
            "id": "report_body",
            "title": "Report body exists",
            "required": require_report_generation,
            "passed": bool(report_text.strip()),
            "evidence": ["phase_10_report_assembly/eda_report.md"],
        },
        {
            "id": "interpretation_narrative",
            "title": "Interpretation narrative",
            "required": bool(report_text.strip()),
            "passed": any(
                token in lower
                for token in (
                    "interpretation",
                    "discussion",
                    "literature context",
                    "解讀",
                    "討論",
                    "文獻",
                )
            ),
            "evidence": ["interpretation_discussion section"],
        },
        {
            "id": "evidence_to_results",
            "title": "Evidence tied to tables, figures, or results",
            "required": has_results and bool(report_text.strip()),
            "passed": any(token in lower for token in ("table 1", "figure", "圖", "p=", "p <")),
            "evidence": ["table_one.md", "visualization_manifest.json", "results_summary.json"],
        },
        {
            "id": "structured_figure_interpretation",
            "title": "Structured figure interpretation harness",
            "required": has_visualization_manifest and bool(report_text.strip()),
            "passed": figure_harness_complete,
            "evidence": ["phase_10_report_assembly/figure_interpretation_harness.json"],
        },
        {
            "id": "limitations_or_caveats",
            "title": "Limitations and caveats",
            "required": bool(report_text.strip()),
            "passed": any(
                token in lower
                for token in (
                    "limitation",
                    "caveat",
                    "sparse",
                    "missing",
                    "bias",
                    "侷限",
                    "限制",
                    "缺失",
                    "偏差",
                )
            ),
            "evidence": ["report narrative"],
        },
        {
            "id": "actionable_recommendations",
            "title": "Actionable recommendations",
            "required": bool(report_text.strip()),
            "passed": any(token in lower for token in ("recommendation", "建議", "後續")),
            "evidence": ["recommendations section"],
        },
    ]
    normalized_checks = []
    for check in checks:
        passed = (not check["required"]) or bool(check["passed"])
        normalized = dict(check)
        normalized["passed"] = passed
        normalized_checks.append(normalized)
    missing = [
        str(check["id"])
        for check in normalized_checks
        if check.get("required", True) and not check.get("passed")
    ]
    return {
        "ready": not missing,
        "assessable": bool(report_text.strip()),
        "checks": normalized_checks,
        "missing_requirements": missing,
        "summary": f"{len(normalized_checks) - len(missing)}/{len(normalized_checks)} semantic report checks passed",
    }


def _execution_adjusted_completion_tier(
    results: dict[str, Any],
    review: dict[str, Any],
    *,
    current_tier: str,
    publication_bundle_met: bool,
) -> str:
    """Upgrade planner tier when executed evidence meets the production contract."""

    if _completion_rank(current_tier) >= _completion_rank("production_ready"):
        return current_tier
    if not publication_bundle_met:
        return current_tier

    total_analyses = int(results.get("total_analyses") or 0)
    plan_coverage = results.get("plan_coverage") or {}
    phase_progress = results.get("phase6_progress") or {}
    coverage = float(plan_coverage.get("coverage") or phase_progress.get("coverage") or 0.0)
    coverage_ready = coverage >= float(phase_progress.get("required_coverage") or 0.8)

    production_target = int(
        review.get("production_analysis_target")
        or review.get("academic_analysis_target")
        or review.get("recommended_analysis_floor")
        or 0
    )
    academic_target = int(
        review.get("academic_analysis_target")
        or review.get("recommended_analysis_floor")
        or 0
    )

    if production_target and total_analyses >= production_target and coverage_ready:
        return "production_ready"
    if academic_target and total_analyses >= academic_target and coverage_ready:
        return "academic_ready"
    return current_tier


def _evaluate_core_goal_audit(
    results: dict[str, Any],
    store: Any,
    *,
    current_tier: str,
    target_tier: str,
    review_status: str,
    publication_bundle_met: bool,
    data_quality: dict[str, Any] | None = None,
    analysis_depth: dict[str, Any] | None = None,
    semantic_quality: dict[str, Any] | None = None,
    require_report_generation: bool = True,
) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase

    def has(phase: PipelinePhase, filename: str) -> bool:
        return bool(store.exists(phase, filename))

    total_analyses = int(results.get("total_analyses") or 0)
    decision_count = int(results.get("decision_count") or 0)
    has_results = total_analyses > 0 or bool(results.get("publishable_items"))
    has_assembled_report = has(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    has_project_manifest = has(PipelinePhase.PROJECT_SETUP, "project.yaml")
    has_results_summary = (
        has(PipelinePhase.COLLECT_RESULTS, "results_summary.json") or has_results
    )
    has_approval_card = has(PipelinePhase.PROJECT_SETUP, "approval_card.json")
    has_harness_dashboard = has(PipelinePhase.PROJECT_SETUP, "harness_dashboard.json")
    has_artifact_index = has(PipelinePhase.PROJECT_SETUP, "artifact_index.json")
    has_blocker_playbook = has(PipelinePhase.PROJECT_SETUP, "blocker_playbook.json")
    has_ux_harness_bundle = (
        has_approval_card
        and has_harness_dashboard
        and has_artifact_index
        and has_blocker_playbook
    )
    has_no_code_evidence = (
        has_project_manifest
        and has_ux_harness_bundle
        and has(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
        and has_results_summary
    )
    has_agent_harness_evidence = (
        has_project_manifest
        and has_ux_harness_bundle
        and has(PipelinePhase.CONCEPT_ALIGNMENT, "concept_alignment.md")
        and has(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
        and has(PipelinePhase.EXECUTE_EXPLORATION, "decision_log.jsonl")
    )

    checks = [
        {
            "id": "data_understanding",
            "title": "Data understanding",
            "passed": has(PipelinePhase.DATA_INTAKE, "intake_report.json")
            and has(PipelinePhase.SCHEMA_REGISTRY, "schema.json"),
            "evidence": [
                "phase_01_data_intake/intake_report.json",
                "phase_02_schema_registry/schema.json",
            ],
            "contract": "The agent must inspect files and build a schema before planning.",
        },
        {
            "id": "data_quality_contract",
            "title": "Data quality contract",
            "passed": bool((data_quality or {}).get("ready")),
            "evidence": [
                "phase_01_data_intake/raw_data_coverage.json",
                "phase_02_schema_registry/profile_summary.json",
                "phase_02_schema_registry/quality_report.json",
            ],
            "contract": (
                "Phase 2 must include reusable profiling and quality evidence, "
                "not only inferred variable names."
            ),
        },
        {
            "id": "analysis_planning",
            "title": "Analysis planning",
            "passed": review_status in {"pass", "repaired"}
            and has(PipelinePhase.CONCEPT_ALIGNMENT, "concept_alignment.md")
            and has(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml"),
            "evidence": [
                "phase_03_concept_alignment/concept_alignment.md",
                "phase_05_plan_completeness_review/analysis_plan_review.json",
                "phase_06_plan_registration/analysis_plan.yaml",
            ],
            "contract": "The agent must map research intent to variables and lock a reviewed plan.",
        },
        {
            "id": "data_correctness",
            "title": "Data correctness",
            "passed": has(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json"),
            "evidence": ["phase_07_pre_explore_check/readiness_checklist.json"],
            "contract": "Readiness checks must run before execution claims are made.",
        },
        {
            "id": "reproducible_exploration",
            "title": "Reproducible exploration",
            "passed": decision_count > 0,
            "evidence": ["phase_08_execute_exploration/decision_log.jsonl"],
            "contract": "Analysis actions must be traceable through append-only decision logs.",
        },
        {
            "id": "analysis_execution_interpretation",
            "title": "Analysis execution and interpretation",
            "passed": has_results and bool((semantic_quality or {}).get("ready", True)),
            "evidence": [
                "phase_09_collect_results/results_summary.json",
                "phase_10_report_assembly/semantic_report_quality.json",
            ],
            "contract": (
                "The run must execute analyses, collect results, and convert them "
                "into reviewable interpretation."
            ),
        },
        {
            "id": "analysis_completeness",
            "title": "Analysis completeness",
            "passed": _completion_rank(current_tier) >= _completion_rank(target_tier)
            and publication_bundle_met,
            "evidence": ["report_readiness.completeness_tier", "report_readiness.deliverables"],
            "contract": "The final report must meet the configured production-ready floor.",
        },
        {
            "id": "analysis_depth",
            "title": "Analysis depth",
            "passed": bool((analysis_depth or {}).get("ready", True)),
            "evidence": [
                "phase_08_execute_exploration/decision_log.jsonl",
                "phase_08_execute_exploration/experiment_ledger.jsonl",
                "phase_08_execute_exploration/derived_variable_registry.json",
            ],
            "contract": (
                "Medical EDA must include the required univariate, bivariate, "
                "multivariable, balance/propensity, and provenance checks when "
                "the schema makes them applicable."
            ),
        },
        {
            "id": "report_generation",
            "title": "Report generation",
            "passed": has_assembled_report or not require_report_generation,
            "evidence": ["phase_10_report_assembly/eda_report.md", "publication deliverables"],
            "contract": "The run must produce an assembled EDA report for non-coders.",
        },
        {
            "id": "no_code_operation",
            "title": "No-code operation",
            "passed": has_no_code_evidence,
            "evidence": [
                "phase_00_project_setup/project.yaml",
                "phase_00_project_setup/approval_card.json",
                "phase_00_project_setup/harness_dashboard.json",
                "phase_00_project_setup/artifact_index.json",
                "phase_00_project_setup/blocker_playbook.json",
                "phase_06_plan_registration/analysis_plan.yaml",
                "phase_09_collect_results/results_summary.json",
            ],
            "contract": "The user should not need notebooks or analysis scripts to complete the flow.",
        },
        {
            "id": "agent_friendly_harness",
            "title": "Agent-friendly harness",
            "passed": has_agent_harness_evidence,
            "evidence": [
                "phase_00_project_setup/project.yaml",
                "phase_00_project_setup/approval_card.json",
                "phase_00_project_setup/harness_dashboard.json",
                "phase_00_project_setup/artifact_index.json",
                "phase_00_project_setup/blocker_playbook.json",
                "phase_03_concept_alignment/concept_alignment.md",
                "phase_06_plan_registration/analysis_plan.yaml",
                "phase_08_execute_exploration/decision_log.jsonl",
            ],
            "contract": "Mainstream agents should have explicit phases, gates, and artifacts to follow.",
        },
    ]
    missing_goals = [str(check["id"]) for check in checks if not check["passed"]]
    return {
        "ready": not missing_goals,
        "checks": checks,
        "missing_goals": missing_goals,
    }


def _render_report_readiness_markdown(readiness: dict[str, Any]) -> str:
    lines = ["# 🧾 Report Readiness\n"]
    lines.append(f"- **target tier:** {readiness.get('target_tier', 'unknown')}")
    lines.append(f"- **current tier:** {readiness.get('current_tier', 'unknown')}")
    lines.append(f"- **methodology review:** {readiness.get('review_status', 'unknown')}")
    lines.append(
        f"- **publication bundle:** {'ready' if readiness.get('publication_bundle_met') else 'missing'}"
    )
    data_quality = readiness.get("data_quality") or {}
    if data_quality:
        lines.append(
            f"- **data quality evidence:** {'ready' if data_quality.get('ready') else 'missing'}"
        )
        missing_quality = data_quality.get("missing_requirements") or []
        if missing_quality:
            lines.append(f"- **missing data quality checks:** {', '.join(missing_quality)}")
        raw_coverage = data_quality.get("raw_data_coverage") or {}
        if isinstance(raw_coverage, dict) and raw_coverage:
            lines.append(
                f"- **raw data coverage:** {'ready' if raw_coverage.get('ready') else 'needs review'}"
            )
            if raw_coverage.get("unloaded_loadable_files"):
                lines.append(
                    f"- **unloaded raw files:** {len(raw_coverage.get('unloaded_loadable_files') or [])}"
                )
            if raw_coverage.get("unselected_data_candidate_sheets"):
                lines.append(
                    f"- **unselected data-like sheets:** {len(raw_coverage.get('unselected_data_candidate_sheets') or [])}"
                )
    analysis_depth = readiness.get("analysis_depth") or {}
    if analysis_depth:
        lines.append(
            f"- **analysis depth:** {'ready' if analysis_depth.get('ready') else 'missing'}"
        )
        missing_depth = analysis_depth.get("missing_requirements") or []
        if missing_depth:
            lines.append(f"- **missing depth checks:** {', '.join(missing_depth)}")
    semantic_quality = readiness.get("semantic_report_quality") or {}
    if semantic_quality:
        lines.append(
            f"- **semantic report quality:** {'ready' if semantic_quality.get('ready') else 'missing'}"
        )
        missing_semantic = semantic_quality.get("missing_requirements") or []
        if missing_semantic:
            lines.append(f"- **missing semantic checks:** {', '.join(missing_semantic)}")
    core_goal_audit = readiness.get("core_goal_audit") or {}
    if core_goal_audit:
        lines.append(
            f"- **core goal audit:** {'ready' if core_goal_audit.get('ready') else 'missing'}"
        )
        missing_goals = core_goal_audit.get("missing_goals") or []
        if missing_goals:
            lines.append(f"- **missing core goals:** {', '.join(missing_goals)}")
    if readiness.get("missing_requirements"):
        lines.append("\n## Missing Requirements")
        for requirement in readiness["missing_requirements"]:
            lines.append(f"- {requirement}")
    return "\n".join(lines)


def _project_relative_path(path: Path, project: Any) -> str:
    try:
        return path.resolve().relative_to(Path(project.output_dir).resolve()).as_posix()
    except Exception:
        try:
            return path.resolve().relative_to(Path(project.artifacts_dir).resolve()).as_posix()
        except Exception:
            return path.name


def _build_claim_provenance_manifest(
    project: Any,
    store: Any,
    *,
    report_source: str,
) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase

    claims: list[dict[str, Any]] = []

    def add_claim(
        claim_type: str,
        text: str,
        evidence: list[dict[str, Any]],
        *,
        variables: list[str] | None = None,
        confidence: str = "exploratory",
    ) -> None:
        claims.append(
            {
                "claim_id": f"C{len(claims) + 1:03d}",
                "claim_type": claim_type,
                "text": text,
                "variables": variables or [],
                "evidence": evidence,
                "confidence": confidence,
            }
        )

    if store.exists(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md"):
        add_claim(
            "baseline_table",
            "Baseline characteristics were summarized in Table 1.",
            [
                {
                    "phase": PipelinePhase.EXECUTE_EXPLORATION.value,
                    "artifact": "table_one.md",
                }
            ],
            confidence="descriptive",
        )

    results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json") or {}
    if isinstance(results, dict):
        for item in results.get("publishable_items") or results.get("candidate_findings") or []:
            if not isinstance(item, dict):
                continue
            variables = [str(value) for value in item.get("variables") or []]
            p_value = item.get("p_value")
            effect = item.get("effect_size")
            detail = f"{item.get('test_name', 'statistical test')}"
            if p_value is not None:
                detail += f", p={p_value}"
            if effect is not None:
                detail += f", effect_size={effect}"
            add_claim(
                "candidate_statistical_signal",
                f"Candidate association detected for {', '.join(variables) or 'reported variables'} ({detail}).",
                [
                    {
                        "phase": PipelinePhase.COLLECT_RESULTS.value,
                        "artifact": "results_summary.json",
                        "marker": item.get("marker", "candidate"),
                    }
                ],
                variables=variables,
                confidence=str(item.get("review_status") or "audit_required"),
            )

    for entry in _resolved_visualization_manifest_entries(project, store):
        if not isinstance(entry, dict) or not entry.get("exists"):
            continue
        variables = [str(value) for value in entry.get("variables") or []]
        figure_path = Path(str(entry.get("output_path") or ""))
        add_claim(
            "figure_evidence",
            (
                f"{entry.get('plot_type', 'figure')} visual evidence was generated "
                f"for {', '.join(variables) or 'specified variables'}."
            ),
            [
                {
                    "phase": PipelinePhase.EXECUTE_EXPLORATION.value,
                    "artifact": "visualization_manifest.json",
                    "figure": _project_relative_path(figure_path, project),
                    "summary": entry.get("summary") or entry.get("stats_summary"),
                }
            ],
            variables=variables,
            confidence="visual_exploratory",
        )

    readiness = store.load(PipelinePhase.REPORT_ASSEMBLY, "report_readiness.json")
    if isinstance(readiness, dict):
        add_claim(
            "readiness_assessment",
            (
                "Report readiness was evaluated as "
                f"{'ready' if readiness.get('ready') else 'not ready'} "
                f"({readiness.get('current_tier')} -> {readiness.get('target_tier')})."
            ),
            [
                {
                    "phase": PipelinePhase.REPORT_ASSEMBLY.value,
                    "artifact": "report_readiness.json",
                    "missing_requirements": readiness.get("missing_requirements", []),
                }
            ],
            confidence="audit_gate",
        )

    if store.exists(PipelinePhase.REPORT_ASSEMBLY, "pubmed_literature_context.md"):
        add_claim(
            "literature_context",
            "Literature context was available and should be interpreted separately from dataset-derived evidence.",
            [
                {
                    "phase": PipelinePhase.REPORT_ASSEMBLY.value,
                    "artifact": "pubmed_literature_context.md",
                }
            ],
            confidence="contextual",
        )

    return {
        "project_id": getattr(project, "id", "unknown"),
        "report_source": report_source,
        "generated_at": datetime.now().isoformat(),
        "claim_count": len(claims),
        "claims": claims,
    }


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

    output_path = _figure_manifest_output_path(project, result_path)
    if output_path is None:
        raise ValueError("Visualization output path must stay inside the project figures directory.")

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
            "output_path": output_path,
            "stats_summary": stats_summary,
            "category": _visualization_category(plot_type, group_var),
        }
    )
    store.save(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json", updated)


def _resolved_visualization_manifest_entries(project: Any, store: Any) -> list[dict[str, Any]]:
    from rde.domain.services.report_asset_contract import (
        resolve_visualization_manifest_entries,
    )

    return resolve_visualization_manifest_entries(project, store)


def _summarize_publication_deliverables(project: Any, store: Any) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase

    valid_entries = [
        entry for entry in _resolved_visualization_manifest_entries(project, store) if entry.get("exists")
    ]

    descriptive = sum(1 for entry in valid_entries if entry.get("category") == "descriptive")
    analytical = sum(1 for entry in valid_entries if entry.get("category") == "analytical")
    figure_files = []
    for entry in valid_entries:
        figure_path = _project_figure_path(project, entry.get("output_path"))
        if figure_path is not None:
            figure_files.append(figure_path.name)
    figure_files = sorted(figure_files)
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
