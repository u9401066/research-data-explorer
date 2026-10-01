"""Human-readable regression evidence from the immutable numerical receipt."""

import json
from pathlib import Path

import pandas as pd

from .longitudinal_report import p_text
from .report import cell, number

TITLE = "多因素關聯、計數與序位迴歸（Prespecified regression）"
DESIGNS = {
    "randomized_parallel": "平行組隨機試驗",
    "observational_cohort": "觀察性世代研究",
    "cross_sectional": "橫斷面研究",
    "case_control": "病例對照研究",
    "unspecified": "尚未確定研究設計",
}


def term_description(row, result):
    if row["role"] == "intercept":
        return "Intercept: all predictors at their declared references"
    if row["role"] == "interaction":
        lookup = {r["term"]: r for r in result["coefficients"]}
        return "Interaction: " + " × ".join(
            term_description(lookup[k], result) for k in row["components"]
        )
    predictor = result["spec"]["predictors"][row["predictor"]]
    name = f"P{row['predictor'] + 1} {predictor['label']}"
    if row["role"] == "categorical":
        return f"{name}: {row['level']} vs {predictor['reference']}"
    if row["role"] == "spline_basis":
        return f"{name}: centered spline basis {row['basis'] + 1}, not a constant per-unit effect"
    return f"{name}: +{number(predictor['increment'])} {predictor['unit']}"


def coefficient_blocks(result):
    """Include every nonintercept term; never mix basis coefficients and ratios."""
    eligible = [r for r in result["coefficients"] if r["role"] != "intercept"]
    groups = {"effects": [], "interactions": [], "basis": []}
    for row in eligible:
        key = (
            "basis"
            if "basis coefficient" in row["effect_scale"]
            else "interactions"
            if row["role"] == "interaction"
            else "effects"
        )
        groups[key].append(row)
    return [
        (f"{name}_{start // 8 + 1}", rows[start : start + 8])
        for name, rows in groups.items()
        for start in range(0, len(rows), 8)
    ]


def flow(result):
    ledger = result["case_ledger"]
    return [
        {"stage": "Source cases", "cases": ledger["input_rows"]},
        {"stage": "Outside cohort", "cases": len(ledger["filter_excluded_data_rows"])},
        {"stage": "Within cohort", "cases": ledger["cohort_rows"]},
        {"stage": "Missing model fields", "cases": len(ledger["missing_excluded_data_rows"])},
        {"stage": "Complete cases", "cases": result["n"]},
    ]


def markdown(result):
    s, model = result["spec"], result["model"]
    ci = f"{s['confidence_level']:.1%}"
    lines = [
        f"## {TITLE}",
        "",
        "### 研究問題與分析方法",
        "",
        f"- 情境：{cell(s['context'])}。研究設計：{DESIGNS[s['study_design']]}（{s['study_design']}）。",
        f"- 結果：{cell(s['outcome'])}；原始單位／定義：{cell(s['outcome_unit'])}。模型：{s['distribution']}，連結函數（link）={model['link']}。",
        f"- 估計：{model['estimation']}。變異數：{model['covariance']}。區間與檢定：{model['inference']}。",
        f"- 研究者確認不同資料列互相獨立；識別欄位：{cell(s['subject'] or '未提供，無法從識別碼驗證重複個案')}。同人重複觀察需使用縱向研究流程。",
        "- 變項、參照值、比較增量、交互作用與樣條節點均於估計前指定，未自動篩選變項、挑最佳節點或依 p 值刪項。",
        "",
        "| 因素 | 原始欄位 | 定義與參照 |",
        "|---|---|---|",
    ]
    for i, predictor in enumerate(s["predictors"]):
        description = (
            f"連續值；單位 {predictor['unit']}；參照 {number(predictor['reference'])}；比較增量 {number(predictor['increment'])}；"
            + (
                f"限制性三次樣條（restricted cubic spline），原始尺度節點 {', '.join(map(number, predictor['knots']))}"
                if predictor["knots"]
                else "線性項"
            )
            if predictor["kind"] == "continuous"
            else f"類別；參照 {predictor['reference']}；完整來源類別：{', '.join(predictor['levels'])}"
        )
        lines.append(
            f"| P{i + 1} {cell(predictor['label'])} | {cell(predictor['column'])} | {cell(description)} |"
        )
    lines += [
        "",
        f"交互作用：{cell('; '.join(' × '.join(pair) for pair in s['interactions']) or '未指定')}。所有交互作用保留所需主效果。",
    ]
    if s["distribution"] == "binomial":
        lines.append(
            f"二元來源編碼：{cell(s['outcome_levels'][0])}=0；{cell(s['outcome_levels'][1])}=1。exp(β) 為勝算比（odds ratio），不是風險比。"
        )
    if s["distribution"] == "ordinal":
        lines += [
            f"序位由低至高：{cell(' < '.join(s['outcome_levels']))}；類別間距沒有被假設相等。比例勝算模型（proportional odds）採 logit P(Y≤k)=cutpoint(k)−Xβ；exp(β)>1 對應較高結果類別的共同累積勝算比。",
            "所有切點共用同一斜率。沒有執行比例勝算假設檢定，收斂不代表該假設成立；模型不含截距，切點另列且不是曝露效果。",
        ]
    if s["distribution"] in {"poisson", "negative_binomial"}:
        lines.append(
            f"觀察時長：{cell(s['exposure'])}，原始單位 {cell(s['exposure_unit'])}；log(時長) 以固定係數 1 加入 offset，因此比較的是發生率比（rate ratio）。每列配適次數仍含該列時長。"
            if s["exposure"]
            else "未指定觀察時長 offset；比較的是平均次數比（mean count ratio），不能稱為每人時發生率比。"
        )
    if s["distribution"] == "negative_binomial":
        lines.append(
            "NB2 的變異數為 μ＋αμ²；α 與平均模型參數聯合估計，未固定為預設 1，也未自動改用 Poisson。零膨脹、hurdle 或複雜抽樣權重未納入此模型。"
        )
    if s["cohort_filter"]:
        lines.append(
            f"納入範圍：{cell(s['cohort_filter']['column'])} 屬於 {cell(', '.join(s['cohort_filter']['values']))}。"
        )
    lines += ["", "### 個案納入與排除（Participant flow）", "", "| 步驟 | 個案數 |", "|---|---:|"]
    names = ["原始資料列", "不符合納入範圍", "範圍內", "必要欄位缺失", "最終共同分析"]
    lines += [
        f"| {label} | {row['cases']} |" for label, row in zip(names, flow(result), strict=True)
    ]
    lines += [
        "",
        "所有係數、聯合檢定與診斷使用同一完整個案集合；沒有補值。識別碼及非法來源值在缺失排除前查驗；逐列納排清單保留從 1 起算且不含標題的來源列號。完整個案不代表缺失可忽略或没有選樣偏差。",
        "",
        "### 係數、效果尺度與不確定性",
        "",
        f"| 參數與比較 | 效果尺度 | 估計 | {ci} 下限 | 上限 | 原始 p | Holm p |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {cell(term_description(row, result))} | {cell(row['effect_scale'])} | {number(row['estimate'])} | {number(row['lower'])} | {number(row['upper'])} | {p_text(row['p_value'])} | {p_text(row['p_adjusted']) if row['p_adjusted'] is not None else '不納入校正家族'} |"
        for row in result["coefficients"]
    ]
    lines += [
        "",
        "主效果在其餘因素的指定參照值下解讀；交互作用為條件效果之差或比值之比。样條的全部基底（包括線性部分）只顯示 β，不把 exp(基底係數) 當成固定每單位的臨床效果；請配合條件曲線與聯合檢定。",
        f"全部 {len(result['multiplicity']['coefficient_family'])} 個非截距係數為第一個 Holm 家族。{ci} 區間為逐項未校正區間；Gaussian 使用 t 近似，其餘使用常態 Wald 近似。比值區間由 β 區間取指數；截距不是組間效果。浮點尾端機率為 0 時顯示 <1e-300，不主張真實機率為零。",
        "",
        "### 預先指定的聯合檢定",
        "",
        "| 檢定 | 因素 | 自由度 | 統計量 | 參考分布 | 原始 p | Holm p |",
        "|---|---|---:|---:|---|---:|---:|",
    ]
    for row in result["joint_tests"]:
        labels = ", ".join(f"P{i + 1} {s['predictors'][i]['label']}" for i in row["predictors"])
        distribution = row["distribution"] + (
            f", denominator df={row['denominator_df']}" if row["denominator_df"] else ""
        )
        lines.append(
            f"| {row['role']} | {cell(labels)} | {row['df']} | {number(row['statistic'])} | {distribution} | {p_text(row['p_value'])} | {p_text(row['p_adjusted'])} |"
        )
    lines += [
        "",
        f"這 {len(result['joint_tests'])} 個聯合檢定另成第二個 Holm 家族，不宣稱兩家族合併或跨模型控制整體錯誤率。main 檢驗該因素主效果的全部基底，條件為其他因素的參照值；interaction 檢驗指定乘積項。nonlinearity 檢驗該因素所有非線性基底及包含它們的交互乘積，不以單一基底 p 值判斷整條曲線。Gaussian 採 Wald F 近似，其餘採 Wald χ² 近似。",
    ]
    lines.append(
        "同一個單自由度對比可能在兩個家族得到不同的 Holm p 值；不可事後挑選較小的一個宣稱陽性。確認性主要假說與其校正範圍應事先寫入研究計畫。"
    )
    if result["nuisance_parameters"]:
        lines += [
            "",
            "### 額外模型參數",
            "",
            f"| 定義 | 估計 | SE | {ci} 下限 | 上限 | 區間方法 |",
            "|---|---:|---:|---:|---:|---|",
        ]
        for row in result["nuisance_parameters"]:
            label = row["kind"] + ("：" + " / ".join(row["between"]) if "between" in row else "")
            lines.append(
                f"| {cell(label)} | {number(row['estimate'])} | {number(row['standard_error'])} | {number(row['lower'])} | {number(row['upper'])} | {row['inference']} |"
            )
        lines.append(
            "這些參數不列入係數或聯合檢定的 Holm 家族；區間為逐項近似，切點區間可以互相重疊。"
        )
    lines += ["", "### 曲線與模型診斷", ""]
    if result["conditional_curves"]:
        lines.append(
            "每個連續因素的條件曲線比較該原始數值與指定參照值，其餘因素固定於參照；範圍限於完整個案實際最小至最大值。圖上帶狀區間是逐點、未做多重校正的模型對比 CI，不是預測區間或整條曲線的同時信賴帶；參照點的對比恆為 0／1，並非該人的結果沒有不確定性。參照組合可能缺乏共同資料支持，曲線不是群體平均處置效果。"
        )
    if s["distribution"] == "ordinal":
        lines += [
            "序位診斷比較原始類別比例與同資料的平均配適機率，不為類別任意指定等距數字後畫殘差。這不是獨立驗證或假設檢定。",
            "",
            "| 結果類別（原順序） | 個案數 | 原始比例 | 平均配適機率 |",
            "|---|---:|---:|---:|",
        ]
        lines += [
            f"| {cell(row['label'])} | {row['n']} | {number(row['observed_proportion'])} | {number(row['mean_fitted_probability'])} |"
            for row in result["outcome_summary"]
        ]
    else:
        lines.append(
            f"Pearson 殘差平方和／(n−平均模型參數數)={number(model['pearson_sum_squares_per_residual_df'])}；僅作描述診斷，不是已檢定變異數模型正確。Gaussian 圖保留原始單位的反應殘差與常態分位圖，其餘畫 Pearson 殘差；不加平滑、抖動或事後刪點。HC3／HC0 不能修正錯誤平均模型或選樣偏差。"
        )
    lines += [
        "",
        "### 解讀與適用範圍",
        "",
        "依已指定研究設計解讀；迴歸本身不驗證隨機化、ITT 完整性或因果效果，也不會將隨機試驗自動改稱觀察性研究。觀察性分析的調整不能排除未測量混雜。沒有執行加權、外部預測驗證或樣本數規劃。",
        "病例對照抽樣的截距和配適機率只描述抽到的病例／對照比例，不能當作族群盛行率或疾病風險。稀疏資料、極端區間、條件組合支持及比例勝算假設仍需研究者審閱；成功收斂、可識別矩陣或漂亮圖形不是統計假設成立的證明。",
        "",
        *[f"- {cell(note)}" for note in result["limitations"]],
    ]
    if result["warnings"]:
        lines += [
            "",
            "估計器原始警告（保留供審閱）：",
            *[f"- {cell(w)}" for w in result["warnings"]],
        ]
    lines += [
        "",
        "### 方法參考",
        "",
        "- [statsmodels GLM](https://www.statsmodels.org/stable/glm.html)",
        "- [statsmodels NB2](https://www.statsmodels.org/stable/generated/statsmodels.discrete.discrete_model.NegativeBinomial.html)",
        "- [statsmodels ordinal logistic](https://www.statsmodels.org/stable/generated/statsmodels.miscmodels.ordinal_model.OrderedModel.html)",
        "",
        f"數值收據 SHA-256：`{result['receipt_sha256']}`",
        f"計算套件：{', '.join(k + ' ' + v for k, v in result['versions'].items())}。",
    ]
    return "\n".join(lines)


def required_figures(result):
    names = {"clinical_regression_flow"}
    names.update(f"clinical_regression_{key}" for key, _ in coefficient_blocks(result))
    names.update(
        f"clinical_regression_curve_P{r['predictor'] + 1}" for r in result["conditional_curves"]
    )
    names.add(
        "clinical_regression_categories"
        if result["spec"]["distribution"] == "ordinal"
        else "clinical_regression_residuals"
    )
    if result["spec"]["distribution"] == "gaussian":
        names.add("clinical_regression_qq")
    return names


def tables(result, directory: Path, prefix):
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "observations": result["points"],
        "coefficients": [
            {"description": term_description(row, result), **row} for row in result["coefficients"]
        ],
        "joint_tests": result["joint_tests"],
        "inclusion": sorted(
            [
                dict(data_row=row, status=status)
                for key, status in [
                    ("complete_data_rows", "included"),
                    ("filter_excluded_data_rows", "outside_cohort"),
                    ("missing_excluded_data_rows", "missing_required_value"),
                ]
                for row in result["case_ledger"][key]
            ],
            key=lambda row: row["data_row"],
        ),
        "coefficient_covariance": [
            dict(
                term_a=a["term"],
                term_b=b["term"],
                covariance=result["coefficient_covariance"][i][j],
            )
            for i, a in enumerate(result["coefficients"])
            for j, b in enumerate(result["coefficients"])
        ],
    }
    for key in ["nuisance_parameters", "outcome_summary"]:
        if result[key]:
            data[key] = result[key]
    for curve in result["conditional_curves"]:
        data[f"curve_P{curve['predictor'] + 1}"] = [
            {
                "column": curve["column"],
                "unit": curve["unit"],
                "reference": curve["reference"],
                "profile": curve["profile"],
                "effect_scale": curve["effect_scale"],
                **row,
            }
            for row in curve["points"]
        ]
    paths = []
    for name, rows in data.items():
        path = directory / f"{prefix}_{name}.csv"
        pd.DataFrame(
            [
                {
                    k: json.dumps(v, ensure_ascii=False, allow_nan=False)
                    if isinstance(v, (list, dict))
                    else v
                    for k, v in row.items()
                }
                for row in rows
            ]
        ).to_csv(path, index=False)
        paths.append(path)
    return paths
