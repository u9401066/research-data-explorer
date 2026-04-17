"""Analysis Tools — Phase 6 (Execute) & Phase 7 (Collect).

All Phase 6 tools auto-log decisions (H-009 enforced).
Soft constraints S-001, S-002, S-003, S-004, S-006, S-007, S-008, S-009, S-010 wired.
All tools return markdown strings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _sanitize_analysis_frame(
    df: Any,
    variables: list[str] | tuple[str, ...],
) -> tuple[Any, list[str], str | None]:
    from rde.domain.services.numeric_plausibility import (
        apply_numeric_plausibility_filters,
        format_plausibility_markdown,
        summarize_plausibility_findings,
    )

    cleaned_df, findings = apply_numeric_plausibility_filters(df, list(variables))
    return cleaned_df, format_plausibility_markdown(findings), summarize_plausibility_findings(findings)


def _normalize_analysis_type(analysis_type: str) -> str:
    """Normalize analysis type names for filenames and routing summaries."""
    return analysis_type.lower().replace("-", "_").replace(" ", "_")


def _is_direct_analysis_contract(result: Any) -> bool:
    """Identify stats-service /direct/analyze job submission responses."""
    return isinstance(result, dict) and {
        "job_id",
        "job_type",
        "status",
        "message",
        "data_preview",
    }.issubset(result.keys())


def _is_async_job_contract(result: Any) -> bool:
    """Identify generic vendor async job submission responses."""
    return (
        isinstance(result, dict)
        and {
            "job_id",
            "job_type",
            "status",
        }.issubset(result.keys())
        and ("message" in result or "status_message" in result)
    )


def _summarize_advanced_analysis_result(analysis_result: Any) -> str:
    """Create a compact decision-log summary from a raw advanced-analysis payload."""
    if _is_direct_analysis_contract(analysis_result):
        preview = analysis_result.get("data_preview", {})
        return (
            f"job_id={analysis_result.get('job_id')}, "
            f"status={analysis_result.get('status')}, "
            f"rows={preview.get('rows', '?')}, columns={preview.get('columns', '?')}"
        )

    if _is_async_job_contract(analysis_result):
        parts = [
            f"job_id={analysis_result.get('job_id')}",
            f"status={analysis_result.get('status')}",
        ]
        if "progress" in analysis_result:
            parts.append(f"progress={analysis_result.get('progress')}")
        status_message = analysis_result.get("status_message") or analysis_result.get("message")
        if status_message:
            parts.append(f"message={status_message}")
        return ", ".join(parts)

    if isinstance(analysis_result, dict):
        if analysis_result.get("error"):
            return str(analysis_result["error"])
        numeric_parts: list[str] = []
        for key in ("calculation_type", "result", "status", "job_id"):
            if key in analysis_result:
                numeric_parts.append(f"{key}={analysis_result[key]}")
        if numeric_parts:
            return ", ".join(numeric_parts)
        return ", ".join(sorted(analysis_result.keys())[:6])

    return str(analysis_result)


def _save_advanced_analysis_artifact(
    project: Any,
    *,
    dataset_id: str,
    analysis_type: str,
    source: str,
    config: dict[str, Any],
    analysis_result: Any,
) -> Path:
    """Persist Phase 6 advanced analysis payload for audit and reporting."""
    from rde.application.pipeline import PipelinePhase
    from rde.infrastructure.persistence.artifact_store import ArtifactStore

    normalized = _normalize_analysis_type(analysis_type)
    job_id = analysis_result.get("job_id") if isinstance(analysis_result, dict) else None
    job_suffix = f"_{str(job_id).replace('/', '_')}" if job_id else ""
    filename = f"advanced_analysis_{normalized}{job_suffix}.json"

    payload = {
        "dataset_id": dataset_id,
        "analysis_type": analysis_type,
        "normalized_analysis_type": normalized,
        "source": source,
        "config": config,
        "result": analysis_result,
        "result_summary": _summarize_advanced_analysis_result(analysis_result),
        "contract": "direct_analyze"
        if _is_direct_analysis_contract(analysis_result)
        else "job_submission"
        if _is_async_job_contract(analysis_result)
        else "structured_response",
    }

    store = ArtifactStore(project.artifacts_dir)
    return store.save(PipelinePhase.EXECUTE_EXPLORATION, filename, payload)


def _save_advanced_analysis_markdown_artifact(
    project: Any,
    *,
    analysis_type: str,
    analysis_result: Any,
    content: str,
) -> Path:
    """Persist the rendered Phase 6 advanced-analysis markdown for reports/handoff."""
    from rde.application.pipeline import PipelinePhase
    from rde.infrastructure.persistence.artifact_store import ArtifactStore

    normalized = _normalize_analysis_type(analysis_type)
    job_id = analysis_result.get("job_id") if isinstance(analysis_result, dict) else None
    job_suffix = f"_{str(job_id).replace('/', '_')}" if job_id else ""
    filename = f"advanced_analysis_{normalized}{job_suffix}.md"

    store = ArtifactStore(project.artifacts_dir)
    return store.save(PipelinePhase.EXECUTE_EXPLORATION, filename, content)


def _append_nested_markdown(lines: list[str], key: str, value: Any) -> None:
    """Render nested dict/list payloads into readable markdown bullets."""
    if isinstance(value, dict):
        lines.append(f"\n### {key}")
        for sub_key, sub_value in value.items():
            if isinstance(sub_value, (dict, list)):
                lines.append(f"- {sub_key}: {sub_value}")
            elif isinstance(sub_value, float):
                lines.append(f"- {sub_key}: {sub_value:.4f}")
            else:
                lines.append(f"- {sub_key}: {sub_value}")
    elif isinstance(value, list):
        lines.append(f"\n### {key}")
        for item in value[:10]:
            lines.append(f"- {item}")
        if len(value) > 10:
            lines.append(f"- ... 共 {len(value)} 筆")


def _format_advanced_analysis_output(
    *,
    analysis_type: str,
    source: str,
    analysis_result: Any,
    artifact_path: Path | None,
    automl_available: bool,
) -> str:
    """Build user-facing markdown for advanced analysis execution."""
    normalized_analysis_type = _normalize_analysis_type(analysis_type)
    lines = [
        f"# 📊 進階分析 — {analysis_type}\n",
        f"**引擎:** {source}",
    ]

    if normalized_analysis_type == "learning_curve_cusum" and isinstance(analysis_result, dict):
        lines.append("\n## 分析設定")
        lines.append(f"- **成功變數:** {analysis_result.get('success_variable', '?')}")
        lines.append(f"- **施打者變數:** {analysis_result.get('operator_variable', '?')}")
        lines.append(f"- **次序變數:** {analysis_result.get('trial_variable', '?')}")
        lines.append(
            f"- **目標成功率:** {float(analysis_result.get('target_success_rate', 0.0)):.1%}"
        )
        lines.append(
            f"- **cohort 成功率:** {float(analysis_result.get('cohort_success_rate', 0.0)):.1%}"
        )
        lines.append(f"- **總試次:** {analysis_result.get('total_trials', '?')}")
        lines.append(f"- **施打者數:** {analysis_result.get('operators_analyzed', '?')}")

        operators = analysis_result.get("operators", [])
        if operators:
            lines.append("\n## 施打者 CUSUM 摘要")
            for operator in operators[:10]:
                lines.append(
                    "- **{operator_id}:** n={n_trials}, success={success_rate:.1%}, final CUSUM={final_cusum:.3f}, "
                    "peak={peak_cusum:.3f} (trial {peak_trial})".format(
                        operator_id=operator.get("operator_id", "?"),
                        n_trials=operator.get("n_trials", "?"),
                        success_rate=float(operator.get("success_rate", 0.0)),
                        final_cusum=float(operator.get("final_cusum", 0.0)),
                        peak_cusum=float(operator.get("peak_cusum", 0.0)),
                        peak_trial=operator.get("peak_trial", "?"),
                    )
                )
            if len(operators) > 10:
                lines.append(f"- ... 共 {len(operators)} 位施打者")

        interpretation = analysis_result.get("interpretation")
        if interpretation:
            lines.append(f"\n**解讀:** {interpretation}")
    elif _is_direct_analysis_contract(analysis_result):
        preview = analysis_result.get("data_preview", {})
        column_names = preview.get("column_names", [])
        sample_rows = preview.get("sample_rows", [])

        lines.append("\n## 工作提交摘要")
        lines.append(f"- **job_id:** {analysis_result.get('job_id')}")
        lines.append(f"- **job_type:** {analysis_result.get('job_type')}")
        lines.append(f"- **status:** {analysis_result.get('status')}")
        lines.append(f"- **message:** {analysis_result.get('message')}")

        lines.append("\n## 資料預覽")
        lines.append(f"- **列數:** {preview.get('rows', '?')}")
        lines.append(f"- **欄數:** {preview.get('columns', '?')}")
        if column_names:
            rendered_cols = ", ".join(column_names[:8])
            if len(column_names) > 8:
                rendered_cols += f" ... 共 {len(column_names)} 欄"
            lines.append(f"- **欄位:** {rendered_cols}")
        if sample_rows:
            lines.append(f"- **sample_rows:** {sample_rows}")
        dtypes = preview.get("dtypes")
        if dtypes:
            _append_nested_markdown(lines, "欄位型別", dtypes)
        lines.append(
            "\n這類 direct analyze 回應代表工作已送入 vendor stats-service 佇列；"
            "若要追蹤完成狀態，請用 job_id 查詢 /jobs/{job_id}。"
        )
    elif _is_async_job_contract(analysis_result):
        lines.append("\n## 工作提交摘要")
        lines.append(f"- **job_id:** {analysis_result.get('job_id')}")
        lines.append(f"- **job_type:** {analysis_result.get('job_type')}")
        lines.append(f"- **status:** {analysis_result.get('status')}")
        if "progress" in analysis_result:
            progress = analysis_result.get("progress")
            if isinstance(progress, (int, float)):
                lines.append(f"- **progress:** {float(progress):.1%}")
            else:
                lines.append(f"- **progress:** {progress}")
        status_message = analysis_result.get("status_message") or analysis_result.get("message")
        if status_message:
            lines.append(f"- **message:** {status_message}")
        if analysis_result.get("created_at"):
            lines.append(f"- **created_at:** {analysis_result.get('created_at')}")
        lines.append(
            "\n這類 async job 回應代表工作已送入 vendor 佇列；"
            "若要追蹤完成狀態，請用 job_id 查詢 /jobs/{job_id}。"
        )
    elif isinstance(analysis_result, dict):
        if analysis_result.get("error"):
            lines.append(f"\n**error:** {analysis_result['error']}")
        if analysis_result.get("suggestion"):
            lines.append(f"- **suggestion:** {analysis_result['suggestion']}")
        for key, value in analysis_result.items():
            if key in {"error", "suggestion"}:
                continue
            if isinstance(value, float):
                lines.append(f"- **{key}:** {value:.4f}")
            elif isinstance(value, (int, str)):
                lines.append(f"- **{key}:** {value}")
            else:
                _append_nested_markdown(lines, key, value)
    else:
        lines.append(str(analysis_result))

    if artifact_path is not None:
        lines.append(f"\n**Artifact:** {artifact_path}")

    if not automl_available and source.startswith("local"):
        lines.append(
            "\n💡 **提示:** automl-stat-mcp 未啟動或不可用；"
            "目前使用本地 fallback，引擎能力可能受限。"
            "啟動方式: `cd vendor/automl-stat-mcp && docker compose --profile ml up -d`"
        )

    return "\n".join(lines)


def _auto_log_decision(
    tool_name: str,
    parameters: dict[str, Any],
    rationale: str,
    result_summary: str,
    artifacts: list[str] | None = None,
) -> None:
    """H-009: Auto-enforce decision logging for every Phase 6 operation.

    Also checks plan adherence (H-007/S-011): if the operation is not
    in the locked analysis plan, auto-logs a deviation entry.
    """
    from rde.application.session import get_session
    from rde.interface.mcp.tools._shared.project_context import (
        compute_phase6_progress,
        mark_phase6_complete_if_ready,
        save_phase6_progress,
    )

    session = get_session()
    project = session.get_project()
    pipeline = session.get_pipeline(project.id)
    logger = session.get_logger(project.id)
    logger.log_decision(
        phase="phase_06",
        action=tool_name,
        tool_used=tool_name,
        parameters=parameters,
        rationale=rationale,
        result_summary=result_summary,
        artifacts=artifacts,
    )

    progress = compute_phase6_progress(project)
    progress, progress_path = save_phase6_progress(
        project,
        progress,
        last_action={
            "tool": tool_name,
            "parameters": parameters,
            "result_summary": result_summary,
        },
    )
    mark_phase6_complete_if_ready(project, pipeline, progress, progress_path)

    # Auto-detect plan deviation (S-011)
    if pipeline.plan_locked:
        from rde.interface.mcp.tools._shared import check_plan_adherence

        in_plan, deviation_msg = check_plan_adherence(project, tool_name, parameters)
        if not in_plan:
            logger.log_deviation(
                phase="phase_06",
                planned_action="(按分析計畫執行)",
                actual_action=f"{tool_name}({parameters})",
                reason=f"[S-011 自動偵測] {deviation_msg}",
                impact_assessment="需在審計時確認此偏離的合理性",
            )


# _suggest_viz_type and _suggest_outlier_strategy removed — logic moved to AnalyzeVariableUseCase.


def register_analysis_tools(server: Any) -> None:
    """Register statistical analysis MCP tools."""

    @server.tool()
    def suggest_cleaning(dataset_id: str) -> str:
        """根據品質評估建議資料清理策略。

        根據 assess_quality() 的結果，自動建議清理動作（如移除高缺失欄位、填補中位數、去重）。
        建議需經用戶確認後，以 apply_cleaning() 執行。

        Args:
            dataset_id: 已評估品質的資料集 ID（先執行 assess_quality）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("suggest_cleaning", {"dataset_id": dataset_id})

        ok, msg, project, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)
        assert project is not None
        assert entry is not None

        if entry.quality_report is None:
            return fmt_error("請先執行 `assess_quality()` 再建議清理策略。")

        try:
            from rde.domain.models.cleaning import (
                CleaningAction,
                CleaningActionType,
                CleaningPlan,
            )

            plan = CleaningPlan(dataset_id=dataset_id)

            for issue in entry.quality_report.issues:
                if issue.category.value == "completeness" and issue.variable_name:
                    if issue.severity.value == "critical":
                        plan.add_action(
                            CleaningAction(
                                action_type=CleaningActionType.DROP_COLUMNS,
                                target_variable=issue.variable_name,
                                description=f"移除缺失值過多的欄位: {issue.variable_name}",
                                rationale=issue.description,
                            )
                        )
                    else:
                        plan.add_action(
                            CleaningAction(
                                action_type=CleaningActionType.FILL_MEDIAN,
                                target_variable=issue.variable_name,
                                description=f"以中位數填補缺失值: {issue.variable_name}",
                                rationale=issue.description,
                            )
                        )
                elif issue.category.value == "uniqueness":
                    plan.add_action(
                        CleaningAction(
                            action_type=CleaningActionType.REMOVE_DUPLICATES,
                            target_variable=None,
                            description="移除重複列",
                            rationale=issue.description,
                        )
                    )

            entry.cleaning_plan = plan

            if not plan.actions:
                return "✅ 資料品質良好，無需清理建議。"

            lines = [
                "# 🧹 清理建議\n",
                f"共 {len(plan.actions)} 項建議：\n",
            ]
            for i, a in enumerate(plan.actions):
                lines.append(
                    f"{i}. **[{a.action_type.value}]** {a.description}\n   理由: {a.rationale}\n"
                )

            lines.append(
                "\n**下一步:** 使用 `apply_cleaning(dataset_id, approved_indices=[0,1,...])` "
                "執行核准的清理動作。"
            )

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("suggest_cleaning", e)
            return fmt_error(f"清理建議失敗: {e}")

    @server.tool()
    def apply_cleaning(dataset_id: str, approved_indices: list[int]) -> str:
        """執行用戶已確認的清理操作。

        執行由 suggest_cleaning() 建議、用戶核准的清理動作。
        支援 14 種清理動作（DROP/FILL/CLIP/ENCODE 等）。H-009 自動記錄。

        Args:
            dataset_id: 資料集 ID（已執行 suggest_cleaning）
            approved_indices: 核准的清理動作索引列表，如 [0, 1, 3]（對應 suggest_cleaning 報告中的編號）
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
            "apply_cleaning",
            {
                "dataset_id": dataset_id,
                "approved_indices": approved_indices,
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

        if entry.cleaning_plan is None:
            return fmt_error("請先執行 `suggest_cleaning()` 取得清理建議。")

        try:
            from rde.infrastructure.adapters import CleaningExecutor

            entry.cleaning_plan.approve_by_index(approved_indices)

            executor = CleaningExecutor()
            cleaned_df, logs = executor.execute(entry.dataframe, entry.cleaning_plan)

            rows_before = logs[0]["rows_before"] if logs else len(entry.dataframe)
            entry.dataframe = cleaned_df
            entry.dataset.mark_cleaned()
            entry.dataset.row_count = len(cleaned_df)

            _auto_log_decision(
                "apply_cleaning",
                {"approved_indices": approved_indices},
                "執行用戶核准的清理動作",
                f"rows: {rows_before} → {len(cleaned_df)}",
            )

            actions_applied = len(
                [log_entry for log_entry in logs if log_entry["status"] == "applied"]
            )

            return fmt_success(
                f"清理完成: {actions_applied} 項動作已執行",
                f"- **清理前列數:** {rows_before:,}\n"
                f"- **清理後列數:** {len(cleaned_df):,}\n"
                f"- **已執行動作:** {actions_applied}",
            )

        except Exception as e:
            log_tool_error("apply_cleaning", e)
            return fmt_error(f"清理失敗: {e}")

    @server.tool()
    def analyze_variable(dataset_id: str, variable_name: str) -> str:
        """分析單一變數的分佈與描述統計。

        自動判斷常態性 (S-001)、建議轉換 (S-004)、偵測極端值 (S-006)、
        建議圖表類型 (S-003)。H-009 自動記錄。

        Args:
            dataset_id: 資料集 ID（由 load_dataset 或 run_intake 回傳）
            variable_name: 要分析的變數名稱，如 "age"、"sofa_score"、"treatment_group"
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            fmt_table,
            ensure_minimum_sample_size,
            ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("analyze_variable", {"variable_name": variable_name})

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

        try:
            from rde.application.use_cases.analyze_variable import AnalyzeVariableUseCase
            from rde.infrastructure.adapters import ScipyStatisticalEngine

            engine = ScipyStatisticalEngine()
            use_case = AnalyzeVariableUseCase(engine)
            profile = use_case.execute(entry.dataset, entry.dataframe, variable_name)

            lines = [f"# 📊 單變數分析 — `{profile.variable_name}`\n"]
            lines.append(f"- **觀測數:** {profile.count}")
            lines.append(f"- **缺失:** {profile.missing_count} ({profile.missing_rate:.1%})")
            lines.append(f"- **唯一值:** {profile.n_unique}")

            if profile.descriptive:
                d = profile.descriptive
                lines.append("\n## 描述統計")
                lines.append(
                    fmt_table(
                        ["統計量", "值"],
                        [
                            ["平均值", f"{d['mean']:.4f}"],
                            ["標準差", f"{d['std']:.4f}"],
                            ["最小值", f"{d['min']:.4f}"],
                            ["25%", f"{d['q1']:.4f}"],
                            ["中位數", f"{d['median']:.4f}"],
                            ["75%", f"{d['q3']:.4f}"],
                            ["最大值", f"{d['max']:.4f}"],
                            ["偏態", f"{d['skewness']:.4f}"],
                            ["峰度", f"{d['kurtosis']:.4f}"],
                        ],
                    )
                )

                if profile.normality_test:
                    nt = profile.normality_test
                    is_normal = nt.p_value > 0.05
                    icon = "✅" if is_normal else "⚠️"
                    lines.append(
                        f"\n{icon} **[S-001] 常態性:** Shapiro-Wilk p = {nt.p_value:.4f} "
                        f"({'常態' if is_normal else '非常態 — 建議無母數檢定'})"
                    )

            elif profile.top_values:
                lines.append(f"\n## 類別分佈 (前 {len(profile.top_values)})")
                lines.append(
                    fmt_table(
                        ["值", "計數"],
                        [[val, cnt] for val, cnt in profile.top_values],
                    )
                )

            if profile.advisories:
                lines.append("\n## 💡 建議")
                for a in profile.advisories:
                    lines.append(f"- {a}")

            if profile.viz_suggestion:
                lines.append(f"- [S-003] 建議圖表: {profile.viz_suggestion}")

            # H-009: Auto-log
            _auto_log_decision(
                "analyze_variable",
                {"variable_name": variable_name},
                "單變數分析",
                f"{variable_name}: {profile.variable_type}",
            )

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("analyze_variable", e)
            return fmt_error(f"分析失敗: {e}")

    @server.tool()
    def compare_groups(
        dataset_id: str,
        outcome_variables: list[str],
        group_variable: str,
        is_paired: bool = False,
    ) -> str:
        """組間比較，自動選擇適當統計檢定。

        自動應用: S-001 (常態性 → 有母數/無母數), S-002 (多重比較),
        S-008 (樣本平衡), S-009 (effect size), S-010 (power)。H-009 自動記錄。
        若操作不在已鎖定計畫中，自動偵測偏離並記錄 (S-011)。

        Args:
            dataset_id: 資料集 ID
            outcome_variables: 要比較的結果變數列表，如 ["sofa_score", "mortality"]
            group_variable: 分組變數，如 "treatment_group"、"gender"
            is_paired: 是否為配對資料（如前後測），預設 false
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call(
            "compare_groups",
            {
                "outcome_variables": outcome_variables,
                "group_variable": group_variable,
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

        try:
            from rde.application.use_cases.compare_groups import CompareGroupsUseCase
            from rde.infrastructure.adapters import ScipyStatisticalEngine

            engine = ScipyStatisticalEngine()
            use_case = CompareGroupsUseCase(engine)
            analysis_df, plausibility_notes, plausibility_summary = _sanitize_analysis_frame(
                entry.dataframe,
                [*outcome_variables, group_variable],
            )

            result = use_case.execute(
                dataset=entry.dataset,
                raw_data=analysis_df,
                outcome_variables=outcome_variables,
                group_variable=group_variable,
                is_paired=is_paired,
            )

            entry.analysis_results.append(result)

            lines = [f"# 📊 組間比較 — by `{group_variable}`\n"]

            # S-008: Sample balance check
            df = analysis_df
            group_counts = df[group_variable].value_counts()
            min_n = group_counts.min()
            max_n = group_counts.max()
            if max_n > 0 and min_n / max_n < 0.5:
                lines.append(
                    f"⚠️ **[S-008] 組間不平衡:** "
                    f"最小組 n={min_n}, 最大組 n={max_n}。"
                    f"考慮使用加權分析或 bootstrap。\n"
                )

            for t in result.tests:
                sig_icon = "🟢" if t.is_significant else "⚪"
                lines.append(f"## {sig_icon} {', '.join(t.variables_involved)}")
                lines.append(f"- **檢定:** {t.test_name}")
                lines.append(f"- **統計量:** {t.statistic:.4f}")
                lines.append(f"- **p 值:** {t.p_value:.4f}")

                # S-009: Effect size
                if t.effect_size is not None:
                    lines.append(f"- **效果量 ({t.effect_size_name}):** {t.effect_size:.3f}")
                else:
                    lines.append("- ⚠️ [S-009] 未計算效果量")

                lines.append(f"- **解讀:** {t.interpretation}")

                # S-010: Compute post-hoc power for non-significant results
                if not t.is_significant and t.effect_size is not None:
                    try:
                        total_n = len(df[group_variable].dropna())
                        n_groups = df[group_variable].nunique()
                        power_result = engine.post_hoc_power(
                            test_name=t.test_name,
                            effect_size=abs(t.effect_size),
                            n=total_n,
                            n_groups=n_groups,
                        )
                        pw = power_result["power"]
                        lines.append(
                            f"- 💡 [S-010] 檢定力 = {pw:.1%}"
                            f" {'(足夠)' if power_result['adequate'] else '(不足 — 可能 Type II error)'}"
                        )
                    except Exception:
                        lines.append("- 💡 [S-010] 結果不顯著，建議進行檢定力分析。")
                lines.append("")

            # S-002: Multiple comparisons
            if len(result.tests) > 1:
                lines.append(
                    f"⚠️ **[S-002] 多重比較:** {len(result.tests)} 個檢定，"
                    f"結果已/應進行 Bonferroni 或 FDR 校正。"
                )

            if result.warnings:
                lines.append("\n**警告:**")
                for w in result.warnings:
                    lines.append(f"- {w}")

            if plausibility_notes:
                lines.append("\n## 資料合理性防護")
                for note in plausibility_notes:
                    lines.append(f"- {note}")

            # H-009
            _auto_log_decision(
                "compare_groups",
                {"outcome_variables": outcome_variables, "group_variable": group_variable},
                "組間比較分析",
                (
                    f"{len(result.tests)} tests, {len(result.significant_tests)} significant"
                    + (f"; {plausibility_summary}" if plausibility_summary else "")
                ),
            )

            return "\n".join(lines)

        except ValueError as e:
            return fmt_error(str(e))
        except Exception as e:
            log_tool_error("compare_groups", e)
            return fmt_error(f"組間比較失敗: {e}")

    @server.tool()
    def correlation_matrix(
        dataset_id: str,
        variables: list[str] | None = None,
    ) -> str:
        """計算相關性矩陣，自動檢查共線性 (S-007)。H-009 自動記錄。

        若發現 VIF > 10 的變數對，會給出警告並建議移除。

        Args:
            dataset_id: 資料集 ID
            variables: 要分析的數值變數列表，如 ["age", "bmi", "creatinine"]（可選，空則分析所有數值變數）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            fmt_table,
            ensure_minimum_sample_size,
            ensure_phase_ready,
        )
        import pandas as pd
        from rde.application.pipeline import PipelinePhase

        log_tool_call("correlation_matrix", {"variables": variables})

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

        try:
            from rde.domain.services.collinearity_checker import check_collinearity

            df = entry.dataframe
            if variables:
                numeric_cols = [
                    v for v in variables if v in df.columns and pd.api.types.is_numeric_dtype(df[v])
                ]
            else:
                numeric_cols = df.select_dtypes(include="number").columns.tolist()

            if len(numeric_cols) < 2:
                return fmt_error("需要至少 2 個數值變數進行相關性分析。")

            analysis_df, plausibility_notes, plausibility_summary = _sanitize_analysis_frame(
                df,
                numeric_cols,
            )

            corr = analysis_df[numeric_cols].corr()

            lines = ["# 📊 相關性矩陣\n"]

            # Build table via fmt_table
            header = [""] + numeric_cols
            rows = []
            for row_name in numeric_cols:
                rows.append([row_name] + [f"{corr.loc[row_name, c]:.3f}" for c in numeric_cols])
            lines.append(fmt_table(header, rows))

            # S-007: Collinearity check (delegated to domain service)
            report = check_collinearity(analysis_df, numeric_cols)
            if report.has_collinearity:
                lines.append("\n## ⚠️ [S-007] 高共線性")
                for w in report.format_warnings():
                    lines.append(f"- {w}")
                lines.append("\n建議: 考慮移除一個變數或使用 VIF 進一步評估。")

            if plausibility_notes:
                lines.append("\n## 資料合理性防護")
                for note in plausibility_notes:
                    lines.append(f"- {note}")

            # H-009
            _auto_log_decision(
                "correlation_matrix",
                {"variables": numeric_cols},
                "相關性矩陣分析",
                (
                    f"{len(numeric_cols)} vars, {len(report.pairs)} collinear pairs"
                    + (f"; {plausibility_summary}" if plausibility_summary else "")
                ),
            )

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("correlation_matrix", e)
            return fmt_error(f"相關性分析失敗: {e}")

    @server.tool()
    def generate_table_one(
        dataset_id: str,
        group_variable: str,
        variables: list[str] | None = None,
    ) -> str:
        """生成 Table 1（基線特徵表）。H-009 自動記錄。

        使用 tableone 套件生成標準化的基線特徵表，
        自動判斷類別/連續變數並選擇適當的檢定方法。

        Args:
            dataset_id: 資料集 ID
            group_variable: 分組變數，如 "treatment_group"、"disease_severity"
            variables: 要納入 Table 1 的變數列表（可選，空則納入分組變數以外的所有變數）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            ensure_minimum_sample_size,
            ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call(
            "generate_table_one",
            {
                "group_variable": group_variable,
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

        df = entry.dataframe
        if group_variable not in df.columns:
            return fmt_error(f"分組變數 '{group_variable}' 不存在。")

        try:
            from rde.infrastructure.adapters import ScipyStatisticalEngine
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            if variables:
                cols = [v for v in variables if v in df.columns]
            else:
                cols = [c for c in df.columns if c != group_variable]

            analysis_df, plausibility_notes, plausibility_summary = _sanitize_analysis_frame(
                df,
                [*cols, group_variable],
            )

            engine = ScipyStatisticalEngine()
            result = engine.generate_table_one(analysis_df, group_variable, cols)

            if "error" in result:
                return fmt_error(result["error"])

            lines = [
                f"# 📊 Table 1 — 基線特徵 by `{group_variable}`\n",
            ]

            # Use pre-rendered text table from tableone
            table_text = result.get("table_text")
            if table_text:
                lines.append(f"```\n{table_text}\n```")
            else:
                # Fallback: render from table_dict
                table_data = result.get("table_dict", {})
                if table_data:
                    # Extract column headers from first row
                    first_key = next(iter(table_data))
                    col_headers = list(table_data[first_key].keys())
                    header = [""] + col_headers
                    lines.append("| " + " | ".join(str(h) for h in header) + " |")
                    lines.append("| " + " | ".join("---" for _ in header) + " |")
                    for row_name, row_vals in table_data.items():
                        vals = [str(row_vals.get(c, "")) for c in col_headers]
                        lines.append(f"| {row_name} | " + " | ".join(vals) + " |")
                else:
                    lines.append("*Table 1 資料為空。*")

            lines.append(
                f"\n- **分組變數:** {group_variable}"
                f"\n- **變數數:** {result.get('n_variables', len(cols))}"
                f"\n- **類別變數:** {result.get('n_categorical', 0)}"
            )

            if plausibility_notes:
                lines.append("\n## 資料合理性防護")
                for note in plausibility_notes:
                    lines.append(f"- {note}")

            table_one_content = "\n".join(lines)
            store = ArtifactStore(project.artifacts_dir)
            table_one_md_path = store.save(
                PipelinePhase.EXECUTE_EXPLORATION,
                "table_one.md",
                table_one_content,
            )
            store.save(
                PipelinePhase.EXECUTE_EXPLORATION,
                "table_one.json",
                {
                    "group_variable": group_variable,
                    "variables": cols,
                    "table_text": result.get("table_text", ""),
                    "table_dict": result.get("table_dict", {}),
                    "n_variables": result.get("n_variables", len(cols)),
                    "n_categorical": result.get("n_categorical", 0),
                },
            )

            lines.append(f"\n**Artifact:** {table_one_md_path}")

            # H-009
            _auto_log_decision(
                "generate_table_one",
                {"group_variable": group_variable, "variables": cols},
                "生成 Table 1 (基線特徵表)",
                (
                    f"Table 1: {result.get('n_variables', len(cols))} variables"
                    + (f"; {plausibility_summary}" if plausibility_summary else "")
                ),
                artifacts=[str(table_one_md_path)],
            )

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("generate_table_one", e)
            return fmt_error(f"Table 1 生成失敗: {e}")

    @server.tool()
    def run_advanced_analysis(
        dataset_id: str,
        analysis_type: str,
        target_variable: str | None = None,
        group_variable: str | None = None,
        covariates: list[str] | None = None,
        time_variable: str | None = None,
        score_variable: str | None = None,
        problem_type: str | None = None,
        endpoint: str | None = None,
        test_type: str | None = None,
        vendor_options: dict[str, Any] | None = None,
    ) -> str:
        """執行進階統計分析，自動委派給 automl-stat-mcp（如可用）。

        支援: propensity_score, survival_analysis, roc_auc,
        logistic_regression, multiple_regression, power_analysis_advanced。
        automl 不可用時自動降級為本地 ScipyStatisticalEngine。
        H-009 自動記錄 + S-011 偏離自動偵測。

        Args:
            dataset_id: 資料集 ID
            analysis_type: 分析類型，如 "propensity_score"、"survival_analysis"、"roc_auc"、"logistic_regression"
            target_variable: 目標變數（如 outcome），如 "mortality"、"readmission"（可選）
            group_variable: 分組變數，如 "treatment"（可選）
            covariates: 共變量列表，如 ["age", "sex", "bmi"]（可選）
            time_variable: survival / learning-curve 類型使用的時間或次序欄位（可選）
            score_variable: ROC 類型使用的風險分數欄位（可選）
            problem_type: AutoML 類型可顯式指定 binary / multiclass / regression（可選）
            endpoint: vendor 子端點，如 propensity full / survival cox / roc compare（可選）
            test_type: power analysis 的 test 類型，如 ttest / anova / chisquare / survival（可選）
            vendor_options: 原樣傳遞給 vendor adapter 的額外參數（可選）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            ensure_minimum_sample_size,
            ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call(
            "run_advanced_analysis",
            {
                "analysis_type": analysis_type,
                "target_variable": target_variable,
                "group_variable": group_variable,
                "time_variable": time_variable,
                "score_variable": score_variable,
                "problem_type": problem_type,
                "endpoint": endpoint,
                "test_type": test_type,
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

        try:
            from rde.infrastructure.adapters import get_analysis_delegator

            delegator = get_analysis_delegator()

            config: dict = {
                "variables": [],
                "project_name": f"rde_{dataset_id}",
                "user_id": f"rde-{project.id}",
            }
            if target_variable:
                config["variables"].append(target_variable)
                config["target"] = target_variable
            if group_variable:
                config["group_var"] = group_variable
                if group_variable not in config["variables"]:
                    config["variables"].append(group_variable)
            if covariates:
                config["covariates"] = covariates
                config["variables"].extend(covariates)
            if time_variable:
                config["time_variable"] = time_variable
                config["variables"].append(time_variable)
                if _normalize_analysis_type(analysis_type) == "learning_curve_cusum":
                    config["trial_var"] = time_variable
            if score_variable:
                config["score_variable"] = score_variable
                config["variables"].append(score_variable)
            if problem_type:
                config["problem_type"] = problem_type
            if endpoint:
                config["endpoint"] = endpoint
            if test_type:
                config["test_type"] = test_type
            if vendor_options:
                config.update(
                    {key: value for key, value in vendor_options.items() if value is not None}
                )

            config["variables"] = list(dict.fromkeys(config["variables"]))

            analysis_df, plausibility_notes, plausibility_summary = _sanitize_analysis_frame(
                entry.dataframe,
                config["variables"],
            )

            result = delegator.run_analysis(analysis_df, analysis_type, config)

            source = result["source"]
            analysis_result = result["result"]

            artifact_path = _save_advanced_analysis_artifact(
                project,
                dataset_id=dataset_id,
                analysis_type=analysis_type,
                source=source,
                config=config,
                analysis_result=analysis_result,
            )

            rendered_output = _format_advanced_analysis_output(
                analysis_type=analysis_type,
                source=source,
                analysis_result=analysis_result,
                artifact_path=artifact_path,
                automl_available=delegator.automl_available,
            )
            if plausibility_notes:
                rendered_output += "\n\n## 資料合理性防護\n" + "\n".join(
                    f"- {note}" for note in plausibility_notes
                )
            markdown_artifact_path = _save_advanced_analysis_markdown_artifact(
                project,
                analysis_type=analysis_type,
                analysis_result=analysis_result,
                content=rendered_output,
            )

            decision_summary = _summarize_advanced_analysis_result(analysis_result)

            # H-009
            _auto_log_decision(
                "run_advanced_analysis",
                {
                    "analysis_type": analysis_type,
                    "source": source,
                    "target_variable": target_variable,
                    "group_variable": group_variable,
                    "variables": [
                        value
                        for value in [target_variable, group_variable, *(covariates or [])]
                        if value
                    ],
                },
                f"進階分析: {analysis_type}",
                (
                    f"source={source}; {decision_summary}"
                    + (f"; {plausibility_summary}" if plausibility_summary else "")
                ),
                artifacts=[artifact_path.name, markdown_artifact_path.name],
            )

            return rendered_output

        except Exception as e:
            log_tool_error("run_advanced_analysis", e)
            return fmt_error(f"進階分析失敗: {e}")

    @server.tool()
    def run_repeated_measures(
        dataset_id: str,
        variables: str,
        alpha: float = 0.05,
    ) -> str:
        """對重複測量變數進行 Friedman 檢定（含 post-hoc Wilcoxon + Bonferroni 校正）。

        適用於同一受試者在多個時間點的測量（如生物標記 0h/4h/24h）。
        自動計算 Kendall's W 效果量和所有配對的 post-hoc 比較。
        H-009 自動記錄 + S-011 偏離自動偵測。

        Args:
            dataset_id: 已載入的資料集 ID
            variables: 逗號分隔的重複測量欄位名稱（至少 3 個），例如 "ngal_0hr,ngal_4hr,ngal_24hr"
            alpha: 顯著水準（預設 0.05），用於判定顯著性和 Bonferroni 校正
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call,
            log_tool_error,
            fmt_error,
            fmt_table,
            ensure_minimum_sample_size,
            ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call(
            "run_repeated_measures",
            {
                "dataset_id": dataset_id,
                "variables": variables,
                "alpha": alpha,
            },
        )

        ok, msg, _, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)
        assert entry is not None
        ok, msg = ensure_minimum_sample_size(entry)
        if not ok:
            return fmt_error(msg)

        var_list = [v.strip() for v in variables.split(",") if v.strip()]
        if len(var_list) < 3:
            return fmt_error("至少需要 3 個重複測量變數（如 0h, 4h, 24h）。")

        # Validate columns exist
        missing_cols = [v for v in var_list if v not in entry.dataframe.columns]
        if missing_cols:
            return fmt_error(f"找不到欄位: {', '.join(missing_cols)}")

        try:
            from rde.infrastructure.adapters import ScipyStatisticalEngine

            engine = ScipyStatisticalEngine()
            analysis_df, plausibility_notes, plausibility_summary = _sanitize_analysis_frame(
                entry.dataframe,
                var_list,
            )
            result = engine.run_test(
                analysis_df,
                "Friedman test",
                var_list,
                alpha=alpha,
            )

            lines = ["# 📊 重複測量分析 — Friedman 檢定\n"]
            lines.append(f"**變數:** {', '.join(var_list)}")
            lines.append(f"**完整配對數:** {result.get('n_complete', '?')}\n")

            # Main test result
            p = result.get("p_value", 1.0)
            w = result.get("effect_size", 0)
            stat = result.get("statistic", 0)
            sig = "✅ 顯著" if p < alpha else "— 不顯著"

            lines.append("## 主檢定")
            lines.append(
                fmt_table(
                    ["統計量", "值"],
                    [
                        ["Friedman χ²", f"{stat:.3f}"],
                        ["p-value", f"{p:.6f}"],
                        ["Kendall's W", f"{w:.3f}"],
                        ["判定", sig],
                    ],
                )
            )

            # Effect size interpretation
            if w < 0.1:
                w_interp = "微小"
            elif w < 0.3:
                w_interp = "小"
            elif w < 0.5:
                w_interp = "中"
            else:
                w_interp = "大"
            lines.append(f"\n**效果量解讀:** Kendall's W = {w:.3f} ({w_interp}效果)")

            # Per-timepoint descriptives
            if "descriptives" in result:
                lines.append("\n## 各時間點描述統計")
                desc_rows = []
                for tp in result["descriptives"]:
                    desc_rows.append(
                        [
                            tp.get("variable", "?"),
                            f"{tp.get('n', '?')}",
                            f"{tp.get('median', 0):.4f}",
                            f"{tp.get('q25', 0):.4f}–{tp.get('q75', 0):.4f}",
                            f"{tp.get('mean', 0):.4f} ± {tp.get('std', 0):.4f}",
                        ]
                    )
                lines.append(
                    fmt_table(
                        ["時間點", "n", "中位數", "IQR", "Mean ± SD"],
                        desc_rows,
                    )
                )

            # Post-hoc pairwise comparisons
            if "post_hoc" in result and result["post_hoc"]:
                lines.append("\n## Post-hoc 配對比較 (Bonferroni 校正)")
                ph_rows = []
                for ph in result["post_hoc"]:
                    adj_p = ph.get("p_adjusted", ph.get("p_value", 1.0))
                    r_eff = ph.get("effect_size", 0)
                    pair_sig = "✅" if adj_p < alpha else "—"
                    ph_rows.append(
                        [
                            ph.get("pair", "?"),
                            f"{ph.get('statistic', 0):.1f}",
                            f"{ph.get('p_value', 1.0):.6f}",
                            f"{adj_p:.6f}",
                            f"{r_eff:.3f}",
                            pair_sig,
                        ]
                    )
                lines.append(
                    fmt_table(
                        ["配對", "W", "p (raw)", "p (adj)", "r", "Sig"],
                        ph_rows,
                    )
                )

            lines.append("\n**[S-001]** 使用非參數 Friedman 檢定（適用於非常態重複測量資料）。")
            if len(var_list) > 2 and p < alpha:
                lines.append(
                    f"**[S-002]** 已對 {len(result.get('post_hoc', []))} 個配對比較"
                    f"進行 Bonferroni 校正 (α = {alpha / len(result.get('post_hoc', [1])):.4f})。"
                )

            if plausibility_notes:
                lines.append("\n## 資料合理性防護")
                for note in plausibility_notes:
                    lines.append(f"- {note}")

            # H-009
            _auto_log_decision(
                "run_repeated_measures",
                {"variables": var_list, "alpha": alpha},
                f"Friedman 檢定: {len(var_list)} 個重複測量時間點",
                f"χ²={stat:.3f}, p={p:.6f}, W={w:.3f}" + (f"; {plausibility_summary}" if plausibility_summary else ""),
            )

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("run_repeated_measures", e)
            return fmt_error(f"重複測量分析失敗: {e}")
