"""Plan Tools — Phase 3 (Concept Alignment), Phase 4 (Plan Registration), Phase 5 (Pre-check).

All tools return markdown strings.
"""

from __future__ import annotations

import json
from typing import Any


def _normalized_plan_family(entry: dict[str, Any]) -> str | None:
    entry_type = str(entry.get("type", "")).strip()
    if not entry_type:
        return None
    normalized = entry_type.lower().replace("-", "_").replace(" ", "_")
    if normalized == "run_advanced_analysis":
        analysis_type = str(entry.get("analysis_type", "")).strip()
        if analysis_type:
            normalized = analysis_type.lower().replace("-", "_").replace(" ", "_")
    alias_map = {
        "descriptive": "analyze_variable",
        "univariate": "analyze_variable",
        "table_one": "generate_table_one",
    }
    return alias_map.get(normalized, normalized)


def _merge_methodology_expansion(
    analyses: list[dict[str, Any]],
    proposal_blueprint: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    merged = [dict(entry) for entry in analyses if isinstance(entry, dict)]
    existing_families = {
        family
        for entry in merged
        for family in [_normalized_plan_family(entry)]
        if family is not None
    }
    existing_visualizations = {
        (
            str(entry.get("plot_type", "")).lower(),
            tuple(str(value) for value in entry.get("variables", [])),
            str(entry.get("group_variable")) if entry.get("group_variable") is not None else None,
        )
        for entry in merged
        if str(entry.get("type", "")).lower() == "visualization"
    }
    added_labels: list[str] = []

    for entry in proposal_blueprint:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("type", "")).lower() == "visualization":
            viz_key = (
                str(entry.get("plot_type", "")).lower(),
                tuple(str(value) for value in entry.get("variables", [])),
                str(entry.get("group_variable")) if entry.get("group_variable") is not None else None,
            )
            if viz_key in existing_visualizations:
                continue
            new_entry = dict(entry)
            new_entry.setdefault("required", False)
            new_entry.setdefault("origin", "methodology_expansion")
            merged.append(new_entry)
            existing_visualizations.add(viz_key)
            added_labels.append(f"visualization:{new_entry.get('plot_type', 'plot')}")
            continue
        family = _normalized_plan_family(entry)
        if family is None or family in existing_families:
            continue
        new_entry = dict(entry)
        new_entry.setdefault("required", False)
        new_entry.setdefault("origin", "methodology_expansion")
        merged.append(new_entry)
        existing_families.add(family)
        added_labels.append(family)

    return merged, added_labels


def _render_greedy_plan_markdown(
    proposal: dict[str, Any],
    *,
    artifact_json: str,
    artifact_md: str,
    plan_locked: bool,
    review_json: str | None = None,
    review_md: str | None = None,
    schedule_json: str | None = None,
    schedule_md: str | None = None,
    enrich_json: str | None = None,
    enrich_md: str | None = None,
    script_path: str | None = None,
) -> str:
    draft_selected = proposal.get("draft_selected", [])
    selected = proposal.get("selected", [])
    schedule = proposal.get("execution_schedule", [])
    enrichment_rounds = proposal.get("enrichment_rounds", [])
    review = proposal.get("review") or {}
    warnings = proposal.get("warnings", [])
    coverage = proposal.get("coverage_tags", [])
    lines = ["# 🧭 Greedy Autonomous EDA Proposal (Phase 3.5)\n"]
    lines.append(f"- **策略:** {proposal.get('strategy', 'greedy_coverage_under_budget')}")
    lines.append(f"- **資料集:** `{proposal.get('dataset_id', '')}`")
    lines.append(f"- **研究問題:** {proposal.get('research_question') or '(未指定)'}")
    lines.append(f"- **候選池大小:** {proposal.get('candidate_pool_size', 0)}")
    lines.append(f"- **draft 分析數:** {len(draft_selected)}")
    lines.append(f"- **選入分析數:** {len(selected)}")
    lines.append(f"- **涵蓋面向:** {', '.join(coverage) if coverage else '(無)'}")
    if review:
        lines.append(f"- **內部 review 狀態:** {review.get('status', 'unknown')}")
        lines.append(
            f"- **方法學最低建議分析數:** {review.get('recommended_analysis_floor', len(selected))}"
        )
        lines.append(
            f"- **學術級目標分析數:** {review.get('academic_analysis_target', review.get('recommended_analysis_floor', len(selected)))}"
        )
        lines.append(
            f"- **production 級目標分析數:** {review.get('production_analysis_target', review.get('academic_analysis_target', review.get('recommended_analysis_floor', len(selected))))}"
        )
        lines.append(f"- **目前完整度 tier:** {review.get('completeness_tier', 'unknown')}")
        lines.append(
            f"- **初始 budget / soft budget:** {review.get('requested_analysis_budget', len(draft_selected))} / {review.get('soft_analysis_budget', len(selected))}"
        )

    if plan_locked:
        lines.append(
            "\n⚠️ **目前計畫已鎖定。以下內容僅能作為偏離評估或下一輪分析草案，不能直接覆蓋既有 plan。**"
        )

    if warnings:
        lines.append("\n## 注意事項")
        for warning in warnings:
            lines.append(f"- {warning}")

    if review:
        lines.append("\n## 內部 Review / Repair")
        signals = review.get("complexity_signals", {})
        if signals:
            lines.append(f"- **complexity signals:** {signals}")
        checks = review.get("checks", [])
        if checks:
            lines.append("- **方法學檢查:**")
            for check in checks:
                lines.append(
                    f"  - [{check.get('status', 'unknown')}] {check.get('name')}: {check.get('detail')}"
                )
        repair_actions = review.get("repair_actions", [])
        if repair_actions:
            lines.append("- **修正動作:**")
            for action in repair_actions:
                replacement = (
                    f" (replaced {action.get('replaced_label')})"
                    if action.get("replaced_label")
                    else ""
                )
                lines.append(
                    f"  - {action.get('action')}: {action.get('candidate_label')} — {action.get('reason')}{replacement}"
                )
        review_warnings = review.get("warnings", [])
        if review_warnings:
            lines.append("- **review warnings:**")
            for warning in review_warnings:
                lines.append(f"  - {warning}")

    if enrichment_rounds:
        lines.append("\n## Plan Enrich Rounds")
        for round_info in enrichment_rounds:
            lines.append(
                f"- **round {round_info.get('round_index', '?')}:** added {round_info.get('added_candidate_labels', [])}"
            )
            lines.append(
                f"  - coverage: {round_info.get('coverage_before', [])} → {round_info.get('coverage_after', [])}"
            )
            lines.append(f"  - rationale: {round_info.get('rationale', '')}")

    if schedule:
        lines.append("\n## Phase 8 Execution Schedule")
        for step in schedule:
            depends_on = ", ".join(step.get("depends_on", [])) or "(none)"
            lines.append(
                f"{step.get('order', 0)}. **{step.get('analysis_label', '')}** via `{step.get('tool_name', '')}`"
                f" [{step.get('stage', '')}]"
            )
            lines.append(f"   - depends_on: {depends_on}")
            lines.append(f"   - variables: {step.get('variables', [])}")
            lines.append(f"   - rationale: {step.get('rationale', '')}")

    if selected:
        lines.append("\n## 建議優先順序（review 後）")
        for index, entry in enumerate(selected, 1):
            label = entry.get("analysis_type") or entry.get("type")
            lines.append(
                f"{index}. **{label}** (score={entry.get('score', 0)})"
                f"\n   - variables: {entry.get('variables', [])}"
                f"\n   - rationale: {entry.get('rationale', '')}"
                f"\n   - coverage: {entry.get('coverage_tags', [])}"
            )
            visualizations = entry.get("visualizations", [])
            if visualizations:
                lines.append("   - visualizations:")
                for viz in visualizations:
                    lines.append(
                        f"     - {viz.get('plot_type')} {viz.get('variables')}"
                        + (
                            f" grouped by {viz.get('group_variable')}"
                            if viz.get("group_variable")
                            else ""
                        )
                    )

    blueprint = proposal.get("plan_blueprint", [])
    lines.append("\n## Phase 4 可直接鎖定的 blueprint")
    lines.append("```json")
    lines.append(json.dumps(blueprint, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append(
        "\n**下一步:** 檢查這份 greedy blueprint，必要時刪減或補充後，用 "
        "`register_analysis_plan(confirm=true)` 鎖定真正要執行的分析。"
    )
    artifact_paths = [artifact_json, artifact_md]
    if review_json:
        artifact_paths.append(review_json)
    if review_md:
        artifact_paths.append(review_md)
    if schedule_json:
        artifact_paths.append(schedule_json)
    if schedule_md:
        artifact_paths.append(schedule_md)
    if enrich_json:
        artifact_paths.append(enrich_json)
    if enrich_md:
        artifact_paths.append(enrich_md)
    if script_path:
        artifact_paths.append(script_path)
    lines.append(f"\n**Artifacts:** {', '.join(f'`{path}`' for path in artifact_paths)}")
    return "\n".join(lines)


def _render_methodology_review_markdown(review: dict[str, Any]) -> str:
    lines = ["# 📏 Plan Methodology Review\n"]
    lines.append(f"- **status:** {review.get('status', 'unknown')}")
    lines.append(f"- **recommended analysis floor:** {review.get('recommended_analysis_floor', 0)}")
    lines.append(f"- **academic analysis target:** {review.get('academic_analysis_target', review.get('recommended_analysis_floor', 0))}")
    lines.append(f"- **production analysis target:** {review.get('production_analysis_target', review.get('academic_analysis_target', review.get('recommended_analysis_floor', 0)))}")
    lines.append(f"- **completeness tier:** {review.get('completeness_tier', 'unknown')}")
    lines.append(f"- **candidate pool size:** {review.get('candidate_pool_size', 0)}")
    lines.append(f"- **requested analysis budget:** {review.get('requested_analysis_budget', 0)}")
    lines.append(f"- **soft analysis budget:** {review.get('soft_analysis_budget', 0)}")
    lines.append(f"- **draft analysis count:** {review.get('draft_analysis_count', 0)}")
    lines.append(f"- **final analysis count:** {review.get('final_analysis_count', 0)}")
    if review.get("complexity_signals"):
        lines.append(f"- **complexity signals:** {review.get('complexity_signals')}")

    checks = review.get("checks", [])
    if checks:
        lines.append("\n## Checks")
        for check in checks:
            lines.append(
                f"- [{check.get('status', 'unknown')}] **{check.get('name')}**: {check.get('detail')}"
            )

    repair_actions = review.get("repair_actions", [])
    if repair_actions:
        lines.append("\n## Repairs")
        for action in repair_actions:
            replacement = (
                f" (replaced {action.get('replaced_label')})"
                if action.get("replaced_label")
                else ""
            )
            lines.append(
                f"- {action.get('action')}: {action.get('candidate_label')} — {action.get('reason')}{replacement}"
            )

    warnings = review.get("warnings", [])
    if warnings:
        lines.append("\n## Warnings")
        for warning in warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines)


def _render_execution_schedule_markdown(schedule: list[dict[str, Any]]) -> str:
    lines = ["# ▶️ Phase 8 Execution Schedule\n"]
    lines.append(f"- **steps:** {len(schedule)}")

    if not schedule:
        lines.append("\nNo executable schedule was generated.")
        return "\n".join(lines)

    lines.append("\n## Ordered Steps")
    for step in schedule:
        depends_on = ", ".join(step.get("depends_on", [])) or "(none)"
        lines.append(
            f"{step.get('order', 0)}. **{step.get('analysis_label', '')}** via `{step.get('tool_name', '')}`"
            f" [{step.get('stage', '')}]"
        )
        lines.append(f"   - step_id: {step.get('step_id', '')}")
        lines.append(f"   - depends_on: {depends_on}")
        lines.append(f"   - variables: {step.get('variables', [])}")
        lines.append(f"   - rationale: {step.get('rationale', '')}")

    return "\n".join(lines)


def _render_plan_enrichment_markdown(rounds: list[dict[str, Any]]) -> str:
    lines = ["# 🔁 Plan Enrich Rounds\n"]
    lines.append(f"- **rounds:** {len(rounds)}")

    if not rounds:
        lines.append(
            "\nNo additional enrich rounds were applied beyond the initial review/repair pass."
        )
        return "\n".join(lines)

    for round_info in rounds:
        lines.append(f"\n## Round {round_info.get('round_index', '?')}")
        lines.append(f"- **added branches:** {round_info.get('added_candidate_labels', [])}")
        lines.append(
            f"- **coverage:** {round_info.get('coverage_before', [])} → {round_info.get('coverage_after', [])}"
        )
        lines.append(f"- **rationale:** {round_info.get('rationale', '')}")

    return "\n".join(lines)


def register_plan_tools(server: Any) -> None:
    """Register planning and pre-registration MCP tools."""

    @server.tool()
    def align_concept(
        project_id: str | None = None,
        research_question: str = "",
        variable_roles: dict[str, str | list[str]] | None = None,
        confirm: bool = False,
    ) -> str:
        """對齊研究概念與資料 schema（Phase 3）。

        將研究問題對應到實際變數，確認 outcome/predictor/confounder 角色。
        ⚠️ 需要用戶確認 (confirm=true) 後才能解鎖 Phase 4。

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
            research_question: 研究問題，如 "ICU sepsis 患者 28 天死亡率的影響因素"
            variable_roles: 變數角色指定，格式: {"outcome": "mortality", "group": "treatment", "covariates": ["age", "sex"]}
            confirm: 是否確認概念對齊，必須設為 true 才能解鎖 Phase 4（預設 false）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_result,
            log_tool_error,
            fmt_error,
            fmt_table,
            ensure_phase_ready,
        )
        from rde.interface.mcp.tools._shared.project_context import persist_project
        from rde.application.pipeline import PipelinePhase

        log_tool_call(
            "align_concept",
            {
                "research_question": research_question,
                "variable_roles": variable_roles,
            },
        )

        ok, msg, project, entry = ensure_phase_ready(
            PipelinePhase.CONCEPT_ALIGNMENT,
            project_id=project_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert entry is not None

        try:
            from datetime import datetime
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult
            from rde.domain.models.project import ProjectStatus
            from rde.domain.models.variable import VariableRole
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            session = get_session()

            if research_question:
                project.research_question = research_question

            ds = entry.dataset
            available_vars = {v.name: v for v in ds.variables}

            role_assignments: dict[str, str] = {}
            if variable_roles:
                for role_key, var_names_raw in variable_roles.items():
                    names_list = (
                        [var_names_raw] if isinstance(var_names_raw, str) else var_names_raw
                    )
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
                v.name
                for v in ds.variables
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
            store.save(
                PipelinePhase.CONCEPT_ALIGNMENT,
                "concept_alignment.md",
                f"# Concept Alignment\n\n"
                f"## Research Question\n{project.research_question}\n\n"
                f"## Variable Roles\n{role_assignments}\n",
            )
            store.save(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json", alignment)

            pipeline = session.get_pipeline(project.id)
            pipeline.mark_started(PipelinePhase.CONCEPT_ALIGNMENT)
            pipeline.mark_completed(
                PhaseResult(
                    phase=PipelinePhase.CONCEPT_ALIGNMENT,
                    completed_at=datetime.now(),
                    success=True,
                    artifacts={"concept_alignment.md": "", "variable_roles.json": ""},
                    user_confirmed=confirm,
                )
            )
            project.advance_to(ProjectStatus.CONCEPT_ALIGNMENT)
            persist_project(project)

            # Build variable table
            headers = ["變數", "類型", "角色", "可分析"]
            rows = [
                [v.name, v.variable_type.value, v.role.value, "✅" if v.is_analyzable() else "❌"]
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

            log_tool_result(
                "align_concept", f"{analyzable} analyzable, {len(role_assignments)} assigned"
            )

            return (
                f"# 🔬 概念對齊 (Phase 3)\n\n"
                f"- **研究問題:** {project.research_question or '(未指定)'}\n"
                f"- **資料集:** `{ds.id}`\n"
                f"- **可分析變數:** {analyzable} / {len(ds.variables)}\n"
                f"{assigned_text}{unassigned_text}\n"
                f"{table}\n\n"
                + (
                    "✅ **已確認概念對齊，可進入 Phase 4。**"
                    if confirm
                    else "⚠️ **尚未確認概念對齊。請用 `confirm=true` 重新呼叫後再進入 Phase 4。**"
                )
            )

        except Exception as e:
            log_tool_error("align_concept", e)
            return fmt_error(f"概念對齊失敗: {e}")

    @server.tool()
    def propose_analysis_plan(
        project_id: str | None = None,
        dataset_id: str | None = None,
        max_analyses: int = 8,
        enrich_rounds: int = 1,
        include_advanced: bool = True,
        include_visualizations: bool = True,
    ) -> str:
        """產生 greedy autonomous EDA 候選計畫（Phase 4 — Creative Ideation）。

        在 Phase 3 已確認後，根據 schema、variable roles 與研究問題，
        用 deterministic greedy heuristic 產生一份「可直接送入 Phase 5」的
        blueprint，協助 agent 更自主地驅動 EDA。

        此工具包含內部 methodology review + repair，會先產生 draft，再補足缺失的分析家族。
        `max_analyses` 是初始 greedy budget，不是硬性上限；若 review 認為應保留延伸 EDA 路線，
        planner 會產生 soft-budget expansion 與 Phase 8 execution schedule。
        另外可用 `enrich_rounds` 讓 planner 在 reviewed blueprint 後再多跑幾輪 enrich，
        每輪都只補少量新 branch，避免一次暴衝失控。
        這個工具不會鎖定計畫；真正鎖定仍需 `register_analysis_plan(confirm=true)`。

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
            dataset_id: 資料集 ID（可選，預設使用當前資料集）
            max_analyses: greedy 初始預算，review 可視需要擴張以保留更多分析路線（預設 8）
            enrich_rounds: reviewed blueprint 後的 enrich 輪數，1 表示只做單輪 review/repair（預設 1）
            include_advanced: 是否納入 regression / ROC / learning-curve 等進階候選（預設 true）
            include_visualizations: 是否同時產生可納入 plan 的 visualization bundle（預設 true）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_result,
            log_tool_error,
            fmt_error,
            ensure_phase_ready,
            ensure_dataset,
        )
        from rde.interface.mcp.tools._shared.project_context import persist_project
        from rde.application.pipeline import PipelinePhase

        log_tool_call(
            "propose_analysis_plan",
            {
                "dataset_id": dataset_id,
                "max_analyses": max_analyses,
                "enrich_rounds": enrich_rounds,
                "include_advanced": include_advanced,
                "include_visualizations": include_visualizations,
            },
        )

        ok, msg, project, entry = ensure_phase_ready(
            PipelinePhase.CREATIVE_IDEATION,
            project_id=project_id,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)

        assert project is not None
        assert entry is not None

        try:
            from rde.application.session import get_session
            from rde.application.use_cases.propose_analysis_plan import (
                ProposeAnalysisPlanUseCase,
            )
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            session = get_session()
            pipeline = session.get_pipeline(project.id)
            use_case = ProposeAnalysisPlanUseCase()
            proposal = use_case.execute(
                entry.dataset,
                research_question=project.research_question or "",
                max_analyses=max_analyses,
                enrich_rounds=enrich_rounds,
                include_advanced=include_advanced,
                include_visualizations=include_visualizations,
            )

            proposal_dict = proposal.to_dict()
            store = ArtifactStore(project.artifacts_dir)
            json_path = store.save(
                PipelinePhase.CREATIVE_IDEATION,
                "greedy_analysis_candidates.json",
                proposal_dict,
            )
            review_dict = proposal_dict.get("review") or {}
            review_json_path = store.save(
                PipelinePhase.CREATIVE_IDEATION,
                "greedy_analysis_review.json",
                review_dict,
            )
            review_md_content = _render_methodology_review_markdown(review_dict)
            review_md_path = store.save(
                PipelinePhase.CREATIVE_IDEATION,
                "greedy_analysis_review.md",
                review_md_content,
            )
            schedule = proposal_dict.get("execution_schedule", [])
            schedule_json_path = store.save(
                PipelinePhase.CREATIVE_IDEATION,
                "greedy_execution_schedule.json",
                schedule,
            )
            schedule_md_path = store.save(
                PipelinePhase.CREATIVE_IDEATION,
                "greedy_execution_schedule.md",
                _render_execution_schedule_markdown(schedule),
            )
            enrichment_rounds_payload = proposal_dict.get("enrichment_rounds", [])
            enrich_json_path = store.save(
                PipelinePhase.CREATIVE_IDEATION,
                "greedy_plan_enrichment.json",
                enrichment_rounds_payload,
            )
            enrich_md_path = store.save(
                PipelinePhase.CREATIVE_IDEATION,
                "greedy_plan_enrichment.md",
                _render_plan_enrichment_markdown(enrichment_rounds_payload),
            )
            from rde.domain.services.autonomous_eda_planner import AutonomousEDAPlanner

            planner = AutonomousEDAPlanner()
            script_content = planner.build_statsmodels_analysis_script(
                entry.dataset,
                list(proposal.plan_blueprint),
                proposal.execution_schedule,
                research_question=project.research_question or "",
            )
            script_path = store.save(
                PipelinePhase.CREATIVE_IDEATION,
                "greedy_statsmodels_base_analysis.py",
                script_content,
            )
            content = _render_greedy_plan_markdown(
                proposal_dict,
                artifact_json=str(json_path),
                artifact_md=str(
                    store.get_path(
                        PipelinePhase.CREATIVE_IDEATION,
                        "greedy_analysis_candidates.md",
                    )
                ),
                plan_locked=pipeline.plan_locked,
                review_json=str(review_json_path),
                review_md=str(review_md_path),
                schedule_json=str(schedule_json_path),
                schedule_md=str(schedule_md_path),
                enrich_json=str(enrich_json_path),
                enrich_md=str(enrich_md_path),
                script_path=str(script_path),
            )
            md_path = store.save(
                PipelinePhase.CREATIVE_IDEATION,
                "greedy_analysis_candidates.md",
                content,
            )

            log_tool_result(
                "propose_analysis_plan",
                f"{len(proposal.selected)} selected from {proposal.candidate_pool_size} candidates",
            )
            return _render_greedy_plan_markdown(
                proposal_dict,
                artifact_json=str(json_path),
                artifact_md=str(md_path),
                plan_locked=pipeline.plan_locked,
                review_json=str(review_json_path),
                review_md=str(review_md_path),
                schedule_json=str(schedule_json_path),
                schedule_md=str(schedule_md_path),
                enrich_json=str(enrich_json_path),
                enrich_md=str(enrich_md_path),
                script_path=str(script_path),
            )

        except Exception as e:
            log_tool_error("propose_analysis_plan", e)
            return fmt_error(f"greedy 計畫提案失敗: {e}")

    @server.tool()
    def register_analysis_plan(
        project_id: str | None = None,
        analyses: list[dict[str, Any]] | None = None,
        alpha: float = 0.05,
        missing_strategy: str = "listwise",
        multiple_comparison_method: str = "bonferroni",
        allow_methodology_override: bool = False,
        confirm: bool = False,
    ) -> str:
        """註冊分析計畫（Phase 6 — Plan Registration）。

        ⚠️ 確認後計畫將被鎖定 (H-007)，後續偏離會自動偵測並記錄。
        每項分析需指定 type、variables、rationale。

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
            analyses: 計畫分析項目清單，每項必須含 type 和 variables，如 [{"type": "compare_groups", "variables": ["sofa_score"], "rationale": "比較兩組 SOFA"}]
            alpha: 顯著水準 α，如 0.05、0.01（預設 0.05）
            missing_strategy: 缺失值處理策略: listwise（預設）、pairwise、impute_median
            multiple_comparison_method: 多重比較校正方法: bonferroni（預設）、fdr
            allow_methodology_override: 若 plan 明顯低於方法學最低覆蓋要求，是否仍強制允許鎖定（預設 false）
            confirm: 是否確認並鎖定計畫，必須設為 true 才會鎖定（預設 false）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_result,
            log_tool_error,
            fmt_error,
            ensure_phase_ready,
            ensure_dataset,
        )
        from rde.interface.mcp.tools._shared.project_context import persist_project
        from rde.application.pipeline import PipelinePhase

        log_tool_call(
            "register_analysis_plan",
            {
                "alpha": alpha,
                "missing_strategy": missing_strategy,
                "allow_methodology_override": allow_methodology_override,
            },
        )

        ok, msg, project, _ = ensure_phase_ready(
            PipelinePhase.PLAN_REGISTRATION, project_id=project_id
        )
        if not ok:
            return fmt_error(msg)
        assert project is not None

        if not confirm:
            return fmt_error(
                "Phase 5 需要明確用戶確認才能鎖定分析計畫。",
                suggestion="以 `confirm=true` 重新呼叫 register_analysis_plan()。",
            )

        try:
            from datetime import datetime
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult
            from rde.domain.models.project import ProjectStatus
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

            # Validate analysis entries schema
            validation_errors: list[str] = []
            VALID_ANALYSIS_TYPES = {
                "compare_groups",
                "analyze_variable",
                "correlation_matrix",
                "generate_table_one",
                "run_advanced_analysis",
                "run_repeated_measures",
                "propensity_score",
                "survival_analysis",
                "roc_auc",
                "logistic_regression",
                "multiple_regression",
                "power_analysis_advanced",
                "descriptive",
                "univariate",
                "table_one",
                "visualization",
            }
            for i, entry in enumerate(analyses):
                if not isinstance(entry, dict):
                    validation_errors.append(f"  #{i}: 必須是字典，收到 {type(entry).__name__}")
                    continue
                if "type" not in entry:
                    validation_errors.append(f"  #{i}: 缺少必填欄位 'type'")
                else:
                    entry_type = str(entry["type"]).lower().replace("-", "_").replace(" ", "_")
                    if entry_type not in VALID_ANALYSIS_TYPES:
                        validation_errors.append(
                            f"  #{i}: 未知分析類型 '{entry['type']}'。"
                            f"支援: {', '.join(sorted(VALID_ANALYSIS_TYPES))}"
                        )
                if "variables" not in entry and "type" in entry:
                    validation_errors.append(
                        f"  #{i} ({entry.get('type', '?')}): 建議指定 'variables' 以啟用自動偏離偵測"
                    )

            if validation_errors:
                return fmt_error(
                    f"分析計畫驗證失敗 ({len(validation_errors)} 個問題):",
                    "\n".join(validation_errors),
                    "每項分析應含 type (必填)、variables (建議)、rationale (選填)。",
                )

            methodology_review_dict: dict[str, Any] | None = None
            execution_schedule: list[dict[str, Any]] = []
            dataset_ok, _, dataset_entry = ensure_dataset(project=project)
            dataset = dataset_entry.dataset if dataset_ok and dataset_entry is not None else None
            planner = None
            auto_expanded_labels: list[str] = []
            if dataset is not None:
                from rde.domain.services.autonomous_eda_planner import AutonomousEDAPlanner

                planner = AutonomousEDAPlanner()

                def _planned_count(entries: list[dict[str, Any]]) -> int:
                    return len(
                        [
                            entry
                            for entry in entries
                            if isinstance(entry, dict)
                            and str(entry.get("type", "")).lower() != "visualization"
                        ]
                    )

                review = planner.review_registered_plan(
                    dataset,
                    analyses,
                    include_advanced=True,
                    max_analyses=_planned_count(analyses),
                )
                if review.status == "needs_override" and not allow_methodology_override:
                    proposal = planner.propose(
                        dataset,
                        research_question=project.research_question or "",
                        max_analyses=max(
                            _planned_count(analyses), review.recommended_analysis_floor
                        ),
                        include_advanced=True,
                        include_visualizations=True,
                    )
                    analyses, auto_expanded_labels = _merge_methodology_expansion(
                        analyses,
                        list(proposal.plan_blueprint),
                    )
                    review = planner.review_registered_plan(
                        dataset,
                        analyses,
                        include_advanced=True,
                        max_analyses=_planned_count(analyses),
                    )
                    if review.status == "needs_override":
                        methodology_review_dict = review.to_dict()
                        return fmt_error(
                            "分析計畫方法學審查未通過。",
                            _render_methodology_review_markdown(methodology_review_dict),
                            "先使用 `propose_analysis_plan()` 生成 reviewed blueprint，或以 `allow_methodology_override=true` 明示覆蓋。",
                        )
                methodology_review_dict = review.to_dict()
            if planner is None:
                from rde.domain.services.autonomous_eda_planner import AutonomousEDAPlanner

                planner = AutonomousEDAPlanner()
            execution_schedule = [
                step.to_dict() for step in planner.build_execution_schedule(analyses)
            ]
            script_dataset = dataset
            script_content = (
                planner.build_statsmodels_analysis_script(
                    script_dataset,
                    analyses,
                    planner.build_execution_schedule(analyses),
                    research_question=project.research_question or "",
                )
                if script_dataset is not None
                else "# No dataset available; statsmodels base analysis script was not generated.\n"
            )

            plan = {
                "project_id": project.id,
                "research_question": project.research_question,
                "alpha": alpha,
                "missing_strategy": missing_strategy,
                "multiple_comparison_method": multiple_comparison_method,
                "analyses": analyses,
                "execution_schedule": execution_schedule,
                "created_at": datetime.now().isoformat(),
                "locked": True,
            }

            store = ArtifactStore(project.artifacts_dir)
            store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
            store.save(
                PipelinePhase.PLAN_REGISTRATION,
                "analysis_execution_schedule.json",
                execution_schedule,
            )
            store.save(
                PipelinePhase.PLAN_REGISTRATION,
                "analysis_execution_schedule.md",
                _render_execution_schedule_markdown(execution_schedule),
            )
            store.save(
                PipelinePhase.PLAN_REGISTRATION,
                "analysis_statsmodels_base.py",
                script_content,
            )
            if methodology_review_dict is not None:
                store.save(
                    PipelinePhase.PLAN_REGISTRATION,
                    "analysis_plan_review.json",
                    methodology_review_dict,
                )
                store.save(
                    PipelinePhase.PLAN_REGISTRATION,
                    "analysis_plan_review.md",
                    _render_methodology_review_markdown(methodology_review_dict),
                )

            pipeline.mark_started(PipelinePhase.PLAN_REGISTRATION)
            pipeline.mark_completed(
                PhaseResult(
                    phase=PipelinePhase.PLAN_REGISTRATION,
                    completed_at=datetime.now(),
                    success=True,
                    artifacts={"analysis_plan.yaml": ""},
                    user_confirmed=True,
                )
            )
            project.advance_to(ProjectStatus.PLAN_REGISTRATION)
            persist_project(project)

            analyses_text = ""
            if analyses:
                analyses_text = "\n**計畫分析項目:**\n"
                for i, a in enumerate(analyses, 1):
                    analyses_text += f"{i}. **{a.get('type', '')}** — {a.get('rationale', '')}\n"
                    if a.get("variables"):
                        analyses_text += f"   變數: {a['variables']}\n"

            log_tool_result("register_analysis_plan", f"{len(analyses)} analyses, locked")

            methodology_text = ""
            if methodology_review_dict is not None:
                methodology_text = (
                    f"- **方法學 review:** {methodology_review_dict.get('status')} "
                    f"(floor={methodology_review_dict.get('recommended_analysis_floor')})\n"
                    f"- **soft budget:** {methodology_review_dict.get('soft_analysis_budget')}\n"
                )

            expansion_text = ""
            if auto_expanded_labels:
                expansion_text = (
                    "- **自動補入 exploratory branches:** " + ", ".join(auto_expanded_labels) + "\n"
                )

            schedule_text = ""
            if execution_schedule:
                schedule_text = (
                    f"- **Phase 6 schedule steps:** {len(execution_schedule)} "
                    f"(artifact: `analysis_execution_schedule.json`)\n"
                )
            script_text = "- **statsmodels base script:** `analysis_statsmodels_base.py`\n"

            return (
                f"🔒 分析計畫已鎖定 (Phase 4)\n\n"
                f"- **顯著水準 (α):** {alpha}\n"
                f"- **缺失值策略:** {missing_strategy}\n"
                f"- **多重比較校正:** {multiple_comparison_method}\n"
                f"- **分析項目數:** {len(analyses)}\n"
                f"{methodology_text}"
                f"{expansion_text}"
                f"{schedule_text}"
                f"{script_text}"
                f"{analyses_text}\n"
                f"⚠️ Phase 6+ 操作偏離此計畫時，必須呼叫 `log_deviation()` 記錄。\n\n"
                f"**下一步:** 使用 `check_readiness()` 執行準備度檢查 (Phase 7)。"
            )

        except Exception as e:
            log_tool_error("register_analysis_plan", e)
            return fmt_error(f"計畫註冊失敗: {e}")

    @server.tool()
    def check_readiness(project_id: str | None = None) -> str:
        """執行探索前準備度檢查（Phase 5）。

        驗證 H-003 (樣本量 ≥10), H-004 (PII), H-007 (計畫已鎖定),
        H-008 (artifact gate), S-001 (常態性提醒), S-005 (缺失模式),
        S-007 (共線性 VIF 預檢)。

        Args:
            project_id: 專案 ID（可選，預設使用當前專案）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_result,
            log_tool_error,
            fmt_error,
            ensure_phase_ready,
            ensure_dataset,
        )
        from rde.interface.mcp.tools._shared.project_context import persist_project
        from rde.interface.mcp.tools._shared.formatting import fmt_checks
        from rde.application.pipeline import PipelinePhase

        log_tool_call("check_readiness", {"project_id": project_id})

        ok, msg, project, _ = ensure_phase_ready(
            PipelinePhase.PRE_EXPLORE_CHECK, project_id=project_id
        )
        if not ok:
            return fmt_error(msg)
        assert project is not None

        try:
            from datetime import datetime
            from rde.application.session import get_session
            from rde.application.pipeline import (
                PipelinePhase,
                PhaseResult,
                REQUIRED_ARTIFACTS,
            )
            from rde.domain.models.project import ProjectStatus
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            session = get_session()
            pipeline = session.get_pipeline(project.id)
            store = ArtifactStore(project.artifacts_dir)
            dataset_ok, dataset_msg, dataset_entry = ensure_dataset(project=project)

            checks: list[dict[str, Any]] = []
            all_passed = True

            # H-003: Min sample size
            if dataset_ok and dataset_entry is not None:
                n = dataset_entry.dataset.row_count
                passed = n >= 10
                checks.append(
                    {
                        "id": "H-003",
                        "name": "最小樣本量",
                        "passed": passed,
                        "detail": f"n = {n}" + ("" if passed else " (需 ≥ 10)"),
                    }
                )
                if not passed:
                    all_passed = False
            else:
                checks.append(
                    {
                        "id": "H-003",
                        "name": "最小樣本量",
                        "passed": False,
                        "detail": dataset_msg,
                    }
                )
                all_passed = False

            # H-004: PII check
            pii_vars = []
            if dataset_ok and dataset_entry is not None:
                pii_vars = [v.name for v in dataset_entry.dataset.variables if v.is_pii_suspect]
            checks.append(
                {
                    "id": "H-004",
                    "name": "PII 偵測",
                    "passed": len(pii_vars) == 0,
                    "detail": f"疑似 PII: {pii_vars}" if pii_vars else "無 PII",
                }
            )
            if pii_vars:
                all_passed = False

            # H-007: Plan locked
            checks.append(
                {
                    "id": "H-007",
                    "name": "分析計畫已鎖定",
                    "passed": pipeline.plan_locked,
                    "detail": "已鎖定" if pipeline.plan_locked else "未鎖定",
                }
            )
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
                checks.append(
                    {
                        "id": "H-008",
                        "name": f"Artifact Gate: {phase.value}",
                        "passed": passed,
                        "detail": f"缺少: {missing}" if missing else "完整",
                    }
                )
                if not passed:
                    all_passed = False

            # S-001: Normality hint
            if dataset_ok and dataset_entry is not None:
                continuous = [
                    v.name
                    for v in dataset_entry.dataset.variables
                    if v.variable_type.value == "continuous"
                ]
                checks.append(
                    {
                        "id": "S-001",
                        "name": "常態性檢定提醒",
                        "passed": True,
                        "detail": f"有 {len(continuous)} 個連續變數，建議執行常態性檢定",
                    }
                )

            # S-005: Missing pattern analysis
            if dataset_ok and dataset_entry is not None:
                df = dataset_entry.dataframe
                missing_cols = [c for c in df.columns if df[c].isna().sum() > 0]
                if missing_cols:
                    try:
                        from rde.infrastructure.adapters import ScipyStatisticalEngine

                        engine = ScipyStatisticalEngine()
                        mp = engine.analyze_missing_patterns(df, missing_cols)
                        pattern = mp.get("pattern", "unknown")
                        rec = mp.get("recommendation", "")
                        checks.append(
                            {
                                "id": "S-005",
                                "name": "缺失模式分析",
                                "passed": True,
                                "detail": f"模式: {pattern}，建議: {rec}",
                            }
                        )
                    except Exception:
                        checks.append(
                            {
                                "id": "S-005",
                                "name": "缺失模式分析",
                                "passed": True,
                                "detail": f"{len(missing_cols)} 個變數有缺失值",
                            }
                        )
                else:
                    checks.append(
                        {
                            "id": "S-005",
                            "name": "缺失模式分析",
                            "passed": True,
                            "detail": "無缺失值",
                        }
                    )

            # S-007: Collinearity check (VIF preview)
            if dataset_ok and dataset_entry is not None:
                df = dataset_entry.dataframe
                from rde.domain.services.collinearity_checker import check_collinearity

                report = check_collinearity(df)
                if report.has_collinearity:
                    checks.append(
                        {
                            "id": "S-007",
                            "name": "共線性預檢",
                            "passed": True,
                            "detail": f"⚠️ 高相關: {', '.join(report.format_warnings())}",
                        }
                    )
                else:
                    checks.append(
                        {
                            "id": "S-007",
                            "name": "共線性預檢",
                            "passed": True,
                            "detail": "無明顯共線性",
                        }
                    )

            # Save artifact
            checklist = {
                "project_id": project.id,
                "all_passed": all_passed,
                "checks": checks,
                "checked_at": datetime.now().isoformat(),
            }
            store.save(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json", checklist)

            pipeline.mark_started(PipelinePhase.PRE_EXPLORE_CHECK)
            pipeline.mark_completed(
                PhaseResult(
                    phase=PipelinePhase.PRE_EXPLORE_CHECK,
                    completed_at=datetime.now(),
                    success=all_passed,
                    artifacts={"readiness_checklist.json": ""},
                )
            )
            project.advance_to(ProjectStatus.PRE_EXPLORE_CHECK)
            persist_project(project)

            checks_text = fmt_checks(checks)

            log_tool_result("check_readiness", f"passed={all_passed}")

            status = "✅ 準備就緒，可進入 Phase 6" if all_passed else "❌ 尚有未通過的檢查項目"

            return f"# 🔍 準備度檢查 (Phase 5)\n\n{checks_text}\n\n**結果:** {status}"

        except Exception as e:
            log_tool_error("check_readiness", e)
            return fmt_error(f"準備度檢查失敗: {e}")
