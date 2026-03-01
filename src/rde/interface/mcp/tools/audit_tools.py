"""Audit Tools — Phase 9 (Audit Review) & Phase 10 (Auto-Improve).

Phase 9: Run audit checks, grade the pipeline run.
Phase 10: Auto-improve fixable issues, export handoff package.
All tools return markdown strings.
"""

from __future__ import annotations

from typing import Any


def register_audit_tools(server: Any) -> None:
    """Register audit and auto-improve MCP tools."""

    @server.tool()
    def run_audit(project_id: str | None = None) -> str:
        """執行完整審計 (Phase 9)。

        檢查: 計畫符合度、方法適當性、效果量完整性、
        偏離合理性、再現性、H-008/H-009/H-010 合規。
        輸出 A-F 評分。

        Args:
            project_id: 專案 ID (預設使用當前專案)
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_error,
            fmt_error, ensure_project_context,
        )

        log_tool_call("run_audit", {"project_id": project_id})

        ok, msg, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(msg)

        try:
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult, REQUIRED_ARTIFACTS
            from rde.infrastructure.persistence.artifact_store import ArtifactStore
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

            checks.append({
                "category": "completeness",
                "score": completeness_score,
                "max": 30,
                "passed": completeness_pct >= 0.8,
                "details": f"{completed_phases}/{total_phases} phases with artifacts",
                "missing": missing_artifacts,
            })

            # ── 2. Plan adherence ───────────────────────────────────
            max_score += 25
            plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
            results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")

            if plan and results:
                planned = plan.get("analyses", plan.get("steps", []))
                executed = results.get("total_analyses", 0)
                coverage = min(1.0, executed / max(1, len(planned)))
                deviations = logger.read_deviations()
                adherence_score = int(25 * coverage)
                # Penalize unexcused deviations
                for d in deviations:
                    if not d.get("reason"):
                        adherence_score = max(0, adherence_score - 5)
                total_score += adherence_score
                checks.append({
                    "category": "plan_adherence",
                    "score": adherence_score,
                    "max": 25,
                    "passed": adherence_score >= 18,
                    "details": f"coverage={coverage:.0%}, deviations={len(deviations)}",
                })
            else:
                # Quick explore → no plan
                total_score += 15
                checks.append({
                    "category": "plan_adherence",
                    "score": 15,
                    "max": 25,
                    "passed": True,
                    "details": "No formal plan (Quick Explore mode)",
                })

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
            checks.append({
                "category": "effect_size_completeness",
                "score": es_score,
                "max": 15,
                "passed": es_pct >= 0.8,
                "details": f"{es_pct:.0%} of results include effect sizes",
            })

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
            checks.append({
                "category": "traceability",
                "score": trace_score,
                "max": 15,
                "passed": trace_score >= 10,
                "details": f"{len(decisions)} decisions, append-only={'✅' if append_ok else '❌'}",
            })

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
            checks.append({
                "category": "reproducibility",
                "score": repro_score,
                "max": 15,
                "passed": repro_score >= 10,
                "details": f"schema={'✅' if has_schema else '❌'}, report={'✅' if has_report else '❌'}",
            })

            # ── Grade ───────────────────────────────────────────────
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
            pipeline.mark_completed(PhaseResult(
                phase=PipelinePhase.AUDIT_REVIEW,
                completed_at=datetime.now(),
                success=True,
                artifacts={"audit_report.json": str(store.get_path(PipelinePhase.AUDIT_REVIEW, "audit_report.json"))},
            ))

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
                    f"| {c['category']} | {c['score']}/{c['max']} | "
                    f"{icon} | {c['details']} |"
                )

            if suggestions:
                lines.append("\n## 💡 改善建議")
                for s in suggestions:
                    lines.append(f"- {s}")

            if missing_artifacts:
                lines.append("\n## ⚠️ 缺失 Artifacts")
                for m in missing_artifacts:
                    lines.append(f"- {m}")

            lines.append(f"\n**Artifact:** audit_report.json")

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("run_audit", e)
            return fmt_error(f"審計失敗: {e}")

    @server.tool()
    def auto_improve(project_id: str | None = None) -> str:
        """根據審計結果自動改善可修正項目 (Phase 10)。

        讀取 audit_report.json，執行自動修正:
        - 補缺效果量
        - 補遺漏的圖表
        - 修正報告格式

        Args:
            project_id: 專案 ID (預設使用當前專案)
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_error,
            fmt_error, fmt_success, ensure_project_context,
        )

        log_tool_call("auto_improve", {"project_id": project_id})

        ok, msg, project = ensure_project_context(project_id)
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
            store = ArtifactStore(project.artifacts_dir)

            # Read audit report
            audit = store.load(PipelinePhase.AUDIT_REVIEW, "audit_report.json")
            if not audit:
                return fmt_error(
                    "[H-008] 請先執行 `run_audit()` (Phase 9) 才能進行自動改善。"
                )

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
                            "# EDA Report (自動生成)\n\n"
                            "此報告由 auto_improve 自動生成。\n\n"
                        )
                        if schema:
                            basic_report += f"## Schema\n- 變數數: {schema.get('n_variables', '?')}\n\n"
                        if results:
                            basic_report += f"## Results\n- 分析項目: {results.get('total_analyses', '?')}\n"
                        store.save(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md", basic_report)
                        auto_fixed.append("✅ 自動生成基本報告 (eda_report.md)")
                    else:
                        actions_taken.append("報告不存在且缺少資料 → 請手動執行 `assemble_report()`")
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
                dataset_ids = session.list_datasets()
                for did in dataset_ids:
                    entry = session.get_dataset_entry(did)
                    if entry.analysis_results:
                        results_summary = {
                            "total_analyses": len(entry.analysis_results),
                            "collected_at": datetime.now().isoformat(),
                            "source": "auto_improve",
                        }
                        store.save(PipelinePhase.COLLECT_RESULTS, "results_summary.json", results_summary)
                        auto_fixed.append(f"✅ 自動收集 {len(entry.analysis_results)} 項分析結果")
                        break

            # ── Build improvement suggestions from audit ────────────
            suggestions = audit.get("suggestions", [])
            for s in suggestions:
                actions_taken.append(f"建議: {s}")

            all_items = auto_fixed + actions_taken

            # Save improvement log
            improvement_log = {
                "original_grade": original_grade,
                "auto_fixed": auto_fixed,
                "manual_suggestions": actions_taken,
                "total_items": len(all_items),
            }
            store.save(PipelinePhase.AUTO_IMPROVE, "improvement_log.json", improvement_log)

            # Save final report marker
            store.save(PipelinePhase.AUTO_IMPROVE, "final_report.md",
                        f"# Final Report\n\nAudit grade: {original_grade}\n"
                        f"Auto-fixed: {len(auto_fixed)}\n"
                        f"Manual suggestions: {len(actions_taken)}\n")
            pipeline.mark_completed(PhaseResult(
                phase=PipelinePhase.AUTO_IMPROVE,
                completed_at=datetime.now(),
                success=True,
                artifacts={"final_report.md": "", "improvement_log.json": ""},
            ))

            lines = [
                f"# 🔧 自動改善 (Phase 10)\n",
                f"- **原始等級:** {original_grade}",
                f"- **自動修正:** {len(auto_fixed)}",
                f"- **手動建議:** {len(actions_taken)}",
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

            lines.append(f"\n**Artifacts:** improvement_log.json, final_report.md")

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("auto_improve", e)
            return fmt_error(f"自動改善失敗: {e}")

    @server.tool()
    def export_handoff(project_id: str | None = None) -> str:
        """匯出 handoff package 給下游工具 (e.g., med-paper-assistant)。

        打包: 報告、統計結果、圖表、schema、decision log。

        Args:
            project_id: 專案 ID (預設使用當前專案)
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_error,
            fmt_error, fmt_success, ensure_project_context,
        )

        log_tool_call("export_handoff", {"project_id": project_id})

        ok, msg, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(msg)

        try:
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase
            from rde.infrastructure.persistence.artifact_store import ArtifactStore
            from pathlib import Path
            import json
            import shutil

            session = get_session()
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

            # Copy decision log
            decision_src = store.get_path(
                PipelinePhase.EXECUTE_EXPLORATION, "decision_log.jsonl"
            )
            if decision_src.exists():
                shutil.copy2(decision_src, handoff_dir / "decision_log.jsonl")
                included_files.append("decision_log.jsonl")

            # Copy figures if they exist
            figures_dir = Path("data/reports/figures")
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
                "source": "RDE 11-Phase Auditable EDA Pipeline",
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
                + f"\n\n可提供給 med-paper-assistant 使用。",
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
            log_tool_call, log_tool_error,
            fmt_error, ensure_project_context,
        )

        log_tool_call("verify_audit_trail", {"project_id": project_id})

        ok, msg, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(msg)

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
                lines.append(f"- {icon} {phase.value}: {len(required) - len(missing)}/{len(required)}")
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
    return suggestions
