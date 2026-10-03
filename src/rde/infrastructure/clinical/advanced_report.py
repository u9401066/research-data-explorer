"""Clinical reading layer for saved general-analysis evidence; never estimates models."""

import math
import re
from html import escape
from pathlib import Path


TITLES = {
    "logistic_regression": "二元結果的多因素關聯（Logistic regression）",
    "multiple_regression": "連續結果的多因素關聯（Linear regression）",
    "risk_estimates": "兩組二元事件比較（Unadjusted event comparison）",
    "propensity_score": "分組機率與因素平衡（Propensity score diagnostics）",
}


def cell(value):
    """Source names remain literal, including Markdown and HTML-looking names."""
    text = escape(str(value), quote=False).replace("\n", " ").replace("\r", " ")
    return re.sub(r"([\\`*_{}\[\]()#+.!|])", r"\\\1", text)


def number(value):
    return (
        f"{value:.6g}"
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else "無法估計／未提供"
    )


def p_text(value):
    return (
        "0（原引擎浮點輸出；不代表真實機率等於零）"
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0
        else number(value)
    )


def binary_coding(coding):
    if not coding:
        return "Outcome coding was not recorded. "
    return (
        f"For {coding['variable']!r}, source value {coding['event']!r} is the modeled event (1) "
        f"and {coding['reference']!r} is the reference (0). "
    )


def predictor_coding(coding):
    """Full readable coding, including dropped terms; no JSON or inferred units."""
    lines = []
    for item in coding:
        name = item["source_column"]
        if item["kind"] == "treatment_dummy":
            contrasts = "; ".join(
                f"{term['name']!r}: {term['level']!r} versus {item['reference']!r}"
                for term in item["encoded_columns"]
            )
            lines.append(f"{name!r} uses indicator coding ({contrasts or 'no nonreference term'}).")
        else:
            converted = item.get("numeric_conversion") == "all nonmissing strings parsed as numeric"
            lines.append(
                f"{name!r} uses numeric values"
                + (
                    " parsed from all nonmissing source strings."
                    if converted
                    else " as recorded in the source, before any saved model scaling."
                )
            )
        if item.get("dropped_constant_columns"):
            lines.append(
                "Constant columns omitted from the model: "
                + ", ".join(repr(c) for c in item["dropped_constant_columns"])
                + "."
            )
    return " ".join(lines) + " "


def propensity_policy(policy):
    """Describe the recorded policy; do not infer an outcome effect or new diagnostics."""
    lo, hi = policy["score_clipping_for_weights"]
    return (
        "Stabilized average-treatment-effect weights use p/e for group 1 and (1-p)/(1-e) for group 0, "
        f"where e is the fitted group-1 probability and p={policy['treatment_prevalence']:.6g} is its observed proportion. "
        f"Only the probabilities used for weights are bounded to [{lo:g}, {hi:g}]; "
        f"{policy['rows_with_clipped_scores']} probabilities required this bounding. "
        "Matching processes group-1 observations in ascending score order and selects the nearest available group-0 observation without replacement. "
        + (
            "No caliper was imposed. "
            if policy["caliper"] is None
            else f"The saved caliper is {policy['caliper']}. "
        )
        + (
            "A common-support restriction was applied. "
            if policy["common_support_restriction"]
            else "No common-support restriction was applied. "
        )
        + "No clinical outcome effect was estimated. "
    )


def supported(result):
    if not isinstance(result, dict) or result.get("error"):
        return False
    method = result.get("analysis_type")
    evidence = (
        result.get("risk_evidence")
        if method == "risk_estimates"
        else result.get("propensity_model", {}).get("model_evidence")
        if method == "propensity_score"
        else result.get("model_evidence")
    )
    return (
        method in TITLES
        and isinstance(evidence, dict)
        and evidence.get("schema")
        == (
            "advanced-risk-evidence-v1"
            if method == "risk_estimates"
            else "advanced-model-evidence-v1"
        )
        and isinstance(result.get("case_set"), dict)
        and {"n_input", "n_analyzed", "n_excluded"}.issubset(result["case_set"])
    )


def _table(lines, headers, rows):
    lines += ["", "| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    lines.append("")


def _model(lines, model, binary):
    evidence = model["model_evidence"]
    confidence = f"{evidence['confidence_level']:.1%}"
    lines += ["## 模型設定與編碼", ""]
    if binary:
        coding = evidence.get("outcome_coding")
        if coding:
            lines.append(
                f"結果欄位 {cell(coding['variable'])}：原碼 {cell(coding['event'])} 編為事件 1；"
                f"{cell(coding['reference'])} 編為參照 0。沒有從欄名推定臨床意義。"
            )
    else:
        lines.append(f"結果欄位：{cell(model['target'])}；保留原始數值尺度，未知單位不推定。")
    rows = []
    for c in evidence["predictor_coding"]:
        meaning = (
            "類別指標；參照 "
            + str(c["reference"])
            + "；"
            + "；".join(
                f"{v['name']}：{v['level']} 對 {c['reference']}" for v in c["encoded_columns"]
            )
            if c["kind"] == "treatment_dummy"
            else "數值項；原始數字尺度"
            + (
                "（非缺值文字已全部解析為數字）"
                if c.get("numeric_conversion") == "all nonmissing strings parsed as numeric"
                else ""
            )
        )
        rows.append(
            [
                c["source_column"],
                meaning,
                "、".join(c["retained_columns"]) or "無",
                "、".join(c["dropped_constant_columns"]) or "無",
            ]
        )
    _table(lines, ["原始因素", "編碼與比較", "實際模型項", "排除的常數項"], rows)
    scaling = evidence.get("scaling")
    if scaling:
        lines.append(
            "本模型將預測項中心化及標準化；係數對應 (原值−平均數)/標準差，不能直接解讀為每個原始單位。"
        )
        _table(
            lines,
            ["模型項", "中心值", "縮放標準差"],
            [
                [name, number(mean), number(sd)]
                for name, mean, sd in zip(
                    evidence["design_columns"][1:],
                    scaling["means"],
                    scaling["standard_deviations"],
                    strict=True,
                )
            ],
        )
    lines += ["## 係數與不確定性", ""]
    intervals = evidence.get("coefficient_intervals")
    rows = []
    for i, name in enumerate(evidence["design_columns"]):
        lo, hi = intervals[i] if intervals is not None else (None, None)
        row = [
            "截距（Intercept）" if name == "const" else name,
            number(evidence["parameters"][i]),
            number(lo),
            number(hi),
            p_text(model.get("p_values", {}).get(name)),
        ]
        if binary:
            ratio_ci = model.get("odds_ratio_ci", {}).get(name) or [None, None]
            row += [
                number(model.get("odds_ratios", {}).get(name)),
                number(ratio_ci[0]),
                number(ratio_ci[1]),
            ]
        rows.append(row)
    _table(
        lines,
        ["模型項", "係數 β", f"{confidence} 下限", "上限", "原始 p"]
        + (["exp(β)", "比值下限", "比值上限"] if binary else []),
        rows,
    )
    lines.append(
        "除截距外，exp(β) 是其他模型項相同時的勝算比（OR），不是風險比；截距的 exp(β) 是所有數值項為 0、類別在參照組時的基準勝算。標準化時 0 代表中心值。"
        if binary
        else "係數 β 是其他模型項相同時的條件平均差；數值項依上方尺度增加一單位，類別項與其參照比較。截距是所有數值項為 0、類別在參照組時的平均值；標準化時 0 代表中心值。"
    )
    if evidence["regularized"]:
        lines.append(
            "本次使用正則化（regularization）。一般未懲罰模型的信賴區間與 p 值不成立；缺少的推論保持缺少，不補造。"
        )
    else:
        lines.append(
            "區間與 p 值為原模型逐項推論，未作多重比較校正；個別不顯著不能證明沒有關聯或兩模型等效。"
        )
    algorithm = evidence.get("algorithm") or {}
    _table(
        lines,
        ["模型資訊", "保存結果"],
        [
            ["估計方法", algorithm.get("method", "未提供")],
            ["共變異數估計", algorithm.get("covariance_type", "依原模型保存程序")],
            ["設計矩陣秩／欄數", f"{evidence['design_rank']}／{evidence['design_columns_count']}"],
            ["殘差自由度", number(evidence.get("df_resid"))],
            [
                "收斂",
                {True: "已收斂；不代表假設成立", False: "未收斂", None: "未提供此檢查"}[
                    evidence.get("converged")
                ],
            ],
            *(
                [["McFadden pseudo R²", number(model.get("pseudo_r2"))]]
                if binary
                else [
                    ["R²", number(model.get("r_squared"))],
                    ["調整 R²", number(model.get("adj_r_squared"))],
                ]
            ),
        ],
    )
    lines.append(
        "McFadden pseudo R²=1−模型對數概似/僅截距模型對數概似，不是解釋變異比例。"
        if binary
        else "R² 描述此樣本的擬合程度；調整 R² 考慮模型項數，可為負值。"
    )
    lines.append(
        "配適值及殘差來自同一建模資料，沒有外部預測驗證；亦未執行交互作用或非線性的額外檢定。"
    )
    for warning in [evidence.get("inference_error"), *evidence.get("warnings", [])]:
        if warning:
            lines.append(f"- 原引擎提醒：{cell(warning)}")


def markdown(result, *, exploratory=False, source_binding=None, artifact_path=None):
    if not supported(result):
        return None
    method, case = result["analysis_type"], result["case_set"]
    lines = [f"# {TITLES[method]}", "", "## 分析範圍", ""]
    if exploratory:
        lines.append(
            "本報告是探索分支，不取代主要分析。未校正跨模型的多重探索，亦未進行模型間差異或等效性檢定。"
        )
    lines.append(
        "數值直接來自已保存的計算結果；本報告不重新估計模型。此方法需要獨立觀察，資料列數不自動等於已驗證的獨立受試者人數。"
    )
    lines += ["", "## 個案納入與排除", ""]
    _table(
        lines,
        ["階段", "資料列數"],
        [
            ["本次分析輸入", case["n_input"]],
            ["本方法排除", case["n_excluded"]],
            ["實際納入", case["n_analyzed"]],
        ],
    )
    lines.append(
        "各方法依自己的必要欄位選取完整個案；不能只憑相同人數認定是相同的人。這裡的排除發生於先前資料清理之後，不表示原始資料從未補值。完整個案分析也不證明缺失可忽略。"
    )
    if source_binding and source_binding.get("status") == "verified":
        lines.append(
            f"已核對原始檔快照與 {len(source_binding['cleaning'])} 批已保存清理；每批可包含多項操作。完整逐列納排與清理步驟保存於來源紀錄。"
        )
    if case.get("missing_by_variable"):
        _table(
            lines,
            ["本方法欄位", "缺值列數"],
            [[k, v] for k, v in case["missing_by_variable"].items()],
        )
        lines.append("不同欄位的缺值可以出現在同一列，不能將各欄缺值相加當成排除人數。")
    if method in {"logistic_regression", "multiple_regression"}:
        _model(lines, result, method == "logistic_regression")
    elif method == "risk_estimates":
        e = result["risk_evidence"]
        lines += [
            "## 事件與比較方向",
            "",
            f"結果：{cell(e['outcome_variable'])}；事件原碼：{cell(e['outcome_event'])}。分組：{cell(e['exposure_variable'])}。本次未調整共變項。",
        ]
        _table(
            lines,
            ["組別原碼", "事件", "非事件", "總數", "事件比例"],
            [
                [value, event, non_event, event + non_event, number(event / (event + non_event))]
                for value, (event, non_event) in zip(
                    [e["exposure_comparison"], e["exposure_reference"]], e["table"], strict=True
                )
            ],
        )
        lines.append(
            f"比較組 {cell(e['exposure_comparison'])} 相對參照組 {cell(e['exposure_reference'])}；比例差採比較減參照，比值採比較除參照。"
        )
        measures = {
            "risk_difference": "事件比例差（RD）",
            "risk_ratio": "事件比例比（RR）",
            "odds_ratio": "勝算比（OR）",
        }
        _table(
            lines,
            ["指標", "估計", f"{e['confidence_level']:.1%} 下限", "上限", "區間方法"],
            [
                [
                    measures[k],
                    number(v["estimate"]),
                    number(v.get("ci_lower")),
                    number(v.get("ci_upper")),
                    v.get("ci_method", "無可用區間"),
                ]
                for k, v in e["estimates"].items()
            ],
        )
        lines += [
            f"雙側 Fisher 精確檢定 p={p_text(result.get('p_value'))}；零格或不可估計區間如實保留。",
            "RD=兩組事件比例之差；RR=兩組比例之比；OR=[p₁/(1−p₁)]/[p₀/(1−p₀)]。三者不能互換。所有區間與檢定未作多重比較校正。",
            "觀察追蹤不齊時，事件比例不是固定時間累積風險，沒有處理設限；病例對照抽樣不能將這裡的樣本比例比解讀為母群風險比。未調整比較不證明介入效果。",
        ]
    else:
        coding, policy = result["treatment_coding"], result["diagnostic_policy"]
        lines += [
            "## 分組機率的用途",
            "",
            f"本次建模結果是分組 {cell(coding['variable'])}：原碼 {cell(coding['event'])} 為 1，{cell(coding['reference'])} 為 0。這是分組身分的模型，沒有另外估計臨床結果效果。",
        ]
        _model(lines, result["propensity_model"], True)
        lines += [
            "## 權重與配對方法",
            "",
            "穩定化逆機率權重（IPTW）使用 p/e 與 (1−p)/(1−e)，e 是每人的分組機率，p 是納入資料的組別 1 比例。這是 ATE 權重的形式，尚未估計平均治療效果。",
            f"p={number(policy['treatment_prevalence'])}；計算權重時將機率限制於 {number(policy['score_clipping_for_weights'][0])} 至 {number(policy['score_clipping_for_weights'][1])}，本次涉及 {policy['rows_with_clipped_scores']} 列。圖表保留原始分數。",
            "配對按組別 1 的分數由低至高，以最近組別 0 個案逐一配對、不重複使用對照。"
            + (
                "未設定配對距離上限（caliper）。"
                if policy["caliper"] is None
                else f"距離上限為 {cell(policy['caliper'])}。"
            ),
            "有套用共同支持範圍限制。"
            if policy["common_support_restriction"]
            else "未按共同支持範圍刪除個案；圖中的分布重疊不證明所有因素組合均可比較。",
        ]
        _table(
            lines,
            ["診斷摘要", "保存結果"],
            [
                [
                    "分組機率範圍",
                    f"{number(result['propensity_score_summary']['min'])}–{number(result['propensity_score_summary']['max'])}",
                ],
                [
                    "權重範圍",
                    f"{number(result['iptw_weight_summary']['min'])}–{number(result['iptw_weight_summary']['max'])}",
                ],
                [
                    "配對數／列數",
                    f"{result['matching_summary']['matched_pairs']}／{result['matching_summary']['matched_rows']}",
                ],
                [
                    "平均／最大配對距離",
                    f"{number(result['matching_summary']['mean_score_distance'])}／{number(result['matching_summary']['max_score_distance'])}",
                ],
            ],
        )
        lines += ["## 因素平衡（Standardized mean difference, SMD）", ""]
        rows = []
        for stage, key in [
            ("原始", "balance_diagnostics"),
            ("加權", "weighted_balance_diagnostics"),
            ("配對", "matched_balance_diagnostics"),
        ]:
            for term, v in result[key].items():
                rows.append(
                    [
                        term,
                        stage,
                        number(v["treated_mean"]),
                        number(v["control_mean"]),
                        number(v["pooled_standard_deviation"]),
                        number(v["standardized_mean_difference"]),
                    ]
                )
        _table(
            lines,
            ["模型項", "階段", "組別 1 平均", "組別 0 平均", "合併標準差", "有方向 SMD"],
            rows,
        )
        lines += [
            "SMD=(組別 1 平均−組別 0 平均)/√[(兩組變異數和)/2]。每階段使用自己的標準差；原始與配對使用樣本變異數，加權使用 Σw(x−加權平均)²/Σw。不能把階段間 SMD 差異當成固定分母下的改變。",
            "看平衡時需區分正負方向與絕對大小；無法估計不是零差異。沒有套用自動通過門檻或做 SMD 顯著性檢定。配對距離較小本身不證明分數分布更集中、因素均平衡或混雜已消除。",
        ]
    lines += [
        "",
        "## 完整證據與使用限制",
        "",
        "表格保留所有模型項；為閱讀而顯示六位有效數字，精確數值、逐列納排、模型矩陣／共變異數或全部配對保留於原始數值檔。圖像來自這些保存數值，不以新擬合取代。",
        "這是統計關聯或分組診斷。研究設計、資料定義與臨床重要性仍須由研究團隊審閱，不能由 p 值、平衡圖或模型收斂認定因果。",
    ]
    if artifact_path:
        lines.append(f"完整數值檔：{cell(Path(artifact_path).name)}。")
    return "\n".join(lines)
