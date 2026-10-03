"""English longitudinal figures and Chinese explanations from saved estimates only."""

from pathlib import Path
import textwrap

import numpy as np
from scipy.stats import norm

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure
from rde.infrastructure.visualization.dictionary import DisplayDictionary
from .longitudinal_report import flow, term_description
from .survival_publication import COLORS, short_label


def term_label(row, result, codes, dictionary=None):
    """Compact contrasts; full original names and reference conditions stay in captions."""
    dictionary = dictionary or DisplayDictionary()
    compact = dictionary.compact if dictionary.value else short_label
    if row["role"] == "interaction":
        terms = {r["term"]: r for r in result["coefficients"]}
        time, group = [terms[key] for key in row["components"]]
        return f"{term_label(time, result, codes, dictionary)} × {codes[group['level']]} vs {codes[group['reference']]}"
    column = row["variable"]
    code = (
        "T"
        if row["role"] == "time"
        else "G"
        if row["role"] == "group"
        else f"C{result['spec']['covariates'].index(column) + 1}"
    )
    name = compact(dictionary.label(column), compact(column, code, 16), 16)
    if "level" in row:

        def label(value):
            # Time stays on its exact numerical scale. Source spellings such as
            # "01" and "1.0" must not be silently merged into one dictionary code.
            if row["role"] == "time":
                return f"{value:g}"
            fallback = (
                codes[value]
                if row["role"] == "group"
                else row["term"] + ":" + ("ref" if value == row["reference"] else "level")
            )
            return compact(dictionary.level(column, value), compact(value, fallback, 14), 14)

        level, reference = label(row["level"]), label(row["reference"])
        return f"{name}: {level} vs {reference}"
    unit = compact(
        dictionary.unit(column, row["unit"] if row["role"] == "time" else "source unit"),
        "source unit",
        16,
    )
    return f"{name} (+1 {unit})"


def figures(result, directory: Path, prefix, preset_id="journal-neutral-english-v1", edition=None):
    import matplotlib

    matplotlib.use("Agg")
    with publication_style(preset_id) as profile:
        if edition:
            profile["edition"] = edition
        return _figures(result, directory, prefix, profile)


def _figures(result, directory, prefix, profile):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    spec, model, records = result["spec"], result["model"], []
    dictionary = DisplayDictionary(profile.get("edition", {}).get("display_dictionary"))
    compact = dictionary.compact if dictionary.value else short_label
    mappings = "".join(
        dictionary.describe(column, [level["value"] for level in entry["levels"]])
        for column, entry in dictionary.entries.items()
        if column != spec["subject"]
    )
    ci = f"{spec['confidence_level']:.1%}"
    labels = sorted({p["group"] for p in result["points"]})
    codes = {label: f"G{i + 1}" for i, label in enumerate(labels)}
    group_note = (
        "Group codes: " + "; ".join(f"{code}={label!r}" for label, code in codes.items()) + ". "
    )

    def group_label(label):
        meaning = dictionary.level(spec["group"], label) if spec["group"] else label
        return compact(f"{codes[label]}: {meaning}", codes[label], 24)

    units = {
        "秒": "s",
        "分鐘": "min",
        "小時": "h",
        "天": "days",
        "日": "days",
        "週": "weeks",
        "月": "months",
        "年": "years",
    }
    time_unit = compact(
        dictionary.unit(spec["time"], units.get(spec["time_unit"], spec["time_unit"])), "U1", 16
    )
    outcome_unit = compact(dictionary.unit(spec["outcome"], spec["outcome_unit"]), "U2", 32)
    exposure_unit = (
        compact(dictionary.unit(spec["exposure"], spec["exposure_unit"]), "U3", 16)
        if spec["exposure"]
        else None
    )
    scale_note = (
        f"Time is source column {spec['time']!r}, in {spec['time_unit']!r} (axis label {time_unit!r}), "
        f"with declared origin {spec['time_origin']!r}; reference time={spec['time_reference']}. "
        f"The response is {spec['outcome']!r}, in source units {spec['outcome_unit']!r} (axis label {outcome_unit!r}). "
        "No numerical unit conversion, jitter, imputation or extrapolation is added. "
    )
    sample_note = (
        f"The study retains {result['n']} observations from {result['n_subjects']} independent subjects; "
        "repeated observations within a subject are not independent sampling units. "
    )
    model_note = (
        f"Prespecified {model['method']} with {model['distribution']} response and {model['link']} link; "
        + (
            f"{spec['correlation']} working correlation, subject-cluster robust sandwich covariance and asymptotic normal Wald inference. "
            if spec["method"] == "gee"
            else f"REML with {model['random_effects']}, model-based fixed-effect covariance and asymptotic normal Wald inference. "
        )
        + "No variable selection, small-sample correction or additional hypothesis test is performed by the renderer. "
    )

    def new(height=125, *, keep_height=False):
        return plt.subplots(
            figsize=(180 / 25.4, height * (180 / profile["width_mm"] if keep_height else 1) / 25.4)
        )

    def save(fig, kind, title, caption, explanation, data):
        required = (dictionary.note(), mappings, group_note) if dictionary.value else ()
        publication = save_publication_figure(
            fig,
            directory,
            f"{prefix}_longitudinal_{kind}",
            number=len(records) + 1,
            title=title,
            caption=sample_note + caption + " " + dictionary.note() + mappings,
            explanation=explanation,
            data=data,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
            required_caption=required,
        )
        if dictionary.value:
            publication["dictionary_sha256"] = dictionary.value["dictionary_sha256"]
        records.append(
            dict(
                path=publication["files"]["png"],
                plot_type=f"clinical_longitudinal_{kind}",
                caption=publication["caption_en"]
                + "\n\n中文解釋："
                + publication["explanation_zh"],
                fonts={"family": profile["font_family"], "font_sha256": profile["font_sha256"]},
                publication=publication,
            )
        )

    fig, ax = new(105)
    ax.axis("off")
    rows = flow(result)
    table = ax.table(
        cellText=[
            [
                textwrap.fill(row["stage"], 19),
                str(row["observations"]),
                str(row["subjects"]) if row["subjects"] is not None else "—",
            ]
            for row in rows
        ],
        colLabels=["Inclusion step", "Observations", "Subjects"],
        colWidths=[0.48, 0.28, 0.24],
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2.25)
    for (row, _), table_cell in table.get_celld().items():
        table_cell.set_edgecolor("#c4cbd0")
        if row == 0:
            table_cell.set_facecolor("#eef3f6")
    ledger = result["case_ledger"]
    save(
        fig,
        "flow",
        "Observation and subject inclusion in the longitudinal study.",
        "The cohort restriction is applied to observations first, followed by observation-wise exclusion of missing model fields. "
        "Partially observed subjects retain their complete visits; exclusion counts refer to observations, not necessarily whole subjects. "
        f"Among eligible subjects, {ledger['subjects_with_no_complete_observations']} have no complete visits and are excluded entirely. "
        f"Included subjects have {ledger['observations_per_subject']['min']}–{ledger['observations_per_subject']['max']} complete visits; "
        f"{ledger['subjects_with_one_complete_observation']} have one complete observation. Subject counts are only enumerated within the declared cohort; dashes are not zero counts. "
        "Duplicate subject/time records and conflicting baseline values are rejected before missing-outcome exclusion. Selection bias or the mechanism of missingness is not resolved by this accounting.",
        "表中分開列出觀察次數與受試者人數；缺一次追蹤不會把整個人刪除。範圍外及單次缺失的列數不能直接當成排除人數；— 表示該列未計算人數，不是0。",
        rows,
    )

    fig, ax = new(125)
    markers = ["o", "s", "^", "D", "v", "P"]
    data = []
    for index, label in enumerate(labels):
        points = [p for p in result["observed_by_time"] if p["group"] == label]
        ax.plot(
            [p["time"] for p in points],
            [p["estimate"] for p in points],
            linestyle="none",
            marker=markers[index],
            color=COLORS[index],
            markersize=5,
            label=group_label(label),
        )
        data.extend({"group_code": codes[label], **p} for p in points)
    ylabel = (
        f"Observed rate\n(count / {exposure_unit})"
        if spec["exposure"]
        else "Observed positive proportion"
        if spec["distribution"] == "binomial"
        else f"Observed mean\n({outcome_unit})"
    )
    time_label = (
        textwrap.fill(
            compact(dictionary.label(spec["time"]), compact(spec["time"], "Time", 24), 40), 24
        )
        + f"\n({time_unit})"
        if dictionary.value
        else f"Time ({time_unit})"
    )
    ax.set(xlabel=time_label, ylabel=ylabel)
    if spec["distribution"] == "binomial":
        ax.set_ylim(-0.03, 1.03)
    observed_times = sorted({p["time"] for p in result["observed_by_time"]})
    if spec["time_mode"] == "categorical":
        ax.set_xticks(spec["time_levels"])
    elif len(observed_times) <= 12:
        ax.set_xticks(observed_times)
    else:
        ax.xaxis.set_major_locator(MaxNLocator(6))
    ax.legend(
        loc="lower left", bbox_to_anchor=(0, 1.01), ncol=2 if profile["width_mm"] < 100 else 3
    )
    ax.grid(alpha=0.15)
    if spec["exposure"]:
        estimand = f"Each point is the sum of observed counts divided by the sum of exposure in {spec['exposure_unit']!r} (axis label {exposure_unit!r}), within that group and exact source time. "
    elif spec["distribution"] == "binomial":
        estimand = f"Each point is the fraction with source outcome {spec['positive']!r} (encoded 1), among complete observations in that group and exact source time; {spec['negative']!r} is encoded 0. "
    else:
        estimand = "Each point is the arithmetic mean of the original responses within that group and exact source time. "
    save(
        fig,
        "observed",
        "Observed responses at the recorded follow-up times.",
        scale_note
        + group_note
        + estimand
        + "These are unadjusted descriptive summaries, not model-based trajectories, standardized population means or causal effects. "
        "All observed times and groups are retained without smoothing, artificial time offsets or a fabricated time origin. "
        "There are no confidence intervals or between-group tests in this figure. The plot data retain the number of observations and subjects, response totals and any exposure totals; denominators can differ by time. Overlapping symbols can conceal identical summaries.",
        "每點使用該組、該實際時點的全部保留觀察；二元值為陽性比例，連續／次數為平均，有時長offset時則為總次數除以總時長。這是未調整的觀察摘要，沒有區間，不能當成模型效果或療效。",
        data,
    )

    coefficients = result["coefficients"][1:]
    ratio = spec["distribution"] in {"binomial", "poisson"}
    for start in range(0, len(coefficients), 8):
        block = coefficients[start : start + 8]
        descriptions = [term_description(row, result) for row in block]
        displays = [term_label(row, result, codes, dictionary) for row in block]
        wrapped = [textwrap.fill(label, 23) for label in displays]
        fig, ax = new(
            max(65, 28 + sum((label.count("\n") + 1) * 4 + 3 for label in wrapped)),
            keep_height=True,
        )
        for i, row in enumerate(block):
            ax.plot([row["lower"], row["upper"]], [i, i], color=COLORS[0])
            ax.plot(row["estimate"], i, "o", color=COLORS[0])
        ax.set_yticks(range(len(block)), wrapped)
        ax.invert_yaxis()
        ax.axvline(1 if ratio else 0, linestyle="--", color="#656565")
        if ratio:
            ax.set_xscale("log")
            lower = min(1, min(row["lower"] for row in block)) * 0.85
            upper = max(1, max(row["upper"] for row in block)) * 1.15
            span = np.log(upper / lower)
            ticks = sorted(
                [1.0, *[t for t in np.geomspace(lower, upper, 4) if abs(np.log(t)) > 0.14 * span]]
            )
            ax.set_xticks(ticks, [f"{t:.3g}" for t in ticks])
            ax.minorticks_off()
            ax.set_xlim(lower, upper)
        else:
            ax.xaxis.set_major_locator(MaxNLocator(5))
        ax.set_xlabel(
            f"{'exp(beta)' if ratio else 'Mean-model effect'} ({ci} CI)"
            + ("\nlog scale" if ratio else "")
        )
        meanings = (
            "; ".join(
                f"{label!r}: {desc!r}; scale={row['effect_scale']}"
                for label, desc, row in zip(displays, descriptions, block, strict=True)
            )
            + ". "
        )
        save(
            fig,
            f"effects_{start // 8 + 1}",
            "Prespecified longitudinal mean-model coefficients and uncertainty.",
            model_note
            + scale_note
            + meanings
            + f"Points and horizontal lines show {'exponentiated coefficients' if ratio else 'coefficients'} and individual {ci} Wald intervals. "
            + (
                "For ratios the axis is logarithmic and the reference is 1; exp(interaction) is a ratio of ratios. "
                if ratio
                else "The reference is 0; interaction terms are differences in time effects. "
            )
            + "Group main effects with time interaction apply at the reference time, and time main effects apply to the reference group. "
            "The intercept is excluded from the forest but retained in the coefficient table. All other terms are shown in blocks of at most eight, without selection by significance. "
            f"Holm p-values in the downloadable data cover all {len(coefficients)} non-intercept coefficients in this model; intervals are not multiplicity-adjusted. "
            "No omnibus interaction test or between-model equivalence test is inferred from these intervals.",
            "保留全部非截距固定效果及逐項區間；原始欄位、參考組與效果尺度在圖說逐一對應。交互作用需解讀為時間效果之差或比值之比，不能當成單獨組別效果；Holm p 值並不表示區間也已校正。",
            [
                {"display_label": label, "description": desc, **row}
                for label, desc, row in zip(displays, descriptions, block, strict=True)
            ],
        )

    fig, ax = new(125)
    for i, label in enumerate(labels):
        points = [p for p in result["points"] if p["group"] == label]
        ax.scatter(
            [p["fitted"] for p in points],
            [p["residual"] for p in points],
            s=12,
            marker=markers[i],
            color=COLORS[i],
            alpha=0.45,
            label=group_label(label),
        )
    ax.axhline(0, color="#656565", linestyle="--")
    ax.set(xlabel="Fitted response", ylabel="Observed minus fitted response")
    ax.legend(
        loc="lower left", bbox_to_anchor=(0, 1.01), ncol=2 if profile["width_mm"] < 100 else 3
    )
    ax.xaxis.set_major_locator(MaxNLocator(5))
    save(
        fig,
        "residuals",
        "Response residuals against fitted responses.",
        model_note
        + group_note
        + scale_note
        + f"Each point is a retained observation; fitted values are the saved {model['fitted_mean']}. "
        "The vertical value is observed minus fitted response, on the original outcome scale. "
        + (
            "For Poisson offsets, fitted values are expected counts at each observation's exposure, not rates. "
            if spec["exposure"]
            else ""
        )
        + "The dashed line is zero. All observations, including overlapping points, are retained without jitter, smoothing or new tests. "
        "Repeated residuals are correlated within subjects. Structure can motivate review of mean/variance specification, but an apparently patternless plot does not establish model validity or missingness assumptions.",
        "每點為一筆保留觀察；殘差＝原始結果−配適值。GEE 使用平均模型，混合模型另包含該人的隨機效果；有offset時配適值仍是該次觀察的預期次數。圖形不構成模型或缺失機制的證明。",
        [{"group_code": codes[p["group"]], **p} for p in result["points"]],
    )
    if spec["distribution"] == "gaussian":
        ordered = sorted(result["points"], key=lambda p: (p["residual"], p["data_row"]))
        probabilities = (np.arange(len(ordered)) + 0.5) / len(ordered)
        theoretical = norm.ppf(probabilities)
        residuals = np.array([p["residual"] for p in ordered])
        normal_quartiles = norm.ppf([0.25, 0.75])
        quartiles = np.quantile(residuals, [0.25, 0.75])
        slope = (quartiles[1] - quartiles[0]) / (normal_quartiles[1] - normal_quartiles[0])
        endpoints = np.array([theoretical[0], theoretical[-1]])
        reference = quartiles[0] + slope * (endpoints - normal_quartiles[0])
        fig, ax = new(125)
        ax.scatter(theoretical, residuals, s=12, color=COLORS[0], alpha=0.45)
        ax.plot(endpoints, reference, "--", color="#656565")
        ax.set(xlabel="Standard normal quantile", ylabel=f"Response residual ({outcome_unit})")
        ax.xaxis.set_major_locator(MaxNLocator(5))
        data = [
            dict(
                plot_role="stored_residual",
                data_row=p["data_row"],
                subject_code=p["subject_code"],
                probability=float(probabilities[i]),
                theoretical_quantile=float(theoretical[i]),
                residual=p["residual"],
            )
            for i, p in enumerate(ordered)
        ]
        data += [
            dict(plot_role="quartile_reference", theoretical_quantile=float(x), residual=float(y))
            for x, y in zip(endpoints, reference, strict=True)
        ]
        save(
            fig,
            "qq",
            "Normal quantile comparison of the saved Gaussian response residuals.",
            model_note
            + scale_note
            + "Sorted saved response residuals are compared with standard normal quantiles at (rank−0.5)/n. "
            "The dashed reference passes through the empirical residual quartiles and normal 0.25/0.75 quantiles; it is plotting geometry, not a fitted regression or hypothesis test. "
            "Empirical quartiles use linear interpolation. No residual values are discarded or winsorized. "
            "Within-subject residuals remain correlated; Gaussian GEE with robust uncertainty does not itself require normally distributed outcomes. "
            "For Gaussian mixed models this is a conditional response-residual diagnostic, not a test of the latent random-effect distribution. A straight pattern is not proof of normality or independence.",
            "保存殘差依大小排序，與常態分位數比較；虛線只通過四分位數，沒有再擬合或做常態檢定。組內殘差仍相關；不能從這張圖認定獨立、常態或隨機效果分布成立。",
            data,
        )
    return records
