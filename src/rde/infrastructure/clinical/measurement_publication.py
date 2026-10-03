"""English publication graphics over a frozen diagnostic/agreement receipt."""

from pathlib import Path
import textwrap

import numpy as np

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure
from rde.infrastructure.visualization.dictionary import DisplayDictionary

BLUE, ORANGE, GRAY, PURPLE = "#0072B2", "#D55E00", "#656565", "#882255"
NAMES = {
    "sensitivity": "Sensitivity",
    "specificity": "Specificity",
    "positive_predictive_value": "Positive predictive value",
    "negative_predictive_value": "Negative predictive value",
    "accuracy": "Accuracy",
}


def number(value):
    return f"{value:.3f}" if value is not None else "not estimable"


def figures(result, directory: Path, prefix, preset_id="journal-neutral-english-v1", edition=None):
    import matplotlib

    matplotlib.use("Agg")
    with publication_style(preset_id) as profile:
        if edition:
            profile["edition"] = edition
        return _figures(result, directory, prefix, profile)


def _figures(result, directory, prefix, profile):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from scipy.stats import probplot

    spec, records = result["spec"], []
    dictionary = DisplayDictionary(profile.get("edition", {}).get("display_dictionary"))
    mappings = "".join(
        dictionary.describe(column, [level["value"] for level in entry["levels"]])
        for column, entry in dictionary.entries.items()
        if column != spec["subject"]
    )
    diagnostic, agreement = spec["diagnostic"], spec["agreement"]
    if diagnostic:
        rule = (
            f"score {'>=' if diagnostic['positive_direction'] == 'greater_equal' else '<='} {diagnostic['threshold']}"
            if diagnostic["test_kind"] == "score"
            else f"positive code {diagnostic['test_positive']!r}; negative code {diagnostic['test_negative']!r}"
        )
        identity_note = f"Reference standard is source column {spec['first']!r}; positive={diagnostic['positive']!r}, negative={diagnostic['negative']!r}. Index test is source column {spec['second']!r}, with locked {rule} ({diagnostic['threshold_status']}). "
        if diagnostic["test_kind"] == "score":
            identity_note += "The saved diagnostic contract does not declare a score unit; any reviewed unit describes the original source scale, without changing the score or locked threshold. "
    elif agreement:
        identity_note = f"Measurement 1 is source column {spec['first']!r}; measurement 2 is {spec['second']!r}. Differences are measurement 1 minus measurement 2; both use saved source unit {agreement['unit']!r}, without conversion. U1 denotes this same source unit when a compact axis label is needed. "
    else:
        identity_note = (
            f"First rater is source column {spec['first']!r}; second rater is {spec['second']!r}. "
            + "; ".join(f"C{i + 1}={c!r}" for i, c in enumerate(result["categories"]))
            + ". Shared raw categories and table direction are unchanged. "
        )

    def variable_label(column, fallback):
        return (
            textwrap.fill(dictionary.compact(dictionary.label(column), fallback, 32), 24)
            if dictionary.value
            else fallback
        )

    n = result["n"]
    ci = f"{spec['confidence_level']:.1%}"
    pair_note = (
        f"The analysis included {n} complete pairs, with one pair per independent participant. "
        "The same included participants were used for all estimates and plots. "
    )

    def new(height=120):
        return plt.subplots(figsize=(180 / 25.4, height / 25.4))

    def save(fig, kind, title, caption, explanation, data, suffix=None):
        publication = save_publication_figure(
            fig,
            directory,
            f"{prefix}_{suffix or kind}",
            number=len(records) + 1,
            title=title,
            caption=caption
            + " "
            + dictionary.note()
            + mappings
            + (identity_note if dictionary.value else ""),
            explanation=explanation,
            data=data,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
            required_caption=(dictionary.note(), mappings, identity_note)
            if dictionary.value
            else (),
        )
        if dictionary.value:
            publication["dictionary_sha256"] = dictionary.value["dictionary_sha256"]
        records.append(
            dict(
                path=publication["files"]["png"],
                plot_type=f"clinical_{kind}",
                caption=publication["caption_en"]
                + "\n\n中文解釋："
                + publication["explanation_zh"],
                fonts={"family": profile["font_family"], "font_sha256": profile["font_sha256"]},
                publication=publication,
            )
        )

    ledger = result["case_ledger"]
    flow = [
        {"stage": "Source participants", "n": ledger["input_rows"]},
        {"stage": "Missing required values", "n": len(ledger["missing_excluded_data_rows"])},
        {
            "stage": "Indeterminate after missing exclusions",
            "n": len(ledger["indeterminate_excluded_data_rows"]),
        },
        {"stage": "Complete pairs analyzed", "n": n},
    ]
    fig, ax = new(100)
    ax.axis("off")
    for yy, row in [(0.88, flow[0]), (0.12, flow[3])]:
        ax.text(
            0.5,
            yy,
            f"{row['stage']}\nn = {row['n']}",
            ha="center",
            va="center",
            fontsize=10,
            bbox=dict(boxstyle="round,pad=0.6", facecolor="white", edgecolor=BLUE),
        )
    ax.annotate(
        "",
        xy=(0.5, 0.26),
        xytext=(0.5, 0.72),
        arrowprops=dict(arrowstyle="->", color=GRAY, linewidth=1.2),
    )
    ax.text(
        0.56,
        0.52,
        f"Excluded\nMissing required values: {flow[1]['n']}\nIndeterminate: {flow[2]['n']}",
        va="center",
        fontsize=9,
    )
    save(
        fig,
        "participant_flow",
        "Participant inclusion and exclusion.",
        pair_note
        + "Exclusions are mutually exclusive: missing required values are assigned first, followed by indeterminate results among remaining complete records. Excluding such results may introduce selection bias.",
        "缺失優先歸類，與剩餘完整欄位中的無法判讀排除互斥；所有數值與圖表共用同一組完整配對。",
        flow,
    )

    if diagnostic or spec["family"] == "cohens_kappa":
        if diagnostic:
            c = result["confusion_counts"]
            matrix, labels = (
                np.asarray([[c["TP"], c["FP"]], [c["FN"], c["TN"]]]),
                ["Positive", "Negative"],
            )
        else:
            matrix = np.asarray(result["table"])
            # Stable short codes keep long/non-English category labels legible.
            # Exact source labels remain in the caption mapping and plot CSV.
            labels = [f"C{i + 1}" for i in range(len(result["categories"]))]
        count = len(labels)
        # At most 10 × 10 cells per panel keeps exact counts readable at 9 pt.
        for start_row in range(0, count, 10):
            for start_col in range(0, count, 10):
                rows, cols = (
                    list(range(start_row, min(count, start_row + 10))),
                    list(range(start_col, min(count, start_col + 10))),
                )
                fig, ax = new(145)
                data = []
                for y, i in enumerate(rows):
                    for x, j in enumerate(cols):
                        value = int(matrix[i, j])
                        strength = value / max(1, int(matrix.max()))
                        ax.add_patch(
                            Rectangle(
                                (x - 0.5, y - 0.5),
                                1,
                                1,
                                facecolor=plt.cm.Blues(0.08 + 0.8 * strength),
                                edgecolor="white",
                            )
                        )
                        abbr = [["TP", "FP"], ["FN", "TN"]][i][j] + "\n" if diagnostic else ""
                        ax.text(
                            x,
                            y,
                            abbr + str(value),
                            ha="center",
                            va="center",
                            fontsize=11 if diagnostic else 9,
                            color="white" if strength > 0.55 else "#202020",
                        )
                        data.append(
                            dict(
                                row_code=labels[i],
                                column_code=labels[j],
                                count=value,
                                row_label=labels[i] if diagnostic else result["categories"][i],
                                column_label=(
                                    diagnostic["positive"] if j == 0 else diagnostic["negative"]
                                )
                                if diagnostic
                                else result["categories"][j],
                            )
                        )
                ax.set(
                    xticks=range(len(cols)),
                    xticklabels=[labels[j] for j in cols],
                    yticks=range(len(rows)),
                    yticklabels=[labels[i] for i in rows],
                    xlim=(-0.5, len(cols) - 0.5),
                    ylim=(len(rows) - 0.5, -0.5),
                    aspect="equal",
                    xlabel=variable_label(
                        spec["first"] if diagnostic else spec["second"],
                        "Reference standard" if diagnostic else "Second rater",
                    ),
                    ylabel=variable_label(
                        spec["second"] if diagnostic else spec["first"],
                        "Index test" if diagnostic else "First rater",
                    ),
                )
                ax.tick_params(length=0)
                for spine in ax.spines.values():
                    spine.set_visible(False)
                if diagnostic:
                    rule = (
                        f"score {'≥' if diagnostic['positive_direction'] == 'greater_equal' else '≤'} {diagnostic['threshold']}"
                        if diagnostic["test_kind"] == "score"
                        else f"positive code {diagnostic['test_positive']!r}"
                    )
                    caption = (
                        pair_note
                        + f"Rows represent the index test and columns the supplied reference standard. The locked index-test rule was {rule} ({diagnostic['threshold_status']}). Reference positive and negative codes were {diagnostic['positive']!r} and {diagnostic['negative']!r}. TP, FP, FN and TN denote true positive, false positive, false negative and true negative relative to that reference. Reference independence was declared {diagnostic['reference_independence']}; software does not verify diagnostic truth or blinding. Darker cells indicate larger counts."
                    )
                    kind, title = (
                        "diagnostic_matrix",
                        "Classification under the locked diagnostic rule.",
                    )
                else:
                    e = result["estimates"]["cohens_kappa"]
                    mapping = "; ".join(
                        f"{code}={label!r}"
                        for code, label in zip(labels, result["categories"], strict=True)
                    )
                    caption = (
                        pair_note
                        + f"Rows represent the first rater and columns the second; both use the same declared categories. Exact mapping: {mapping}. "
                    )
                    if count > 10:
                        caption += f"This panel displays rows {labels[rows[0]]}–{labels[rows[-1]]} and columns {labels[cols[0]]}–{labels[cols[-1]]}; all panels share the count scale. "
                    caption += f"Unweighted Cohen kappa for the full table was {number(e['estimate'])} ({ci} asymptotic normal CI {number(e['ci_lower'])}–{number(e['ci_upper'])}); observed agreement was {number(result['observed_agreement'])}. Kappa is sensitive to category frequencies, and sparse-table intervals can be unstable. Agreement does not establish diagnostic validity. Darker cells indicate larger counts."
                    kind, title = "kappa_matrix", "Paired ratings and chance-adjusted agreement."
                suffix = (
                    f"{kind}_{start_row // 10 + 1}_{start_col // 10 + 1}" if count > 10 else kind
                )
                save(
                    fig,
                    kind,
                    title,
                    caption,
                    "逐格保留配對人數；列為待測方法的陽性／陰性分類，欄為參照標準。原始代碼與分類規則分開記錄。"
                    if diagnostic
                    else "逐格保留配對人數；列為第一評分者、欄為第二評分者。類別代號與原始值有明確對照，不以一致性宣稱診斷正確。",
                    data,
                    suffix=suffix,
                )

    if diagnostic:
        fig, ax = new(115)
        entries = list(result["estimates"].items())
        data, labels = [], []
        for i, (key, row) in enumerate(entries):
            labels.append(
                NAMES[key]
                + (f"\n{row['numerator']}/{row['denominator']}" if "denominator" in row else "")
            )
            if row.get("estimate") is not None:
                ax.plot(
                    [row["ci_lower"], row["ci_upper"]], [i, i], color=BLUE, marker="|", markersize=6
                )
                ax.plot(row["estimate"], i, "o", color=BLUE)
            else:
                reason = (
                    "Not reported: sampling design"
                    if row.get("status") == "withheld_by_sampling_design"
                    else "Not estimable: zero denominator"
                )
                ax.text(0.5, i, reason, ha="center", va="center", fontsize=8, color=GRAY)
            data.append({"indicator": key, **row})
        ax.set(
            yticks=range(len(entries)),
            yticklabels=labels,
            ylim=(len(entries) - 0.5, -0.5),
            xlim=(-0.02, 1.02),
            xlabel=f"Proportion ({ci} Wilson confidence interval)",
        )
        save(
            fig,
            "diagnostic_intervals",
            "Diagnostic estimates with their own denominators.",
            pair_note
            + f"Points and capped horizontal lines show proportions and {ci} Wilson confidence intervals, without multiplicity adjustment. Each displayed fraction is that measure's numerator and denominator. Sampling was declared {diagnostic['sampling']}. Predictive values and accuracy are not reported when sampling is unknown or outcome-selected; this policy differs from a zero denominator. Sensitivity and specificity may still be affected by spectrum or selection bias. Single-gate sampling does not guarantee population representativeness.",
            "每個指標保留自己的分子與分母；橫線是 Wilson 區間。依抽樣設計不提供與零分母無法估計分開標示。",
            data,
        )
        r = result["roc"]
        if r is not None:
            fig, ax = new(135)
            ax.plot([0, 1], [0, 1], "--", color=GRAY, linewidth=1)
            data = [{"series": "empirical_roc", **p} for p in r["curve"]]
            if r["curve"]:
                ax.plot(
                    [p["false_positive_rate"] for p in r["curve"]],
                    [p["sensitivity"] for p in r["curve"]],
                    color=BLUE,
                    label=f"AUC {number(r['estimate'])} ({ci} CI {number(r['ci_lower'])}–{number(r['ci_upper'])})",
                )
                e = result["estimates"]
                fpr, tpr = 1 - e["specificity"]["estimate"], e["sensitivity"]["estimate"]
                ax.plot(fpr, tpr, "D", color=ORANGE, label="Locked threshold")
                data.append(
                    dict(
                        series="locked_threshold",
                        false_positive_rate=fpr,
                        sensitivity=tpr,
                        oriented_threshold=diagnostic["threshold"]
                        * (1 if diagnostic["positive_direction"] == "greater_equal" else -1),
                    )
                )
                ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), fontsize=8)
            else:
                ax.text(0.5, 0.5, "ROC not estimable:\nonly one reference class", ha="center")
                data.append(dict(series="not_estimable", reason=r["reason"]))
            ax.set(
                xlim=(0, 1),
                ylim=(0, 1.02),
                xlabel="False-positive rate (1 − specificity)",
                ylabel="Sensitivity",
            )
            save(
                fig,
                "diagnostic_roc",
                "Empirical discrimination of the supplied diagnostic score.",
                pair_note
                + f"The curve uses every score threshold; the diamond marks the locked rule (score {'≥' if diagnostic['positive_direction'] == 'greater_equal' else '≤'} {diagnostic['threshold']}, {diagnostic['threshold_status']}). The dashed diagonal denotes no discrimination. AUC={number(r['estimate'])}; {ci} CI {number(r['ci_lower'])}–{number(r['ci_upper'])}. "
                "When each reference class has at least two participants, the AUC interval uses 1,000 stratified participant bootstrap draws (seed 20261001), fixing each class count. Otherwise the interval is not estimated. The interval is for scalar AUC, not a band for the curve; small or perfectly separated samples can yield degenerate intervals. No cutoff was optimized and no external validation was performed.",
                "標記的是鎖定閾值，ROC 不另找最佳切點；AUC 區間不是整條曲線的信賴帶。參照或選樣偏差不能靠 bootstrap 修正。",
                data,
            )

    if agreement:
        points, e = result["points"], result["estimates"]
        unit = (
            dictionary.compact(
                dictionary.unit(spec["first"], dictionary.unit(spec["second"], agreement["unit"])),
                "U1",
                18,
            )
            if dictionary.value
            else agreement["unit"]
        )
        # Raw column names remain in captions/CSV; numbered methods keep plot labels English.
        definitions = f"Measurement 1 is source column {spec['first']!r}; measurement 2 is {spec['second']!r}. Both use {agreement['unit']}; no unit conversion was applied. "
        fig, ax = new(145)
        ax.scatter(
            [p["mean"] for p in points],
            [p["difference"] for p in points],
            s=18,
            facecolors="none",
            edgecolors=BLUE,
            linewidths=0.8,
        )
        for key, label, color, style in [
            ("bias_first_minus_second", "Mean difference", BLUE, "-"),
            ("lower_limit_of_agreement", "Lower limit of agreement", ORANGE, "--"),
            ("upper_limit_of_agreement", "Upper limit of agreement", ORANGE, "--"),
        ]:
            row = e[key]
            ax.axhline(
                row["estimate"],
                color=color,
                linestyle=style,
                linewidth=1.1,
                label=f"{label}: {number(row['estimate'])}",
            )
            ax.axhspan(row["ci_lower"], row["ci_upper"], color=color, alpha=0.1)
        if result["margin_comparison"]:
            for key, label in [
                ("acceptable_lower", "Acceptable lower limit"),
                ("acceptable_upper", "Acceptable upper limit"),
            ]:
                ax.axhline(
                    agreement[key],
                    color=PURPLE,
                    linestyle=":",
                    label=f"{label}: {number(agreement[key])}",
                )
        ax.set(
            xlabel=textwrap.fill(f"Mean of measurements 1 and 2 ({unit})", 38),
            ylabel=textwrap.fill(f"Difference: measurement 1 − measurement 2 ({unit})", 38),
        )
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), fontsize=8)
        estimates = "; ".join(
            f"{label} {number(e[key]['estimate'])} ({ci} CI {number(e[key]['ci_lower'])} to {number(e[key]['ci_upper'])})"
            for key, label in [
                ("bias_first_minus_second", "mean difference"),
                ("lower_limit_of_agreement", "lower limit"),
                ("upper_limit_of_agreement", "upper limit"),
            ]
        )
        caption = (
            pair_note
            + definitions
            + f"Each circle is one pair. Differences are measurement 1 minus measurement 2; the horizontal coordinate is their mean. The {agreement['coverage']:.1%} limits of agreement use mean difference ± the corresponding normal quantile × sample SD: {estimates}, in {unit}. Shaded horizontal regions show separate {ci} intervals for the mean difference (t method) and each limit (normal-differences approximation); they are neither a simultaneous band nor intervals for individual differences. Normal differences and stable variance are assumptions, not proven by the plot. "
        )
        caption += (
            "Dotted purple lines show prespecified acceptable differences; this descriptive comparison is not a formal equivalence test."
            if result["margin_comparison"]
            else "No acceptable-difference margins were specified; interchangeability cannot be concluded."
        )
        plot_data = [{"record_type": "pair", **p} for p in points] + [
            {"record_type": "estimate", "indicator": key, **row} for key, row in e.items()
        ]
        if result["margin_comparison"]:
            plot_data += [
                {"record_type": "acceptable_margin", "indicator": key, "estimate": agreement[key]}
                for key in ["acceptable_lower", "acceptable_upper"]
            ]
        save(
            fig,
            "bland_altman",
            "Paired differences and limits of agreement.",
            caption,
            "差異固定為第一減第二。涵蓋比例、一致性界限自身的 CI、平均差異 CI 是不同概念；陰影不是包含所有點的信賴帶。",
            plot_data,
        )

        theoretical, observed = probplot([p["difference"] for p in points], dist="norm", fit=False)
        reference = e["bias_first_minus_second"]["estimate"] + result["sd_difference"] * theoretical
        fig, ax = new(125)
        ax.plot(theoretical, observed, "o", color=BLUE, markerfacecolor="none", markersize=4)
        ax.plot(
            theoretical, reference, "--", color=GRAY, label="Normal reference (sample mean and SD)"
        )
        ax.set(
            xlabel="Theoretical standard-normal quantile",
            ylabel=f"Ordered paired difference ({unit})",
        )
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), fontsize=8)
        ordered = sorted(points, key=lambda p: p["difference"])
        save(
            fig,
            "agreement_qq",
            "Normal probability plot of paired differences.",
            pair_note
            + definitions
            + "Observed differences are ordered against Filliben standard-normal order-statistic medians. The dashed line uses the sample mean difference and SD from this analysis; no new regression line or hypothesis test was fitted. Curvature or extreme departures can indicate inadequacy of the normal-differences approximation, but apparent alignment does not establish normality or interchangeability.",
            "常態機率圖使用保存的平均差異與標準差畫參考線，不另擬合迴歸或新增 p 值；接近直線不能證明假設成立。",
            [
                dict(
                    data_row=p["data_row"],
                    theoretical_quantile=float(x),
                    ordered_difference=float(y),
                    saved_normal_reference=float(v),
                )
                for p, x, y, v in zip(ordered, theoretical, observed, reference, strict=True)
            ],
        )
        fig, ax = new(125)
        ax.scatter(
            [p["second"] for p in points],
            [p["first"] for p in points],
            s=18,
            facecolors="none",
            edgecolors=BLUE,
        )
        low, high = (
            min(min(p["first"], p["second"]) for p in points),
            max(max(p["first"], p["second"]) for p in points),
        )
        ax.plot([low, high], [low, high], "--", color=GRAY, label="Identity")
        ax.set(
            xlabel=f"{variable_label(spec['second'], 'Measurement 2')}\n({unit})",
            ylabel=f"{variable_label(spec['first'], 'Measurement 1')}\n({unit})",
            aspect="equal",
        )
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), fontsize=8)
        save(
            fig,
            "measurement_pairs",
            "Original paired measurements.",
            pair_note
            + definitions
            + "Each circle is one paired observation on the original scale. The dashed line is identity. The axes use equal physical scaling; no regression or correlation test is added. Correlation, even if high, would not establish agreement.",
            "原始配對保持相同單位及等比例座標；相關程度不能替代一致性判讀。",
            points,
        )
    return records
