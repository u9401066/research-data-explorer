"""Observed-row summaries without independence, sampling or endpoint assumptions."""

from __future__ import annotations

import math
import pandas as pd


def parse_options(value):
    if not isinstance(value, dict) or set(value) != {"columns", "identifiers", "unresolved"}:
        raise ValueError("descriptive_options requires exactly columns, identifiers, unresolved")
    for key, maximum in [("columns", 80), ("identifiers", 8), ("unresolved", 12)]:
        items = value[key]
        if (
            not isinstance(items, list)
            or len(items) > maximum
            or any(not isinstance(x, str) or not x.strip() or len(x) > 1000 for x in items)
            or len(set(items)) != len(items)
        ):
            raise ValueError(f"Invalid descriptive {key}")
    if not value["columns"] or not set(value["identifiers"]).issubset(value["columns"]):
        raise ValueError("Identifiers must be included in the selected columns")
    return value


def summarize(frame, options):
    options = parse_options(options)
    if any(column not in frame.columns for column in options["columns"]):
        raise ValueError("A descriptive column is absent from the source")
    summaries = []
    for column in options["columns"]:
        series = frame[column]
        values = series.dropna()
        counts = values.value_counts()
        row = dict(
            column=column,
            rows=len(series),
            observed=int(series.notna().sum()),
            missing=int(series.isna().sum()),
            distinct=int(values.nunique()),
        )
        if column in options["identifiers"]:
            row.update(
                kind="identifier",
                repeated_values=int((counts > 1).sum()),
                rows_with_repeated_value=int(counts[counts > 1].sum()),
                max_rows_per_value=int(counts.max()) if len(counts) else 0,
            )
        elif pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            finite = values[values.map(math.isfinite)]
            row.update(
                kind="numeric",
                nonfinite=len(values) - len(finite),
                finite=len(finite),
                summary={
                    key: float(finite.quantile(q)) if len(finite) else None
                    for key, q in [
                        ("min", 0),
                        ("q1", 0.25),
                        ("median", 0.5),
                        ("q3", 0.75),
                        ("max", 1),
                    ]
                },
            )
            # Low-cardinality numeric codes remain codes, not assumed events.
            if len(counts) <= 20:
                row["levels"] = [
                    dict(value=str(k), rows=int(v))
                    for k, v in sorted(counts.items(), key=lambda x: str(x[0]))
                ]
        else:
            row.update(kind="categorical", levels_suppressed=len(counts) > 20)
            if len(counts) <= 20:
                row["levels"] = [
                    dict(value=str(k), rows=int(v))
                    for k, v in sorted(counts.items(), key=lambda x: str(x[0]))
                ]
        summaries.append(row)
    patterns = frame[options["columns"]].isna().value_counts(sort=False)
    missing_patterns = (
        [
            dict(
                missing_columns=[c for c, absent in zip(options["columns"], key) if absent],
                rows=int(n),
            )
            for key, n in patterns.items()
        ]
        if len(patterns) <= 20
        else None
    )
    if missing_patterns is not None:
        missing_patterns.sort(key=lambda x: x["missing_columns"])
    return dict(
        schema="rde-descriptive-study-v1",
        scope="observed_rows_only",
        input_rows=len(frame),
        input_columns=len(frame.columns),
        described_columns=len(options["columns"]),
        missing_pattern_count=len(patterns),
        missing_patterns=missing_patterns,
        exact_duplicate_rows=int(frame.duplicated().sum()),
        columns=summaries,
        unresolved=options["unresolved"],
        missing_policy="per_column_observed_no_imputation_no_row_removal",
        inference_performed=False,
    )


def markdown(result):
    def safe(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;")

    lines = [
        "# 描述性資料研究報告",
        "",
        "已完成本次分析輸入資料列的描述；不宣稱推論研究已完成。研究設計、身份、獨立性及時間定義依已保存計畫與資料準備證據，不由本描述步驟推定。",
        f"分析輸入：{result['input_rows']} 列；全欄位完全重複的額外列：{result['exact_duplicate_rows']}。本描述步驟沒有刪除或合併資料；上游準備的關聯與納排另見準備收據。",
        "缺失逐欄計算，不補值、不當成陰性；各欄分母不同。數值摘要保留原始單位，不把資料列數當病人人數。",
        "",
        "| 欄位 | 有值列 | 缺失列 | 不同值 | 描述 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in result["columns"]:
        if row["kind"] == "identifier":
            detail = f"重複代碼 {row['repeated_values']} 個、涵蓋 {row['rows_with_repeated_value']} 列；每碼最多 {row['max_rows_per_value']} 列。代碼唯一不證明個案独立。"
        else:
            detail = (
                f"有限數值 {row['finite']} 列；非有限值 {row['nonfinite']} 列；"
                + "、".join(
                    f"{k}={format(v, '.6g') if v is not None else '未提供'}"
                    for k, v in row["summary"].items()
                )
                if row["kind"] == "numeric"
                else "原始代碼分布"
            )
            if "levels" in row:
                detail += "；" + "、".join(f"{x['value']}: {x['rows']} 列" for x in row["levels"])
            elif row.get("levels_suppressed"):
                detail += "（高基數，不列出原值）"
        lines.append(
            f"| {safe(row['column'])} | {row['observed']} | {row['missing']} | {row['distinct']} | {safe(detail)} |"
        )
    lines.extend(
        [
            "",
            "## 輸入資料列的缺失組合",
            "",
            f"本次描述 {result['described_columns']} / {result['input_columns']} 個欄位。以下組合僅限所選欄位；不是缺失機制檢定。",
        ]
    )
    if result["missing_patterns"] is not None:
        for pattern in result["missing_patterns"]:
            lines.append(
                f"- {pattern['rows']} 列：缺失欄位 {safe('、'.join(pattern['missing_columns'])) if pattern['missing_columns'] else '無（所選欄位均有值）'}"
            )
    else:
        lines.append(
            f"共 {result['missing_pattern_count']} 種缺失組合，超過列出上限20種；相同缺失數不代表同一批資料列。"
        )
    lines.extend(
        [
            "",
            "## 計畫記錄的待釐清事項與限制",
            "",
            *[f"- {safe(x)}" for x in result["unresolved"]],
            "",
            "本階段沒有估計 p 值、信賴區間、治療效果或預測效能。沒有自行選首次事件、認定隨機分派或把未觀測當作無事件。後續推論需修訂／追加計畫並重新審閱。",
            "",
        ]
    )
    return "\n".join(lines)
