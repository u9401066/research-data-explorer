"""Human reading, CSVs and figures derived solely from saved measurement receipts."""

from pathlib import Path
import textwrap

import numpy as np
import pandas as pd

from rde.infrastructure.clinical.report import cell, number

TITLES = {
    "diagnostic_accuracy": "診斷準確度（Diagnostic accuracy）",
    "bland_altman": "量測差異與一致性（Bland–Altman）",
    "cohens_kappa": "評分者一致性（Cohen kappa）",
}
ESTIMATES = {
    "sensitivity": "敏感度（Sensitivity）",
    "specificity": "特異度（Specificity）",
    "positive_predictive_value": "陽性預測值（PPV）",
    "negative_predictive_value": "陰性預測值（NPV）",
    "accuracy": "正確率（Accuracy）",
    "bias_first_minus_second": "平均差異：第一 − 第二（Bias）",
    "lower_limit_of_agreement": "一致性界限下限（Lower LoA）",
    "upper_limit_of_agreement": "一致性界限上限（Upper LoA）",
    "cohens_kappa": "未加權 Kappa",
}
SAMPLING = {
    "single_gate": "共同納入途徑（single-gate）",
    "two_gate": "分別納入有病與無病個案（two-gate）",
    "unknown": "來源抽樣方式尚未確認",
}
INDEPENDENCE = {"independent": "已確認獨立", "not_independent": "未獨立建立", "unknown": "尚未確認"}


def flow(result):
    ledger = result["case_ledger"]
    return [
        ("原始資料", ledger["input_rows"]),
        ("必要欄位缺失", len(ledger["missing_excluded_data_rows"])),
        ("完整欄位但無法判讀", len(ledger["indeterminate_excluded_data_rows"])),
        ("最終共同分析人數", result["n"]),
    ]


def markdown(result):
    s, ledger = result["spec"], result["case_ledger"]
    d, a = s["diagnostic"], s["agreement"]
    ci = f"{s['confidence_level']:.1%}"
    lines = [
        f"## {TITLES[s['family']]}",
        "",
        "### 研究問題與分析方法",
        "",
        f"- 研究情境與收集方式：{cell(s['context'])}",
        f"- 第一欄位：{cell(s['first'])}；第二欄位：{cell(s['second'])}。受試者欄位：{cell(s['subject'] or '未提供；由研究者確認一人一列')}。",
        f"- 信賴區間：{ci}。各指標區間為逐項區間（pointwise），未作跨指標多重校正。",
        "- 每列必須是同一位受試者的一對觀察，不同列互相獨立；只使用共同完整個案，不補值、不依結果調整閾值。",
    ]
    if d:
        rule = (
            f"{cell(s['second'])} {'≥' if d['positive_direction'] == 'greater_equal' else '≤'} {number(d['threshold'])}"
            if d["test_kind"] == "score"
            else f"陽性={cell(d['test_positive'])}；陰性={cell(d['test_negative'])}"
        )
        lines += [
            f"- 參照標準：{cell(d['reference_description'])}；陽性={cell(d['positive'])}，陰性={cell(d['negative'])}。",
            f"- 參照標準是否獨立於待測方法：{INDEPENDENCE[d['reference_independence']]}。此欄是研究者陳述，軟體不代為驗證診斷真值。",
            f"- 待測方法判定：{rule}；{'事先指定' if d['threshold_status'] == 'prespecified' else '探索性設定，不能聲稱已驗證'}。規則依據：{cell(d['threshold_basis'])}。",
            f"- 抽樣方式：{SAMPLING[d['sampling']]}。",
            f"- 無法判讀代碼：參照欄 {cell(', '.join(d['reference_indeterminate']) or '未指定')}；待測欄 {cell(', '.join(d['test_indeterminate']) or '未指定')}。未宣告的代碼會停止分析，不自動當成陰性。",
        ]
    if a:
        lines += [
            f"- 差異定義：{cell(s['first'])} − {cell(s['second'])}；兩欄單位都為 {cell(a['unit'])}，此流程不做單位換算。",
            f"- 一致性界限涵蓋比例：{a['coverage']:.1%}，與估計值的 {ci} 信賴區間分開設定。",
            "- 平均差異的 CI 使用 t 分布；一致性界限為平均差異 ± z × 差異標準差，界限本身的 CI 為常態差異近似。假設不同配對獨立、差異大致常態且變異穩定；必須檢視差異圖與 Q–Q 圖。",
        ]
    if s["family"] == "cohens_kappa":
        lines += [
            f"- 事先指定共用類別：{cell(', '.join(s['categories']))}。不指定高低順序、不加權；不同評分者必須使用相同分類意義。",
            "- Kappa=(觀察一致率 − 機會一致率)/(1 − 機會一致率)，CI 使用漸近常態近似，可能超出理論邊界；少量或稀疏類別時不穩定。",
        ]
    lines += ["", "### 個案納入與排除（Participant flow）", "", "| 步驟 | 人數 |", "|---|---:|"]
    lines += [f"| {label} | {count} |" for label, count in flow(result)]
    lines += [
        "",
        "逐列納排紀錄可下載；資料列號從 1 開始，不包含標題列。缺失優先歸類，因此上表互斥；原始無法判讀列另保留於收據，不會被缺失原因掩蓋。排除無法判讀或缺失可能造成偏差，不能據此宣稱全部受試者都可成功檢測。",
    ]
    if d:
        lines.append(
            f"參照欄曾標記無法判讀：{len(ledger['reference_indeterminate_rows'])} 列；待測欄：{len(ledger['test_indeterminate_rows'])} 列（可重疊）。"
        )
        c = result["confusion_counts"]
        lines += [
            "",
            "### 診斷交叉表",
            "",
            "| 待測判定 | 參照陽性 | 參照陰性 |",
            "|---|---:|---:|",
            f"| 陽性 | {c['TP']}（TP） | {c['FP']}（FP） |",
            f"| 陰性 | {c['FN']}（FN） | {c['TN']}（TN） |",
            "",
            "敏感度=TP/(TP+FN)；特異度=TN/(TN+FP)；PPV=TP/(TP+FP)；NPV=TN/(TN+FN)。每個指標使用自己的分母與 Wilson 區間，零分母表示無法估計。",
        ]
        if d["sampling"] != "single_gate":
            lines.append(
                "**此抽樣設計不提供 PPV、NPV 與正確率。** 樣本比例仍可由交叉表計算，並非數學上無法計算；平台因抽樣設計限制不列出這些指標。它們受疾病比例影響，不能從特意選入或抽樣方式不明的有病／無病比例推論臨床母群。敏感度與特異度仍可能受疾病譜與選擇偏差影響。"
            )
        else:
            lines.append(
                "PPV、NPV 與正確率僅反映本研究樣本；共同納入途徑不代表本樣本已能代表其他醫院或篩檢母群，仍需外部驗證。"
            )
    lines += [
        "",
        "### 估計值與不確定性",
        "",
        f"| 指標 | 估計 | {ci} 下限 | 上限 | 分子／分母 | 方法或缺省原因 |",
        "|---|---:|---:|---:|---|---|",
    ]
    for key, row in result["estimates"].items():
        denominator = f"{row['numerator']} / {row['denominator']}" if "denominator" in row else "—"
        withheld = row.get("status") == "withheld_by_sampling_design"
        estimate = "依抽樣設計不提供" if withheld else number(row["estimate"])
        lower = "—" if withheld else number(row["ci_lower"])
        upper = "—" if withheld else number(row["ci_upper"])
        lines.append(
            f"| {ESTIMATES.get(key, cell(key))} | {estimate} | {lower} | {upper} | {denominator} | {cell(row.get('reason') or row.get('ci_method', ''))} |"
        )
    if result["roc"] is not None:
        roc = result["roc"]
        lines += [
            "",
            "### 整體區辨能力（ROC / AUC）",
            "",
            f"AUC={number(roc['estimate'])}；{ci} CI {number(roc['ci_lower'])}–{number(roc['ci_upper'])}。",
            "ROC 是同一組完整個案中不同閾值的描述；圖中標記為已鎖定的分析閾值，沒有依 ROC 自動挑選最佳切點。低值陽性會先反轉分數方向。",
            "兩個參照類別各至少 2 人時，AUC 區間使用分層受試者 bootstrap（1,000 次，seed=20261001）；固定類別人數，不能修正選擇或查證偏差。任一類別只有 1 人時不估計 AUC 區間；樣本極小或完全區分時區間仍可能退化，不代表真實不確定性為零。",
        ]
        if roc.get("reason"):
            lines.append(roc["reason"])
    if s["family"] == "cohens_kappa":
        labels, table = result["categories"], result["table"]
        lines += [
            "",
            f"原始一致率={number(result['observed_agreement'])}。下表列為第一評分者、欄為第二評分者，兩者使用同一類別順序：",
            "",
            "| 第一 \\ 第二 | " + " | ".join(cell(v) for v in labels) + " |",
            "|---|" + "---:|" * len(labels),
        ]
        lines += [
            "| " + cell(label) + " | " + " | ".join(str(v) for v in row) + " |"
            for label, row in zip(labels, table, strict=True)
        ]
    if a:
        margin = result["margin_comparison"]
        lines += ["", "### 與研究者指定可接受差異比較", ""]
        if margin:
            lines += [
                f"可接受差異：{number(margin['lower'])} 至 {number(margin['upper'])} {cell(a['unit'])}；依據：{cell(margin['basis'])}。",
                f"觀察差異位於範圍內：{margin['within_count']} / {margin['n']}。一致性界限的點估計是否都在範圍內：{'是' if margin['point_limits_within'] else '否'}；界限的外側 CI 是否也在範圍內：{'是' if margin['outer_ci_bounds_within'] else '否'}。",
                "這是描述性比較，不是正式等效性檢定；平均差異接近 0、相關很高或界限在範圍內，都不能單獨證明臨床可互換。",
            ]
        else:
            lines.append(
                "未提供事先設定的可接受差異，因此不判定兩種量測是否可互換；可在新研究計畫中依臨床需求另訂界限。"
            )
    lines += [
        "",
        "### 解讀與適用範圍",
        "",
        "- 本流程不建立因果結論、不選最佳切點，也沒有訓練／驗證新的多變項模型。",
        "- 診斷準確度需可靠且獨立的參照標準、適當納入方式與盲判資訊；未知資訊不得由模型補寫。",
        "- 一致性不是診斷效度。未加權 Kappa 受類別盛行率與兩位評分者分布影響；不能用固定分級字詞取代臨床判讀。",
        "- 重複量測、同一人多個病灶或多個評分者需要相應的叢集／多層方法，本流程僅分析獨立配對。",
        "- 報告完整性檢查僅確認計畫、收據與檔案一致，不能認定研究符合全部 STARD 項目或已可投稿。",
        "",
    ]
    lines += [f"- {cell(v)}" for v in result["warnings"]]
    lines += [
        "",
        "### 方法參考",
        "",
        "- [STARD 診斷準確度報告指引](https://www.equator-network.org/reporting-guidelines/stard/)",
        "- [Wilson 二項比例區間](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_confint.html)",
        "- [Cohen kappa 計算](https://www.statsmodels.org/stable/generated/statsmodels.stats.inter_rater.cohens_kappa.html)",
        "",
        f"數值收據 SHA-256：`{result['receipt_sha256']}`",
    ]
    return "\n".join(lines)


def required_figures(result):
    names = {"clinical_participant_flow"}
    if result["spec"]["diagnostic"]:
        names |= {"clinical_diagnostic_matrix", "clinical_diagnostic_intervals"}
        if result["roc"] is not None:
            names.add("clinical_diagnostic_roc")
    elif result["spec"]["agreement"]:
        names |= {"clinical_bland_altman", "clinical_agreement_qq", "clinical_measurement_pairs"}
    else:
        names.add("clinical_kappa_matrix")
    return names


def figures(result, directory: Path, prefix):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.stats import probplot
    from rde.infrastructure.visualization.fonts import configure_plot_fonts

    font_receipt = configure_plot_fonts()
    directory.mkdir(parents=True, exist_ok=True)
    records, s = [], result["spec"]
    ci = f"{s['confidence_level']:.1%}"

    def save(fig, name, caption):
        path = directory / f"{prefix}_{name}.png"
        fig.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(fig)
        records.append(
            dict(path=str(path), plot_type=f"clinical_{name}", caption=caption, fonts=font_receipt)
        )

    fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
    labels, counts = zip(*flow(result), strict=True)
    ax.barh(labels[::-1], counts[::-1], color=["#16766e", "#bc7647", "#bc7647", "#6188a5"])
    ax.set(xlim=(0, max(counts) * 1.15), xlabel="人數", title="同一組完整配對：納入與排除")
    for i, n in enumerate(counts[::-1]):
        ax.text(n + max(counts) * 0.015, i, str(n), va="center")
    save(
        fig,
        "participant_flow",
        "納入排除：缺失與無法判讀排除為互斥分類；所有估計共用最終完整個案。",
    )
    if s["diagnostic"] or s["family"] == "cohens_kappa":
        diagnostic = bool(s["diagnostic"])
        if diagnostic:
            c = result["confusion_counts"]
            matrix, labels = [[c["TP"], c["FP"]], [c["FN"], c["TN"]]], ["陽性", "陰性"]
        else:
            matrix, labels = result["table"], result["categories"]
        size = max(5, min(13, len(labels) * 0.55))
        fig, ax = plt.subplots(figsize=(size + 1, size), layout="constrained")
        image = ax.imshow(matrix, cmap="Blues", vmin=0)
        display_labels = [textwrap.fill(label, 18) for label in labels]
        ax.set_xticks(range(len(labels)), display_labels, rotation=35, ha="right")
        ax.set_yticks(range(len(labels)), display_labels)
        for i, row in enumerate(matrix):
            for j, count in enumerate(row):
                ax.text(
                    j,
                    i,
                    str(count),
                    ha="center",
                    va="center",
                    color="white" if count > np.max(matrix) * 0.55 else "black",
                    fontsize=max(7, 12 - len(labels) // 4),
                )
        ax.set(
            xlabel="參照標準" if diagnostic else s["second"],
            ylabel="待測方法" if diagnostic else s["first"],
            title=f"{'診斷交叉表' if diagnostic else '評分者交叉表'} | n={result['n']}",
        )
        fig.colorbar(image, ax=ax, label="人數", shrink=0.7)
        save(
            fig,
            "diagnostic_matrix" if diagnostic else "kappa_matrix",
            "橫軸與縱軸依圖中定義；每格為同一组完整個案的觀察人數，對角線代表一致判定。",
        )
    if s["diagnostic"]:
        estimates = [
            (ESTIMATES[k], v)
            for k, v in result["estimates"].items()
            if v.get("estimate") is not None
        ]
        fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
        for i, (name, row) in enumerate(estimates):
            ax.plot([row["ci_lower"], row["ci_upper"]], [i, i], color="#16766e")
            ax.plot(row["estimate"], i, "o", color="#16766e")
        ax.set_yticks(range(len(estimates)), [v[0] for v in estimates])
        ax.set(xlim=(-0.02, 1.02), xlabel=f"比例與 {ci} Wilson CI", title="固定判定規則的診斷表現")
        ax.invert_yaxis()
        ax.grid(axis="x", alpha=0.2)
        save(
            fig,
            "diagnostic_intervals",
            f"已鎖定規則下的估計值與 {ci} Wilson 區間；未估計的指標不繪製。各指標分母見表，區間未跨指標校正。",
        )
        if result["roc"] is not None:
            r = result["roc"]
            fig, ax = plt.subplots(figsize=(6, 5), layout="constrained")
            ax.plot([0, 1], [0, 1], "--", color="gray", label="無區辨參考")
            if r["curve"]:
                ax.plot(
                    [p["false_positive_rate"] for p in r["curve"]],
                    [p["sensitivity"] for p in r["curve"]],
                    color="#16766e",
                    label=f"AUC {number(r['estimate'])}",
                )
                e = result["estimates"]
                ax.plot(
                    1 - e["specificity"]["estimate"],
                    e["sensitivity"]["estimate"],
                    "o",
                    color="#ba562e",
                    label="鎖定閾值",
                )
            else:
                ax.text(0.5, 0.5, "缺少其中一個參照類別\nROC / AUC 無法估計", ha="center")
            ax.set(
                xlim=(0, 1),
                ylim=(0, 1.02),
                xlabel="1 − 特異度（False-positive rate）",
                ylabel="敏感度（Sensitivity）",
                title="ROC：同一研究樣本的描述",
            )
            ax.legend(loc="lower right")
            save(
                fig,
                "diagnostic_roc",
                "ROC 沒有用來選切點；標記為已鎖定的判定閾值。AUC 區間見表，此圖未繪製同時信賴帶，也不表示外部驗證完成。",
            )
    if s["agreement"]:
        a, p, e = s["agreement"], pd.DataFrame(result["points"]), result["estimates"]
        fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
        ax.scatter(p["mean"], p.difference, s=18, alpha=0.5, color="#16766e")
        for key, label, color in [
            ("bias_first_minus_second", "平均差異", "#16766e"),
            ("lower_limit_of_agreement", "一致性下限", "#ba562e"),
            ("upper_limit_of_agreement", "一致性上限", "#ba562e"),
        ]:
            row = e[key]
            ax.axhline(
                row["estimate"],
                color=color,
                linestyle="--",
                label=f"{label} {number(row['estimate'])}",
            )
            ax.axhspan(row["ci_lower"], row["ci_upper"], color=color, alpha=0.09)
        if result["margin_comparison"]:
            for key in ["acceptable_lower", "acceptable_upper"]:
                ax.axhline(
                    a[key], color="#884c92", linestyle=":", label=f"可接受界限 {number(a[key])}"
                )
        ax.set(
            xlabel=f"兩次量測平均（{a['unit']}）",
            ylabel=f"第一 − 第二（{a['unit']}）",
            title=f"Bland–Altman | {a['coverage']:.0%} 一致性界限 | n={result['n']}",
        )
        ax.legend(fontsize=8, bbox_to_anchor=(1, 1), loc="upper left")
        save(
            fig,
            "bland_altman",
            f"每點為一名受試者；第一欄減第二欄。陰影為平均差異與兩個一致性界限各自的 {ci} CI，不是涵蓋所有點的信賴帶。檢查差異是否隨量測大小改變；未證明可互換。",
        )
        fig, ax = plt.subplots(figsize=(6, 5), layout="constrained")
        probplot(p.difference, dist="norm", plot=ax)
        ax.set(
            xlabel="常態理論分位數", ylabel=f"觀察差異（{a['unit']}）", title="差異的常態 Q–Q 診斷"
        )
        save(
            fig,
            "agreement_qq",
            "觀察配對差異的常態 Q–Q 圖；明顯偏離直線提示常態差異近似需再檢視。圖形接近直線不保證假設成立。",
        )
        fig, ax = plt.subplots(figsize=(6, 5), layout="constrained")
        ax.scatter(p["second"], p["first"], alpha=0.5, s=18, color="#16766e")
        low, high = (
            float(p[["first", "second"]].min().min()),
            float(p[["first", "second"]].max().max()),
        )
        ax.plot([low, high], [low, high], "--", color="gray", label="兩次量測相等")
        ax.set(
            xlabel=f"{s['second']}（{a['unit']}）",
            ylabel=f"{s['first']}（{a['unit']}）",
            title="配對量測：原始尺度",
        )
        ax.legend()
        save(
            fig,
            "measurement_pairs",
            "原始量測配對與相等參考線；線性相關不等於一致性，也不作單位換算。",
        )
    return records


def tables(result, directory: Path, prefix):
    directory.mkdir(parents=True, exist_ok=True)
    ledger = result["case_ledger"]
    rows = [
        {"data_row": row, "status": label}
        for key, label in [
            ("complete_data_rows", "included"),
            ("missing_excluded_data_rows", "missing_required"),
            ("indeterminate_excluded_data_rows", "indeterminate"),
        ]
        for row in ledger[key]
    ]
    data = {
        "participants": sorted(rows, key=lambda r: r["data_row"]),
        "estimates": [{"indicator": key, **value} for key, value in result["estimates"].items()],
    }
    if result["spec"]["diagnostic"]:
        data["confusion_counts"] = [result["confusion_counts"]]
    if result["roc"] and result["roc"]["curve"]:
        data["roc_curve"] = result["roc"]["curve"]
    if result["points"]:
        data["measurement_pairs"] = result["points"]
    if "table" in result:
        labels = result["categories"]
        data["rater_counts"] = [
            dict(first=x, second=y, count=result["table"][i][j])
            for i, x in enumerate(labels)
            for j, y in enumerate(labels)
        ]
    paths = []
    for name, rows in data.items():
        path = directory / f"{prefix}_{name}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        paths.append(path)
    return paths
