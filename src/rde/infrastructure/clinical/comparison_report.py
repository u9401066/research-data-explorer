"""Human-readable comparisons and complete CSVs from a frozen study receipt."""

from pathlib import Path
import json

import pandas as pd

from .regression_report import flow
from .report import cell, number


EFFECTS = {
    "mean_difference": ("平均差", "Mean difference"),
    "rank_biserial": ("秩效果量", "Rank-biserial correlation"),
    "proportion_difference": ("事件比例差", "Event proportion difference"),
    "proportion_ratio": ("事件比例比", "Event proportion ratio"),
    "odds_ratio": ("條件勝算比", "Conditional odds ratio"),
}


def scalar_text(value):
    if value["status"] == "finite":
        return number(value["value"])
    return {"positive_infinity": "+∞", "negative_infinity": "−∞", "undefined": "無法定義"}[
        value["status"]
    ]


def effect_rows(result):
    rows = []
    for contrast in result["contrasts"]:
        for kind, effect in contrast["effects"].items():
            row = {
                "contrast_id": contrast["id"],
                "first_group": contrast["groups"][0],
                "second_group": contrast["groups"][1],
                "first_n": contrast["sample_sizes"][0],
                "second_n": contrast["sample_sizes"][1],
                "effect": kind,
                "primary": kind == contrast["primary_effect"],
                "confidence_level": effect["confidence_level"],
                "interval_method": effect["method"],
                "interval_status": effect["status"],
                "interval_reason": effect["reason"],
                "raw_p": contrast["p_value"],
                "adjusted_p": contrast["adjusted_p_value"],
                "test": contrast["test"],
                "correction": result["spec"]["multiplicity"],
                "interval_coverage": effect["coverage"],
            }
            for field in ("estimate", "lower", "upper"):
                row[field] = effect[field]["value"]
                row[field + "_status"] = effect[field]["status"]
            rows.append(row)
    return rows


def figure_blocks(result):
    available = set().union(*(c["effects"] for c in result["contrasts"]))
    primary = result["spec"]["primary_effect"]
    kinds = [primary] + [kind for kind in EFFECTS if kind in available and kind != primary]
    rows = effect_rows(result)
    return [
        (
            f"{kind}_{start // 6 + 1}",
            kind,
            [r for r in rows if r["effect"] == kind][start : start + 6],
        )
        for kind in kinds
        for start in range(0, len(result["contrasts"]), 6)
    ]


def required_figures(result):
    return {
        "clinical_comparison_flow",
        "clinical_comparison_distribution",
        *[f"clinical_comparison_{key}" for key, _, _ in figure_blocks(result)],
    }


def markdown(result):
    spec = result["spec"]
    ci = f"{spec['confidence_level']:.1%}"
    lines = [
        "## 獨立組比較：預先指定效果量與不確定性",
        "",
        f"研究情境：{cell(spec['context'])}；抽樣設計：{cell(spec['study_design'])}。每列宣告為不同受試者的獨立觀察。",
        f"結果欄位：{cell(spec['outcome'])}；定義：{cell(spec['outcome_definition'])}；來源單位：{cell(spec['outcome_unit'])}；觀察窗口：{cell(spec['outcome_window'])}。",
        f"主要效果量：{EFFECTS[spec['primary_effect']][0]}（{EFFECTS[spec['primary_effect']][1]}）。差值為第一組減第二組，比值為第一組除以第二組；組別方向在核准前固定。",
        f"身份欄位：{cell(spec['subject'] or '未提供，無法依識別碼排除重複個案')}。唯一識別碼不能證明生物學獨立或已隨機分派。",
        "",
        "### 個案納入與排除",
        "",
        "| 步驟 | 個案數 |",
        "|---|---:|",
    ]
    for label, row in zip(
        ["來源列", "不符合納入限制", "限制範圍內", "必要欄位缺失", "共同完整個案"],
        flow(result),
        strict=True,
    ):
        lines.append(f"| {label} | {row['cases']} |")
    lines += [
        "",
        "全部比較均從同一結果／組別完整個案集合取出事先指定組別。來源列號從 1 起算、不含標題；非法代碼與身份重複先於缺失排除檢查。完整個案分析不能消除缺失偏差。",
        "",
        "### 各組原始分布",
        "",
    ]
    if spec["method"] == "binary":
        lines += [
            f"事件原碼：{cell(spec['outcome_levels'][1])}；非事件原碼：{cell(spec['outcome_levels'][0])}。沒有把未確認追蹤者改成非事件。",
            "",
            "| 組別 | 納入 n | 事件 | 非事件 |",
            "|---|---:|---:|---:|",
        ]
        lines += [
            f"| {cell(g['label'])} | {g['n']} | {g['events']} | {g['non_events']} |"
            for g in result["groups"]
        ]
    else:
        lines += ["| 組別 | 納入 n | 中位數 | Q1 | Q3 |", "|---|---:|---:|---:|---:|"]
        lines += [
            f"| {cell(g['label'])} | {g['n']} | {number(g['median'])} | {number(g['q25'])} | {number(g['q75'])} |"
            for g in result["groups"]
        ]
        if spec["method"] == "welch_mean":
            lines += ["", "| 組別 | 平均值 | 樣本 SD |", "|---|---:|---:|"]
            lines += [
                f"| {cell(g['label'])} | {number(g['mean'])} | {number(g['sd'])} |"
                for g in result["groups"]
            ]
    lines += [
        "",
        "### 固定比較與效果量",
        "",
        f"各區間為 {ci} 逐項信賴區間，未作多重校正；不能用區間是否包含無效值，代替下表的家族校正檢定。未達門檻不等於等效或沒有作用。",
        "",
    ]
    for contrast in result["contrasts"]:
        lines += [
            f"#### {cell(contrast['groups'][0])} 對 {cell(contrast['groups'][1])}",
            "",
            f"各組納入數：{contrast['sample_sizes'][0]}／{contrast['sample_sizes'][1]}；計畫 ID：{contrast['id']}。",
            "",
            f"| 效果 | 估計值 | {ci} 下限 | 上限 |",
            "|---|---:|---:|---:|",
        ]
        for kind, effect in contrast["effects"].items():
            lower, upper = (
                scalar_text(effect[k]) if effect["status"] == "available" else "未能估計"
                for k in ("lower", "upper")
            )
            lines.append(
                f"| {EFFECTS[kind][0]}{'（主要）' if kind == spec['primary_effect'] else '（補充）'} | {scalar_text(effect['estimate'])} | {lower} | {upper} |"
            )
        lines.append("")
        for kind, effect in contrast["effects"].items():
            lines.append(
                f"- {EFFECTS[kind][0]}方法：{cell(effect['method'])}。"
                + (f"限制：{cell(effect['reason'])}" if effect["reason"] else "")
            )
        if contrast.get("resampling"):
            lines.append(
                f"- 秩效果量是 P(第一組值 > 第二組值) − P(第一組值 < 第二組值)，平手貢獻為零；不是中位數差。BCa 分組獨立重抽樣完成 {contrast['resampling']['completed']}／{contrast['resampling']['requested']} 次，seed={contrast['resampling']['seed']}。"
            )
        lines.extend(f"- {cell(warning)}" for warning in contrast.get("warnings", []))
        lines.append("")
    lines += [
        "### 預先指定的檢定家族",
        "",
        f"方法：{spec['multiplicity']}；α={1-spec['confidence_level']:.6g}；家族包含 {result['multiplicity']['size']} 項。未能計算的檢定仍保留計畫位置，不能藉刪除它而縮小校正家族。其他結果變項、研究與探索分支不在此家族內。",
        "",
        "| 計畫項目 | 檢定 | 原始 p | 校正 p | 結果 |",
        "|---|---|---:|---:|---|",
    ]
    for row in result["hypotheses"]:
        status = (
            "未能計算"
            if row["reject_null"] is None
            else "達校正門檻"
            if row["reject_null"]
            else "未達校正門檻"
        )
        lines.append(
            f"| {row['id']} | {cell(row['test'])} | {number(row['p_value'])} | {number(row['adjusted_p_value'])} | {status} |"
        )
    lines.extend(
        f"\n方法限制：{cell(w)}\n"
        for row in result["hypotheses"]
        if row["role"] == "omnibus"
        for w in row["warnings"]
    )
    lines += [
        "",
        "### 解讀與適用範圍",
        "",
        "- 未經調整的組間關聯不直接代表因果療效；本流程不處理群集、重複測量或複雜抽樣。",
        "- 勝算比不是比例比。病例對照或尚未釐清的抽樣只提供條件勝算比，不提供母群事件比例及其差／比。",
        "- 零值、無法定義與無限大分開保存；+∞ 是樣本邊界估計或開放區間，不代表已證明母群效果無限大。",
        "- Mann–Whitney、BCa、Newcombe、比例比 score 與 Fisher central exact 使用不同推論程序；區間與雙尾 p 並非一律互為反演。",
        "",
        f"數值收據 SHA256：`{result['receipt_sha256']}`；改期刊樣式只能重畫這份數值，不重新估計、抽樣或改變參照組。",
    ]
    return "\n".join(lines)


def tables(result, directory: Path, prefix):
    directory.mkdir(parents=True, exist_ok=True)
    tables = {
        "effects": effect_rows(result),
        "groups": result["groups"],
        "observations": result["observations"],
        "hypotheses": result["hypotheses"],
    }
    ledger = result["case_ledger"]
    included = set(ledger["complete_data_rows"])
    outside = set(ledger["filter_excluded_data_rows"])
    tables["case_ledger"] = [
        {
            "data_row": row,
            "status": "included"
            if row in included
            else "outside_cohort"
            if row in outside
            else "missing_required",
        }
        for row in range(1, ledger["input_rows"] + 1)
    ]
    paths = []
    for key, rows in tables.items():
        path = directory / f"{prefix}_{key}.csv"
        encoded = [
            {
                k: json.dumps(v, ensure_ascii=False, allow_nan=False)
                if isinstance(v, (dict, list))
                else v
                for k, v in row.items()
            }
            for row in rows
        ]
        pd.DataFrame(encoded).to_csv(path, index=False)
        paths.append(path)
    return paths
