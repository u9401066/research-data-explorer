"""Analysis Tools — Phase 6 (Execute) & Phase 7 (Collect).

All Phase 6 tools auto-log decisions (H-009 enforced).
Soft constraints S-001, S-002, S-003, S-004, S-006, S-007, S-008, S-009, S-010 wired.
All tools return markdown strings.
"""

from __future__ import annotations

from typing import Any


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

    session = get_session()
    project = session.get_project()
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

    # Auto-detect plan deviation (S-011)
    pipeline = session.get_pipeline(project.id)
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
            log_tool_call, log_tool_error,
            fmt_error, ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("suggest_cleaning", {"dataset_id": dataset_id})

        ok, msg, _, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)

        if entry.quality_report is None:
            return fmt_error("請先執行 `assess_quality()` 再建議清理策略。")

        try:
            from rde.domain.models.cleaning import (
                CleaningAction, CleaningActionType, CleaningPlan,
            )

            plan = CleaningPlan(dataset_id=dataset_id)

            for issue in entry.quality_report.issues:
                if issue.category.value == "completeness" and issue.variable_name:
                    if issue.severity.value == "critical":
                        plan.add_action(CleaningAction(
                            action_type=CleaningActionType.DROP_COLUMNS,
                            target_variable=issue.variable_name,
                            description=f"移除缺失值過多的欄位: {issue.variable_name}",
                            rationale=issue.description,
                        ))
                    else:
                        plan.add_action(CleaningAction(
                            action_type=CleaningActionType.FILL_MEDIAN,
                            target_variable=issue.variable_name,
                            description=f"以中位數填補缺失值: {issue.variable_name}",
                            rationale=issue.description,
                        ))
                elif issue.category.value == "uniqueness":
                    plan.add_action(CleaningAction(
                        action_type=CleaningActionType.REMOVE_DUPLICATES,
                        target_variable=None,
                        description="移除重複列",
                        rationale=issue.description,
                    ))

            entry.cleaning_plan = plan

            if not plan.actions:
                return "✅ 資料品質良好，無需清理建議。"

            lines = [
                f"# 🧹 清理建議\n",
                f"共 {len(plan.actions)} 項建議：\n",
            ]
            for i, a in enumerate(plan.actions):
                lines.append(
                    f"{i}. **[{a.action_type.value}]** {a.description}\n"
                    f"   理由: {a.rationale}\n"
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
            log_tool_call, log_tool_error,
            fmt_error, fmt_success, ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("apply_cleaning", {
            "dataset_id": dataset_id, "approved_indices": approved_indices,
        })

        ok, msg, _, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)

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

            actions_applied = len([l for l in logs if l["status"] == "applied"])

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
            log_tool_call, log_tool_error,
            fmt_error, fmt_table, ensure_minimum_sample_size, ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("analyze_variable", {"variable_name": variable_name})

        ok, msg, _, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)
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
                lines.append(f"\n## 描述統計")
                lines.append(fmt_table(
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
                ))

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
                lines.append(fmt_table(
                    ["值", "計數"],
                    [[val, cnt] for val, cnt in profile.top_values],
                ))

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
            log_tool_call, log_tool_error,
            fmt_error, ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("compare_groups", {
            "outcome_variables": outcome_variables,
            "group_variable": group_variable,
        })

        ok, msg, _, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)

        try:
            from rde.application.use_cases.compare_groups import CompareGroupsUseCase
            from rde.infrastructure.adapters import ScipyStatisticalEngine

            engine = ScipyStatisticalEngine()
            use_case = CompareGroupsUseCase(engine)

            result = use_case.execute(
                dataset=entry.dataset,
                raw_data=entry.dataframe,
                outcome_variables=outcome_variables,
                group_variable=group_variable,
                is_paired=is_paired,
            )

            entry.analysis_results.append(result)

            lines = [f"# 📊 組間比較 — by `{group_variable}`\n"]

            # S-008: Sample balance check
            df = entry.dataframe
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
                    lines.append(
                        f"- **效果量 ({t.effect_size_name}):** {t.effect_size:.3f}"
                    )
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
                        lines.append(
                            f"- 💡 [S-010] 結果不顯著，建議進行檢定力分析。"
                        )
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

            # H-009
            _auto_log_decision(
                "compare_groups",
                {"outcome_variables": outcome_variables, "group_variable": group_variable},
                "組間比較分析",
                f"{len(result.tests)} tests, {len(result.significant_tests)} significant",
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
            log_tool_call, log_tool_error,
            fmt_error, fmt_table, ensure_minimum_sample_size, ensure_phase_ready,
        )
        import pandas as pd
        from rde.application.pipeline import PipelinePhase

        log_tool_call("correlation_matrix", {"variables": variables})

        ok, msg, _, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)
        ok, msg = ensure_minimum_sample_size(entry)
        if not ok:
            return fmt_error(msg)

        try:
            from rde.domain.services.collinearity_checker import check_collinearity

            df = entry.dataframe
            if variables:
                numeric_cols = [
                    v for v in variables
                    if v in df.columns and pd.api.types.is_numeric_dtype(df[v])
                ]
            else:
                numeric_cols = df.select_dtypes(include="number").columns.tolist()

            if len(numeric_cols) < 2:
                return fmt_error("需要至少 2 個數值變數進行相關性分析。")

            corr = df[numeric_cols].corr()

            lines = [f"# 📊 相關性矩陣\n"]

            # Build table via fmt_table
            header = [""] + numeric_cols
            rows = []
            for row_name in numeric_cols:
                rows.append(
                    [row_name] + [f"{corr.loc[row_name, c]:.3f}" for c in numeric_cols]
                )
            lines.append(fmt_table(header, rows))

            # S-007: Collinearity check (delegated to domain service)
            report = check_collinearity(df, numeric_cols)
            if report.has_collinearity:
                lines.append("\n## ⚠️ [S-007] 高共線性")
                for w in report.format_warnings():
                    lines.append(f"- {w}")
                lines.append("\n建議: 考慮移除一個變數或使用 VIF 進一步評估。")

            # H-009
            _auto_log_decision(
                "correlation_matrix",
                {"variables": numeric_cols},
                "相關性矩陣分析",
                f"{len(numeric_cols)} vars, {len(report.pairs)} collinear pairs",
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
            log_tool_call, log_tool_error,
            fmt_error, ensure_minimum_sample_size, ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("generate_table_one", {
            "group_variable": group_variable, "variables": variables,
        })

        ok, msg, _, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)
        ok, msg = ensure_minimum_sample_size(entry)
        if not ok:
            return fmt_error(msg)

        df = entry.dataframe
        if group_variable not in df.columns:
            return fmt_error(f"分組變數 '{group_variable}' 不存在。")

        try:
            from rde.infrastructure.adapters import ScipyStatisticalEngine

            if variables:
                cols = [v for v in variables if v in df.columns]
            else:
                cols = [c for c in df.columns if c != group_variable]

            engine = ScipyStatisticalEngine()
            result = engine.generate_table_one(df, group_variable, cols)

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

            # H-009
            _auto_log_decision(
                "generate_table_one",
                {"group_variable": group_variable, "variables": cols},
                "生成 Table 1 (基線特徵表)",
                f"Table 1: {result.get('n_variables', len(cols))} variables",
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
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_error,
            fmt_error, ensure_minimum_sample_size, ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("run_advanced_analysis", {
            "analysis_type": analysis_type,
            "target_variable": target_variable,
            "group_variable": group_variable,
        })

        ok, msg, _, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)
        ok, msg = ensure_minimum_sample_size(entry)
        if not ok:
            return fmt_error(msg)

        try:
            from rde.infrastructure.adapters import get_analysis_delegator

            delegator = get_analysis_delegator()

            config: dict = {
                "variables": [],
                "project_name": f"rde_{dataset_id}",
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

            result = delegator.run_analysis(entry.dataframe, analysis_type, config)

            source = result["source"]
            analysis_result = result["result"]

            lines = [
                f"# 📊 進階分析 — {analysis_type}\n",
                f"**引擎:** {source}\n",
            ]

            # Format result
            if isinstance(analysis_result, dict):
                for key, value in analysis_result.items():
                    if key in ("error", "message"):
                        lines.append(f"**{key}:** {value}")
                    elif isinstance(value, (int, float)):
                        lines.append(f"- **{key}:** {value:.4f}" if isinstance(value, float) else f"- **{key}:** {value}")
                    elif isinstance(value, str):
                        lines.append(f"- **{key}:** {value}")
                    elif isinstance(value, dict):
                        lines.append(f"\n### {key}")
                        for k2, v2 in value.items():
                            lines.append(f"- {k2}: {v2}")
            else:
                lines.append(str(analysis_result))

            if not delegator.automl_available:
                lines.append(
                    "\n💡 **提示:** automl-stat-mcp 未啟動。"
                    "進階分析使用本地引擎（功能可能受限）。"
                    "啟動方式: `cd vendor/automl-stat-mcp && docker compose up -d`"
                )

            # H-009
            _auto_log_decision(
                "run_advanced_analysis",
                {"analysis_type": analysis_type, "source": source},
                f"進階分析: {analysis_type}",
                f"source={source}",
            )

            return "\n".join(lines)

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
            log_tool_call, log_tool_error,
            fmt_error, fmt_success, fmt_table, ensure_minimum_sample_size, ensure_phase_ready,
        )
        from rde.application.pipeline import PipelinePhase

        log_tool_call("run_repeated_measures", {
            "dataset_id": dataset_id, "variables": variables, "alpha": alpha,
        })

        ok, msg, _, entry = ensure_phase_ready(
            PipelinePhase.EXECUTE_EXPLORATION,
            dataset_id=dataset_id,
            require_dataset=True,
        )
        if not ok:
            return fmt_error(msg)
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
            result = engine.run_test(
                entry.dataframe,
                "Friedman test",
                var_list,
                alpha=alpha,
            )

            lines = [f"# 📊 重複測量分析 — Friedman 檢定\n"]
            lines.append(f"**變數:** {', '.join(var_list)}")
            lines.append(f"**完整配對數:** {result.get('n_complete', '?')}\n")

            # Main test result
            p = result.get("p_value", 1.0)
            w = result.get("effect_size", 0)
            stat = result.get("statistic", 0)
            sig = "✅ 顯著" if p < alpha else "— 不顯著"

            lines.append("## 主檢定")
            lines.append(fmt_table(
                ["統計量", "值"],
                [
                    ["Friedman χ²", f"{stat:.3f}"],
                    ["p-value", f"{p:.6f}"],
                    ["Kendall's W", f"{w:.3f}"],
                    ["判定", sig],
                ],
            ))

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
                    desc_rows.append([
                        tp.get("variable", "?"),
                        f"{tp.get('n', '?')}",
                        f"{tp.get('median', 0):.4f}",
                        f"{tp.get('q25', 0):.4f}–{tp.get('q75', 0):.4f}",
                        f"{tp.get('mean', 0):.4f} ± {tp.get('std', 0):.4f}",
                    ])
                lines.append(fmt_table(
                    ["時間點", "n", "中位數", "IQR", "Mean ± SD"],
                    desc_rows,
                ))

            # Post-hoc pairwise comparisons
            if "post_hoc" in result and result["post_hoc"]:
                lines.append("\n## Post-hoc 配對比較 (Bonferroni 校正)")
                ph_rows = []
                for ph in result["post_hoc"]:
                    adj_p = ph.get("p_adjusted", ph.get("p_value", 1.0))
                    r_eff = ph.get("effect_size", 0)
                    pair_sig = "✅" if adj_p < alpha else "—"
                    ph_rows.append([
                        ph.get("pair", "?"),
                        f"{ph.get('statistic', 0):.1f}",
                        f"{ph.get('p_value', 1.0):.6f}",
                        f"{adj_p:.6f}",
                        f"{r_eff:.3f}",
                        pair_sig,
                    ])
                lines.append(fmt_table(
                    ["配對", "W", "p (raw)", "p (adj)", "r", "Sig"],
                    ph_rows,
                ))

            lines.append(f"\n**[S-001]** 使用非參數 Friedman 檢定（適用於非常態重複測量資料）。")
            if len(var_list) > 2 and p < alpha:
                lines.append(
                    f"**[S-002]** 已對 {len(result.get('post_hoc', []))} 個配對比較"
                    f"進行 Bonferroni 校正 (α = {alpha/len(result.get('post_hoc', [1])):.4f})。"
                )

            # H-009
            _auto_log_decision(
                "run_repeated_measures",
                {"variables": var_list, "alpha": alpha},
                f"Friedman 檢定: {len(var_list)} 個重複測量時間點",
                f"χ²={stat:.3f}, p={p:.6f}, W={w:.3f}",
            )

            return "\n".join(lines)

        except Exception as e:
            log_tool_error("run_repeated_measures", e)
            return fmt_error(f"重複測量分析失敗: {e}")
