"""Publication figures over saved survival estimates, without refitting or resampling."""

from pathlib import Path
import textwrap

import numpy as np

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure
from rde.infrastructure.visualization.dictionary import DisplayDictionary, submission_text

COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#555555"]
STYLES = ["-", "--", "-.", ":", (0, (3, 1, 1, 1, 1, 1)), (0, (5, 2))]


def short_label(value, code, limit=28):
    """Keep exact short ASCII labels; map other source text explicitly in the caption."""
    value = str(value)
    return value if value.isascii() and value.isprintable() and len(value) <= limit else code


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

    spec, strata, records = result["spec"], result["strata"], []
    dictionary = DisplayDictionary(profile.get("edition", {}).get("display_dictionary"))
    annotation_note = dictionary.note()

    def legend_label(column, raw, code):
        label = dictionary.level(column, raw)
        return f"{code}: {label}" if label != raw and len(label) <= 38 else code

    ci = f"{spec['confidence_level']:.1%}"
    competing = bool(spec["competing_values"])
    groups = {g["label"]: f"G{i + 1}" for i, g in enumerate(strata)}
    mapping = "; ".join(
        f"{groups[g['label']]}={g['label']!r}"
        + (
            f" ({dictionary.level(spec['group'], g['label'])})"
            if dictionary.level(spec["group"], g["label"]) != g["label"]
            else ""
        )
        for g in strata
    )
    unit = {
        "秒": "s",
        "分鐘": "min",
        "小時": "h",
        "天": "days",
        "日": "days",
        "週": "weeks",
        "月": "months",
        "年": "years",
    }.get(spec["time_unit"], short_label(spec["time_unit"], "U1", 18))
    unit = (
        short_label(dictionary.unit(spec["time"]), "U1", 18)
        if dictionary.unit(spec["time"])
        else unit
    )
    followup = f"Follow-up ({unit})"
    population = (
        f"All estimates use the same {result['n']} complete participants, with one independent "
        "record per participant and no delayed entry. "
    )
    time_note = (
        f"Time uses source column {spec['time']!r}, measured in {spec['time_unit']!r}"
        + (f" (displayed as {unit!r})" if unit != spec["time_unit"] else "")
        + f", from the declared origin {spec['time_origin']!r}; no unit conversion was applied. "
    )
    group_note = f"Group codes preserve the original values: {mapping}. "
    event_note = (
        f"The target event is {spec['event_value']!r} in {spec['event']!r}; "
        f"right censoring is {spec['censor_value']!r}. "
    )
    if dictionary.value:
        for value in (spec["event_value"], spec["censor_value"]):
            label = dictionary.level(spec["event"], value)
            if label != value:
                event_note += f"Code {value!r} denotes {label!r}. "
    exploratory = (
        "This is an exploratory adjustment-sensitivity branch on the primary complete-case "
        "population; omitted predictors do not restore excluded participants. Intervals are "
        "not adjusted across exploratory models. "
        if result.get("primary_binding") or result.get("population_spec")
        else ""
    )

    def new(height=125):
        return plt.subplots(figsize=(180 / 25.4, height / 25.4))

    def save(fig, kind, title, caption, explanation, data, suffix=None):
        publication = save_publication_figure(
            fig,
            directory,
            f"{prefix}_{suffix or kind}",
            number=len(records) + 1,
            title=title,
            caption=(population + exploratory + caption).rstrip()
            + (" " + annotation_note if annotation_note else ""),
            explanation=explanation,
            data=data,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
            required_caption=(exploratory, annotation_note),
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
        {"stage": "Outside cohort", "n": len(ledger["filter_excluded_data_rows"])},
        {"stage": "Missing required values", "n": len(ledger["missing_excluded_data_rows"])},
        {"stage": "Complete participants", "n": result["n"]},
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
            bbox=dict(boxstyle="round,pad=0.6", facecolor="white", edgecolor=COLORS[0]),
        )
    ax.annotate(
        "", xy=(0.5, 0.26), xytext=(0.5, 0.72), arrowprops=dict(arrowstyle="->", color="#656565")
    )
    ax.text(
        0.56,
        0.52,
        f"Excluded\nOutside cohort: {flow[1]['n']}\nMissing required values: {flow[2]['n']}",
        va="center",
        fontsize=9,
    )
    save(
        fig,
        "participant_flow",
        "Participant inclusion in the survival study.",
        "Exclusions are mutually exclusive: the prespecified cohort restriction is applied first, "
        "then records missing required analysis fields are excluded. Curves, risk counts and "
        "models share this population. Complete-case restriction may introduce selection bias.",
        "先按事先指定族群排除，再排除必要欄位缺失；曲線、在險人數與模型共用同一組完整個案。完整個案不代表沒有選樣偏差。",
        flow,
    )

    if not competing:
        fig, ax = new(130)
        data = []
        for index, group in enumerate(strata):
            code, color = groups[group["label"]], COLORS[index % len(COLORS)]
            curve = group["estimate"]["curve"]
            times, estimates, lower, upper = [
                [r[k] for r in curve] for k in ["time", "estimate", "lower", "upper"]
            ]
            ax.step(
                times,
                estimates,
                where="post",
                color=color,
                linestyle=STYLES[index % len(STYLES)],
                label=textwrap.fill(
                    f"{legend_label(spec['group'], group['label'], code)} (n={group['n']})", 28
                ),
            )
            ax.fill_between(times, lower, upper, step="post", color=color, alpha=0.12)
            censored = [r for r in curve if r["censored"]]
            ax.plot(
                [r["time"] for r in censored],
                [r["estimate"] for r in censored],
                "+",
                color=color,
                markersize=5,
            )
            data.extend({"group": code, "source_group": group["label"], **row} for row in curve)
        ax.set(
            xlabel=followup,
            ylabel="Probability without target event",
            ylim=(0, 1.03),
            xlim=(0, max(1, max(g["followup_max"] for g in strata))),
        )
        ax.xaxis.set_major_locator(MaxNLocator(5))
        ax.legend(
            loc="lower left",
            bbox_to_anchor=(0, 1.01),
            ncol=(1 if profile["width_mm"] < 100 else 2)
            if dictionary.value
            else (2 if profile["width_mm"] < 100 else 3),
        )
        ax.grid(alpha=0.15)
        logrank = result["logrank"]
        comparison = (
            f"The prespecified overall unadjusted log-rank comparison gave chi-squared "
            f"{logrank['statistic']:.4g} on {logrank['df']} degrees of freedom (p={logrank['p_value']:.4g}); "
            "it is not a pairwise comparison or a treatment-effect estimate. "
            if logrank and "statistic" in logrank
            else "The overall log-rank comparison was not estimable. "
            if logrank
            else "No between-group log-rank comparison was specified. "
        )
        save(
            fig,
            "survival",
            "Kaplan–Meier estimates of remaining free of the target event.",
            time_note
            + event_note
            + group_note
            + f"Steps show Kaplan–Meier estimates; shaded regions are {ci} Greenwood log–log pointwise intervals, not simultaneous bands. "
            "A plus marks a time with one or more right-censored participants, at the post-event estimate when events and censoring coincide; multiplicity is retained in the plot data. "
            "Each curve stops at that group's last observation. Independent censoring is assumed. "
            + comparison
            + "A median not reached during follow-up is not extrapolated. No observed events or a boundary interval does not establish absence of risk; consult the accompanying risk counts.",
            "階梯與陰影為 KM 估計及逐點區間；+ 表示該時點有設限，重複人數保存在 CSV。同時事件先反映於曲線，設限標記位於該時點更新後的曲線。大 p 值不證明兩組相同。",
            data,
        )
    else:
        causes = [spec["event_value"], *spec["competing_values"]]
        cause_mapping = "; ".join(
            f"E{i + 1}={cause!r}"
            + (" (target)" if i == 0 else " (competing)")
            + (
                f" ({dictionary.level(spec['event'], cause)})"
                if dictionary.level(spec["event"], cause) != cause
                else ""
            )
            for i, cause in enumerate(causes)
        )
        for group in strata:
            code = groups[group["label"]]
            fig, ax = new(130)
            data = []
            no_events = group["estimate"].get("no_observed_events", False)
            for index, cause in enumerate(causes):
                curve = group["estimate"]["curves"][cause]
                if not curve:
                    data.append(
                        {
                            "group": code,
                            "source_group": group["label"],
                            "event": f"E{index + 1}",
                            "source_event": cause,
                            "plot_role": "not_estimated_no_events",
                        }
                    )
                    continue
                times, estimates, lower, upper = [
                    [r[k] for r in curve] for k in ["time", "estimate", "lower", "upper"]
                ]
                # An explicit pre-event origin is plotting geometry, not a new fitted observation.
                if times[0] > 0:
                    times, estimates, lower, upper = (
                        [0, *times],
                        [0, *estimates],
                        [0, *lower],
                        [0, *upper],
                    )
                    data.append(
                        {
                            "group": code,
                            "source_group": group["label"],
                            "event": f"E{index + 1}",
                            "source_event": cause,
                            "plot_role": "pre_event_origin",
                            "time": 0,
                            "estimate": 0,
                            "lower": 0,
                            "upper": 0,
                        }
                    )
                data.extend(
                    {
                        "group": code,
                        "source_group": group["label"],
                        "event": f"E{index + 1}",
                        "source_event": cause,
                        "plot_role": "stored_estimate",
                        **r,
                    }
                    for r in curve
                )
                color = COLORS[index % len(COLORS)]
                ax.step(
                    times,
                    estimates,
                    where="post",
                    color=color,
                    linestyle=STYLES[index % len(STYLES)],
                    label=textwrap.fill(
                        f"{legend_label(spec['event'], cause, f'E{index + 1}')} ({'target' if index == 0 else 'competing'})",
                        28,
                    ),
                )
                ax.fill_between(times, lower, upper, step="post", color=color, alpha=0.12)
            ax.set(
                xlabel=followup,
                ylabel="Cumulative incidence",
                ylim=(0, 1.03),
                xlim=(0, max(1, group["followup_max"])),
            )
            ax.xaxis.set_major_locator(MaxNLocator(5))
            if no_events:
                ax.text(
                    0.5,
                    0.5,
                    "No observed events\nUncertainty not estimated",
                    transform=ax.transAxes,
                    ha="center",
                    va="center",
                )
            else:
                ax.legend(
                    loc="lower left",
                    bbox_to_anchor=(0, 1.01),
                    ncol=(1 if profile["width_mm"] < 100 else 2)
                    if dictionary.value
                    else (2 if profile["width_mm"] < 100 else 3),
                )
            ax.grid(alpha=0.15)
            save(
                fig,
                "incidence_" + code,
                f"Cumulative incidence with competing events in {code}.",
                time_note
                + event_note
                + group_note
                + f"This panel shows {code}: n={group['n']}, target events={group['events']}, competing events={group['competing']}, right censored={group['censored']}. "
                + f"Event codes: {cause_mapping}. Steps are Aalen–Johansen estimates with {ci} pointwise normal-approximation intervals bounded to [0, 1]. "
                "Original tied times are retained without jitter. Shading is not a simultaneous band. Competing events are not treated as ordinary censoring when estimating cumulative incidence. "
                "A zero event count or degenerate interval does not establish zero population risk. With no observed events, the absence of an estimated interval is stated explicitly. "
                "Group follow-up lengths can differ; final curve endpoints are not fixed-time group comparisons. No Gray test, Fine–Gray model or causal treatment comparison is added.",
                "各組分圖保留所有事件類別及相同0–1機率尺度；目標事件與競爭事件有明確代碼。逐點近似區間可能在少量事件或邊界失準，不能把競爭事件當普通失訪。",
                data,
                suffix=f"incidence_{code}",
            )

    times = [r["time"] for r in strata[0]["risk_table"]]
    # Fixed six-column blocks keep all prespecified time points at legible type sizes,
    # including the narrowest journal preset; no counts are omitted to fit a canvas.
    for start in range(0, len(times), 6):
        block = times[start : start + 6]
        labels = [f"{t:.6g}" for t in block]
        if len(set(labels)) != len(labels) or any(len(t) > 9 for t in labels):
            labels = [f"T{i + 1}" for i in range(start, start + len(block))]
        fig, ax = new(62 + 7 * len(strata))
        ax.axis("off")
        contents = [
            [groups[g["label"]], *[str(r["at_risk"]) for r in g["risk_table"][start : start + 6]]]
            for g in strata
        ]
        table = ax.table(
            cellText=contents, colLabels=["Group", *labels], cellLoc="center", loc="center"
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1, 1.5)
        for (row, _), cell in table.get_celld().items():
            cell.set_edgecolor("#c4cbd0")
            if row == 0:
                cell.set_facecolor("#eef3f6")
        ax.set_title(f"Number at risk before each time ({unit})", pad=14)
        data = [
            {"group": groups[g["label"]], "source_group": g["label"], **r}
            for g in strata
            for r in g["risk_table"][start : start + 6]
        ]
        time_mapping = "; ".join(f"{label}={t!r}" for label, t in zip(labels, block, strict=True))
        save(
            fig,
            f"risk_table_{start // 6 + 1}",
            "Participants at risk at the specified follow-up times.",
            time_note
            + group_note
            + f"Displayed times (labels to exact source values): {time_mapping}. "
            "Counts are immediately before events or censoring at the specified time: a participant whose observed follow-up equals that time is included. "
            "Earlier target events, competing events and right censoring remove participants from the risk set. "
            "The downloadable table also retains each of these prior removal counts. Times beyond a group's last observation have zero at risk; this is not evidence of zero event risk.",
            "人數計算於各時點事件／設限之前，恰於該時點結束追蹤者仍列入。每張表至多六個時點，所有指定時點均保留；CSV另存先前各原因的退出人數。",
            data,
            suffix=f"risk_table_{start // 6 + 1}",
        )

    cox = result["cox"]
    if not cox:
        return records
    coefficients = cox["coefficients"]
    labels, term_notes = [], []
    for index, row in enumerate(coefficients):
        description = (
            f"{row['variable']}: {row['level']} vs {row['reference']}"
            if "level" in row
            else f"{row['variable']} (+1 source unit)"
        )
        if dictionary.value:
            display = dictionary.label(row["variable"])
            if "level" in row:
                display += f": {dictionary.level(row['variable'], row['level'])} vs {dictionary.level(row['variable'], row['reference'])}"
            else:
                display += f" ({dictionary.unit(row['variable']) or '+1 source unit'})"
            label = display if submission_text(display) and len(display) <= 84 else f"V{index + 1}"
            description += f"; reviewed label {display!r}"
        else:
            label = short_label(description, f"V{index + 1}", 36)
        labels.append(label)
        term_notes.append(f"{label!r} denotes {description!r}")
    model_note = (
        f"The {'cause-specific ' if competing else ''}Cox model uses Efron handling of tied events, "
        f"with {cox['n']} participants and {cox['events']} target events. "
        "All displayed parameters were specified before fitting; no variable selection was added. "
        + (
            "Competing events leave the risk set at their occurrence; this is not a Fine–Gray subdistribution hazard ratio. "
            if competing
            else ""
        )
    )
    for start in range(0, len(coefficients), 8):
        block = coefficients[start : start + 8]
        terms = "; ".join(term_notes[start : start + 8]) + ". "
        if any(not 0 < r["lower"] <= r["hazard_ratio"] <= r["upper"] < float("inf") for r in block):
            raise ValueError(
                "Cox log-scale publication requires finite positive HR bounds; review model instability."
            )
        fig, ax = new(max(100, 15 * len(block)))
        for i, row in enumerate(block):
            ax.plot([row["lower"], row["upper"]], [i, i], color=COLORS[0])
            ax.plot(row["hazard_ratio"], i, "o", color=COLORS[0])
        ax.set_yticks(range(len(block)), [textwrap.fill(t, 23) for t in labels[start : start + 8]])
        ax.invert_yaxis()
        ax.set_xscale("log")
        ax.axvline(1, linestyle="--", color="#656565")
        lower = min(1, min(r["lower"] for r in block)) * 0.85
        upper = max(1, max(r["upper"] for r in block)) * 1.15
        span = np.log(upper / lower)
        ticks = sorted(
            [1.0, *[t for t in np.geomspace(lower, upper, 4) if abs(np.log(t)) > 0.14 * span]]
        )
        ax.set_xticks(ticks, [f"{t:.3g}" for t in ticks])
        ax.minorticks_off()
        ax.set(
            xlim=(lower, upper),
            xlabel=f"Adjusted {'cause-specific ' if competing else ''}HR ({ci} CI; log scale)",
        )
        data = [
            {"display_label": label, **row}
            for label, row in zip(labels[start : start + 8], block, strict=True)
        ]
        save(
            fig,
            f"cox_{start // 8 + 1}",
            "Adjusted hazard ratios for the target event.",
            model_note
            + terms
            + f"Points are exp(beta); horizontal lines are {ci} Wald intervals, exp(beta ± z × SE), without multiplicity adjustment. "
            "The horizontal axis is logarithmic and the dashed reference is HR=1. Continuous predictors compare a one-unit increase on the stored scale; categorical predictors compare the stated level with its reference. "
            "HR compares instantaneous target-event rates among those still at risk, not cumulative risks or causal effects. "
            + f"There are {cox['events_per_parameter']:.3g} target events per encoded parameter; this is a descriptive diagnostic, not proof of sample-size adequacy. "
            "All parameters and intervals are retained, regardless of significance.",
            "點與橫線為 HR 及其逐一區間，虛線為1；連續欄位按原始單位增加1，不擅自換成年或標準差。類別比較保留參考組，HR不等於累積風險比或因果療效。",
            data,
            suffix=f"cox_{start // 8 + 1}",
        )
    for index, row in enumerate(coefficients):
        data = [
            {
                "data_row": r["data_row"],
                "time": r["time"],
                "term": row["term"],
                "scaled_schoenfeld": r[row["term"]],
            }
            for r in cox["scaled_schoenfeld"]
        ]
        fig, ax = new(110)
        ax.scatter(
            [r["time"] for r in data],
            [r["scaled_schoenfeld"] for r in data],
            s=12,
            color=COLORS[0],
            alpha=0.45,
        )
        ax.axhline(0, linestyle="--", color="#656565")
        ax.set(xlabel=followup, ylabel="Scaled Schoenfeld residual")
        ax.xaxis.set_major_locator(MaxNLocator(5))
        checks = [c for c in cox["ph_checks"] if c["term"] == row["term"]]
        tests = "; ".join(
            f"{c['transform']} transform: statistic={c['statistic']:.4g}, raw p={c['p_value']:.4g}, Holm p={c['p_adjusted']:.4g}"
            for c in checks
        )
        save(
            fig,
            "ph_" + row["term"],
            f"Proportional-hazards diagnostic for parameter V{index + 1}.",
            time_note + model_note + f"Parameter V{index + 1}: {term_notes[index]}. "
            "Each point is one target event's scaled Schoenfeld residual, placed at its original follow-up time; tied events are retained. The dashed line is zero. "
            "No smoothing line, regression or additional test is fitted by this renderer. "
            + f"Saved proportional-hazards checks: {tests}. Holm adjustment covers both rank and KM transforms across all encoded terms within this model. "
            "Small adjusted p values can motivate review of time dependence; large values or an apparently flat scatter do not prove proportional hazards. These diagnostic p values do not test a treatment effect.",
            "每點是一個目標事件的縮放 Schoenfeld 殘差；保留同時事件，橫軸為原始時間。圖說列出已保存的 rank／KM 檢查及模型內 Holm 校正，不另擬合趨勢或依顯著性挑圖。",
            data,
            suffix=f"ph_{row['term']}",
        )
    return records
