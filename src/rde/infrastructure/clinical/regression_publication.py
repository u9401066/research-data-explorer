"""English publication plots from frozen coefficients, contrasts and diagnostics."""

import json
from pathlib import Path
import textwrap

import numpy as np
from scipy.stats import norm

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure
from .regression_report import coefficient_blocks, flow, term_description
from .survival_publication import COLORS, short_label


def term_label(row, result):
    if row["role"] == "interaction":
        terms = {r["term"]: r for r in result["coefficients"]}
        return " × ".join(term_label(terms[k], result) for k in row["components"])
    p = result["spec"]["predictors"][row["predictor"]]
    name = f"P{row['predictor'] + 1}"
    if row["role"] == "spline_basis":
        return f"{name}: spline basis {row['basis'] + 1}"
    name = short_label(p["label"], name, 20)
    if row["role"] == "categorical":
        return f"{name}: {short_label(row['level'], 'level', 14)} vs {short_label(p['reference'], 'reference', 14)}"
    return f"{name}: +{p['increment']:g} {short_label(p['unit'], 'source units', 14)}"


def ratio_axis(ax, values, *, orientation="x"):
    """Use explicit positive ticks, including the null, across the full interval."""
    from matplotlib.ticker import NullLocator

    lower, upper = min(1.0, min(values)) * 0.85, max(1.0, max(values)) * 1.15
    span = np.log(upper) - np.log(lower)
    ticks = sorted(
        [1.0, *[float(t) for t in np.geomspace(lower, upper, 4) if abs(np.log(t)) > 0.14 * span]]
    )
    getattr(ax, f"set_{orientation}scale")("log")
    getattr(ax, f"set_{orientation}ticks")(ticks, [f"{t:.3g}" for t in ticks])
    getattr(ax, f"set_{orientation}lim")(lower, upper)
    getattr(ax, f"{orientation}axis").set_minor_locator(NullLocator())


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

    s, model, records = result["spec"], result["model"], []
    ci = f"{s['confidence_level']:.1%}"
    outcome_unit = short_label(s["outcome_unit"], "source units", 28)
    source_note = f"One common complete-case sample of {result['n']} independent cases; declared study design: {s['study_design']}. Outcome {s['outcome']!r}, original units/definition {s['outcome_unit']!r}. "
    model_note = f"Prespecified {s['distribution']} model, {model['link']} link; {model['covariance']} covariance; {model['inference']} inference. "
    predictor_note = (
        "Predictors: "
        + "; ".join(
            f"P{i + 1}={p['label']!r}, source {p['column']!r}, reference={p['reference']!r}"
            + (
                f", source unit={p['unit']!r}, comparison increment={p['increment']}, spline knots={p['knots']}"
                if p["kind"] == "continuous"
                else f", source levels={p['levels']}"
            )
            for i, p in enumerate(s["predictors"])
        )
        + ". "
    )
    outcome_note = (
        f"Outcome order from lowest to highest: {s['outcome_levels']}. The proportional-odds equation is logit P(Y<=k)=cutpoint(k)-X beta; positive beta favors higher categories. The proportional-odds assumption has not been formally tested. "
        if s["distribution"] == "ordinal"
        else f"Binary outcome coding: {s['outcome_levels'][0]!r}=0, {s['outcome_levels'][1]!r}=1. Odds ratios are not risk ratios. "
        if s["distribution"] == "binomial"
        else f"Offset=log({s['exposure']!r}), in source units {s['exposure_unit']!r}; the offset coefficient is fixed at 1. Fitted responses are counts, while comparisons are rate ratios. "
        if s["exposure"]
        else "There is no duration offset; ratios compare expected counts, not person-time rates. "
        if s["distribution"] in {"poisson", "negative_binomial"}
        else ""
    )
    if s["study_design"] == "case_control":
        outcome_note += "Fitted probabilities and the intercept describe the sampled case-control mix, not population disease risks. "

    def new(height=125):
        return plt.subplots(figsize=(180 / 25.4, height / 25.4))

    def save(fig, kind, title, caption, explanation, data):
        publication = save_publication_figure(
            fig,
            directory,
            f"{prefix}_regression_{kind}",
            number=len(records) + 1,
            title=title,
            caption=source_note + caption,
            explanation=explanation,
            data=data,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
        )
        records.append(
            dict(
                path=publication["files"]["png"],
                plot_type=f"clinical_regression_{kind}",
                caption=publication["caption_en"]
                + "\n\n中文解釋："
                + publication["explanation_zh"],
                fonts={"family": profile["font_family"], "font_sha256": profile["font_sha256"]},
                publication=publication,
            )
        )

    fig, ax = new(90)
    ax.axis("off")
    rows = flow(result)
    table = ax.table(
        cellText=[[textwrap.fill(r["stage"], 21), str(r["cases"])] for r in rows],
        colLabels=["Inclusion step", "Cases"],
        colWidths=[0.65, 0.35],
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2.15)
    for (row, _), table_cell in table.get_celld().items():
        table_cell.set_edgecolor("#c4cbd0")
        if row == 0:
            table_cell.set_facecolor("#eef3f6")
    save(
        fig,
        "flow",
        "Case inclusion in the prespecified regression study.",
        "The declared cohort restriction precedes common complete-case exclusion for the outcome, all predictors and any exposure duration. No imputation, duplicate averaging or outcome-dependent selection is applied. Supplied case identifiers and invalid source values are checked before missing-field exclusion. Independence is a declared study assumption, not established by the number of rows. The ledger retains one-based source row locators excluding the header; these counts do not establish ignorable missingness.",
        "所有估計採同一完整個案集合；保留原始列號與排除原因。獨立性需由研究設計確認，沒有識別碼時不能據此保證一人一列；沒有補值或平均重複列。",
        rows,
    )

    for key, block in coefficient_blocks(result):
        ratio = block[0]["exponentiated"]
        labels = [term_label(row, result) for row in block]
        wrapped = [textwrap.fill(label, 23) for label in labels]
        # Keep physical space for multiline labels after a narrow journal preset
        # rescales the canvas but retains readable type. Uniform row spacing must
        # accommodate the longest label, including full interaction descriptions.
        lines = max(label.count("\n") + 1 for label in wrapped)
        minimum_height = 24 + len(block) * (4 * lines + 2)
        fig, ax = new(max(75, minimum_height * 180 / profile["width_mm"]))
        for i, row in enumerate(block):
            ax.plot([row["lower"], row["upper"]], [i, i], color=COLORS[0])
            ax.plot(row["estimate"], i, "o", color=COLORS[0])
        ax.set_yticks(range(len(block)), wrapped)
        ax.invert_yaxis()
        ax.axvline(1 if ratio else 0, linestyle="--", color="#656565")
        if ratio:
            ratio_axis(ax, [r[k] for r in block for k in ["lower", "upper"]])
        else:
            ax.xaxis.set_major_locator(MaxNLocator(5))
        ratio_label = {
            "binomial": "Odds ratio",
            "ordinal": "Common cumulative OR",
            "poisson": "Rate ratio" if s["exposure"] else "Mean count ratio",
            "negative_binomial": "Rate ratio" if s["exposure"] else "Mean count ratio",
            "gaussian": "",
        }[s["distribution"]]
        if key.startswith("interactions"):
            ratio_label = "Ratio of conditional ratios"
        ax.set_xlabel(
            f"{ratio_label} ({ci} CI)\nlog scale"
            if ratio
            else f"Coefficient beta\n({outcome_unit}; {ci} CI)"
            if s["distribution"] == "gaussian"
            else f"Coefficient beta ({ci} CI)"
        )
        descriptions = [term_description(r, result) for r in block]
        mapping = (
            "; ".join(
                f"{label!r}: {description}; scale={row['effect_scale']}"
                for label, description, row in zip(labels, descriptions, block, strict=True)
            )
            + ". "
        )
        save(
            fig,
            key,
            "Prespecified regression coefficients and pointwise uncertainty.",
            model_note
            + outcome_note
            + predictor_note
            + mapping
            + f"Points and horizontal lines show estimates and individual unadjusted {ci} intervals. "
            + (
                "Ratios use a logarithmic axis with null value 1. "
                if ratio
                else "Coefficients use a linear axis with null value 0. "
            )
            + "All nonintercept terms are retained in blocks of at most eight, without selection by significance. Main effects apply at the other declared reference values. Interactions compare conditional effects; all spline basis coefficients, including the linear component, remain on the linear-predictor scale and are not constant per-unit clinical effects. "
            + f"The downloadable Holm p-values cover all {len(result['multiplicity']['coefficient_family'])} nonintercept coefficients, including terms on other panels. Joint-term tests constitute a separate Holm family; neither these intervals nor comparisons across models have familywise adjustment. The intercept and nuisance parameters remain in the report tables.",
            "逐一保留非截距係數；效果、交互作用與樣條基底分開呈現。基底係數不是固定每單位的臨床效果，需看條件曲線；Holm 只校正指定家族的 p 值，圖中的逐項區間未校正。",
            [
                {"display_label": label, "description": desc, **row}
                for label, desc, row in zip(labels, descriptions, block, strict=True)
            ],
        )

    for curve in result["conditional_curves"]:
        p = s["predictors"][curve["predictor"]]
        code = f"P{curve['predictor'] + 1}"
        values = [r["value"] for r in curve["points"]]
        fig, ax = new()
        ax.fill_between(
            values,
            [r["lower"] for r in curve["points"]],
            [r["upper"] for r in curve["points"]],
            color=COLORS[0],
            alpha=0.17,
        )
        ax.plot(values, [r["estimate"] for r in curve["points"]], color=COLORS[0])
        ratio = s["distribution"] != "gaussian"
        ax.axhline(1 if ratio else 0, linestyle="--", color="#656565")
        ax.axvline(curve["reference"], linestyle=":", color="#656565")
        scale = (
            f"Mean difference ({outcome_unit})"
            if not ratio
            else "Cumulative odds ratio"
            if s["distribution"] == "ordinal"
            else "Odds ratio"
            if s["distribution"] == "binomial"
            else "Rate ratio"
            if s["exposure"]
            else "Mean count ratio"
        )
        ax.set(
            xlabel=f"{code} {short_label(p['label'], code, 28)}\n({short_label(p['unit'], 'source unit', 22)})",
            ylabel=f"{scale}\nvs reference {curve['reference']:g}"
            + (" (log scale)" if ratio else ""),
        )
        ax.xaxis.set_major_locator(MaxNLocator(5))
        if ratio:
            ratio_axis(
                ax, [r[k] for r in curve["points"] for k in ["lower", "upper"]], orientation="y"
            )
        save(
            fig,
            f"curve_{code}",
            f"Conditional model contrasts across the observed range of {code}.",
            model_note
            + outcome_note
            + predictor_note
            + f"The line compares each {p['column']!r} value with {curve['reference']} {p['unit']}; all other predictors are held at {curve['profile']}. The band is a pointwise unadjusted {ci} interval from the frozen contrast covariance, not a simultaneous confidence band or prediction interval. The vertical dotted line marks the reference; the horizontal dashed line marks the null contrast. "
            + "At the reference, the contrast and its interval equal exactly the null by definition, not because an individual's outcome has no uncertainty. The grid stays within the complete-case marginal range, but the joint reference profile may have sparse or no empirical support. These are conditional comparisons, not standardized population effects or validated patient predictions. No knots, covariates or fits are reselected during rendering.",
            "曲線比較原始數值與指定參照，其他因素固定。色帶是逐點模型對比 CI，不是預測區間或整條曲線同時信賴帶；參照處的 0／1 是對比定義。沒有超出單一因素的實際範圍，但參照因素組合仍可能欠缺共同資料支持。",
            [
                {
                    "column": curve["column"],
                    "unit": curve["unit"],
                    "reference": curve["reference"],
                    "profile": json.dumps(curve["profile"], ensure_ascii=False),
                    "effect_scale": curve["effect_scale"],
                    **r,
                }
                for r in curve["points"]
            ],
        )

    if s["distribution"] == "ordinal":
        fig, ax = new()
        rows = result["outcome_summary"]
        x = np.arange(len(rows))
        ax.bar(
            x - 0.18,
            [r["observed_proportion"] for r in rows],
            0.36,
            label="Observed",
            color=COLORS[0],
        )
        ax.bar(
            x + 0.18,
            [r["mean_fitted_probability"] for r in rows],
            0.36,
            label="Mean fitted",
            color=COLORS[1],
            hatch="//",
        )
        ax.set_xticks(
            x,
            [
                textwrap.fill(short_label(r["label"], f"L{i + 1}", 22), 13)
                for i, r in enumerate(rows)
            ],
        )
        ax.set(
            xlabel="Outcome category (declared order)",
            ylabel="Proportion / mean probability",
            ylim=(0, 1),
        )
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01))
        save(
            fig,
            "categories",
            "Observed and mean fitted ordinal category probabilities.",
            model_note
            + outcome_note
            + "Paired bars show the original category proportions and average saved fitted category probabilities in the same sample. Categories follow the declared source order, without assuming equal numeric spacing. No confidence intervals or goodness-of-fit tests are added. Similar aggregate bars do not verify proportional odds, calibration by covariates, independence or external predictive performance.",
            "按原始類別順序比較樣本比例與平均配適機率，不把序位當等距連續量；整體比例相近不能證明比例勝算假設、校準或外部預測效能。",
            rows,
        )
    else:
        gaussian = s["distribution"] == "gaussian"
        residual_key = "residual" if gaussian else "pearson_residual"
        fig, ax = new()
        ax.scatter(
            [r["fitted"] for r in result["points"]],
            [r[residual_key] for r in result["points"]],
            s=11,
            alpha=0.4,
            color=COLORS[0],
        )
        ax.axhline(0, linestyle="--", color="#656565")
        ax.set(
            xlabel=f"Fitted response ({outcome_unit})"
            if gaussian
            else "Fitted probability"
            if s["distribution"] == "binomial"
            else "Fitted count",
            ylabel=f"Response residual\n({short_label(s['outcome_unit'], 'source units', 30)})"
            if gaussian
            else "Pearson residual",
        )
        ax.xaxis.set_major_locator(MaxNLocator(5))
        save(
            fig,
            "residuals",
            "Saved residuals against fitted responses.",
            model_note
            + outcome_note
            + (
                "Response residuals are observed minus fitted responses in the original outcome units. "
                if gaussian
                else "Pearson residuals divide observed-minus-fitted responses by the model's conditional standard deviation; binomial variance is mu(1-mu), Poisson variance is mu, and NB2 variance is mu+alpha*mu^2 with estimated alpha. "
            )
            + "Every retained case appears without jitter, smoothing, clipping or post-fit exclusion; overlaps remain. These are in-sample diagnostics, not independent validation or proof of the mean/variance model.",
            "保留所有完整個案，沒有抖動、平滑或事後刪點。Gaussian 顯示原始單位殘差，其餘以模型條件標準差縮放；圖形不能證明模型正確，也不是獨立驗證。",
            result["points"],
        )
        if gaussian:
            ordered = sorted(result["points"], key=lambda r: r["residual"])
            probabilities = (np.arange(len(ordered)) + 0.5) / len(ordered)
            theoretical = norm.ppf(probabilities)
            residuals = np.array([r["residual"] for r in ordered])
            quartiles = np.quantile(residuals, [0.25, 0.75])
            normal_quartiles = norm.ppf([0.25, 0.75])
            slope = np.diff(quartiles)[0] / np.diff(normal_quartiles)[0]
            endpoints = theoretical[[0, -1]]
            reference = quartiles[0] + slope * (endpoints - normal_quartiles[0])
            fig, ax = new()
            ax.scatter(theoretical, residuals, s=11, alpha=0.4, color=COLORS[0])
            ax.plot(endpoints, reference, "--", color="#656565")
            ax.set(
                xlabel="Standard normal quantile",
                ylabel=f"Response residual\n({short_label(s['outcome_unit'], 'source units', 30)})",
            )
            data = [
                dict(
                    plot_role="saved_residual",
                    data_row=r["data_row"],
                    probability=float(probabilities[i]),
                    theoretical_quantile=float(theoretical[i]),
                    residual=r["residual"],
                )
                for i, r in enumerate(ordered)
            ]
            data += [
                dict(
                    plot_role="quartile_reference", theoretical_quantile=float(x), residual=float(y)
                )
                for x, y in zip(endpoints, reference, strict=True)
            ]
            save(
                fig,
                "qq",
                "Normal quantile comparison of saved Gaussian residuals.",
                model_note
                + "All sorted response residuals are compared with standard normal quantiles at (rank-0.5)/n. The dashed line passes through empirical residual quartiles (linear interpolation) and normal 0.25/0.75 quantiles; it is plotting geometry, not a fitted regression or a normality test. No residual is trimmed or winsorized. HC3 inference is a robust asymptotic approximation; a straight pattern does not prove normality, independence, a correct mean model or adequate sample size.",
                "常態分位圖只比較保存的殘差；虛線通過四分位數，不再擬合或做常態檢定。HC3 是穩健近似，圖形接近直線不保證獨立、模型正確或樣本充足。",
                data,
            )
    return records
