"""English weighting figures drawn only from the saved numerical receipt."""

from pathlib import Path
import textwrap

import numpy as np

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure
from .regression_report import flow
from .survival_publication import COLORS, short_label
from .weighting_report import balance_blocks, balance_description


def figures(result, directory: Path, prefix, preset_id="journal-neutral-english-v1", edition=None):
    import matplotlib

    matplotlib.use("Agg")
    with publication_style(preset_id) as profile:
        if edition:
            profile["edition"] = edition
        return _figures(result, directory, prefix, profile)


def _figures(result, directory, prefix, profile):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator, NullLocator

    spec, diagnostics, records = result["spec"], result["diagnostics"], []

    def sentence(text):
        text = text.strip()
        return text if text.endswith((".", "!", "?", "。", "！", "？")) else text + "."

    source = (
        f"Prespecified {spec['estimand']} weighting in an observational cohort; one common complete-case sample of {result['n']} cases under an independent-case working model. "
        f"G0 (A=0)={spec['treatment_levels'][0]!r}; G1 (A=1)={spec['treatment_levels'][1]!r}. "
        f"Exposure: {sentence(spec['treatment_definition'])} Time zero: {sentence(spec['time_origin'])} "
        f"Outcome {spec['outcome']!r}, source unit/definition {spec['outcome_unit']!r}. "
        f"Ascertainment: {sentence(spec['outcome_definition'])} Outcome window: {sentence(spec['outcome_window'])} "
        f"Study context: {sentence(spec['context'])} "
    )
    method = (
        "Unpenalized logistic propensity e=P(A=1|X), with all prespecified covariate bases and interactions retained. "
        f"Raw group weights: w1={result['model']['weight_formula'][0]}, w0={result['model']['weight_formula'][1]}. "
        "No imputation, automatic variable selection, clipping or trimming. ATE, ATT and ATO concern different target populations. "
    )
    covariates = (
        "Covariate definitions: "
        + "; ".join(
            f"C{i + 1}={p['label']!r}, source={p['column']!r}, reference={p['reference']!r}, pre-exposure basis={p['pre_exposure_basis']!r}"
            + (
                f", units={p['unit']!r}, design increment={p['increment']}, spline knots={p['knots']}"
                if p["kind"] == "continuous"
                else f", levels={p['levels']}"
            )
            for i, p in enumerate(spec["covariates"])
        )
        + f". Prespecified interactions: {spec['interactions']}. "
    )

    def new(height=100, *, rows=1):
        # Hold physical height when a journal preset narrows the canvas.
        return plt.subplots(
            rows, 1, figsize=(180 / 25.4, height * 180 / profile["width_mm"] / 25.4), squeeze=False
        )

    def save(fig, kind, title, caption, explanation, data):
        pub = save_publication_figure(
            fig,
            directory,
            f"{prefix}_weighting_{kind}",
            number=len(records) + 1,
            title=title,
            caption=source + caption,
            explanation=explanation,
            data=data,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
        )
        records.append(
            dict(
                path=pub["files"]["png"],
                plot_type=f"clinical_weighting_{kind}",
                caption=pub["caption_en"] + "\n\n中文解釋：" + pub["explanation_zh"],
                fonts={"family": profile["font_family"], "font_sha256": profile["font_sha256"]},
                publication=pub,
            )
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
        "Common case inclusion for propensity weighting.",
        "The cohort restriction precedes common complete-case exclusion for treatment, outcome and every propensity covariate. Supplied identity and invalid source coding are checked before missing-field exclusion. Every source row retains its status and one-based locator excluding the header. Complete-case inclusion does not establish ignorable missingness or complete endpoint ascertainment.",
        "所有圖表使用同一完整個案集合；身份及非法代碼先於缺失排除檢查。保留原始列號與全部納排紀錄，不把完整個案當成缺失可忽略的證明。",
        rows,
    )

    for key, block, basis in balance_blocks(result):
        labels = []
        data = []

        def basis_label(row):
            if row["role"] == "interaction":
                lookup = {item["term"]: item for item in result["propensity_terms"]}
                return " × ".join(basis_label(lookup[name]) for name in row["components"])
            identity = f"C{row['predictor'] + 1}"
            if row["role"] == "categorical":
                return f"{identity}: {short_label(row['level'], 'level', 10)}"
            return (
                f"{identity}: basis {row['basis'] + 1}"
                if row["role"] == "spline_basis"
                else f"{identity}: linear"
            )

        for row in block:
            # Stable row labels avoid silently eliding long interaction names.
            all_rows = diagnostics["basis_balance" if basis else "covariate_balance"]
            identity = f"{'B' if basis else 'V'}{all_rows.index(row) + 1:02d}"
            description = balance_description(row, result, basis=basis)
            if basis:
                visible = basis_label(row)
            else:
                p = spec["covariates"][row["covariate"]]
                visible = short_label(p["label"], f"C{row['covariate'] + 1}", 22)
                if row["level"] is not None:
                    visible += ": " + short_label(row["level"], "level", 12)
            labels.append(textwrap.fill(f"{identity} {visible}", 24))
            data.append({"figure_label": identity, "description": description, **row})
        line_count = max(label.count("\n") + 1 for label in labels)
        fig, axes = new(max(65, 28 + len(block) * (line_count * 4 + 2)))
        ax = axes[0, 0]
        for i, row in enumerate(block):
            for k, marker, color, label in [
                ("smd", "o", COLORS[1], "Before"),
                ("weighted_smd", "s", COLORS[0], "After"),
            ]:
                if row[k] is not None:
                    ax.plot(
                        abs(row[k]),
                        i,
                        marker,
                        color=color,
                        markersize=4,
                        label=label if i == 0 else None,
                    )
            if row["smd"] is None:
                ax.text(0, i, "  Undefined SD", va="center", fontsize=8)
        ax.set_yticks(range(len(block)), labels)
        ax.invert_yaxis()
        largest = max(
            [abs(row[k]) for row in block for k in ["smd", "weighted_smd"] if row[k] is not None],
            default=0,
        )
        right = max(0.05, largest * 1.15)
        ax.set_xlim(-0.035 * right, right)
        ax.xaxis.set_major_locator(MaxNLocator(4))
        ax.set_xlabel("Absolute standardized\nmean difference")
        ax.set_ylabel("Model basis (see caption)" if basis else "Covariate (see caption)")
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=2, frameon=False)
        mapping = (
            "Labels: "
            + "; ".join(f"{row['figure_label']}={row['description']}" for row in data)
            + ". "
        )
        save(
            fig,
            key,
            "Model basis balance before and after weighting."
            if basis
            else "Covariate balance before and after weighting.",
            method
            + covariates
            + mapping
            + "Symbols show absolute SMD; the CSV and report retain signed differences, both group means and the fixed standardization denominator. Before and after use the same unweighted treated SD for ATT or the square root of the mean of unweighted group variances for ATE/ATO. Continuous columns use sample variances (ddof=1); indicator columns use p(1-p). Zero denominators are undefined, not zero differences. No hypothesis tests or pass/fail threshold are applied. Fitted overlap-weighted basis balance does not establish balance of unmeasured covariates or causal identification.",
            "每個代碼在英文圖說與資料表有完整因素對照；圖顯示絕對 SMD，表保留方向。前後分母固定，全部原始類別指標及模型基底各自保留。平衡不等於未測量混雜已消除，沒有按 p 值選模型。",
            data,
        )

    fig, axes = new(115, rows=2)
    all_bins = diagnostics["propensity_histogram"]
    largest = max(row[k] for row in all_bins for k in ["proportion", "weighted_proportion"])
    for ax, key, title in zip(
        axes[:, 0],
        ["proportion", "weighted_proportion"],
        ["Before weighting", "After weighting"],
        strict=True,
    ):
        for code in [0, 1]:
            bins = [row for row in all_bins if row["treatment_code"] == code]
            ax.stairs(
                [row[key] for row in bins],
                [row["left"] for row in bins] + [bins[-1]["right"]],
                color=COLORS[code],
                label=f"G{code}",
                linewidth=1.2,
                linestyle="solid" if code == 0 else "dashed",
            )
        ax.set_xlim(0, 1)
        ax.set_ylim(0, max(0.05, largest * 1.15))
        ax.yaxis.set_major_locator(MaxNLocator(4))
        ax.set_ylabel("Within-group fraction")
        ax.set_title(title, loc="left")
        ax.legend(
            frameon=False, ncol=2, loc="lower right", bbox_to_anchor=(1, 1.01), borderaxespad=0
        )
    axes[1, 0].set_xlabel("Propensity score e(X)")
    save(
        fig,
        "overlap",
        "Propensity distributions on a common scale.",
        method
        + "Histograms use the saved 20 equal bins across [0,1]; bins are left-closed and right-open except the final bin. Solid G0 and dashed G1 lines keep both groups visible when they coincide. Each group is normalized separately before and after weighting, so its fractions sum to one. Both panels use identical axes. No new score estimation, smoothing, trimming or changes to eligibility are performed for this plot. Marginal score overlap does not establish positivity for every covariate combination.",
        "上下圖共用相同軸與區間；每組內比例加總為 1。這是分數分布的描述，不能只因分布重疊就宣稱所有病人特徵都有足夠比較對象。",
        all_bins,
    )

    fig, axes = new(80)
    ax = axes[0, 0]
    weight_data = []
    for i, group in enumerate(diagnostics["groups"]):
        q = group["weight_quantiles"]
        ax.plot([q["min"], q["max"]], [i, i], color=COLORS[i], alpha=0.35, linewidth=1)
        ax.plot([q["p01"], q["p99"]], [i, i], color=COLORS[i], linewidth=1, linestyle="dashed")
        ax.fill_betweenx([i - 0.09, i + 0.09], q["p25"], q["p75"], color=COLORS[i], alpha=0.25)
        ax.plot(q["median"], i, "o", color="white", markeredgecolor=COLORS[i], markersize=5)
        weight_data.append({k: v for k, v in group.items() if k != "weight_quantiles"} | q)
    ax.set_yticks(
        [0, 1],
        [
            f"G{g['treatment_code']}\nn={g['n']}; ESS={g['kish_ess']:.1f}"
            for g in diagnostics["groups"]
        ],
    )
    ax.set_ylim(-0.65, 1.65)
    ax.invert_yaxis()
    lower = min(row["min"] for row in weight_data) / 1.2
    upper = max(row["max"] for row in weight_data) * 1.2
    ticks = np.geomspace(lower, upper, 4)
    ax.set_xscale("log")
    ax.set_xticks(ticks, [f"{value:.3g}" for value in ticks])
    ax.xaxis.set_minor_locator(NullLocator())
    ax.set_xlim(lower, upper)
    ax.set_xlabel("Raw observation weight\n(log scale)")
    save(
        fig,
        "weights",
        "Raw weight concentration and effective sample size.",
        method
        + "Pale solid lines span the full minimum-to-maximum range, dashed lines the first-to-99th percentiles, shaded boxes the interquartile range and hollow circles the median. The horizontal axis is logarithmic. ESS is Kish's (sum w)^2/sum(w^2), a descriptive concentration measure; n is the actual retained case count. These intervals describe the distribution of raw weights, not confidence intervals. ESS is not additional patients, a power calculation or a guarantee of precision.",
        "保留全部權重極值，以對數軸呈現集中程度；實線、虛線、色塊與圓點是權重分布摘要，不是效果的信賴區間。n 是真正個案數，ESS 是權重集中指標。",
        weight_data,
    )

    effect = result["effect"]
    p_label = "p<1e-300" if effect["p_value"] == 0 else f"p={effect['p_value']:.8g}"
    fig, axes = new(70)
    ax = axes[0, 0]
    ax.plot([effect["lower"], effect["upper"]], [0, 0], color=COLORS[0], linewidth=1.5)
    ax.plot(effect["estimate"], 0, "o", color=COLORS[0])
    ax.axvline(0, color="#656565", linestyle="--")
    ax.set_yticks([0], [spec["estimand"]])
    ax.set_ylim(-0.8, 0.8)
    ax.xaxis.set_major_locator(MaxNLocator(4))
    unit = short_label(spec["outcome_unit"], "source units", 24)
    ax.set_xlabel(
        (
            "Probability difference"
            if spec["outcome_type"] == "binary"
            else f"Mean difference ({unit})"
        )
        + f"\nG1 minus G0; {spec['confidence_level']:.1%} CI"
    )
    save(
        fig,
        "effect",
        "Prespecified weighted outcome contrast with uncertainty.",
        method
        + f"The estimate is the difference of separately normalized Hájek means, G1 minus G0: {effect['estimate']:.8g} (SE {effect['standard_error']:.8g}; {spec['confidence_level']:.1%} CI {effect['lower']:.8g} to {effect['upper']:.8g}; two-sided {p_label}). "
        + "The joint independent-case estimating-equation sandwich includes propensity parameters, both outcome means, their covariance and weight derivatives. Limits use the asymptotic normal approximation without a finite-sample correction or bootstrap. There is one prespecified contrast, without multiplicity control across other estimands or branches. The null difference is zero. "
        + (
            f"Outcome coding: {spec['outcome_levels'][0]!r}=0, {spec['outcome_levels'][1]!r}=1. The difference is expressed in proportion units; multiply by 100 to obtain percentage points. A negative difference is possible. This is not an odds ratio or risk ratio. Wald limits are not clipped to [-1,1]. "
            if spec["outcome_type"] == "binary"
            else f"The difference retains the original outcome unit {spec['outcome_unit']!r}. "
        )
        + "Causal interpretation additionally requires valid timing, consistency, conditional exchangeability, positivity and suitable sampling; balance and significance do not establish these assumptions.",
        "主要對比為處置組減參照組，區間已包含 propensity 估計的不確定性。二元結果是絕對機率差，乘 100 才是百分點；連續結果保留原始單位。沒有跨其他目標校正多重比較，也沒有從平衡或顯著性推定因果療效。",
        [effect],
    )
    return records
