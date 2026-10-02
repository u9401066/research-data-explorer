"""Readable paired-study evidence, using only the immutable numerical receipt."""

import json
from pathlib import Path

import pandas as pd

from .comparison_report import scalar_text
from .regression_report import flow
from .report import cell, number

EFFECTS = {
    "mean_difference": ("配對平均差", "Paired mean difference"),
    "rank_biserial": ("配對秩效果量", "Matched rank-biserial correlation"),
    "kendall_w": ("整體秩一致程度", "Kendall concordance W"),
}


def effect_rows(result):
    rows = []
    for contrast in result["contrasts"] + ([result["omnibus"]] if result["omnibus"] else []):
        effect = contrast["effect"]
        row = {
            "contrast_id": contrast["id"],
            "first_column": contrast.get("columns", [None, None])[0],
            "second_column": contrast.get("columns", [None, None])[1],
            "n": contrast["n"],
            "effect": contrast["effect_kind"],
            "confidence_level": effect["confidence_level"],
            "interval_method": effect["method"],
            "interval_status": effect["status"],
            "interval_reason": effect["reason"],
            "raw_p": contrast["p_value"],
            "adjusted_p": contrast["adjusted_p_value"],
            "test": contrast["test"],
            "p_value_method": contrast.get("p_value_method", contrast["test"]),
            "correction": result["spec"]["multiplicity"],
            "interval_coverage": effect["coverage"],
            "nonzero_pairs": contrast.get("nonzero_pairs"),
            "zero_difference_pairs": contrast.get("zero_difference_pairs"),
        }
        for field in ("estimate", "lower", "upper"):
            row[field] = effect[field]["value"]
            row[field + "_status"] = effect[field]["status"]
        rows.append(row)
    return rows


def blocks(result, size):
    return [
        (str(start // size + 1), result["contrasts"][start : start + size])
        for start in range(0, len(result["contrasts"]), size)
    ]


def required_figures(result):
    return {
        "clinical_repeated_flow",
        "clinical_repeated_trajectory",
        *[f"clinical_repeated_pairs_{key}" for key, _ in blocks(result, 2)],
        *[f"clinical_repeated_effects_{key}" for key, _ in blocks(result, 6)],
        *(["clinical_repeated_kendall_w"] if result["omnibus"] else []),
    }


def markdown(result):
    s, ledger = result["spec"], result["case_ledger"]
    labels = {m["column"]: m["label"] for m in s["measurements"]}
    ci = f"{s['confidence_level']:.1%}"
    lines = [
        "## 配對與重複量測：事先指定比較與不確定性",
        "",
        f"研究情境：{cell(s['context'])}。結果：{cell(s['outcome_name'])}；定義：{cell(s['outcome_definition'])}；各時點共同來源單位：{cell(s['outcome_unit'])}。",
        f"身份欄位：{cell(s['subject'])}；已明訂同一人各時點量測同一結果、不同受試者獨立。識別碼唯一不能證明生物學獨立。主要效果：{EFFECTS[s['primary_effect']][0]}。",
        "方向為每項計畫的第一時點減第二時點；顯示順序不會改變比較方向。所有固定比較均保留，不依整體 p 值篩選。",
        "",
        "### 個案納入與排除",
        "",
        "| 步驟 | 受試者數 |",
        "|---|---:|",
    ]
    for label, row in zip(
        ["來源列", "不符合納入限制", "限制範圍內", "任一量測缺失", "共同完整個案"],
        flow(result),
        strict=True,
    ):
        lines.append(f"| {label} | {row['cases']} |")
    strategy = (
        "各項比較使用全時點共同完整個案"
        if s["case_strategy"] == "complete"
        else "每項比較使用該兩個時點均完整的個案"
    )
    lines += [
        "",
        f"缺失策略：{strategy}。共同軌跡、時點摘要與可選 Friedman 均用同一批 {result['n']} 人；每項比較的來源列與分母另列，不能混用。來源列號從 1 起算、不含標題。",
        "身份於缺失排除前檢查；沒有補值或根據 BMI 等欄名自動刪值。完整個案／每對完整個案均不能消除資訊性缺失偏差。",
        "",
        "| 時點 | 原始欄位 | 範圍內有值 n | 共同摘要 n | 平均值 | SD | 中位數 [Q1, Q3] |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in result["occasions"]:
        lines.append(
            f"| {cell(row['label'])} | {cell(row['column'])} | {ledger['observed_by_occasion'][row['column']]} | {row['n']} | {number(row['mean'])} | {number(row['sd'])} | {number(row['median'])} [{number(row['q25'])}, {number(row['q75'])}] |"
        )
    lines += [
        "",
        "### 固定的成對比較",
        "",
        f"效果量區間為 {ci} 逐項未校正；正式檢定另外使用完整家族校正 p。描述性 Q1／Q3 不是真正效果量的信賴區間。",
        "",
    ]
    for contrast in result["contrasts"] + ([result["omnibus"]] if result["omnibus"] else []):
        effect = contrast["effect"]
        title = (
            "Friedman 整體檢定"
            if contrast["id"] == "omnibus"
            else " − ".join(cell(labels[c]) for c in contrast["columns"])
        )
        lines += [
            f"#### {title}",
            "",
            f"計畫項目 {contrast['id']}；實際完整受試者 n={contrast['n']}。",
            "",
            f"| 效果 | 估計值 | {ci} 下限 | 上限 |",
            "|---|---:|---:|---:|",
            f"| {EFFECTS[contrast['effect_kind']][0]} | {scalar_text(effect['estimate'])} | {scalar_text(effect['lower'])} | {scalar_text(effect['upper'])} |",
            "",
            f"區間方法：{cell(effect['method'])}。"
            + (f"無法估計原因：{cell(effect['reason'])}" if effect["reason"] else ""),
        ]
        if "nonzero_pairs" in contrast:
            lines.append(
                f"非零差配對 {contrast['nonzero_pairs']} 人、零差 {contrast['zero_difference_pairs']} 人；p 值方法：{cell(contrast['p_value_method'])}。零差從秩與分母排除，但仍保留在受試者重抽樣中。"
            )
        if contrast.get("resampling"):
            receipt = contrast["resampling"]
            lines.append(
                f"以完整受試者向量重抽樣（subject bootstrap），BCa 完成 {receipt['completed']}／{receipt['requested']} 次，seed={receipt['seed']}。無定義樣本不會被丟棄後重算。"
            )
        lines.extend(f"\n方法限制：{cell(w)}" for w in contrast.get("warnings", []))
        lines.append("")
    lines += [
        "### 預先指定的檢定家族",
        "",
        f"{s['multiplicity']}；α={1-s['confidence_level']:.6g}；全部 {result['multiplicity']['size']} 項。無法計算的檢定保留家族位置，p 仍呈現無法估計。其他結果變項、研究與分支不在此校正家族內。",
        "",
        "| 項目 | n | 檢定 | 原始 p | 校正 p | 結果 |",
        "|---|---:|---|---:|---:|---|",
    ]
    for row in result["hypotheses"]:
        status = (
            "無法估計"
            if row["reject_null"] is None
            else "達校正門檻"
            if row["reject_null"]
            else "未達校正門檻"
        )
        lines.append(
            f"| {row['id']} | {row['n']} | {cell(row['test'])} | {number(row['p_value'])} | {number(row['adjusted_p_value'])} | {status} |"
        )
    lines += [
        "",
        "### 解讀與適用範圍",
        "",
        "- 配對平均差針對個人差值的平均；t 推論需要受試者獨立及差值分布假設，並非把前後兩次量測當成獨立樣本。",
        "- 配對秩效果量為（正差秩和 − 負差秩和）／非零差總秩和；不是中位數差，也不是獨立組優勢機率。signed-rank 檢定在虛無假設下需要符號對稱性。",
        "- Kendall W 是時點間相對排序的一致程度，不是配對差值；沒有方向，也不是已解釋的結果變異比例。",
        "- 區間與檢定可能使用不同程序，不能用區間是否含零取代校正 p；未達門檻不代表沒有作用或等效。",
        "- 人內變化不證明治療因果效果；本流程不調整共變項、不估計處置×時間交互作用，也不處理群集或 crossover 的期別與殘留效果。",
        "- 欄位／方法／方向／seed 均事先固定；改期刊樣式只重畫保存數值，不重新估計或選取顯著結果。",
        "",
        f"數值收據 SHA256：`{result['receipt_sha256']}`。",
    ]
    return "\n".join(lines)


def case_rows(result):
    ledger = result["case_ledger"]
    included, outside = set(ledger["complete_data_rows"]), set(ledger["filter_excluded_data_rows"])
    pairs = {c["id"]: set(c["complete_data_rows"]) for c in ledger["contrasts"]}
    return [
        {
            "data_row": row,
            "common_status": "included"
            if row in included
            else "outside_cohort"
            if row in outside
            else "missing_measurement",
            **{key: row in rows for key, rows in pairs.items()},
        }
        for row in range(1, ledger["input_rows"] + 1)
    ]


def tables(result, directory: Path, prefix):
    directory.mkdir(parents=True, exist_ok=True)
    content = {
        "effects": effect_rows(result),
        "occasions": result["occasions"],
        "observations": [
            {
                "data_row": p["data_row"],
                "measurement_column": measurement["column"],
                "occasion_label": measurement["label"],
                "value": value,
            }
            for p in result["observations"]
            for measurement, value in zip(result["spec"]["measurements"], p["values"], strict=True)
        ],
        "paired_observations": [
            {"contrast_id": c["id"], **row}
            for c in result["contrasts"]
            for row in c["observations"]
        ],
        "hypotheses": result["hypotheses"],
        "case_ledger": case_rows(result),
    }
    paths = []
    for name, rows in content.items():
        path = directory / f"{prefix}_{name}.csv"
        pd.DataFrame(
            [
                {
                    k: json.dumps(v, ensure_ascii=False, allow_nan=False)
                    if isinstance(v, (dict, list))
                    else v
                    for k, v in row.items()
                }
                for row in rows
            ]
        ).to_csv(path, index=False)
        paths.append(path)
    return paths
