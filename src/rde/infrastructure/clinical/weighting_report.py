"""Complete reading and export layer over frozen weighting evidence."""

import json
from pathlib import Path

import pandas as pd

from .longitudinal_report import p_text
from .regression_report import flow
from .report import cell, number

TARGETS = {
    "ATE": "納入的共同完整個案族群",
    "ATT": "納入的處置組族群",
    "ATO": "依 propensity 的 e(1−e) 傾斜之重疊族群",
}


def balance_description(row, result, *, basis=False):
    covariates = result["spec"]["covariates"]
    if not basis:
        p = covariates[row["covariate"]]
        return f"C{row['covariate'] + 1} {p['label']}" + (
            f": {row['level']}" if row["level"] is not None else f" ({p['unit']})"
        )
    if row["role"] == "interaction":
        lookup = {r["term"]: r for r in result["propensity_terms"]}
        return " × ".join(
            balance_description(lookup[key], result, basis=True) for key in row["components"]
        )
    p = covariates[row["predictor"]]
    base = f"C{row['predictor'] + 1} {p['label']}"
    if row["role"] == "categorical":
        return f"{base}: indicator({row['level']})"
    if row["role"] == "spline_basis":
        return f"{base}: centered spline basis {row['basis'] + 1}"
    return f"{base}: centered linear basis / {p['increment']} {p['unit']}"


def balance_blocks(result):
    return [
        (f"{name}_{start // 10 + 1}", rows[start : start + 10], basis)
        for name, rows, basis in [
            ("balance", result["diagnostics"]["covariate_balance"], False),
            ("basis_balance", result["diagnostics"]["basis_balance"], True),
        ]
        for start in range(0, len(rows), 10)
    ]


def required_figures(result):
    return {
        "clinical_weighting_flow",
        "clinical_weighting_overlap",
        "clinical_weighting_weights",
        "clinical_weighting_effect",
        *[f"clinical_weighting_{key}" for key, _, _ in balance_blocks(result)],
    }


def markdown(result):
    s, effect, diagnostics = result["spec"], result["effect"], result["diagnostics"]
    ci = f"{s['confidence_level']:.1%}"
    lines = [
        "## 觀察性研究的傾向加權（Propensity weighting）",
        "",
        "### 研究問題、時序與目標族群",
        "",
        f"- 情境：{cell(s['context'])}。研究設計為觀察性世代（observational cohort），每列為宣告獨立的個案。",
        f"- 處置欄位：{cell(s['treatment'])}；原始定義：{cell(s['treatment_definition'])}。參照組 {cell(s['treatment_levels'][0])}=0；處置組 {cell(s['treatment_levels'][1])}=1。",
        f"- 起算點（time zero）：{cell(s['time_origin'])}。結果觀察窗口：{cell(s['outcome_window'])}。",
        f"- 結果：{cell(s['outcome'])}；單位／來源定義：{cell(s['outcome_unit'])}。確認方式：{cell(s['outcome_definition'])}。",
        f"- 事先指定目標 {s['estimand']}：{TARGETS[s['estimand']]}。不同目標回答不同問題，不按顯著性或平衡圖換目標。",
        f"- 識別欄位：{cell(s['subject'] or '未提供；不能由識別碼檢查重複個案')}。識別碼唯一不等於生物學獨立；此流程不處理群集、重複處置、時變混雜或複雜抽樣。",
    ]
    if s["outcome_type"] == "binary":
        lines.append(
            f"二元結果原碼：{cell(s['outcome_levels'][0])}=0；{cell(s['outcome_levels'][1])}=1。分析的是後者的加權機率；未確認追蹤者不能自動當作沒有事件。"
        )
    if s["cohort_filter"]:
        lines.append(
            f"納入限制：{cell(s['cohort_filter']['column'])} 屬於 {cell(', '.join(s['cohort_filter']['values']))}。"
        )
    lines += [
        "",
        "### 處置前共變項與固定模型",
        "",
        "| 因素 | 原始欄位與規格 | 處置前依據 |",
        "|---|---|---|",
    ]
    for i, p in enumerate(s["covariates"]):
        definition = (
            f"{p['column']}；{p['unit']}；參照 {number(p['reference'])}；設計矩陣增量 {number(p['increment'])}；樣條結點 {p['knots'] or '無（線性）'}"
            if p["kind"] == "continuous"
            else f"{p['column']}；類別 {p['levels']}；參照 {p['reference']}"
        )
        lines.append(
            f"| C{i + 1} {cell(p['label'])} | {cell(definition)} | {cell(p['pre_exposure_basis'])} |"
        )
    lines += [
        "",
        f"預先指定交互作用：{cell('; '.join(' × '.join(pair) for pair in s['interactions']) or '無')}。",
        "Propensity 為接受處置的條件機率 e(X)=P(A=1|X)，以未懲罰 logistic 模型估計；所有指定基底及交互作用保留。沒有自動選變項、改節點、配對、補值、分數裁切或權重截斷。連續變項的中心化／增量僅定義模型矩陣，原始資料不改寫；propensity 係數不是處置對結果的效果。",
        "",
        "### 個案納入與排除",
        "",
        "| 步驟 | 個案數 |",
        "|---|---:|",
    ]
    names = ["來源資料列", "不符合納入限制", "限制範圍內", "必要欄位缺失", "共同完整個案"]
    lines += [f"| {name} | {row['cases']} |" for name, row in zip(names, flow(result), strict=True)]
    lines += [
        "",
        "個案識別與所有已觀察到的非法代碼先於缺失排除檢查。所有估計和診斷使用同一完整個案集合；完整列紀錄含排除原因及原始列號（從 1 起算，不含標題），沒有只匯出前 500 列。完整個案不證明缺失可忽略，排除仍可能造成選擇偏差。",
        "",
        "### 加權結果與不確定性",
        "",
        f"原始權重依 {s['estimand']} 固定：處置組 w1={result['model']['weight_formula'][0]}；參照組 w0={result['model']['weight_formula'][1]}。每組分別正規化，平均數 μa=sum(waYa)/sum(wa)。單一主要對比為 μ1−μ0。",
        "",
        f"| 目標 | 參照組加權平均 | 處置組加權平均 | 處置組 − 參照組 | {ci} 下限 | 上限 | SE | 原始 p |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        f"| {s['estimand']} | {number(effect['control_mean'])} | {number(effect['treated_mean'])} | {number(effect['estimate'])} | {number(effect['lower'])} | {number(effect['upper'])} | {number(effect['standard_error'])} | {p_text(effect['p_value'])} |",
        "",
        (
            "效果是絕對機率差（probability difference）；乘 100 才是百分點，不是相對百分比、勝算比或風險比。加權機率與研究母群風險的連結仍取決於抽樣、結果確認及研究假設。"
            if s["outcome_type"] == "binary"
            else f"效果為原始單位 {cell(s['outcome_unit'])} 的加權平均差，不是風險比、標準化效果量或中位數差。"
        ),
        "不確定性使用共同估計方程的 sandwich：同時納入 propensity 係數 β、μ1、μ0 及權重對 β 的導數，不把估得的權重視為已知常數。J=−mean(∂ψ/∂θ)，S=mean(ψψᵀ)，Cov(θ)=J⁻¹SJ⁻ᵀ/n；差異的變異數包含兩組平均數的共變異項。完整方程、參數順序、J、S 與共變異數均可下載。",
        f"{ci} 區間=差異 ± z×SE；雙尾常態 Wald 檢定的虛無差異為 0。只有一個事先指定的對比，沒有跨 ATE／ATT／ATO 或跨研究分支的多重比較校正。未做小樣本修正或 bootstrap；最低資料量門檻不是檢定力足夠的依據。",
    ]
    if s["outcome_type"] == "binary":
        lines.append(
            "普通 Wald 區間可超出 [−1,1]，此處保留未裁切區間；不以截斷端點營造較窄的不確定性。小樣本與邊界機率需審慎解讀。"
        )
    lines += [
        "",
        "### 權重集中程度與重疊",
        "",
        "| 組別 | n | sum(w) | Kish ESS | 最小權重 | 中位數 | 第 99 百分位 | 最大權重 | Propensity 範圍 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for group in diagnostics["groups"]:
        q = group["weight_quantiles"]
        lines.append(
            f"| {cell(group['label'])} | {group['n']} | {number(group['weight_sum'])} | {number(group['kish_ess'])} | {number(q['min'])} | {number(q['median'])} | {number(q['p99'])} | {number(q['max'])} | {number(group['propensity_min'])} – {number(group['propensity_max'])} |"
        )
    support = diagnostics["common_score_range"]
    lines += [
        "",
        f"兩組觀察分數範圍的交集：{number(support['lower'])} – {number(support['upper'])}"
        + ("。" if support["overlaps"] else "（下限大於上限，無範圍交集）。"),
        "Kish ESS=(sum w)²/sum(w²) 描述權重集中程度，不是增加或刪除的病人人數，也不保證推論精度。分數直方圖固定同一 0–1 軸與 20 個區間；各組內的比例分別加總為 1。沒有平滑、修剪或因重疊不足自動換模型；觀察範圍相交不能證明所有共變項組合都具有 positivity。",
        "",
        "### 共變項與模型基底平衡",
        "",
        "標準化差異（standardized mean difference, SMD）=處置組與參照組的平均／比例差除以固定未加權標準差。ATT 用原處置組標準差；ATE／ATO 用兩組未加權變異數平均的平方根。連續值採樣本變異數 ddof=1，類別指標採 p(1−p)；加權前後使用同一分母。零分母標記無法定義，仍保留原始差，不能填成零。",
    ]
    for label, key, basis in [
        ("原始共變項（全部類別指標）", "covariate_balance", False),
        ("完整 propensity 模型基底", "basis_balance", True),
    ]:
        lines += [
            "",
            f"**{label}**",
            "",
            "| 因素／基底 | 未加權參照均值 | 未加權處置均值 | 加權參照均值 | 加權處置均值 | 未加權 SMD | 加權 SMD |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for row in diagnostics[key]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        cell(balance_description(row, result, basis=basis)),
                        *[
                            number(row[k])
                            for k in [
                                "control_mean",
                                "treated_mean",
                                "control_weighted_mean",
                                "treated_weighted_mean",
                                "smd",
                                "weighted_smd",
                            ]
                        ],
                    ]
                )
                + " |"
            )
    lines += [
        "",
        "平衡沒有假設檢定，也不使用 p 值篩選模型。ATO 在未懲罰 logistic 配適下可使已指定的模型基底達到數值上的平均平衡；這不表示未測量變項平衡或無混雜。圖表顯示絕對 SMD，表格保留正負方向。",
        "",
        "### 解讀與適用範圍、可重現性",
        "",
        "因果解釋另外需要處置一致性、適當時序、沒有未測量混雜、positivity 及合適抽樣。宣告、收斂、平衡或顯著差異都不能驗證這些條件。若結果尚未確認或存在設限，不能直接編為沒有事件；本流程不是加權生存模型。",
        "再出圖只使用已保存數值；不重新估計 propensity、挑選目標、改納排或覆寫原始成果。",
        f"數值收據 SHA256：`{result['receipt_sha256']}`。",
        f"來源欄位指紋：`{result['dataframe_sha256']}`；規格指紋：`{result['spec_sha256']}`；設計矩陣指紋：`{result['design_sha256']}`。",
        f"版本：{cell(json.dumps(result['versions'], ensure_ascii=False))}。",
    ]
    if result["warnings"]:
        lines += ["", "配適器訊息：", *[f"- {cell(note)}" for note in result["warnings"]]]
    return "\n".join(lines)


def tables(result, directory: Path, prefix):
    directory.mkdir(parents=True, exist_ok=True)
    joint = result["joint_estimation"]
    data = {
        "observations": result["points"],
        "effect": [result["effect"]],
        "weight_groups": result["diagnostics"]["groups"],
        "propensity_histogram": result["diagnostics"]["propensity_histogram"],
        "parameters": [
            dict(parameter=name, estimate=value)
            for name, value in zip(joint["parameter_order"], joint["parameters"], strict=True)
        ],
    }
    for key, basis in [("covariate_balance", False), ("basis_balance", True)]:
        data[key] = [
            {"description": balance_description(row, result, basis=basis), **row}
            for row in result["diagnostics"][key]
        ]
    for key in ["bread", "meat", "covariance"]:
        data[f"joint_{key}"] = [
            dict(parameter_a=a, parameter_b=b, value=joint[key][i][j])
            for i, a in enumerate(joint["parameter_order"])
            for j, b in enumerate(joint["parameter_order"])
        ]
    paths = []
    for name, rows in data.items():
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
