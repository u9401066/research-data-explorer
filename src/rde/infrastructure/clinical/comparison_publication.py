"""Independent comparisons rendered from frozen estimates; no refit or resampling."""

from pathlib import Path
import math
import textwrap

import numpy as np

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure
from rde.infrastructure.visualization.dictionary import DisplayDictionary
from .comparison_report import EFFECTS, figure_blocks
from .regression_report import flow
from .survival_publication import COLORS


def figures(result, directory: Path, prefix, preset_id="journal-neutral-english-v1", edition=None):
    import matplotlib

    matplotlib.use("Agg")
    with publication_style(preset_id) as profile:
        if edition:
            profile["edition"] = edition
        return _figures(result, directory, prefix, profile)


def _number(value, status):
    return (
        f"{value:.3g}"
        if status == "finite"
        else {"positive_infinity": "+inf", "negative_infinity": "-inf", "undefined": "Undefined"}[
            status
        ]
    )


def _figures(result, directory, prefix, profile):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator, LogLocator, NullLocator

    spec, records = result["spec"], []
    dictionary = DisplayDictionary(profile.get("edition", {}).get("display_dictionary"))
    mappings = "".join(
        dictionary.describe(column, [level["value"] for level in entry["levels"]])
        for column, entry in dictionary.entries.items()
        if column != spec["subject"]
    )
    unit = (
        dictionary.compact(dictionary.unit(spec["outcome"], spec["outcome_unit"]), "U1", 18)
        if dictionary.value
        else "U1"
    )
    labels = {name: f"G{i + 1}" for i, name in enumerate(spec["group_levels"])}
    identity_note = (
        "; ".join(f"{code}={name!r}" for name, code in labels.items())
        + f". Outcome={spec['outcome']!r}; U1 denotes source unit {spec['outcome_unit']!r}. "
    )
    direction_note = "Differences are first group minus second; ratios are first / second. "
    if spec["method"] == "binary":
        identity_note += (
            f"Source event={spec['outcome_levels'][1]!r}; non-event={spec['outcome_levels'][0]!r}. "
        )
    confidence = f"{spec['confidence_level']:.1%}"
    source = (
        f"Prespecified independent groups; design={spec['study_design']}; {result['n']} common complete cases. "
        + identity_note
        + f"Outcome definition={spec['outcome_definition']!r}; observation window={spec['outcome_window']!r}. "
        f"Study context={spec['context']!r}. "
        + direction_note
        + "No adjustment for covariates, clusters or repeated observations. Declared sampling does not verify randomization or causal identification. "
    )

    def new(height=80, columns=1):
        return plt.subplots(
            1,
            columns,
            squeeze=False,
            figsize=(180 / 25.4, height * 180 / profile["width_mm"] / 25.4),
            gridspec_kw={"width_ratios": [2, 1.25]} if columns == 2 else None,
        )

    def save(fig, kind, title, caption, explanation, data):
        publication = save_publication_figure(
            fig,
            directory,
            f"{prefix}_comparison_{kind}",
            number=len(records) + 1,
            title=title,
            caption=source + caption + " " + dictionary.note() + mappings,
            explanation=explanation,
            data=data,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
            required_caption=(dictionary.note(), mappings, identity_note, direction_note)
            if dictionary.value
            else (),
        )
        if dictionary.value:
            publication["dictionary_sha256"] = dictionary.value["dictionary_sha256"]
        records.append(
            {
                "path": publication["files"]["png"],
                "plot_type": f"clinical_comparison_{kind}",
                "caption": publication["caption_en"]
                + "\n\n中文解釋："
                + publication["explanation_zh"],
                "fonts": {"family": profile["font_family"], "font_sha256": profile["font_sha256"]},
                "publication": publication,
            }
        )

    fig, axes = new(75)
    ax = axes[0, 0]
    ax.axis("off")
    rows = flow(result)
    table = ax.table(
        cellText=[[textwrap.fill(row["stage"], 21), str(row["cases"])] for row in rows],
        colLabels=["Inclusion step", "Cases"],
        colWidths=[0.68, 0.32],
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2.15)
    for (row, _), item in table.get_celld().items():
        item.set_edgecolor("#c4cbd0")
        if row == 0:
            item.set_facecolor("#eef3f6")
    save(
        fig,
        "flow",
        "Common case inclusion for independent comparisons.",
        "Eligibility is applied before common outcome/group complete-case exclusion. Invalid source codes and supplied identities are checked before missing-outcome exclusion. All prespecified contrasts select their two groups from this common case set; contrast sample sizes differ when more than two groups are specified. Every source row has a retained inclusion status. Complete-case selection does not resolve missingness bias.",
        "先固定納入條件及結果／組別共同完整個案，再取出各項事先指定的兩組比較。圖表保留納排數，資料表可追到每一來源列；完整個案不表示沒有缺失偏差。",
        rows,
    )

    groups = result["groups"]
    fig, axes = new(max(80, 28 + len(groups) * 12))
    ax = axes[0, 0]
    if spec["method"] != "binary":
        for i, group in enumerate(groups):
            points = [p for p in result["observations"] if p["group"] == group["label"]]
            # Display-only deterministic jitter; original outcomes and all rows remain unchanged.
            jitter = [((p["data_row"] * 0.6180339887498949) % 1 - 0.5) * 0.44 for p in points]
            ax.scatter(
                [p["value"] for p in points],
                i + np.array(jitter),
                s=7,
                alpha=0.35,
                color=COLORS[0],
                edgecolors="none",
                rasterized=len(points) > 1000,
            )
            ax.bxp(
                [
                    {
                        "med": group["median"],
                        "q1": group["q25"],
                        "q3": group["q75"],
                        "whislo": group["whisker_low"],
                        "whishi": group["whisker_high"],
                    }
                ],
                positions=[i],
                vert=False,
                widths=0.42,
                showfliers=False,
                manage_ticks=False,
                boxprops={"color": "#222222"},
                medianprops={"color": "#222222"},
                whiskerprops={"color": "#222222"},
                capprops={"color": "#222222"},
            )
        outcome_label = (
            dictionary.compact(dictionary.label(spec["outcome"]), "Observed outcome", 30)
            if dictionary.value
            else "Observed outcome"
        )
        ax.set_xlabel(textwrap.fill(f"{outcome_label} ({unit})", 28))
        caption = "Every retained outcome is shown, with deterministic vertical jitter for display only. Boxes show saved quartiles and medians; whiskers reach the outermost observed values within 1.5 IQR of the quartiles. Points beyond whiskers remain visible and included. These descriptive boxes are not confidence intervals or estimates of median differences. No refitting, resampling or statistical recalculation is performed during rendering."
        data = [{"record": "observation", **p} for p in result["observations"]] + [
            {"record": "summary", **g} for g in groups
        ]
    elif spec["study_design"] in {"case_control", "unspecified"}:
        for i, group in enumerate(groups):
            ax.barh(i, group["events"], color=COLORS[0], label="Event" if i == 0 else None)
            ax.barh(
                i,
                group["non_events"],
                left=group["events"],
                color=COLORS[1],
                label="Non-event" if i == 0 else None,
            )
        ax.set_xlabel("Observed cases")
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.legend(ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.01), frameon=False)
        caption = "Bars show observed event and non-event counts only. Case-control or unspecified sampling does not identify population event probabilities; no probability estimates or confidence intervals are plotted. Outcome counts can reflect the sampling design."
        data = groups
    else:
        for i, group in enumerate(groups):
            ax.hlines(i, group["lower"], group["upper"], color=COLORS[0])
            ax.plot(group["proportion"], i, "o", color=COLORS[0], clip_on=False)
        ax.set_xlim(0, 1)
        ax.set_xlabel("Observed event proportion")
        caption = f"Points are saved event proportions and lines are {confidence} Wilson intervals for each group, pointwise and unadjusted. Overlap of group intervals is not a between-group test. Event proportions depend on the prespecified ascertainment window and sampling assumptions."
        data = groups

    def group_label(value):
        return (
            dictionary.compact(
                f"{labels[value]}: {dictionary.level(spec['group'], value)}", labels[value], 24
            )
            if dictionary.value
            else labels[value]
        )

    ax.set_yticks(
        range(len(groups)),
        [f"{textwrap.fill(group_label(g['label']), 20)}\nn={g['n']}" for g in groups],
    )
    ax.invert_yaxis()
    ax.set_ylabel("Prespecified group")
    save(
        fig,
        "distribution",
        "Observed outcomes by prespecified group.",
        caption,
        "分布圖呈現同一批完整個案；箱型圖是描述分布，病例對照僅顯示計數。一般二元研究的組別區間與組間效果量區間是不同的估計，不以圖上是否重疊判定差異。",
        data,
    )

    for key, kind, rows in figure_blocks(result):
        ratio = kind in {"proportion_ratio", "odds_ratio"}
        null = 1 if ratio else 0
        finite = [
            row[field]
            for row in rows
            for field in ["estimate", "lower", "upper"]
            if row[field + "_status"] == "finite" and (not ratio or row[field] > 0)
        ] + [null]
        if ratio:
            lower_log, upper_log = math.log10(min(finite)), math.log10(max(finite))
            pad = max(0.5, (upper_log - lower_log) * 0.12)
            limits = 10 ** (lower_log - pad), 10 ** (upper_log + pad)
        else:
            low, high = min(finite), max(finite)
            pad = max(0.05 if kind != "mean_difference" else 1e-12, (high - low) * 0.12)
            limits = low - pad, high + pad
        fig, axes = new(max(65, 26 + 13 * len(rows)), columns=2)
        ax, text_ax = axes[0]
        if ratio:
            ax.set_xscale("log")
            ax.xaxis.set_major_locator(LogLocator(numticks=4))
            ax.xaxis.set_minor_locator(NullLocator())
        else:
            ax.xaxis.set_major_locator(MaxNLocator(4))
        ax.set_xlim(*limits)
        ax.axvline(null, color="#777777", linewidth=0.7, linestyle="dashed")
        for i, row in enumerate(rows):
            if row["interval_status"] == "available":
                open_left = (
                    row["lower_status"] == "negative_infinity" or ratio and row["lower"] == 0
                )
                open_right = row["upper_status"] == "positive_infinity"
                low = limits[0] if open_left else row["lower"]
                high = limits[1] if open_right else row["upper"]
                if low is None or high is None:
                    raise ValueError(
                        "An available interval must have defined finite or unbounded endpoints."
                    )
                ax.hlines(i, low, high, color=COLORS[0])
                # Arrows denote genuine parameter-space boundaries, never cropped finite intervals.
                for opened, x, marker in [(open_left, low, "<"), (open_right, high, ">")]:
                    if opened:
                        ax.plot(x, i, marker, color=COLORS[0], markersize=4, clip_on=False)
            if row["estimate_status"] == "finite" and (not ratio or row["estimate"] > 0):
                ax.plot(row["estimate"], i, "o", color=COLORS[0], markersize=4)
            text = _number(row["estimate"], row["estimate_status"])
            text += "\n" + (
                "["
                + _number(row["lower"], row["lower_status"])
                + ", "
                + _number(row["upper"], row["upper_status"])
                + "]"
                if row["interval_status"] == "available"
                else "CI unavailable"
            )
            text_ax.text(0.02, i, text, va="center", fontsize=8)
        ax.set_yticks(
            range(len(rows)),
            [
                f"{labels[r['first_group']]} vs {labels[r['second_group']]}\nn={r['first_n']}/{r['second_n']}"
                for r in rows
            ],
        )
        ax.set_ylim(len(rows) - 0.5, -0.5)
        text_ax.set_ylim(ax.get_ylim())
        text_ax.set_xlim(0, 1)
        text_ax.axis("off")
        text_ax.set_title(f"Estimate\n[{confidence} CI]", loc="left", fontsize=9)
        axis_label = EFFECTS[kind][1] + (f" ({unit})" if kind == "mean_difference" else "")
        ax.set_xlabel(textwrap.fill(axis_label + (" (log scale)" if ratio else ""), 25))
        methods = "; ".join(dict.fromkeys(r["interval_method"] for r in rows))
        description = (
            f"{'Primary' if kind == spec['primary_effect'] else 'Supplementary'} effect: {EFFECTS[kind][1]}; interval procedure: {methods}. "
            f"Pointwise {confidence} intervals are unadjusted. The separate {spec['multiplicity']} p-value family contains {result['multiplicity']['size']} prespecified tests, including an omnibus only if planned. Supplementary effects of one contrast do not create extra independent test results. "
            "The point and interval are drawn independently, because a BCa interval need not contain the observed estimate. Zero, undefined and infinite ratio points have no fabricated location on the log axis and remain explicit in the numeric column. Arrows denote open infinite bounds or the zero limit on a log axis; every finite positive bound is retained within the axis. An unavailable interval is labelled and never replaced by zero width. "
            "The interval and two-sided test can use different procedures; null inclusion is not a substitute for the adjusted p-value. Full precision estimates, endpoint states, interval methods, raw/adjusted p-values and limitations are retained in the CSV and study report. "
        )
        if kind == "rank_biserial":
            description += (
                "Rank-biserial correlation is P(first > second) - P(first < second), with ties contributing zero; it is not a median difference. BCa uses independent within-group resampling, fixed PCG64 seeds and the saved empirical bias and analytic delete-one acceleration. "
                f"Requested resamples={spec['bootstrap']['resamples']}; base seed={spec['bootstrap']['seed']}, incremented by the contrast's zero-based plan index modulo 2^32. Degenerate resampling support cannot quantify population uncertainty. "
            )
        save(
            fig,
            key,
            f"Prespecified {EFFECTS[kind][1].lower()} contrasts.",
            description,
            "方向在計畫內固定，區間為逐項未校正；正式判讀另看完整家族校正 p。零、無法定義、無限大與無法估計區間各自保留。每張最多六項對比，完整文字與原碼在圖說及資料表；換期刊樣式不重新估計。",
            rows,
        )
    return records
