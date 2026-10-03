"""Publication figures for saved paired effects; never estimate or resample here."""

from pathlib import Path
import textwrap

import numpy as np

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure
from rde.infrastructure.visualization.dictionary import DisplayDictionary
from .comparison_publication import _number
from .regression_report import flow
from .repeated_report import EFFECTS, blocks, effect_rows
from .survival_publication import COLORS


def figures(result, directory: Path, prefix, preset_id="journal-neutral-english-v1", edition=None):
    import matplotlib

    matplotlib.use("Agg")
    with publication_style(preset_id) as profile:
        if edition:
            profile["edition"] = edition
        return _figures(result, directory, prefix, profile)


def _figures(result, directory, prefix, profile):
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.ticker import MaxNLocator

    spec, records = result["spec"], []
    dictionary = DisplayDictionary(profile.get("edition", {}).get("display_dictionary"))
    mappings = "".join(
        dictionary.describe(column, [level["value"] for level in entry["levels"]])
        for column, entry in dictionary.entries.items()
        if column != spec["subject"]
    )
    # Every occasion has already been checked against the same saved outcome unit.
    reviewed_units = [
        e["unit"]
        for c, e in dictionary.entries.items()
        if c in [m["column"] for m in spec["measurements"]] and "unit" in e
    ]
    unit = (
        dictionary.compact(reviewed_units[0] if reviewed_units else spec["outcome_unit"], "U1", 18)
        if dictionary.value
        else "U1"
    )
    labels = {m["column"]: f"T{i + 1}" for i, m in enumerate(spec["measurements"])}

    def occasion_label(column):
        return (
            dictionary.compact(f"{labels[column]}: {dictionary.label(column)}", labels[column], 22)
            if dictionary.value
            else labels[column]
        )

    confidence = f"{spec['confidence_level']:.1%}"
    source = (
        "Prespecified within-person comparisons; "
        + "; ".join(
            f"{labels[m['column']]}={m['label']!r} (source {m['column']!r})"
            for m in spec["measurements"]
        )
        + f". Outcome={spec['outcome_name']!r}; U1 denotes source unit {spec['outcome_unit']!r}. "
        f"Outcome definition={spec['outcome_definition']!r}; context={spec['context']!r}. "
        f"Case strategy={spec['case_strategy']}; common complete subjects n={result['n']}. "
        "Every contrast is first occasion minus second, as prespecified; display order does not change direction. "
        "No imputation, implicit rounding or column-name plausibility exclusion. Within-person differences do not establish causal treatment effects. "
    )

    def new(height=80, rows=1, columns=1, forest=False):
        return plt.subplots(
            rows,
            columns,
            squeeze=False,
            figsize=(180 / 25.4, height * 180 / profile["width_mm"] / 25.4),
            gridspec_kw={"width_ratios": [2, 1.25]} if forest else None,
        )

    def save(fig, key, title, caption, explanation, data):
        publication = save_publication_figure(
            fig,
            directory,
            f"{prefix}_repeated_{key}",
            number=len(records) + 1,
            title=title,
            caption=source + caption + " " + dictionary.note() + mappings,
            explanation=explanation,
            data=data,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
            required_caption=(dictionary.note(), mappings, source) if dictionary.value else (),
        )
        if dictionary.value:
            publication["dictionary_sha256"] = dictionary.value["dictionary_sha256"]
        records.append(
            {
                "path": publication["files"]["png"],
                "plot_type": f"clinical_repeated_{key}",
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
    rows[3]["stage"] = "Missing any occasion"
    rows[4]["stage"] = "Common complete subjects"
    table = ax.table(
        cellText=[[textwrap.fill(r["stage"], 22), str(r["cases"])] for r in rows],
        colLabels=["Inclusion step", "Subjects"],
        colWidths=[0.7, 0.3],
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
        "Common complete subject inclusion.",
        "Identity checks precede missing-measurement exclusion within the eligible cohort. The common trajectory, occasion summaries and optional Friedman analysis use this complete set. Prespecified pairwise contrasts can retain additional subjects under the pairwise strategy; each contrast's own n and source rows are reported separately. Missingness bias is not resolved by deletion.",
        "共同描述圖與 Friedman 使用全時點完整個案；若採每對完整個案，每項比較另標自己的 n。圖表與資料表保留排除原因，身份重複不能被缺失掩蓋。",
        rows,
    )

    fig, axes = new(85)
    ax = axes[0, 0]
    values = np.array([row["values"] for row in result["observations"]])
    x = np.arange(values.shape[1])
    segments = np.stack([np.broadcast_to(x, values.shape), values], axis=-1)
    collection = LineCollection(
        segments, color=COLORS[0], alpha=0.22, linewidth=0.55, rasterized=len(values) > 1000
    )
    ax.add_collection(collection)
    ax.scatter(
        np.tile(x, len(values)),
        values.ravel(),
        s=5,
        color=COLORS[0],
        alpha=0.22,
        edgecolors="none",
        rasterized=len(values) > 1000,
    )
    occasions = result["occasions"]
    medians = [r["median"] for r in occasions]
    ax.plot(x, medians, "o-", color="#222222", label="Median", markersize=4)
    ax.vlines(
        x,
        [r["q25"] for r in occasions],
        [r["q75"] for r in occasions],
        color="#222222",
        linewidth=2,
    )
    ax.autoscale_view()
    ax.set_xticks(
        x, [f"{textwrap.fill(occasion_label(r['column']), 12)}\nn={r['n']}" for r in occasions]
    )
    ax.set_xlabel("Prespecified occasion (categorical spacing)")
    outcome_label = (
        dictionary.compact(spec["outcome_name"], "Observed outcome", 30)
        if dictionary.value
        else "Observed outcome"
    )
    ax.set_ylabel(textwrap.fill(f"{outcome_label} ({unit})", 28))
    ax.legend(loc="best", frameon=False)
    save(
        fig,
        "trajectory",
        "Individual trajectories and common-case summaries.",
        "Every common-complete subject is connected across all declared occasions. The black points and vertical bars are saved medians and first/third quartiles, not confidence intervals. Occasions are equally spaced categories, not a continuous elapsed-time axis. No fitted trajectory or outcome rescaling is shown. Dense individual marks above 1,000 subjects are rasterized inside vector exports; no subjects are sampled out. Source rows and full original values remain in the drawing table.",
        "每條線連接同一位受試者的全部時點。黑點／直線是中位數與四分位距，並非效果量 CI；時點等距只代表分類順序。沒有抽掉密集個案，也沒有把缺失者補成完整軌跡。",
        [
            {
                "record": "observation",
                "data_row": row["data_row"],
                **dict(zip(labels.values(), row["values"], strict=True)),
            }
            for row in result["observations"]
        ]
        + [{"record": "summary", **row} for row in occasions],
    )

    for key, contrasts in blocks(result, 2):
        fig, axes = new(70 * len(contrasts), rows=len(contrasts), columns=2)
        data = []
        for i, contrast in enumerate(contrasts):
            ax, diff_ax = axes[i]
            a, b = [labels[c] for c in contrast["columns"]]
            first_label, second_label = [occasion_label(c) for c in contrast["columns"]]
            observations = contrast["observations"]
            first, second = [p["first"] for p in observations], [p["second"] for p in observations]
            low, high = min(first + second), max(first + second)
            span = high - low
            pad = max(abs(low) * 0.01, 1e-12) if span == 0 else span * 0.08
            limits = low - pad, high + pad
            ax.plot(limits, limits, linestyle="dashed", color="#777777", linewidth=0.7)
            ax.scatter(
                second,
                first,
                s=10,
                alpha=0.4,
                color=COLORS[0],
                edgecolors="none",
                rasterized=len(observations) > 1000,
            )
            ax.set_xlim(*limits)
            ax.set_ylim(*limits)
            ax.set_xlabel(textwrap.fill(f"{second_label} ({unit})", 24))
            ax.set_ylabel(textwrap.fill(f"{first_label} ({unit})", 24))
            ax.set_title(f"{a} vs {b}; n={contrast['n']}", fontsize=9)
            ax.xaxis.set_major_locator(MaxNLocator(4))
            ax.yaxis.set_major_locator(MaxNLocator(4))
            jitter = [((p["data_row"] * 0.6180339887498949) % 1 - 0.5) * 0.7 for p in observations]
            diff_ax.scatter(
                [p["difference"] for p in observations],
                jitter,
                s=10,
                alpha=0.4,
                color=COLORS[0],
                edgecolors="none",
                rasterized=len(observations) > 1000,
            )
            diff_ax.axvline(0, color="#777777", linewidth=0.7, linestyle="dashed")
            diff_ax.set_ylim(-0.6, 0.6)
            diff_ax.set_yticks([])
            diff_ax.set_xlabel(textwrap.fill(f"{a} minus {b} ({unit})", 24))
            diff_ax.set_title("Individual paired differences", fontsize=9)
            diff_ax.xaxis.set_major_locator(MaxNLocator(4))
            data.extend(
                {
                    "contrast_id": contrast["id"],
                    "first_column": contrast["columns"][0],
                    "second_column": contrast["columns"][1],
                    **p,
                }
                for p in observations
            )
        save(
            fig,
            f"pairs_{key}",
            "Paired observations and individual differences.",
            "Each left panel shows both measurements from the same retained subject; the dashed line denotes equality. Each right panel shows every saved first-minus-second difference, with deterministic vertical jitter for visibility only. Subject pairing, values and sample sizes are unchanged. Panels are descriptive, not fitted regression, correlation inference or population effect intervals; the effect forest carries the separately estimated uncertainty. Pairwise and common-case populations can differ.",
            "左圖每個點來自同一人的兩次量測；右圖呈現每個人的原始差值。抖動只為避免遮蔽。這些是描述圖，不是相關檢定或效果量區間；每張都標示實際配對 n。",
            data,
        )

    effect_lookup = {row["contrast_id"]: row for row in effect_rows(result)}
    forests = [
        (f"effects_{key}", spec["primary_effect"], [effect_lookup[c["id"]] for c in contrasts])
        for key, contrasts in blocks(result, 6)
    ]
    if result["omnibus"]:
        forests.append(("kendall_w", "kendall_w", [effect_lookup["omnibus"]]))
    for key, kind, rows in forests:
        fig, axes = new(max(65, 26 + 13 * len(rows)), columns=2, forest=True)
        ax, text_ax = axes[0]
        finite = [
            row[k]
            for row in rows
            for k in ("estimate", "lower", "upper")
            if row[k + "_status"] == "finite"
        ] + [0]
        low, high = min(finite), max(finite)
        if kind == "rank_biserial":
            limits = -1.05, 1.05
        elif kind == "kendall_w":
            limits = -0.05, 1.05
        else:
            pad = max(1e-12, (high - low) * 0.12)
            limits = low - pad, high + pad
        ax.set_xlim(*limits)
        ax.axvline(0, linestyle="dashed", color="#777777", linewidth=0.7)
        for i, row in enumerate(rows):
            if row["interval_status"] == "available":
                ax.hlines(i, row["lower"], row["upper"], color=COLORS[0])
            if row["estimate_status"] == "finite":
                ax.plot(row["estimate"], i, "o", color=COLORS[0], markersize=4)
            value = _number(row["estimate"], row["estimate_status"])
            bounds = (
                "["
                + _number(row["lower"], row["lower_status"])
                + ", "
                + _number(row["upper"], row["upper_status"])
                + "]"
                if row["interval_status"] == "available"
                else "CI unavailable"
            )
            text_ax.text(0.02, i, value + "\n" + bounds, va="center", fontsize=8)
        ax.set_yticks(
            range(len(rows)),
            [
                f"{labels[r['first_column']]} - {labels[r['second_column']]}\nn={r['n']}"
                if r["first_column"]
                else f"All occasions\nn={r['n']}"
                for r in rows
            ],
        )
        ax.set_ylim(len(rows) - 0.5, -0.5)
        ax.xaxis.set_major_locator(MaxNLocator(4))
        ax.set_xlabel(
            textwrap.fill(
                EFFECTS[kind][1] + (f" ({unit})" if kind == "mean_difference" else ""), 25
            )
        )
        text_ax.set_ylim(ax.get_ylim())
        text_ax.set_xlim(0, 1)
        text_ax.axis("off")
        text_ax.set_title(f"Estimate\n[{confidence} CI]", loc="left", fontsize=9)
        method = "; ".join(dict.fromkeys(r["interval_method"] for r in rows))
        caption = (
            f"Saved {EFFECTS[kind][1]} with pointwise, unadjusted {confidence} intervals. Procedure: {method}. "
            f"All {result['multiplicity']['size']} prespecified tests, including Friedman only if planned, form one {spec['multiplicity']} p-value family; no contrasts are selected by significance. "
            "Points and intervals are drawn separately because a BCa interval need not contain the observed point. Undefined estimates and unavailable intervals remain explicit; no fabricated zero-width interval is drawn. Full-precision values, actual n, raw/adjusted p and failure reasons are in the data and report. "
        )
        if kind != "mean_difference":
            caption += f"BCa resamples complete subject vectors with NumPy PCG64, {spec['bootstrap']['resamples']} requested draws; base seed={spec['bootstrap']['seed']}, plus the zero-based contrast index, or the number of contrasts for Friedman, modulo 2^32. Undefined resamples are not discarded. "
        if kind == "rank_biserial":
            caption += "The effect is (positive difference rank sum - negative difference rank sum) / total nonzero rank sum. Wilcox zeros are excluded from ranks, retained in subject resampling. It is not a median difference or independent-group dominance. BCa null inclusion does not invert the conditional signed-rank test. "
        if kind == "kendall_w":
            caption += "Tie-corrected W has no signed direction and is not a proportion of outcome variance explained. Friedman uses a chi-square approximation, potentially inaccurate with at most 10 subjects or at most 6 occasions. W uncertainty is separate from the paired contrast effects. "
        save(
            fig,
            key,
            "Prespecified paired effect uncertainty."
            if kind != "kendall_w"
            else "Overall occasion rank concordance.",
            caption,
            "每條效果量與區間來自保存數值，完整保留方向、配對 n 與無法估計原因。CI 逐項未校正，正式檢定另看全家族校正 p；配對秩效果與整體 Kendall W 是不同的量，不作混用。",
            rows,
        )
    return records
