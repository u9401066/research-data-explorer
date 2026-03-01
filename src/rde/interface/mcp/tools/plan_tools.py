"""Plan Tools — Phase 3 (Concept Alignment), Phase 4 (Plan Registration), Phase 5 (Pre-check).

All tools return markdown strings.
"""

from __future__ import annotations

from typing import Any


def register_plan_tools(server: Any) -> None:
    """Register planning and pre-registration MCP tools."""

    @server.tool()
    def align_concept(
        project_id: str | None = None,
        research_question: str = "",
        variable_roles: dict[str, str | list[str]] | None = None,
    ) -> str:
        """對齊研究概念與資料 schema（Phase 3）。

        將研究問題對應到實際變數，確認 outcome/predictor/confounder 角色。
        ⚠️ 需要用戶確認後才能進入 Phase 4。

        Args:
            project_id: 專案 ID
            research_question: 研究問題
            variable_roles: 變數角色指定，例:
                {"outcome": "mortality", "group": "treatment",
                 "covariates": ["age", "sex"]}
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_result, log_tool_error,
            fmt_error, fmt_table, ensure_project_context,
        )

        log_tool_call("align_concept", {
            "research_question": research_question,
            "variable_roles": variable_roles,
        })

        ok, msg, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(msg)

        try:
            from datetime import datetime
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult
            from rde.domain.models.variable import VariableRole
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            session = get_session()

            if research_question:
                project.research_question = research_question

            dataset_ids = session.list_datasets()
            if not dataset_ids:
                return fmt_error("尚未載入任何資料集。請先使用 `load_dataset()` 或 `run_intake()`。")

            entry = session.get_dataset_entry(dataset_ids[0])
            ds = entry.dataset
            available_vars = {v.name: v for v in ds.variables}

            role_assignments: dict[str, str] = {}
            if variable_roles:
                for role_key, var_names_raw in variable_roles.items():
                    names_list = [var_names_raw] if isinstance(var_names_raw, str) else var_names_raw
                    for vn in names_list:
                        if vn in available_vars:
                            try:
                                role_enum = VariableRole(role_key)
                            except ValueError:
                                role_enum = VariableRole.UNASSIGNED
                            available_vars[vn].role = role_enum
                            role_assignments[vn] = role_key

            analyzable = sum(1 for v in ds.variables if v.is_analyzable())
            unassigned = [
                v.name for v in ds.variables
                if v.role == VariableRole.UNASSIGNED and v.is_analyzable()
            ]
            pii_suspects = [v.name for v in ds.variables if v.is_pii_suspect]

            # Save artifacts
            alignment = {
                "research_question": project.research_question,
                "dataset": ds.id,
                "total_variables": len(ds.variables),
                "analyzable_variables": analyzable,
                "variable_roles": role_assignments,
                "unassigned": unassigned,
                "pii_suspects": pii_suspects,
            }

            store = ArtifactStore(project.artifacts_dir)
            store.save(PipelinePhase.CONCEPT_ALIGNMENT, "concept_alignment.md",
                        f"# Concept Alignment\n\n"
                        f"## Research Question\n{project.research_question}\n\n"
                        f"## Variable Roles\n{role_assignments}\n")
            store.save(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json", alignment)

            pipeline = session.get_pipeline(project.id)
            pipeline.mark_started(PipelinePhase.CONCEPT_ALIGNMENT)
            pipeline.mark_completed(PhaseResult(
                phase=PipelinePhase.CONCEPT_ALIGNMENT,
                completed_at=datetime.now(),
                success=True,
                artifacts={"concept_alignment.md": "", "variable_roles.json": ""},
                user_confirmed=False,
            ))

            # Build variable table
            headers = ["變數", "類型", "角色", "可分析"]
            rows = [
                [v.name, v.variable_type.value, v.role.value,
                 "✅" if v.is_analyzable() else "❌"]
                for v in ds.variables
            ]
            table = fmt_table(headers, rows)

            assigned_text = ""
            if role_assignments:
                assigned_text = "\n**已指定角色:**\n" + "\n".join(
                    f"- {var} → {role}" for var, role in role_assignments.items()
                )

            unassigned_text = ""
            if unassigned:
                unassigned_text = f"\n**未指定角色:** {', '.join(unassigned)}\n"

            log_tool_result("align_concept", f"{analyzable} analyzable, {len(role_assignments)} assigned")

            return (
                f"# 🔬 概念對齊 (Phase 3)\n\n"
                f"- **研究問題:** {project.research_question or '(未指定)'}\n"
                f"- **資料集:** `{ds.id}`\n"
                f"- **可分析變數:** {analyzable} / {len(ds.variables)}\n"
                f"{assigned_text}{unassigned_text}\n"
                f"{table}\n\n"
                f"⚠️ **請確認變數角色分配是否正確，再進入 Phase 4。**"
            )

        except Exception as e:
            log_tool_error("align_concept", e)
            return fmt_error(f"概念對齊失敗: {e}")

    @server.tool()
    def register_analysis_plan(
        project_id: str | None = None,
        analyses: list[dict[str, Any]] | None = None,
        alpha: float = 0.05,
        missing_strategy: str = "listwise",
        multiple_comparison_method: str = "bonferroni",
    ) -> str:
        """註冊分析計畫（Phase 4 — Pre-registration）。

        ⚠️ 完成後計畫將被鎖定 (H-007)，後續偏離必須使用 log_deviation() 記錄。

        Args:
            project_id: 專案 ID
            analyses: 計畫清單，每項含 type/variables/rationale
            alpha: 顯著水準（預設 0.05）
            missing_strategy: 缺失值策略 (listwise/pairwise/impute_median)
            multiple_comparison_method: 多重比較校正 (bonferroni/fdr)
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_result, log_tool_error,
            fmt_error, ensure_project_context,
        )

        log_tool_call("register_analysis_plan", {
            "alpha": alpha, "missing_strategy": missing_strategy,
        })

        ok, msg, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(msg)

        try:
            from datetime import datetime
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            session = get_session()
            pipeline = session.get_pipeline(project.id)

            if pipeline.plan_locked:
                return fmt_error(
                    "分析計畫已鎖定 (H-007)，無法修改。",
                    suggestion="偏離計畫請使用 `log_deviation()`。",
                )

            if not analyses:
                analyses = []

            plan = {
                "project_id": project.id,
                "research_question": project.research_question,
                "alpha": alpha,
                "missing_strategy": missing_strategy,
                "multiple_comparison_method": multiple_comparison_method,
                "analyses": analyses,
                "created_at": datetime.now().isoformat(),
                "locked": True,
            }

            store = ArtifactStore(project.artifacts_dir)
            store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)

            pipeline.mark_started(PipelinePhase.PLAN_REGISTRATION)
            pipeline.mark_completed(PhaseResult(
                phase=PipelinePhase.PLAN_REGISTRATION,
                completed_at=datetime.now(),
                success=True,
                artifacts={"analysis_plan.yaml": ""},
                user_confirmed=True,
            ))
            project.plan_locked = True

            analyses_text = ""
            if analyses:
                analyses_text = "\n**計畫分析項目:**\n"
                for i, a in enumerate(analyses, 1):
                    analyses_text += f"{i}. **{a.get('type', '')}** — {a.get('rationale', '')}\n"
                    if a.get('variables'):
                        analyses_text += f"   變數: {a['variables']}\n"

            log_tool_result("register_analysis_plan", f"{len(analyses)} analyses, locked")

            return (
                f"🔒 分析計畫已鎖定 (Phase 4)\n\n"
                f"- **顯著水準 (α):** {alpha}\n"
                f"- **缺失值策略:** {missing_strategy}\n"
                f"- **多重比較校正:** {multiple_comparison_method}\n"
                f"- **分析項目數:** {len(analyses)}\n"
                f"{analyses_text}\n"
                f"⚠️ Phase 6+ 操作偏離此計畫時，必須呼叫 `log_deviation()` 記錄。\n\n"
                f"**下一步:** 使用 `check_readiness()` 執行準備度檢查 (Phase 5)。"
            )

        except Exception as e:
            log_tool_error("register_analysis_plan", e)
            return fmt_error(f"計畫註冊失敗: {e}")

    @server.tool()
    def check_readiness(project_id: str | None = None) -> str:
        """執行探索前準備度檢查（Phase 5）。

        驗證 H-003 (樣本量), H-004 (PII), H-007 (計畫鎖定),
        H-008 (artifact gate), S-001 (常態性提醒)。

        Args:
            project_id: 專案 ID
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_result, log_tool_error,
            fmt_error, ensure_project_context,
        )
        from rde.interface.mcp.tools._shared.formatting import fmt_checks

        log_tool_call("check_readiness", {"project_id": project_id})

        ok, msg, project = ensure_project_context(project_id)
        if not ok:
            return fmt_error(msg)

        try:
            from datetime import datetime
            from rde.application.session import get_session
            from rde.application.pipeline import (
                PipelinePhase, PhaseResult, REQUIRED_ARTIFACTS,
            )
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            session = get_session()
            pipeline = session.get_pipeline(project.id)
            store = ArtifactStore(project.artifacts_dir)

            checks: list[dict[str, Any]] = []
            all_passed = True

            # H-003: Min sample size
            dataset_ids = session.list_datasets()
            if dataset_ids:
                entry = session.get_dataset_entry(dataset_ids[0])
                n = entry.dataset.row_count
                passed = n >= 10
                checks.append({
                    "id": "H-003", "name": "最小樣本量",
                    "passed": passed,
                    "detail": f"n = {n}" + ("" if passed else " (需 ≥ 10)"),
                })
                if not passed:
                    all_passed = False
            else:
                checks.append({"id": "H-003", "name": "最小樣本量", "passed": False, "detail": "無資料集"})
                all_passed = False

            # H-004: PII check
            pii_vars = []
            if dataset_ids:
                entry = session.get_dataset_entry(dataset_ids[0])
                pii_vars = [v.name for v in entry.dataset.variables if v.is_pii_suspect]
            checks.append({
                "id": "H-004", "name": "PII 偵測",
                "passed": len(pii_vars) == 0,
                "detail": f"疑似 PII: {pii_vars}" if pii_vars else "無 PII",
            })
            if pii_vars:
                all_passed = False

            # H-007: Plan locked
            checks.append({
                "id": "H-007", "name": "分析計畫已鎖定",
                "passed": pipeline.plan_locked,
                "detail": "已鎖定" if pipeline.plan_locked else "未鎖定",
            })
            if not pipeline.plan_locked:
                all_passed = False

            # H-008: Artifact gate
            prereq_phases = [
                PipelinePhase.PROJECT_SETUP,
                PipelinePhase.DATA_INTAKE,
                PipelinePhase.SCHEMA_REGISTRY,
                PipelinePhase.CONCEPT_ALIGNMENT,
                PipelinePhase.PLAN_REGISTRATION,
            ]
            for phase in prereq_phases:
                required = REQUIRED_ARTIFACTS.get(phase, [])
                missing = [f for f in required if not store.exists(phase, f)]
                passed = len(missing) == 0
                checks.append({
                    "id": "H-008",
                    "name": f"Artifact Gate: {phase.value}",
                    "passed": passed,
                    "detail": f"缺少: {missing}" if missing else "完整",
                })
                if not passed:
                    all_passed = False

            # S-001: Normality hint
            if dataset_ids:
                entry = session.get_dataset_entry(dataset_ids[0])
                continuous = [
                    v.name for v in entry.dataset.variables
                    if v.variable_type.value == "continuous"
                ]
                checks.append({
                    "id": "S-001", "name": "常態性檢定提醒",
                    "passed": True,
                    "detail": f"有 {len(continuous)} 個連續變數，建議執行常態性檢定",
                })

            # S-005: Missing pattern analysis
            if dataset_ids:
                entry = session.get_dataset_entry(dataset_ids[0])
                df = entry.dataframe
                missing_cols = [
                    c for c in df.columns if df[c].isna().sum() > 0
                ]
                if missing_cols:
                    try:
                        from rde.infrastructure.adapters import ScipyStatisticalEngine
                        engine = ScipyStatisticalEngine()
                        mp = engine.analyze_missing_patterns(df, missing_cols)
                        pattern = mp.get("pattern", "unknown")
                        rec = mp.get("recommendation", "")
                        checks.append({
                            "id": "S-005", "name": "缺失模式分析",
                            "passed": True,
                            "detail": f"模式: {pattern}，建議: {rec}",
                        })
                    except Exception:
                        checks.append({
                            "id": "S-005", "name": "缺失模式分析",
                            "passed": True,
                            "detail": f"{len(missing_cols)} 個變數有缺失值",
                        })
                else:
                    checks.append({
                        "id": "S-005", "name": "缺失模式分析",
                        "passed": True,
                        "detail": "無缺失值",
                    })

            # S-007: Collinearity check (VIF preview)
            if dataset_ids:
                entry = session.get_dataset_entry(dataset_ids[0])
                df = entry.dataframe
                from rde.domain.services.collinearity_checker import check_collinearity
                report = check_collinearity(df)
                if report.has_collinearity:
                    checks.append({
                        "id": "S-007", "name": "共線性預檢",
                        "passed": True,
                        "detail": f"⚠️ 高相關: {', '.join(report.format_warnings())}",
                    })
                else:
                    checks.append({
                        "id": "S-007", "name": "共線性預檢",
                        "passed": True,
                        "detail": "無明顯共線性",
                    })

            # Save artifact
            checklist = {
                "project_id": project.id,
                "all_passed": all_passed,
                "checks": checks,
                "checked_at": datetime.now().isoformat(),
            }
            store.save(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json", checklist)

            pipeline.mark_started(PipelinePhase.PRE_EXPLORE_CHECK)
            pipeline.mark_completed(PhaseResult(
                phase=PipelinePhase.PRE_EXPLORE_CHECK,
                completed_at=datetime.now(),
                success=all_passed,
                artifacts={"readiness_checklist.json": ""},
            ))

            checks_text = fmt_checks(checks)

            log_tool_result("check_readiness", f"passed={all_passed}")

            status = "✅ 準備就緒，可進入 Phase 6" if all_passed else "❌ 尚有未通過的檢查項目"

            return (
                f"# 🔍 準備度檢查 (Phase 5)\n\n"
                f"{checks_text}\n\n"
                f"**結果:** {status}"
            )

        except Exception as e:
            log_tool_error("check_readiness", e)
            return fmt_error(f"準備度檢查失敗: {e}")
