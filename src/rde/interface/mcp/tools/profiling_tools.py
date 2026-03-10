"""Profiling Tools — Phase 2 (Schema Registry) profiling & quality assessment.

All tools return markdown strings.
"""

from __future__ import annotations

from typing import Any


def register_profiling_tools(server: Any) -> None:
    """Register data profiling MCP tools."""

    @server.tool()
    def profile_dataset(dataset_id: str) -> str:
        """生成資料集的完整 profiling 報告（ydata-profiling）。

        產出每個變數的分佈、缺失模式、相關性矩陣，並偵測高缺失率變數。
        若 ydata-profiling 未安裝，自動降級為 pandas 基礎 profiling。

        Args:
            dataset_id: 已載入的資料集 ID（由 load_dataset 或 run_intake 回傳）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_result, log_tool_error,
            fmt_error, fmt_table, ensure_dataset,
        )

        log_tool_call("profile_dataset", {"dataset_id": dataset_id})

        ok, msg, entry = ensure_dataset(dataset_id)
        if not ok:
            return fmt_error(msg)

        try:
            from rde.application.use_cases.profile_dataset import ProfileDatasetUseCase
            from rde.infrastructure.adapters import YDataProfiler

            try:
                profiler = YDataProfiler()
                use_case = ProfileDatasetUseCase(profiler)
                profile, summary = use_case.execute(entry.dataset, entry.dataframe)
                entry.profile = profile
            except ImportError:
                # Fallback: basic profiling without ydata-profiling
                import pandas as pd
                from rde.domain.models.profile import DataProfile, VariableProfile

                df = entry.dataframe
                dup_count = int(df.duplicated().sum())

                var_profiles = []
                for v in entry.dataset.variables:
                    col = df[v.name] if v.name in df.columns else None
                    vp_kwargs: dict = {
                        "variable_name": v.name,
                        "count": int(col.count()) if col is not None else 0,
                        "missing_count": v.n_missing,
                        "missing_rate": v.n_missing / max(1, entry.dataset.row_count),
                        "unique_count": v.n_unique,
                        "dtype": v.dtype,
                    }
                    if col is not None and pd.api.types.is_numeric_dtype(col):
                        desc = col.describe()
                        vp_kwargs.update({
                            "mean": float(desc.get("mean", 0)),
                            "std": float(desc.get("std", 0)),
                            "min_val": float(desc.get("min", 0)),
                            "max_val": float(desc.get("max", 0)),
                            "median": float(desc.get("50%", 0)),
                            "q1": float(desc.get("25%", 0)),
                            "q3": float(desc.get("75%", 0)),
                            "skewness": float(col.skew()),
                            "kurtosis": float(col.kurtosis()),
                        })
                    elif col is not None:
                        vc = col.value_counts().head(10)
                        vp_kwargs["top_values"] = tuple(
                            (str(k), int(cnt)) for k, cnt in vc.items()
                        )
                        vp_kwargs["mode"] = str(vc.index[0]) if len(vc) > 0 else None

                    var_profiles.append(VariableProfile(**vp_kwargs))

                profile = DataProfile(
                    dataset_id=entry.dataset.id,
                    created_at=__import__("datetime").datetime.now(),
                    row_count=entry.dataset.row_count,
                    column_count=len(entry.dataset.variables),
                    variable_profiles=tuple(var_profiles),
                    duplicate_row_count=dup_count,
                    engine="basic-fallback",
                )
                entry.profile = profile

                # Fallback has no separate summary — we build the table
                # directly below using profile + dataset.variables.
                summary = None

            high_missing = profile.variables_with_high_missing()

            # Build variable table — works for both ydata and fallback paths
            headers = ["變數", "類型", "dtype", "缺失率", "唯一值", "PII"]
            rows = []
            if summary is not None and hasattr(summary, "variables"):
                # ydata path: summary object has .variables
                for v in summary.variables:
                    pii = "⚠️" if v.is_pii_suspect else ""
                    rows.append([
                        v.name, v.variable_type, v.dtype,
                        f"{v.missing_rate:.1%}", v.n_unique, pii,
                    ])
            else:
                # Fallback: build from profile + dataset
                var_map = {v.name: v for v in entry.dataset.variables}
                for vp in profile.variable_profiles:
                    dv = var_map.get(vp.variable_name)
                    pii = "⚠️" if (dv and dv.is_pii_suspect) else ""
                    var_type = dv.variable_type.value if dv else "unknown"
                    rows.append([
                        vp.variable_name, var_type, vp.dtype,
                        f"{vp.missing_rate:.1%}", vp.unique_count, pii,
                    ])
            table = fmt_table(headers, rows)

            warnings_text = ""
            if profile.warnings:
                warnings_text = "\n**⚠️ 警告:**\n" + "\n".join(
                    f"- {w}" for w in profile.warnings
                )

            high_missing_text = ""
            if high_missing:
                high_missing_text = "\n**缺失率過高的變數:**\n" + "\n".join(
                    f"- {v}" for v in high_missing
                )

            log_tool_result("profile_dataset", f"{profile.column_count} vars profiled")

            return (
                f"✅ Profiling 完成\n\n"
                f"- **資料集:** `{profile.dataset_id}`\n"
                f"- **列數:** {profile.row_count:,}\n"
                f"- **變數數:** {profile.column_count}\n"
                f"- **整體缺失率:** {profile.overall_missing_rate:.1%}\n"
                f"- **重複列數:** {profile.duplicate_row_count}\n\n"
                f"{table}"
                f"{high_missing_text}"
                f"{warnings_text}\n\n"
                f"**下一步:** 使用 `assess_quality()` 評估資料品質。"
            )

        except Exception as e:
            log_tool_error("profile_dataset", e)
            return fmt_error(f"Profiling 失敗: {e}")

    @server.tool()
    def assess_quality(dataset_id: str) -> str:
        """評估資料品質：完整性、一致性、有效性。自動偵測 PII (H-004)。

        Args:
            dataset_id: 已載入的資料集 ID（需先執行 profile_dataset）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_result, log_tool_error,
            fmt_error, ensure_dataset,
        )

        log_tool_call("assess_quality", {"dataset_id": dataset_id})

        ok, msg, entry = ensure_dataset(dataset_id)
        if not ok:
            return fmt_error(msg)

        if entry.profile is None:
            return fmt_error("請先執行 `profile_dataset()` 再評估品質。")

        try:
            from rde.domain.services.quality_assessor import QualityAssessor

            assessor = QualityAssessor()
            report = assessor.assess(entry.profile)
            entry.quality_report = report
            entry.dataset.mark_quality_assessed()

            critical = report.critical_issues
            critical_text = ""
            if critical:
                critical_text = "\n## 🚨 嚴重問題\n" + "\n".join(
                    f"- **{i.variable_name}** ({i.category.value}): {i.description}\n"
                    f"  建議: {i.suggestion}"
                    for i in critical
                )

            pii_text = ""
            if report.has_pii:
                pii_text = "\n⚠️ **[H-004] 偵測到 PII 欄位！** 請確認處理方式。\n"

            log_tool_result("assess_quality", f"score={report.overall_score:.1f}")

            ready_icon = "✅" if report.is_analysis_ready else "❌"

            return (
                f"# 📊 資料品質評估\n\n"
                f"- **品質分數:** {report.overall_score:.1f}/100\n"
                f"- **完整性:** {report.completeness_score:.1f}\n"
                f"- **一致性:** {report.consistency_score:.1f}\n"
                f"- **有效性:** {report.validity_score:.1f}\n"
                f"- **可分析:** {ready_icon}\n"
                f"- **問題總數:** {len(report.issues)}\n"
                f"{pii_text}{critical_text}\n\n"
                f"**下一步:** 使用 `suggest_cleaning()` 取得清理建議，"
                f"或 `align_concept()` 進行概念對齊。"
            )

        except Exception as e:
            log_tool_error("assess_quality", e)
            return fmt_error(f"品質評估失敗: {e}")
