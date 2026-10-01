"""Readable longitudinal reports over the saved numerical receipt, without refitting."""

from pathlib import Path

import pandas as pd

from .report import cell, number

TITLE = "縱向追蹤與重複觀察（Longitudinal analysis）"


def term_description(row, result, *, conditional=True):
    spec = result["spec"]
    if row["role"] == "intercept":
        return row["description"]
    if row["role"] == "interaction":
        terms = {r["term"]: r for r in result["coefficients"]}
        return "Interaction: " + " × ".join(
            term_description(terms[k], result, conditional=False) for k in row["components"]
        )
    description = (
        f"{row['variable']}: {row['level']} vs {row['reference']}"
        if "level" in row
        else f"{row['variable']}: +1 {row['unit']}"
    )
    if conditional and spec["time_by_group"]:
        if row["role"] == "group":
            description += f" at time={spec['time_reference']} {spec['time_unit']}"
        elif row["role"] == "time":
            description += f" in reference group {spec['group_reference']!r}"
    return description


def p_text(value):
    # scipy's normal tail can underflow; 0 here is a machine value, not a zero probability.
    return "<1e-300" if value == 0 else number(value)


def flow(result):
    ledger = result["case_ledger"]
    return [
        {"stage": "Source observations", "observations": ledger["input_rows"], "subjects": None},
        {
            "stage": "Outside cohort",
            "observations": len(ledger["filter_excluded_data_rows"]),
            "subjects": None,
        },
        {
            "stage": "Within cohort",
            "observations": ledger["cohort_rows"],
            "subjects": ledger["cohort_subjects"],
        },
        {
            "stage": "Missing model fields",
            "observations": len(ledger["missing_excluded_data_rows"]),
            "subjects": None,
        },
        {
            "stage": "Complete observations",
            "observations": result["n"],
            "subjects": result["n_subjects"],
        },
    ]


def markdown(result):
    s, ledger, model = result["spec"], result["case_ledger"], result["model"]
    ci = f"{s['confidence_level']:.1%}"
    family = {
        "gaussian": "連續值／identity link",
        "binomial": "二元結果／logit link",
        "poisson": "事件次數／log link",
    }[s["distribution"]]
    method = (
        "廣義估計方程式（GEE）" if s["method"] == "gee" else "Gaussian 線性混合模型（Mixed model）"
    )
    lines = [
        f"## {TITLE}",
        "",
        "### 研究問題與分析方法",
        "",
        f"- 研究情境：{cell(s['context'])}。",
        f"- 結果欄位：{cell(s['outcome'])}；原始單位：{cell(s['outcome_unit'])}。方法：{method}，{family}。",
        f"- 受試者欄位：{cell(s['subject'])}。不同受試者由研究者確認互相獨立；同一人的各次觀察具有相關性，不把資料列数當成獨立人數。",
        f"- 時間欄位：{cell(s['time'])}；單位：{cell(s['time_unit'])}；原點：{cell(s['time_origin'])}。參考時間={number(s['time_reference'])}。保留原始尺度和負值，未做單位換算。",
        f"- 時間形式：{'線性；以原始時間減去參考時間，係數表示每增加一個原始單位的變化' if s['time_mode'] == 'linear' else '類別時間；各時點相對於參考時間，未假定等間隔的線性變化：' + ', '.join(map(number, s['time_levels']))}。",
        f"- 基線分組：{cell(s['group'] or '未分組')}；參考組：{cell(s['group_reference'] or '不適用')}；時間×組別：{'已指定' if s['time_by_group'] else '未指定'}。",
        f"- 額外調整因素：{cell(', '.join(s['covariates']) or '無')}；其中時間變動因素：{cell(', '.join(s['time_varying_covariates']) or '無')}。其餘因素與分組須在同一人內保持基線值。",
        f"- 類別因素參考值：{cell('; '.join(k + '=' + v for k, v in s['references'].items()) or '無')}。連續調整因素每次比較增加一個原始來源單位，不自動標準化或轉換。",
    ]
    if s["distribution"] == "binomial":
        lines.append(
            f"- 二元編碼：{cell(s['positive'])}=1；{cell(s['negative'])}=0。係數 exp(β) 是群體平均勝算比（odds ratio），不是風險比或個人特定勝算比。"
        )
    if s["distribution"] == "poisson":
        lines.append(
            f"- 觀察時長欄位：{cell(s['exposure'])}，單位 {cell(s['exposure_unit'])}；以 log(時長) 作固定係數 1 的 offset。exp(β) 比較發生率；模型預期次數仍包含每列時長。"
            if s["exposure"]
            else "- 未指定觀察時長 offset；exp(β) 比較每次觀察的平均事件次數（mean count ratio），不是每人時發生率。不同追蹤時長需要明確處理。"
        )
    if s["method"] == "gee":
        lines += [
            f"- 工作相關結構（working correlation）：{s['correlation']}；估計相關={number(model['estimated_working_correlation']) if s['correlation'] != 'independence' else '固定為 0'}。採受試者叢集 robust sandwich 變異數。",
            "- GEE 估計群體平均關聯；robust 變異數不能修正錯誤平均模型、選樣偏差或不足的獨立受試者數。工作相關結構不是已證明的真實相關性。",
        ]
    else:
        lines += [
            f"- REML 估計；受試者隨機效果：{'截距＋相關的線性時間斜率' if s['random_slope'] else '截距'}。殘差變異數={number(model['residual_variance'])}。",
            "- 固定效果描述調整後平均關係；每列配適值另包含該受試者估計的隨機效果（conditional fitted mean），不能當成新受試者的已驗證預測。",
        ]
    if s["cohort_filter"]:
        lines.append(
            f"- 納入範圍：{cell(s['cohort_filter']['column'])} 屬於 {cell(', '.join(s['cohort_filter']['values']))}；按觀察列篩選。"
        )
    lines += [
        "",
        "### 個案納入與排除（Participant flow）",
        "",
        "| 步驟 | 觀察列數 | 受試者數 |",
        "|---|---:|---:|",
    ]
    names = ["原始觀察", "不符合指定納入範圍", "範圍內", "必要模型欄位缺失", "最終共同分析"]
    lines += [
        f"| {label} | {row['observations']} | {row['subjects'] if row['subjects'] is not None else '—'} |"
        for label, row in zip(names, flow(result), strict=True)
    ]
    lines += [
        "",
        f"共 {result['n_subjects']} 位受試者、{result['n']} 次觀察。每人保留 {ledger['observations_per_subject']['min']}–{ledger['observations_per_subject']['max']} 次；僅剩一次者 {ledger['subjects_with_one_complete_observation']} 人；沒有任何完整觀察而全數排除者 {ledger['subjects_with_no_complete_observations']} 人。",
        "必要模型欄位缺失只排除該次觀察，保留同一人其餘完整追蹤。排除前已查驗同一受試者／时间點唯一、識別與時間完整、基線值一致；不平均重複列、不補出未記錄的追蹤。來源資料列號從 1 開始，不含標題列。範圍外列不加入範圍內受試者數。",
        "",
        "### 固定效果估計與不確定性",
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
        "Gaussian 的表中估計為 β；binomial／Poisson 為 exp(β)。β 的 Wald 區間=β±z×SE，比值區間再取指數；p 值以 β/SE 的常態近似計算。截距對應參考時間、參考類別及連續共變項為零的情況，可能沒有臨床代表性；不把截距當成組間比值。",
        "若常態尾端機率因浮點下溢在數值收據保存為 0，報告顯示 <1e-300，不表示真實機率等於零。",
        f"Holm 校正家族含全部 {len(result['multiplicity']['family'])} 個非截距係數；保留全部結果，不按顯著性挑選。CI 是未作多重校正的逐項區間；未進行整體交互作用或跨模型比較檢定。",
    ]
    if s["time_by_group"]:
        lines.append(
            "含時間×組別時：組別主效果是在參考時間的比較，時間主效果適用參考組。Gaussian 交互作用是時間效果之差；比值模型的 exp(交互作用) 是比值之比，不能直接叫作該組的勝算比／次數比／發生率比。類別時間交互作用則比較各組相對參考時點的變化。"
        )
    if result["random_effects"]:
        random = result["random_effects"]
        lines += [
            "",
            "### 隨機效果與診斷",
            "",
            "| 隨機參數一 | 隨機參數二 | 共變異数 |",
            "|---|---|---:|",
        ]
        lines += [
            f"| {cell(a)} | {cell(b)} | {number(random['covariance'][i][j])} |"
            for i, a in enumerate(random["terms"])
            for j, b in enumerate(random["terms"])
            if j <= i
        ]
        lines.append(
            "隨機效果共變異數、匿名受試者代碼與條件估計另有 CSV；它們是收縮估計，不能把其分布直接當作母群隨機效果分布的證明。"
        )
    lines += [
        "",
        "### 圖表如何解讀",
        "",
        "時間摘要圖使用所有保留觀察的原始結果，呈現各組各時點的觀察平均／比例；有 offset 時是總事件次數除以總觀察時長。它沒有調整共變項、沒有區間，也不是模型預測軌跡。",
        "配適值對殘差圖使用同一模型保存的逐列數值；殘差=觀察結果−配適值，零線不是新檢定。Gaussian 的 Q–Q 圖比對保存殘差與標準常態分位數；組內殘差仍相關，圖形不能證明常態性、獨立性或模型正確。二元／計數結果不另畫常態 Q–Q 圖。",
        "",
        "### 解讀與適用範圍",
        "",
        "- 獨立單位是受試者；計算下限不等於樣本數充足或檢定力保證。",
        "- 工作台只估計事先指定模型，不自動改變時間形式、相關結構、調整因素或追逐 p 值。收斂不表示研究假設成立。",
        "- 失訪或缺值可能與病情相關；普通 GEE 完整觀察分析不會自動解決結果相關的缺失，混合模型的 likelihood 推論也需要在模型資訊下可忽略的缺失機制。沒有實施失訪加權或插補，也沒有從已觀察資料認定 MAR／MCAR。",
        "- 時間變動共變項需適當外生性假設，尤其非獨立 working correlation；軟體不自動處理先前結果影響後續暴露的回饋。",
        "- Wald 採常態漸近推論；未使用小樣本 sandwich 修正或 Satterthwaite／Kenward–Roger 自由度。少量受試者、稀少事件、變異數邊界需要額外審閱。",
        "- 觀察性關聯與共變項調整不能證明因果；不顯著不能證明相同／等效。沒有完成的臨床效果、隨機化或外部驗證不得由文字補出。",
        "",
        "原始模型警告：",
        "",
    ]
    lines += [f"- {cell(warning)}" for warning in result["warnings"]] or [
        "- 沒有收到估計器警告；這不代表已通過全部模型假設。"
    ]
    if s["method"] == "gee" and result["n_subjects"] < 40:
        lines.append(
            "- 獨立受試者少於 40 人，漸近 sandwich／Wald 區間可能不可靠；未做小樣本修正。這項提醒不是 40 人即充足的保證。"
        )
    lines += [
        "",
        "### 方法參考",
        "",
        "- [statsmodels GEE](https://www.statsmodels.org/stable/gee.html)",
        "- [statsmodels Gaussian MixedLM](https://www.statsmodels.org/stable/mixed_linear.html)",
        "",
        f"數值收據 SHA-256：`{result['receipt_sha256']}`",
        f"計算套件：{', '.join(k + ' ' + v for k, v in result['versions'].items())}。",
    ]
    return "\n".join(lines)


def required_figures(result):
    names = {
        "clinical_longitudinal_flow",
        "clinical_longitudinal_observed",
        "clinical_longitudinal_residuals",
    }
    names.update(
        f"clinical_longitudinal_effects_{i + 1}"
        for i in range((len(result["coefficients"]) - 1 + 7) // 8)
    )
    if result["spec"]["distribution"] == "gaussian":
        names.add("clinical_longitudinal_qq")
    return names


def tables(result, directory: Path, prefix):
    directory.mkdir(parents=True, exist_ok=True)
    ledger = result["case_ledger"]
    data = {
        "observations": result["points"],
        "observed_by_time": result["observed_by_time"],
        "coefficients": [
            {"description": term_description(row, result), **row} for row in result["coefficients"]
        ],
        "inclusion": sorted(
            [
                dict(data_row=row, status=status)
                for key, status in [
                    ("complete_data_rows", "included"),
                    ("filter_excluded_data_rows", "outside_cohort"),
                    ("missing_excluded_data_rows", "missing_required_value"),
                ]
                for row in ledger[key]
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
    random = result["random_effects"]
    if random:
        data["random_covariance"] = [
            dict(term_a=a, term_b=b, covariance=random["covariance"][i][j])
            for i, a in enumerate(random["terms"])
            for j, b in enumerate(random["terms"])
        ]
        data["random_conditional_modes"] = [
            dict(
                subject_code=row["subject_code"],
                **dict(zip(random["terms"], row["values"], strict=True)),
            )
            for row in random["conditional_modes"]
        ]
    paths = []
    for name, rows in data.items():
        path = directory / f"{prefix}_{name}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        paths.append(path)
    return paths
