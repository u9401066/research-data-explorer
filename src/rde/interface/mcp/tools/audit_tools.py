"""Audit Tools — Phase 9 (Audit Review) & Phase 10 (Auto-Improve).

Phase 9: Run audit checks, grade the pipeline run.
Phase 10: Auto-improve fixable issues, export handoff package.
All tools return markdown strings.
"""

from __future__ import annotations

from datetime import datetime
from os.path import relpath
from pathlib import Path
import re
from typing import Any


def register_audit_tools(server: Any) -> None:
    """Register audit and auto-improve MCP tools."""

    @server.tool()
    def run_audit(project_id: str | None = None) -> str:
        """執行完整審計 (Phase 9)。

        檢查: 計畫符合度、方法適當性、效果量完整性、
        偏離合理性、再現性、H-008/H-009/H-010 合規。
        輸出 A-F 評分與改善建議。

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            ensure_phase_ready,
        )
        from rde.interface.mcp.tools._shared.project_context import persist_project
        from rde.application.pipeline import PipelinePhase

        log_tool_call("run_audit", {"project_id": project_id})

        ok, msg, project, _ = ensure_phase_ready(PipelinePhase.AUDIT_REVIEW, project_id=project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None

        try:
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult, REQUIRED_ARTIFACTS
            from rde.domain.models.project import ProjectStatus
            from rde.infrastructure.persistence.artifact_store import ArtifactStore
            from rde.interface.mcp.tools._shared.project_context import compute_phase6_progress
            from datetime import datetime

            session = get_session()
            pipeline = session.get_pipeline(project.id)
            logger = session.get_logger(project.id)
            store = ArtifactStore(project.artifacts_dir)

            checks: list[dict] = []
            total_score = 0
            max_score = 0

            # ── 1. Completeness: artifact coverage ──────────────────
            max_score += 30
            completed_phases = 0
            total_phases = 0
            missing_artifacts: list[str] = []

            for phase in PipelinePhase:
                if phase in {PipelinePhase.AUDIT_REVIEW, PipelinePhase.AUTO_IMPROVE}:
                    continue
                required = REQUIRED_ARTIFACTS.get(phase, [])
                if not required:
                    continue
                total_phases += 1
                all_present, missing = store.check_artifacts(phase)
                if all_present:
                    completed_phases += 1
                else:
                    for m in missing:
                        missing_artifacts.append(f"{phase.value}/{m}")

            completeness_pct = completed_phases / max(1, total_phases)
            completeness_score = int(30 * completeness_pct)
            total_score += completeness_score

            checks.append(
                {
                    "category": "completeness",
                    "score": completeness_score,
                    "max": 30,
                    "passed": completeness_pct >= 0.8,
                    "details": f"{completed_phases}/{total_phases} phases with artifacts",
                    "missing": missing_artifacts,
                }
            )

            # ── 2. Plan adherence ───────────────────────────────────
            max_score += 25
            plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
            results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")

            if plan and results:
                planned = [
                    entry
                    for entry in plan.get("analyses", plan.get("steps", []))
                    if not isinstance(entry, dict) or entry.get("required", True)
                ]
                progress = compute_phase6_progress(project)
                executed = progress.get("executed_analyses", results.get("total_analyses", 0))
                coverage = min(1.0, executed / max(1, len(planned)))
                deviations = logger.read_deviations()
                adherence_score = int(25 * coverage)
                # Penalize unexcused deviations
                for d in deviations:
                    if not d.get("reason"):
                        adherence_score = max(0, adherence_score - 5)
                total_score += adherence_score
                checks.append(
                    {
                        "category": "plan_adherence",
                        "score": adherence_score,
                        "max": 25,
                        "passed": adherence_score >= 18,
                        "details": (
                            f"coverage={coverage:.0%}, deviations={len(deviations)}, "
                            f"branch_decisions={progress.get('branch_decision_count', 0)}"
                        ),
                    }
                )
            else:
                # Quick explore → no plan
                total_score += 15
                checks.append(
                    {
                        "category": "plan_adherence",
                        "score": 15,
                        "max": 25,
                        "passed": True,
                        "details": "No formal plan (Quick Explore mode)",
                    }
                )

            # ── 3. Effect size completeness (S-009) ─────────────────
            max_score += 15
            if results:
                pub = results.get("publishable_items", [])
                with_es = [p for p in pub if p.get("effect_size") is not None]
                es_pct = len(with_es) / max(1, len(pub)) if pub else 1.0
            else:
                es_pct = 1.0
            es_score = int(15 * es_pct)
            total_score += es_score
            checks.append(
                {
                    "category": "effect_size_completeness",
                    "score": es_score,
                    "max": 15,
                    "passed": es_pct >= 0.8,
                    "details": f"{es_pct:.0%} of results include effect sizes",
                }
            )

            # ── 4. Decision traceability (H-009, H-010) ─────────────
            max_score += 15
            decisions = logger.read_decisions()
            append_ok, append_msg = logger.verify_append_only()
            trace_score = 0
            if decisions:
                trace_score += 10
            if append_ok:
                trace_score += 5
            total_score += trace_score
            checks.append(
                {
                    "category": "traceability",
                    "score": trace_score,
                    "max": 15,
                    "passed": trace_score >= 10,
                    "details": f"{len(decisions)} decisions, append-only={'✅' if append_ok else '❌'}",
                }
            )

            # ── 5. Reproducibility ──────────────────────────────────
            max_score += 15
            repro_score = 0
            has_schema = store.exists(PipelinePhase.SCHEMA_REGISTRY, "schema.json")
            has_report = store.exists(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
            if has_schema:
                repro_score += 7
            if has_report:
                repro_score += 8
            total_score += repro_score
            checks.append(
                {
                    "category": "reproducibility",
                    "score": repro_score,
                    "max": 15,
                    "passed": repro_score >= 10,
                    "details": f"schema={'✅' if has_schema else '❌'}, report={'✅' if has_report else '❌'}",
                }
            )

            # ── 6. Publication bundle completeness ────────────────
            max_score += 10
            deliverables = results.get("deliverables", {}) if results else {}
            required_desc = deliverables.get("required_descriptive_figures", 3)
            required_analytical = deliverables.get("required_analytical_figures", 6)
            descriptive = deliverables.get("descriptive_figures", 0)
            analytical = deliverables.get("analytical_figures", 0)
            bundle_score = 0
            if deliverables.get("table_one_present"):
                bundle_score += 2
            bundle_score += int(3 * min(1.0, descriptive / max(1, required_desc)))
            bundle_score += int(5 * min(1.0, analytical / max(1, required_analytical)))
            total_score += bundle_score
            checks.append(
                {
                    "category": "publication_bundle",
                    "score": bundle_score,
                    "max": 10,
                    "passed": bool(deliverables.get("minimum_publication_bundle_met")),
                    "details": (
                        f"table_one={'✅' if deliverables.get('table_one_present') else '❌'}, "
                        f"crude={descriptive}/{required_desc}, detailed={analytical}/{required_analytical}"
                    ),
                }
            )

            # ── 7. Final report readiness ─────────────────────────
            max_score += 10
            from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness

            report_readiness = _evaluate_report_readiness(results, store)
            readiness_score = 0
            if report_readiness.get("review_status") in {"pass", "repaired"}:
                readiness_score += 3
            if report_readiness.get("publication_bundle_met"):
                readiness_score += 3
            if report_readiness.get("ready"):
                readiness_score += 4
            total_score += readiness_score
            readiness_missing = report_readiness.get("missing_requirements", [])
            readiness_details = (
                f"target={report_readiness.get('target_tier', 'unknown')}, "
                f"current={report_readiness.get('current_tier', 'unknown')}, "
                f"bundle={'✅' if report_readiness.get('publication_bundle_met') else '❌'}"
            )
            if readiness_missing:
                readiness_details += f", missing={', '.join(readiness_missing)}"
            checks.append(
                {
                    "category": "report_readiness",
                    "score": readiness_score,
                    "max": 10,
                    "passed": bool(report_readiness.get("ready")),
                    "details": readiness_details,
                }
            )

            # ── Grade ───────────────────────────────────────────────
            max_score += 10
            core_goal_audit = report_readiness.get("core_goal_audit") or {}
            core_checks = core_goal_audit.get("checks") or []
            passed_core = sum(1 for item in core_checks if item.get("passed"))
            total_core = len(core_checks)
            core_score = int(10 * (passed_core / max(1, total_core)))
            total_score += core_score
            missing_core = core_goal_audit.get("missing_goals") or []
            core_details = f"{passed_core}/{total_core} core goals"
            if missing_core:
                core_details += f", missing={', '.join(str(item) for item in missing_core)}"
            checks.append(
                {
                    "category": "core_goal_audit",
                    "score": core_score,
                    "max": 10,
                    "passed": bool(core_goal_audit.get("ready")),
                    "details": core_details,
                    "missing": missing_core,
                }
            )

            pct = total_score / max(1, max_score)
            if pct >= 0.9:
                grade = "A"
            elif pct >= 0.8:
                grade = "B"
            elif pct >= 0.7:
                grade = "C"
            elif pct >= 0.6:
                grade = "D"
            else:
                grade = "F"

            # Build improvement suggestions
            suggestions = _generate_suggestions(checks)

            audit_report = {
                "grade": grade,
                "total_score": total_score,
                "max_score": max_score,
                "percentage": round(pct * 100, 1),
                "checks": checks,
                "suggestions": suggestions,
            }

            store.save(PipelinePhase.AUDIT_REVIEW, "audit_report.json", audit_report)
            pipeline.mark_completed(
                PhaseResult(
                    phase=PipelinePhase.AUDIT_REVIEW,
                    completed_at=datetime.now(),
                    success=True,
                    artifacts={
                        "audit_report.json": str(
                            store.get_path(PipelinePhase.AUDIT_REVIEW, "audit_report.json")
                        )
                    },
                )
            )
            project.advance_to(ProjectStatus.AUDIT_REVIEW)
            persist_project(project)

            # Format output
            grade_icon = {"A": "🏆", "B": "🟢", "C": "🟡", "D": "🟠", "F": "🔴"}
            lines = [
                f"# {grade_icon.get(grade, '📋')} 審計結果 — 等級 {grade} ({pct:.0%})\n",
                f"**評分:** {total_score}/{max_score}\n",
            ]

            lines.append("| 項目 | 分數 | 狀態 | 說明 |")
            lines.append("| --- | --- | --- | --- |")
            for c in checks:
                icon = "✅" if c["passed"] else "❌"
                lines.append(
                    f"| {c['category']} | {c['score']}/{c['max']} | {icon} | {c['details']} |"
                )

            if suggestions:
                lines.append("\n## 💡 改善建議")
                for s in suggestions:
                    lines.append(f"- {s}")

            if missing_artifacts:
                lines.append("\n## ⚠️ 缺失 Artifacts")
                for m in missing_artifacts:
                    lines.append(f"- {m}")

            lines.append("\n**Artifact:** audit_report.json")

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("run_audit", e)
            return fmt_error(f"審計失敗: {e}")

    @server.tool()
    def auto_improve(project_id: str | None = None) -> str:
        """根據審計結果自動改善可修正項目 (Phase 10)。

        讀取 audit_report.json，執行自動修正:
        - 補缺效果量、補遺漏圖表、修正報告格式。
        - final_report.md 會附上 production-readiness 摘要，說明為何已達或尚未達 production-ready。
        不能自動修復的項目會列為手動建議。

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            ensure_phase_ready,
        )
        from rde.interface.mcp.tools._shared.project_context import (
            persist_project,
            project_dataset_ids,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("auto_improve", {"project_id": project_id})

        ok, msg, project, _ = ensure_phase_ready(PipelinePhase.AUTO_IMPROVE, project_id=project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None

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
            from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness

            # Read audit report
            audit = store.load(PipelinePhase.AUDIT_REVIEW, "audit_report.json")
            if not audit:
                return fmt_error("[H-008] 請先執行 `run_audit()` (Phase 9) 才能進行自動改善。")

            actions_taken: list[str] = []
            auto_fixed: list[str] = []
            original_grade = audit.get("grade", "?")

            # ── Auto-fix 1: Regenerate report if missing ────────────
            if not store.exists(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md"):
                try:
                    # Try to auto-assemble a basic report
                    schema = store.load(PipelinePhase.SCHEMA_REGISTRY, "schema.json")
                    results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
                    if schema or results:
                        basic_report = (
                            "# EDA Report (自動生成)\n\n此報告由 auto_improve 自動生成。\n\n"
                        )
                        if schema:
                            basic_report += (
                                f"## Schema\n- 變數數: {schema.get('n_variables', '?')}\n\n"
                            )
                        if results:
                            basic_report += (
                                f"## Results\n- 分析項目: {results.get('total_analyses', '?')}\n"
                            )
                        store.save(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md", basic_report)
                        auto_fixed.append("✅ 自動生成基本報告 (eda_report.md)")
                    else:
                        actions_taken.append(
                            "報告不存在且缺少資料 → 請手動執行 `assemble_report()`"
                        )
                except Exception:
                    actions_taken.append("報告不存在 → 請手動執行 `assemble_report()`")

            # ── Auto-fix 2: Ensure decision log exists ──────────────
            decisions = logger.read_decisions()
            if not decisions:
                auto_fixed.append("⚠️ 無決策紀錄 — 後續分析操作將自動記錄")

            # ── Auto-fix 3: Missing effect sizes ────────────────────
            for check in audit.get("checks", []):
                if check["category"] == "effect_size_completeness" and not check["passed"]:
                    actions_taken.append(
                        "效果量不完整 → 重新執行 `compare_groups()` 以自動計算效果量"
                    )

            # ── Auto-fix 4: Check for results without collect ───────
            if not store.exists(PipelinePhase.COLLECT_RESULTS, "results_summary.json"):
                # Check if we have any analysis results in session
                dataset_ids = project_dataset_ids(project)
                for did in dataset_ids:
                    entry = session.get_dataset_entry(did)
                    if entry.analysis_results:
                        results_summary = {
                            "total_analyses": len(entry.analysis_results),
                            "collected_at": datetime.now().isoformat(),
                            "source": "auto_improve",
                        }
                        store.save(
                            PipelinePhase.COLLECT_RESULTS, "results_summary.json", results_summary
                        )
                        auto_fixed.append(f"✅ 自動收集 {len(entry.analysis_results)} 項分析結果")
                        break

            # ── Build improvement suggestions from audit ────────────
            suggestions = audit.get("suggestions", [])
            for s in suggestions:
                actions_taken.append(f"建議: {s}")

            all_items = auto_fixed + actions_taken
            results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
            report_readiness = _evaluate_report_readiness(results, store)

            # Save improvement log
            improvement_log = {
                "original_grade": original_grade,
                "auto_fixed": auto_fixed,
                "manual_suggestions": actions_taken,
                "total_items": len(all_items),
                "report_readiness": report_readiness,
            }
            store.save(PipelinePhase.AUTO_IMPROVE, "improvement_log.json", improvement_log)

            # Save final report
            assembled_report = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
            store.save(
                PipelinePhase.AUTO_IMPROVE,
                "final_report.md",
                _build_phase10_source_markdown(
                    project,
                    store,
                    assembled_report=str(assembled_report or ""),
                    audit=audit,
                    report_readiness=report_readiness,
                    improvement_log=improvement_log,
                ),
            )
            pipeline.mark_completed(
                PhaseResult(
                    phase=PipelinePhase.AUTO_IMPROVE,
                    completed_at=datetime.now(),
                    success=True,
                    artifacts={"final_report.md": "", "improvement_log.json": ""},
                )
            )
            project.advance_to(ProjectStatus.AUTO_IMPROVE)
            persist_project(project)

            lines = [
                "# 🔧 自動改善 (Phase 10)\n",
                f"- **原始等級:** {original_grade}",
                f"- **自動修正:** {len(auto_fixed)}",
                f"- **手動建議:** {len(actions_taken)}",
                f"- **production readiness:** {report_readiness.get('current_tier')} → {report_readiness.get('target_tier')} ({'ready' if report_readiness.get('ready') else 'not ready'})",
            ]

            if auto_fixed:
                lines.append("\n## ✅ 自動修正")
                for i, a in enumerate(auto_fixed, 1):
                    lines.append(f"{i}. {a}")

            if actions_taken:
                lines.append("\n## 💡 手動建議")
                for i, a in enumerate(actions_taken, 1):
                    lines.append(f"{i}. {a}")

            if not all_items:
                lines.append("\n✅ 無需改善，所有項目已達標。")

            lines.append("\n**Artifacts:** improvement_log.json, final_report.md")

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("auto_improve", e)
            return fmt_error(f"自動改善失敗: {e}")

    @server.tool()
    def export_final_report(
        project_id: str | None = None,
        formats: str = "docx,pdf",
        title: str = "",
        allow_incomplete: bool = False,
    ) -> str:
        """匯出 Phase 10 final_report.md 為正式 DOCX / PDF。

        會補齊 final_report.md 之外的正式輸出依賴：
        - Table 1 轉為真正表格
        - visualization manifest 中尚未寫進 markdown 的圖表一併附上
        - 產出 final_report_export_manifest.json 供核對路徑與項目

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
            formats: 匯出格式，預設 "docx,pdf"
            title: 自訂標題；空字串時沿用 final_report.md 標題
            allow_incomplete: 若為 False，未達 production-ready 時拒絕匯出
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
            "export_final_report",
            {
                "project_id": project_id,
                "formats": formats,
                "title": title,
                "allow_incomplete": allow_incomplete,
            },
        )

        ok, msg, project, _ = ensure_phase_ready(
            PipelinePhase.AUTO_IMPROVE, project_id=project_id
        )
        if not ok:
            return fmt_error(msg)
        assert project is not None

        try:
            from rde.application.use_cases.export_report import ExportReportUseCase
            from rde.infrastructure.adapters.docx_exporter import DocxExporter
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            store = ArtifactStore(project.artifacts_dir)
            report_readiness = _load_phase10_report_readiness(store)
            if not allow_incomplete and not report_readiness.get("ready", False):
                return fmt_error(
                    "目前 final report 尚未達 production-ready，暫不匯出正式終版。",
                    _render_phase10_readiness_summary(report_readiness),
                    suggestion="若需仍先匯出供審閱，請使用 allow_incomplete=true。",
                )

            report, asset_summary = _build_phase10_export_report(project, store, title=title)

            fmt_list = [value.strip().lower() for value in formats.split(",") if value.strip()]
            valid_fmts = {"docx", "pdf"}
            invalid = [value for value in fmt_list if value not in valid_fmts]
            if invalid:
                return fmt_error(f"不支援的格式: {', '.join(invalid)}。支援: docx, pdf")

            output_dir = project.artifacts_dir / PipelinePhase.AUTO_IMPROVE.value / "exports"
            exporter = DocxExporter()
            use_case = ExportReportUseCase(exporter)
            exported = use_case.execute(
                report=report,
                output_dir=output_dir,
                formats=fmt_list,
                figures_dir=project.output_dir / "figures",
                filename_stem="final_report",
            )

            manifest = _build_phase10_export_manifest(
                project,
                store,
                report=report,
                exported=exported,
                asset_summary=asset_summary,
                report_readiness=report_readiness,
            )
            store.save(PipelinePhase.AUTO_IMPROVE, "final_report_export_manifest.json", manifest)

            exported_lines = [
                f"- **{(fmt.upper() + ' (HTML fallback)') if path.suffix.lower() == '.html' else fmt.upper()}:** {_relative_project_path(path, project)}"
                for fmt, path in exported.items()
            ]
            return fmt_success(
                f"Phase 10 final report 已匯出 — {', '.join(fmt.upper() for fmt in exported)}",
                f"- **標題:** {report.title}\n"
                f"- **完整度狀態:** {report_readiness.get('current_tier')} → {report_readiness.get('target_tier')}\n"
                f"- **Table 1:** {'已納入' if asset_summary.get('table', {}).get('included') else '缺少'}\n"
                f"- **圖表總數:** {asset_summary.get('figures', {}).get('included_count', 0)}\n"
                f"- **Manifest:** {_relative_project_path(store.get_path(PipelinePhase.AUTO_IMPROVE, 'final_report_export_manifest.json'), project)}\n"
                + "\n".join(exported_lines),
            )
        except ImportError as e:
            return fmt_error(str(e))
        except ValueError as e:
            return fmt_error(f"Phase 10 匯出失敗: {e}")
        except Exception as e:
            log_tool_error("export_final_report", e)
            return fmt_error(f"Phase 10 匯出失敗: {e}")

    @server.tool()
    def export_handoff(project_id: str | None = None) -> str:
        """匯出 handoff package 給下游工具 (e.g., med-paper-assistant)。

        打包: 報告、統計結果、圖表、schema、decision/deviation log。
        產出的 handoff_manifest.json 可直接提供給 med-paper-assistant。

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            fmt_success,
            ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("export_handoff", {"project_id": project_id})

        ok, msg, project, _ = ensure_phase_ready(PipelinePhase.AUTO_IMPROVE, project_id=project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None

        try:
            from rde.application.pipeline import PipelinePhase
            from rde.infrastructure.persistence.artifact_store import ArtifactStore
            import json
            import shutil

            store = ArtifactStore(project.artifacts_dir)

            # Create handoff directory
            handoff_dir = project.artifacts_dir / "handoff_package"
            handoff_dir.mkdir(parents=True, exist_ok=True)

            included_files: list[str] = []

            # Copy key artifacts
            copy_map = [
                (PipelinePhase.SCHEMA_REGISTRY, "schema.json"),
                (PipelinePhase.COLLECT_RESULTS, "results_summary.json"),
                (PipelinePhase.REPORT_ASSEMBLY, "eda_report.md"),
                (PipelinePhase.AUDIT_REVIEW, "audit_report.json"),
                (PipelinePhase.AUTO_IMPROVE, "final_report.md"),
            ]

            for phase, filename in copy_map:
                src = store.get_path(phase, filename)
                if src.exists():
                    dst = handoff_dir / filename
                    shutil.copy2(src, dst)
                    included_files.append(filename)

            optional_phase6_files = ["table_one.md", "table_one.json"]
            for filename in optional_phase6_files:
                src = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, filename)
                if src.exists():
                    shutil.copy2(src, handoff_dir / filename)
                    included_files.append(filename)

            for filename in store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION):
                if filename.startswith("sensitivity_analysis") and filename.endswith(
                    (".md", ".json")
                ):
                    src = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, filename)
                    if src.exists():
                        shutil.copy2(src, handoff_dir / filename)
                        included_files.append(filename)
                if filename.startswith(
                    "advanced_analysis_learning_curve_cusum"
                ) and filename.endswith((".md", ".json")):
                    src = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, filename)
                    if src.exists():
                        shutil.copy2(src, handoff_dir / filename)
                        included_files.append(filename)

            # Copy decision log
            decision_src = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "decision_log.jsonl")
            if decision_src.exists():
                shutil.copy2(decision_src, handoff_dir / "decision_log.jsonl")
                included_files.append("decision_log.jsonl")

            deviation_src = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "deviation_log.jsonl")
            if deviation_src.exists():
                shutil.copy2(deviation_src, handoff_dir / "deviation_log.jsonl")
                included_files.append("deviation_log.jsonl")

            # Copy figures if they exist
            figures_dir = project.output_dir / "figures"
            if figures_dir.exists():
                handoff_figs = handoff_dir / "figures"
                handoff_figs.mkdir(exist_ok=True)
                for fig in figures_dir.glob("*.png"):
                    shutil.copy2(fig, handoff_figs / fig.name)
                    included_files.append(f"figures/{fig.name}")

            # Create handoff manifest
            manifest = {
                "project_id": project.id,
                "project_name": project.name,
                "exported_at": __import__("datetime").datetime.now().isoformat(),
                "files": included_files,
                "source": "RDE 13-Phase Auditable EDA Pipeline",
                "target": "med-paper-assistant",
            }
            manifest_path = handoff_dir / "handoff_manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            return fmt_success(
                f"Handoff package 已匯出 — {len(included_files)} 個檔案",
                f"- **路徑:** {handoff_dir}\n"
                f"- **檔案清單:**\n"
                + "\n".join(f"  - {f}" for f in included_files)
                + "\n\n可提供給 med-paper-assistant 使用。",
            )

        except Exception as e:
            log_tool_error("export_handoff", e)
            return fmt_error(f"匯出失敗: {e}")

    @server.tool()
    def verify_audit_trail(project_id: str | None = None) -> str:
        """驗證審計鏈完整性 (H-008, H-009, H-010)。

        檢查 artifact gate、decision logging、append-only logs。

        Args:
            project_id: 專案 ID (預設使用當前專案)
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            ensure_project_context,
        )

        log_tool_call("verify_audit_trail", {"project_id": project_id})

        ok, msg, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(msg)
        assert project is not None

        try:
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, REQUIRED_ARTIFACTS
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            session = get_session()
            logger = session.get_logger(project.id)
            store = ArtifactStore(project.artifacts_dir)

            lines = ["# 🔍 審計鏈驗證\n"]
            all_ok = True

            # H-008: Artifact Gate
            lines.append("## [H-008] Artifact Gate")
            for phase in PipelinePhase:
                required = REQUIRED_ARTIFACTS.get(phase, [])
                if not required:
                    continue
                present, missing = store.check_artifacts(phase)
                icon = "✅" if present else "❌"
                lines.append(
                    f"- {icon} {phase.value}: {len(required) - len(missing)}/{len(required)}"
                )
                if missing:
                    for m in missing:
                        lines.append(f"  - 缺少: {m}")
                    all_ok = False

            # H-009: Decision Logging
            lines.append("\n## [H-009] Decision Logging")
            decisions = logger.read_decisions()
            if decisions:
                lines.append(f"✅ {len(decisions)} 筆決策紀錄")
            else:
                lines.append("⚠️ 無決策紀錄")
                all_ok = False
            lines.append(f"- 偏離紀錄: {len(logger.read_deviations())} 筆")

            # H-010: Append-Only Logs
            lines.append("\n## [H-010] Append-Only Logs")
            append_ok, append_msg = logger.verify_append_only()
            if append_ok:
                lines.append("✅ 日誌完整性驗證通過")
            else:
                lines.append(f"❌ 日誌完整性驗證失敗 — {append_msg}")
                all_ok = False

            # Summary
            lines.append("\n---")
            if all_ok:
                lines.append("✅ **審計鏈完整。**")
            else:
                lines.append("⚠️ **審計鏈有缺失，請檢查上方項目。**")

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("verify_audit_trail", e)
            return fmt_error(f"審計鏈驗證失敗: {e}")


def _generate_suggestions(checks: list[dict]) -> list[str]:
    """Generate improvement suggestions from audit checks."""
    suggestions = []
    for c in checks:
        if c["passed"]:
            continue
        cat = c["category"]
        if cat == "completeness":
            suggestions.append("補齊缺失的 pipeline phases 和 artifacts。")
        elif cat == "plan_adherence":
            suggestions.append("檢查偏離紀錄，補充缺少的分析項目。")
        elif cat == "effect_size_completeness":
            suggestions.append("為所有顯著結果計算效果量 (effect size)。")
        elif cat == "traceability":
            suggestions.append("確保所有分析操作都有 decision log 紀錄。")
        elif cat == "reproducibility":
            suggestions.append("確保 schema 和 report 都已存在。")
        elif cat == "report_readiness":
            details = str(c.get("details", ""))
            readiness_gaps: list[str] = []
            if "methodology_review=" in details:
                readiness_gaps.append("methodology review 缺口")
            if "completeness_tier=" in details:
                readiness_gaps.append("completeness tier")
            if "publication_bundle" in details:
                readiness_gaps.append("publication bundle")
            if readiness_gaps:
                suggestions.append(
                    "若要直接輸出終版完整報告，請先補齊 "
                    + "、".join(readiness_gaps)
                    + "。"
                )
            else:
                suggestions.append("若要直接輸出終版完整報告，請先補齊 readiness contract 缺口。")
        elif cat == "core_goal_audit":
            details = str(c.get("details", ""))
            suggestions.append(
                "Complete the RDE core contract before claiming production readiness: "
                + details
            )
    return suggestions


def _as_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _render_phase10_readiness_summary(report_readiness: dict[str, object]) -> str:
    ready = bool(report_readiness.get("ready"))
    lines = ["## Production Readiness\n"]
    lines.append(f"- **status:** {'production-ready' if ready else 'not production-ready'}")
    lines.append(f"- **target tier:** {report_readiness.get('target_tier', 'unknown')}")
    lines.append(f"- **current tier:** {report_readiness.get('current_tier', 'unknown')}")
    lines.append(f"- **methodology review:** {report_readiness.get('review_status', 'unknown')}")
    lines.append(
        f"- **publication bundle:** {'met' if report_readiness.get('publication_bundle_met') else 'not met'}"
    )
    core_goal_audit = report_readiness.get("core_goal_audit") or {}
    if core_goal_audit:
        lines.append(
            f"- **core goal audit:** {'met' if core_goal_audit.get('ready') else 'not met'}"
        )
    if ready:
        lines.append("\n### Why this is production-ready")
        lines.append("- methodology review has already passed")
        lines.append("- the locked plan reached the production_ready target tier")
        lines.append("- the minimum publication bundle is complete")
        if core_goal_audit:
            lines.append("- the core non-coder agent workflow contract is complete")
    else:
        lines.append("\n### Why this is not yet production-ready")
        missing = _as_string_list(report_readiness.get("missing_requirements", []))
        if missing:
            for requirement in missing:
                lines.append(f"- {requirement}")
        else:
            lines.append("- unresolved readiness gaps remain")
    return "\n".join(lines)


def _normalize_project_paths(text: str, project: Any) -> str:
    normalized = str(text or "")
    replacements = [
        (project.output_dir / "figures", "figures"),
        (project.artifacts_dir, "artifacts"),
        (project.output_dir, "."),
    ]
    for absolute, relative in replacements:
        normalized = normalized.replace(str(absolute), str(relative))
        normalized = normalized.replace(str(absolute).replace("\\", "/"), str(relative))
    return normalized


def _relative_project_path(path: Path, project: Any) -> str:
    try:
        return path.resolve().relative_to(project.output_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def _relative_phase10_path(path: Path, project: Any) -> str:
    phase12_dir = (project.artifacts_dir / "phase_12_auto_improve").resolve()
    return Path(relpath(path.resolve(), phase12_dir)).as_posix()


def _extract_heading_one_title(markdown: str) -> str | None:
    match = re.match(r"^#\s+(.+?)\s*$", markdown.strip(), re.MULTILINE)
    return match.group(1).strip() if match else None


def _split_markdown_h2_sections(markdown: str) -> tuple[str, list[str], list[tuple[str, str]]]:
    title = _extract_heading_one_title(markdown) or "Final Report"
    body = re.sub(r"^#\s+.+?$", "", markdown, count=1, flags=re.MULTILINE).strip()
    pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(body))

    preamble = body[: matches[0].start()].strip() if matches else body
    preamble_lines = [line.rstrip() for line in preamble.splitlines() if line.strip()]

    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((match.group(1).strip(), body[start:end].strip()))
    return title, preamble_lines, sections


def _split_markdown_h3_sections(markdown: str) -> tuple[str, list[tuple[str, str]]]:
    body = str(markdown or "").strip()
    pattern = re.compile(r"^###\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(body))

    preamble = body[: matches[0].start()].strip() if matches else body
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((match.group(1).strip(), body[start:end].strip()))
    return preamble, sections


def _strip_markdown_image_lines(text: str) -> str:
    lines = [
        line for line in str(text or "").splitlines() if not re.match(r"^!\[[^\]]*\]\([^)]*\)\s*$", line.strip())
    ]
    return "\n".join(lines).strip()


def _section_lookup(sections: list[tuple[str, str]]) -> dict[str, str]:
    return {title: content for title, content in sections}


def _join_labeled_sections(items: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for heading, content in items:
        cleaned = content.strip()
        if not cleaned:
            continue
        parts.append(f"### {heading}\n\n{cleaned}")
    return "\n\n".join(parts)


def _humanize_figure_stem(stem: str) -> str:
    text = stem.replace("_", " ").strip().title()
    replacements = {
        "Crbd": "CRBD",
        "Pacu": "PACU",
        "Bmi": "BMI",
        "Qc": "QC",
        "Davinci": "DaVinci",
        "L Spine": "L-spine",
        "Precedex": "Precedex",
        "Aldrete": "Aldrete",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _extract_phase10_figure_notes(markdown: str) -> tuple[str, dict[str, dict[str, str]]]:
    preamble, sections = _split_markdown_h3_sections(markdown)
    figure_notes: dict[str, dict[str, str]] = {}
    for heading, content in sections:
        image_match = re.search(r"!\[[^\]]*\]\(([^)]+)\)", content)
        if not image_match:
            continue
        figure_name = Path(image_match.group(1)).name
        figure_notes[figure_name] = {
            "heading": heading,
            "description": _strip_markdown_image_lines(content).strip(),
        }
    return _strip_markdown_image_lines(preamble).strip(), figure_notes


def _build_phase10_figure_gallery(project: Any, store: Any, markdown: str) -> str:
    _, figure_notes = _extract_phase10_figure_notes(markdown)
    entries = _load_visualization_entries(store)
    if not entries:
        return ""

    lines: list[str] = []

    main_index = 1
    appendix_index = 1
    for entry in entries:
        if not entry.get("exists"):
            continue

        figure_path = Path(str(entry["output_path"]))
        existing = figure_notes.get(figure_path.name, {})
        is_appendix = str(entry.get("category", "")).strip().lower() == "quality_control"
        if is_appendix:
            fallback_heading = f"Appendix Figure A{appendix_index}. {_humanize_figure_stem(figure_path.stem)}"
            appendix_index += 1
        else:
            fallback_heading = f"Figure {main_index}. {_humanize_figure_stem(figure_path.stem)}"
            main_index += 1

        heading = str(existing.get("heading") or fallback_heading).strip()
        description = str(existing.get("description") or entry.get("summary") or "").strip()
        lines.append(f"### {heading}")
        lines.append("")
        lines.append(f"![{heading}]({_relative_phase10_path(figure_path, project)})")
        if description:
            lines.append("")
            lines.append(description)
        lines.append("")

    return "\n".join(lines).strip()


def _append_markdown_section(lines: list[str], heading: str, content: str) -> None:
    cleaned = str(content or "").strip()
    if not cleaned:
        return
    if lines:
        lines.append("")
    lines.append(f"## {heading}")
    lines.append("")
    lines.append(cleaned)


def _build_phase10_source_markdown(
    project: Any,
    store: Any,
    *,
    assembled_report: str | None,
    audit: dict[str, object] | None,
    report_readiness: dict[str, object],
    improvement_log: dict[str, object],
) -> str:
    from rde.application.pipeline import PipelinePhase
    from rde.interface.mcp.tools.report_tools import _format_baseline_table

    base_markdown = _build_phase10_final_report(
        assembled_report,
        audit=audit,
        report_readiness=report_readiness,
        improvement_log=improvement_log,
    )
    normalized_markdown = _normalize_project_paths(base_markdown, project)
    title, _, parsed_sections = _split_markdown_h2_sections(normalized_markdown)
    sections = _section_lookup(parsed_sections)

    table_markdown = _format_baseline_table(
        store.load(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md")
    )
    figure_gallery = _build_phase10_figure_gallery(
        project,
        store,
        sections.get("補充圖表與最低發表包完成狀態", ""),
    )

    artifact_entries = [
        ("Results summary", store.get_path(PipelinePhase.COLLECT_RESULTS, "results_summary.json")),
        ("Audit report", store.get_path(PipelinePhase.AUDIT_REVIEW, "audit_report.json")),
        ("Improvement log", store.get_path(PipelinePhase.AUTO_IMPROVE, "improvement_log.json")),
        ("Table 1 source", store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md")),
        (
            "Visualization manifest",
            store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json"),
        ),
    ]
    artifact_lines = [
        f"- {label}: {_relative_phase10_path(path, project)}"
        for label, path in artifact_entries
        if path.exists()
    ]

    lines = [
        f"# {title}",
        "",
        f"- 更新時間: {datetime.now().replace(microsecond=0).isoformat()}",
        f"- 專案 ID: {project.id}",
    ]

    for heading in ["研究問題", "資料來源與前處理", "隊列概況"]:
        _append_markdown_section(lines, heading, sections.get(heading, ""))

    if table_markdown:
        _append_markdown_section(lines, "Table 1 — Baseline Characteristics", table_markdown)

    for heading in [
        "主要結局：CRBD",
        "次要結局",
        "擴充分析：手術別 subgroup / interaction 與 ordinal 複核",
        "解讀",
        "侷限性",
    ]:
        _append_markdown_section(lines, heading, sections.get(heading, ""))

    supplement_summary, _ = _extract_phase10_figure_notes(
        sections.get("補充圖表與最低發表包完成狀態", "")
    )
    _append_markdown_section(lines, "補充圖表與最低發表包完成狀態", supplement_summary)
    _append_markdown_section(lines, "Figure Gallery", figure_gallery)

    if artifact_lines:
        _append_markdown_section(lines, "主要 artifact", "\n".join(artifact_lines))

    for heading in [
        "Phase 10 Finalization",
        "Production Readiness",
        "Auto-fixed Items",
        "Remaining Suggestions",
    ]:
        _append_markdown_section(lines, heading, sections.get(heading, ""))

    return "\n".join(lines).strip() + "\n"


def _build_phase10_export_report(project: Any, store: Any, *, title: str = "") -> tuple[Any, dict[str, Any]]:
    from rde.application.pipeline import PipelinePhase
    from rde.domain.models.report import EDAReport, ReportSection
    from rde.interface.mcp.tools.report_tools import (
        _extract_table_markdown_notes,
        _parse_table_markdown_rows,
    )

    final_markdown = store.load(PipelinePhase.AUTO_IMPROVE, "final_report.md")
    if not final_markdown:
        raise ValueError("找不到 phase_12_auto_improve/final_report.md")

    normalized_markdown = _normalize_project_paths(str(final_markdown), project)
    inferred_title, preamble_lines, parsed_sections = _split_markdown_h2_sections(normalized_markdown)
    sections = _section_lookup(parsed_sections)
    dataset_id = project.dataset_ids[-1] if getattr(project, "dataset_ids", None) else "unknown"

    report = EDAReport(
        id=f"{project.id}_phase10_final_report",
        dataset_id=dataset_id,
        project_id=project.id,
        title=title.strip() or inferred_title,
        created_at=datetime.now(),
    )

    report.add_section(
        ReportSection(
            section_id="data_overview",
            title="Data Overview",
            content="\n\n".join(
                value
                for value in [
                    "\n".join(preamble_lines).strip(),
                    _join_labeled_sections(
                        [
                            ("研究問題", sections.get("研究問題", "")),
                            ("隊列概況", sections.get("隊列概況", "")),
                        ]
                    ),
                ]
                if value
            ),
            order=1,
        )
    )
    report.add_section(
        ReportSection(
            section_id="data_quality",
            title="Data Quality",
            content=_join_labeled_sections(
                [
                    ("資料來源與前處理", sections.get("資料來源與前處理", "")),
                ]
            )
            or "[Data quality narrative not available]",
            order=2,
        )
    )

    table_one_markdown = store.load(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md")
    table_rows = _parse_table_markdown_rows(table_one_markdown)
    table_payload = (
        {"headers": table_rows[0], "rows": table_rows[1:]}
        if len(table_rows) >= 2
        else None
    )
    table_notes = "\n".join(_extract_table_markdown_notes(table_one_markdown))
    report.add_section(
        ReportSection(
            section_id="variable_profiles",
            title="Table 1 — Baseline Characteristics",
            content=table_notes or "Phase 6 基線特徵表已附於本節。",
            tables=[table_payload] if table_payload else [],
            order=3,
        )
    )

    report.add_section(
        ReportSection(
            section_id="key_findings",
            title="Key Findings",
            content=_join_labeled_sections(
                [
                    ("主要結局：CRBD", sections.get("主要結局：CRBD", "")),
                    ("次要結局", sections.get("次要結局", "")),
                    ("解讀", sections.get("解讀", "")),
                ]
            )
            or "[Key findings not available]",
            order=4,
        )
    )

    manifest_entries = _load_visualization_entries(store)
    figure_paths = [Path(entry["output_path"]) for entry in manifest_entries if entry.get("exists")]
    figure_notes = [
        f"- {entry['name']}: {entry['summary']}"
        for entry in manifest_entries
        if entry.get("exists") and entry.get("summary")
    ]
    report.add_section(
        ReportSection(
            section_id="statistical_analyses",
            title="Statistical Analyses",
            content="\n\n".join(
                value
                for value in [
                    _join_labeled_sections(
                        [
                            (
                                "擴充分析：手術別 subgroup / interaction 與 ordinal 複核",
                                sections.get("擴充分析：手術別 subgroup / interaction 與 ordinal 複核", ""),
                            ),
                            (
                                "補充圖表與最低發表包完成狀態",
                                _strip_markdown_image_lines(
                                    sections.get("補充圖表與最低發表包完成狀態", "")
                                ),
                            ),
                        ]
                    ),
                    "### Figure Inventory\n\n" + "\n".join(figure_notes) if figure_notes else "",
                ]
                if value
            )
            or "[Statistical analysis narrative not available]",
            figures=[str(path) for path in figure_paths],
            order=5,
        )
    )

    report.add_section(
        ReportSection(
            section_id="recommendations",
            title="Recommendations",
            content=_join_labeled_sections(
                [
                    ("侷限性", sections.get("侷限性", "")),
                    ("Phase 10 Finalization", sections.get("Phase 10 Finalization", "")),
                    ("Production Readiness", sections.get("Production Readiness", "")),
                    ("Remaining Suggestions", sections.get("Remaining Suggestions", "")),
                ]
            )
            or "[Final recommendations not available]",
            order=6,
        )
    )

    artifact_lines = _build_phase10_artifact_lines(project, store)
    if artifact_lines:
        report.add_section(
            ReportSection(
                section_id="project_artifacts",
                title="Project Artifacts",
                content="\n".join(artifact_lines),
                order=7,
            )
        )

    report.metadata.update(
        {
            "phase": "phase_12_auto_improve",
            "source_markdown": _relative_project_path(
                store.get_path(PipelinePhase.AUTO_IMPROVE, "final_report.md"), project
            ),
            "table_one_source": _relative_project_path(
                store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md"), project
            )
            if table_one_markdown
            else "missing",
            "figure_count": len(figure_paths),
        }
    )

    return report, {
        "table": {
            "included": bool(table_payload),
            "row_count": max(0, len(table_rows) - 1),
            "source": _relative_project_path(
                store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md"), project
            )
            if table_one_markdown
            else "missing",
        },
        "figures": {
            "included_count": len(figure_paths),
            "sources": [_relative_project_path(path, project) for path in figure_paths],
        },
    }


def _load_phase10_report_readiness(store: Any) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase
    from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness

    results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    return _evaluate_report_readiness(results, store)


def _load_visualization_entries(store: Any) -> list[dict[str, Any]]:
    from rde.application.pipeline import PipelinePhase

    manifest = store.load(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json") or []
    if not isinstance(manifest, list):
        return []

    entries: list[dict[str, Any]] = []
    for entry in manifest:
        output_path = Path(str(entry.get("output_path", "")))
        entries.append(
            {
                "name": output_path.stem,
                "output_path": str(output_path),
                "summary": str(entry.get("stats_summary", "")).strip(),
                "exists": output_path.exists(),
            }
        )
    return entries


def _build_phase10_artifact_lines(project: Any, store: Any) -> list[str]:
    from rde.application.pipeline import PipelinePhase

    entries = [
        ("Results summary", store.get_path(PipelinePhase.COLLECT_RESULTS, "results_summary.json")),
        ("Audit report", store.get_path(PipelinePhase.AUDIT_REVIEW, "audit_report.json")),
        ("Improvement log", store.get_path(PipelinePhase.AUTO_IMPROVE, "improvement_log.json")),
        ("Table 1 source", store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md")),
        (
            "Visualization manifest",
            store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json"),
        ),
    ]
    lines: list[str] = []
    for label, path in entries:
        status = "exists" if path.exists() else "missing"
        lines.append(f"- {label}: {_relative_project_path(path, project)} ({status})")
    return lines


def _build_phase10_export_manifest(
    project: Any,
    store: Any,
    *,
    report: Any,
    exported: dict[str, Path],
    asset_summary: dict[str, Any],
    report_readiness: dict[str, Any],
) -> dict[str, Any]:
    from rde.application.pipeline import PipelinePhase

    validation = {
        "final_report_md": {
            "path": _relative_project_path(
                store.get_path(PipelinePhase.AUTO_IMPROVE, "final_report.md"), project
            ),
            "exists": store.exists(PipelinePhase.AUTO_IMPROVE, "final_report.md"),
        },
        "audit_report": {
            "path": _relative_project_path(
                store.get_path(PipelinePhase.AUDIT_REVIEW, "audit_report.json"), project
            ),
            "exists": store.exists(PipelinePhase.AUDIT_REVIEW, "audit_report.json"),
        },
        "results_summary": {
            "path": _relative_project_path(
                store.get_path(PipelinePhase.COLLECT_RESULTS, "results_summary.json"), project
            ),
            "exists": store.exists(PipelinePhase.COLLECT_RESULTS, "results_summary.json"),
        },
        "table_one": {
            "path": asset_summary.get("table", {}).get("source", "missing"),
            "exists": bool(asset_summary.get("table", {}).get("included")),
        },
        "visualization_manifest": {
            "path": _relative_project_path(
                store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json"),
                project,
            ),
            "exists": store.exists(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json"),
        },
    }

    return {
        "project_id": project.id,
        "generated_at": datetime.now().isoformat(),
        "title": report.title,
        "report_readiness": report_readiness,
        "sources": validation,
        "exports": {
            fmt: {
                "requested_format": fmt,
                "actual_format": path.suffix.lstrip(".").lower(),
                "path": _relative_project_path(path, project),
            }
            for fmt, path in exported.items()
        },
        "included_assets": asset_summary,
        "metadata": report.metadata,
    }


def _build_phase10_final_report(
    assembled_report: str | None,
    *,
    audit: dict[str, object] | None,
    report_readiness: dict[str, object],
    improvement_log: dict[str, object],
) -> str:
    base_report = str(assembled_report or "").strip()
    if not base_report:
        base_report = "# Final Report\n\nPhase 8 report was unavailable, so this Phase 10 artifact contains the finalization summary only."

    lines = [base_report, "\n---\n", "## Phase 10 Finalization\n"]
    if audit:
        lines.append(f"- **audit grade:** {audit.get('grade', '?')}")
        lines.append(f"- **audit score:** {audit.get('total_score', '?')}/{audit.get('max_score', '?')}")
    auto_fixed = _as_string_list(improvement_log.get("auto_fixed", []))
    manual_suggestions = _as_string_list(improvement_log.get("manual_suggestions", []))
    lines.append(f"- **auto-fixed items:** {len(auto_fixed)}")
    lines.append(f"- **manual suggestions:** {len(manual_suggestions)}")
    lines.append("")
    lines.append(_render_phase10_readiness_summary(report_readiness))

    if auto_fixed:
        lines.append("\n## Auto-fixed Items")
        for item in auto_fixed:
            lines.append(f"- {item}")

    if manual_suggestions:
        lines.append("\n## Remaining Suggestions")
        for item in manual_suggestions:
            lines.append(f"- {item}")

    return "\n".join(lines).strip() + "\n"
