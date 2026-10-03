"""Publication figures from complete, saved general-analysis receipts; never refit."""

from copy import deepcopy
import json
import math
from pathlib import Path
import textwrap

from rde.infrastructure.prediction.splits import digest
from .dictionary import DisplayDictionary
from .publication import publication_style, save_publication_figure


METHODS = {"logistic_regression", "multiple_regression", "risk_estimates", "propensity_score"}
COLORS = ["#0072B2", "#D55E00", "#009E73"]
SCOPE = (
    "Exploratory analysis; no correction across explored models. "
    "Model-specific complete cases need not equal those of the primary analysis. "
    "These figures do not replace the primary analysis or establish causality."
)


def publication_result(record):
    """Freeze the plot input while checking complete numerical receipt identities.

    Source snapshot/cleaning and native execution ledgers are verified by the
    caller. This function checks saved numerical structure, not statistical truth.
    """
    method = record["analysis_contract"].get("analysis_type")
    if method not in METHODS or record.get("status") != "completed":
        raise ValueError("A completed supported general analysis is required.")
    if record.get("sha256") != digest({k: v for k, v in record.items() if k != "sha256"}):
        raise ValueError("The complete numerical branch receipt has changed.")
    binding = record["input_evidence"]["source_binding"]
    if binding.get("status") != "verified":
        raise ValueError("Publication requires a source-bound input frame.")
    analysis = record["analysis_result"]
    if analysis.get("analysis_type") != method:
        raise ValueError("The executed method differs from the saved contract.")
    if method == "risk_estimates":
        evidence = analysis["risk_evidence"]
    elif method == "propensity_score":
        evidence = analysis["propensity_model"]["model_evidence"]
    else:
        evidence = analysis["model_evidence"]
    if evidence["sha256"] != digest({k: v for k, v in evidence.items() if k != "sha256"}):
        raise ValueError("Saved model or risk evidence has changed.")
    contract = record["analysis_contract"]
    if method == "risk_estimates":
        roles_match = (
            evidence["outcome_variable"] == contract.get("target_variable")
            and evidence["exposure_variable"] == contract.get("group_variable")
            and not contract.get("covariates")
            and all(analysis[k] == evidence[k] for k in ("estimates", "table", "table_order"))
        )
    else:
        roles_match = (
            analysis["treatment_variable"] == contract.get("group_variable")
            if method == "propensity_score"
            else analysis["target"] == contract.get("target_variable")
        ) and (
            analysis["covariates"]
            if method == "propensity_score"
            else analysis["source_covariates"]
        ) == contract.get("covariates", [])
    if not roles_match or evidence["confidence_level"] != contract.get("confidence_level", 0.95):
        raise ValueError("Saved outcomes, factors or confidence level differ from the contract.")
    case = analysis["case_set"]
    positions = case["included_row_positions"]
    if (
        case != evidence["case_set"]
        or case["n_input"] != binding["input_frame"]["rows"]
        or case["n_input"] != case["n_analyzed"] + case["n_excluded"]
        or len(positions) != case["n_analyzed"]
        or len(set(positions)) != len(positions)
        or any(type(p) is not int or not 0 <= p < case["n_input"] for p in positions)
        or [r["row_position"] for r in evidence["rows"]] != positions
    ):
        raise ValueError("The complete case set and full saved rows differ.")
    if method == "propensity_score":
        if (
            analysis.get("propensity_scores_truncated") is not False
            or analysis.get("matched_pairs_truncated") is not False
            or [r["row_position"] for r in analysis["propensity_scores"]] != positions
            or analysis["diagnostic_policy"].get("outcome_effect_estimated") is not False
        ):
            raise ValueError(
                "Complete propensity diagnostics without outcome-effect claims are required."
            )
        by_position = {r["row_position"]: r for r in analysis["propensity_scores"]}
        treated, controls = set(), set()
        for pair in analysis["matched_pairs"]:
            t, c = pair["treated_row_position"], pair["control_row_position"]
            if (
                t not in by_position
                or c not in by_position
                or t in treated
                or c in controls
                or by_position[t]["treatment"] != 1
                or by_position[c]["treatment"] != 0
                or pair["treated_propensity_score"] != by_position[t]["propensity_score"]
                or pair["control_propensity_score"] != by_position[c]["propensity_score"]
            ):
                raise ValueError("Saved propensity pair identities are incomplete or inconsistent.")
            treated.add(t)
            controls.add(c)
    result = {
        "schema": "advanced-publication-v1",
        "status": "completed",
        "spec": {"family": "advanced_exploration", "method": method},
        "contract": record["analysis_contract"],
        "analysis": analysis,
        "source_binding": binding,
        "preprocessing": {
            "derived_variables": record.get("derived_variables", []),
            "plausibility_notes": record.get("plausibility_notes", []),
            "plausibility_summary": record.get("plausibility_summary"),
        },
        "numerical_record_sha256": digest(
            {
                k: v
                for k, v in record.items()
                if k not in {"sha256", "publication_result", "figures", "artifacts"}
            }
        ),
    }
    result = deepcopy(result)
    result["receipt_sha256"] = digest(result)
    return result


def figures(result, directory: Path, prefix, preset_id="journal-neutral-english-v1", edition=None):
    import matplotlib

    matplotlib.use("Agg")
    if result["receipt_sha256"] != digest(
        {k: v for k, v in result.items() if k != "receipt_sha256"}
    ):
        raise ValueError("Saved publication input changed.")
    with publication_style(preset_id) as profile:
        if edition:
            profile["edition"] = edition
        return _figures(result, directory, prefix, profile)


def _figures(result, directory, prefix, profile):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    method, analysis = result["spec"]["method"], result["analysis"]
    binding, case = result["source_binding"], analysis["case_set"]
    dictionary = DisplayDictionary(profile.get("edition", {}).get("display_dictionary"))
    records = []
    mappings = "".join(
        dictionary.describe(column, [level["value"] for level in entry["levels"]])
        for column, entry in dictionary.entries.items()
    )
    context = (
        f"Input after {len(binding['cleaning'])} recorded cleaning step(s): {case['n_input']} rows; "
        f"analyzed: {case['n_analyzed']}; excluded for this analysis: {case['n_excluded']}. "
        "Any preceding cleaning or imputation is recorded in the source lineage; "
        "complete-case handling here concerns the resulting analysis input. "
        "Reviewed units describe the original source scale; no numerical conversion is performed. "
    )
    if (
        result["preprocessing"]["derived_variables"]
        or result["preprocessing"]["plausibility_notes"]
    ):
        context += "Recorded variable derivations and plausibility handling precede model-specific exclusion; see the full preprocessing receipt. "

    def label(column, fallback, limit=24):
        return dictionary.compact(dictionary.label(column, column), fallback, limit)

    def new(height=80):
        fig, ax = plt.subplots(figsize=(profile["width_mm"] / 25.4, height / 25.4))
        ax.xaxis.set_major_locator(MaxNLocator(4))
        ax.yaxis.set_major_locator(MaxNLocator(4))
        return fig, ax

    def ratio_ticks(ax):
        # Saved log geometry, readable ratio ticks; no coefficient/interval cap.
        left, right = ax.get_xlim()
        points = [left + (right - left) * fraction for fraction in (0.1, 0.5, 0.9)]
        if left <= 0 <= right:
            points = sorted(set([points[0], 0, points[-1]]))
        for precision in (3, 5, 8, 12, 17):
            labels = []
            for value in points:
                try:
                    ratio = math.exp(value)
                    labels.append(
                        f"{ratio:.{precision}g}" if ratio else f"exp({value:.{precision}g})"
                    )
                except OverflowError:
                    labels.append(f"exp({value:.{precision}g})")
            if len(set(labels)) == len(points):
                break
        ax.set_xticks(points, labels)

    mandatory_method = (
        "The propensity model estimates group assignment, not a clinical endpoint; no outcome effect was estimated. "
        "Balance uses each stage's own pooled standard deviation. "
        "Weighting and matching follow the saved policy; no causal identification is established."
        if method == "propensity_score"
        else "Observed binary endpoint fractions are not censoring-adjusted or common-time survival risks. "
        "These unadjusted estimates require independent observations and risk-estimable sampling."
        if method == "risk_estimates"
        else "In-sample model diagnostics do not establish externally validated prediction. "
        + (
            "This is a regularized fit; conventional unpenalized inference is not established. "
            if analysis["model_evidence"]["regularized"]
            else "Intervals use the saved model-based procedure. "
        )
        + (
            "Coefficients use the saved centered and scaled predictor basis."
            if analysis["model_evidence"]["scaling"]
            else "Numeric predictors retain their source scale."
        )
    )

    def save(fig, key, title, caption, explanation, data):
        pub = save_publication_figure(
            fig,
            directory,
            f"{prefix}_advanced_{key}",
            number=len(records) + 1,
            title=title,
            caption=context + caption,
            explanation=explanation,
            data=data,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
            required_caption=(SCOPE, context, mandatory_method, dictionary.note(), mappings),
        )
        if dictionary.value:
            pub["dictionary_sha256"] = dictionary.value["dictionary_sha256"]
        records.append(
            {
                "path": pub["files"]["png"],
                "plot_type": f"advanced_{key}",
                "caption": pub["caption_en"] + "\n\n中文解釋：" + explanation,
                "publication": pub,
            }
        )

    included = set(case["included_row_positions"])
    flow = [
        {"input_position": i, "normalized_source_index": index, "included": i in included}
        for i, index in enumerate(binding["input_source_indices"])
    ]
    fig, ax = new(72)
    ax.axis("off")
    table = ax.table(
        cellText=[
            ["Bound input", str(case["n_input"])],
            ["Excluded for this analysis", str(case["n_excluded"])],
            ["Analyzed", str(case["n_analyzed"])],
        ],
        colLabels=["Inclusion step", "Rows"],
        colWidths=[0.76, 0.24],
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 2)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor("#bac4cc")
        if row == 0:
            cell.set_facecolor("#eef3f6")
    save(
        fig,
        "inclusion",
        "Case inclusion for this exploratory analysis.",
        "The CSV retains every input position and normalized source index, including excluded rows. "
        "Source indices are not physical CSV line numbers. Missingness does not establish missing at random.",
        "列出這次分析真正使用與排除的列；CSV 保留全部列位置。各模型個案可能不同，不能只看樣本數就認定是相同的人。",
        flow,
    )

    if method in {"logistic_regression", "multiple_regression"}:
        evidence = analysis["model_evidence"]
        rows = evidence["rows"]
        binary = method == "logistic_regression"
        coding = evidence["predictor_coding"]
        names = evidence["design_columns"]
        model_note = (
            f"Engine: {analysis['engine']}. "
            + (
                "Regularized fit; conventional unpenalized inference is not established. "
                if evidence["regularized"]
                else "Unadjusted model-based intervals; no external validation. "
            )
            + (
                "Predictors use saved centering and scaling; see the complete scaling receipt. "
                if evidence["scaling"]
                else "Numeric predictors retain their source scale. "
            )
            + "Predictor coding: "
            + json.dumps(coding, ensure_ascii=False)
            + ". "
        )
        if binary:
            model_note += (
                "Outcome coding: "
                + json.dumps(evidence["outcome_coding"], ensure_ascii=False)
                + ". "
            )
        # An intercept on the same axis can hide all clinically relevant intervals.
        indices = [i for i, name in enumerate(names) if name != "const"]
        blocks = [[names.index("const")]] if "const" in names else []
        blocks += [indices[start : start + 6] for start in range(0, len(indices), 6)]
        for block_number, positions in enumerate(blocks, 1):
            block = [names[i] for i in positions]
            intercept = block == ["const"]
            fig, ax = new(max(58, 35 + len(block) * 9))
            data, labels = [], []
            for y, (i, name) in enumerate(zip(positions, block, strict=True)):
                interval = evidence["coefficient_intervals"]
                lo, hi = interval[i] if interval is not None else (None, None)
                value = evidence["parameters"][i]
                shown = "Intercept" if name == "const" else label(name, f"P{i}", 18)
                labels.append(textwrap.fill(f"P{i}: {shown}", 22))
                if value is not None:
                    ax.plot(value, y, "o", color=COLORS[0])
                if lo is not None and hi is not None:
                    ax.plot([lo, hi], [y, y], color=COLORS[0])
                elif value is not None:
                    ax.annotate(
                        "  CI unavailable", (value, y), fontsize=7, xycoords=("data", "data")
                    )
                data.append(
                    {
                        "term": name,
                        "figure_code": f"P{i}",
                        "display_label": shown,
                        "coefficient": value,
                        "lower": lo,
                        "upper": hi,
                        "odds_ratio": analysis.get("odds_ratios", {}).get(name),
                        "p_value": analysis.get("p_values", {}).get(name),
                    }
                )
            ax.axvline(0, color="#777777", linestyle="--", linewidth=0.8)
            ax.set_yticks(range(len(block)), labels)
            ax.set_ylim(len(block) - 0.5, -0.5)
            ax.set_xlabel(
                "Intercept (log odds)"
                if binary and intercept
                else "Odds ratio (log scale)"
                if binary
                else "Intercept (outcome scale)"
                if intercept
                else "Coefficient (model scale)"
            )
            if binary and not intercept:
                ratio_ticks(ax)
            save(
                fig,
                f"coefficients_{block_number}",
                "Saved model coefficients and uncertainty.",
                model_note
                + f"Intervals are the saved {evidence['confidence_level']:.1%} coefficient intervals, "
                "when estimable; unavailable intervals are not zero-width intervals. "
                + (
                    "The intercept panel shows baseline log odds on its own axis. Predictor panels show odds ratios on logarithmic axes; "
                    "their reference line is OR=1. CSV retains original log coefficients and available odds ratios. "
                    "Tick labels use exp(value) explicitly if exponentiation is not representable; no estimate is capped. "
                    if binary
                    else "The intercept is on the outcome scale; other coefficients depend on predictor coding and scale. "
                )
                + "Figure codes: "
                + "; ".join(f"{r['figure_code']}={r['term']!r}" for r in data)
                + ".",
                "顯示保存的係數與區間；缺少區間會明示，不補造推論。截距與其他因素意義不同，分類參考組與尺度見完整圖說。",
                data,
            )
        target = analysis["target"]
        if binary:
            fig, ax = new()
            data = []
            for group in [0, 1]:
                selected = sorted(
                    [r for r in rows if r["outcome"] == group],
                    key=lambda r: (r["fitted"], r["row_position"]),
                )
                for rank, row in enumerate(selected, 1):
                    data.append({**row, "within_outcome_rank": rank})
                ax.plot(
                    range(1, len(selected) + 1),
                    [r["fitted"] for r in selected],
                    ".",
                    color=COLORS[group],
                    markersize=3,
                    label=f"Y={group} (n={len(selected)})",
                )
            ax.set_ylim(-0.03, 1.03)
            ax.set_xlabel("Rank within observed outcome group")
            ax.set_ylabel("In-sample fitted probability")
            ax.legend(loc="best", fontsize=7)
            save(
                fig,
                "fitted",
                "In-sample fitted probabilities by observed outcome.",
                model_note
                + "Dots are all saved fitted probabilities, sorted separately within each observed outcome. "
                "Ranks are display positions, not follow-up time. This is neither a calibration plot nor validated predictive performance.",
                "全部個案按各結果組內的擬合機率排序；這只是同一批建模資料的描述，不代表校準或外部預測效能。",
                data,
            )
        else:
            fig, ax = new()
            ax.scatter(
                [r["fitted"] for r in rows],
                [r["outcome"] for r in rows],
                s=9,
                color=COLORS[0],
                alpha=0.6,
            )
            limits = [
                min(min(r["fitted"], r["outcome"]) for r in rows),
                max(max(r["fitted"], r["outcome"]) for r in rows),
            ]
            ax.plot(limits, limits, "--", color="#777777", linewidth=0.8)
            unit = dictionary.unit(target, "source units")
            ax.set_xlabel(
                f"Fitted {label(target, 'outcome', 18)}\n({dictionary.compact(unit, 'source units', 20)})"
            )
            ax.set_ylabel("Observed outcome (same scale)")
            save(
                fig,
                "fitted",
                "Observed outcomes and in-sample fitted values.",
                model_note
                + f"Outcome source column: {target!r}. Every saved fitted value is shown; dashed line is identity, "
                "not a fitted smoother. In-sample agreement does not estimate out-of-sample performance.",
                "點為全部建模個案；虛線只是觀察值與擬合值相等的位置，不是新擬合的線，也不能當成外部驗證。",
                rows,
            )
            fig, ax = new()
            ax.scatter(
                [r["fitted"] for r in rows],
                [r["response_residual"] for r in rows],
                s=9,
                color=COLORS[0],
                alpha=0.6,
            )
            ax.axhline(0, color="#777777", linestyle="--", linewidth=0.8)
            ax.set_xlabel("In-sample fitted value (source scale)")
            ax.set_ylabel("Response residual\n(observed minus fitted)")
            save(
                fig,
                "residuals",
                "Saved response residuals against fitted values.",
                model_note
                + "Residuals use the outcome source scale. No smoothing, new test, refitting or resampling is performed. "
                "A visually unstructured pattern does not prove independence or constant variance.",
                "殘差是觀察值減擬合值，沿用原結果尺度；圖形沒有明顯模式也不能證明模型假設成立。",
                rows,
            )
    elif method == "risk_estimates":
        evidence = analysis["risk_evidence"]
        risk_note = (
            f"Outcome {evidence['outcome_variable']!r}, event={evidence['outcome_event']!r}; "
            f"exposure {evidence['exposure_variable']!r}, comparison={evidence['exposure_comparison']!r}, "
            f"reference={evidence['exposure_reference']!r}. Independent-case unadjusted comparison. "
            "These are observed binary endpoint fractions, not censoring-adjusted or common-time survival risks. "
            "Risk ratios require risk-estimable sampling and are not risk estimates in case-control sampling. "
        )
        fig, ax = new()
        data = []
        for i, (events, non_events) in enumerate(evidence["table"]):
            name = "Comparison" if i == 0 else "Reference"
            n = events + non_events
            data.append(
                {
                    "group": name,
                    "events": events,
                    "non_events": non_events,
                    "n": n,
                    "fraction": events / n,
                }
            )
            ax.bar(i, events / n, width=0.5, color=COLORS[i])
            ax.text(i, events / n + 0.03, f"{events}/{n}", ha="center", fontsize=8)
        ax.set_ylim(0, 1.14)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1])
        ax.set_xticks([0, 1], ["Comparison", "Reference"])
        ax.set_ylabel("Observed event fraction")
        save(
            fig,
            "fractions",
            "Observed event fractions in the two groups.",
            risk_note
            + "Bars show events divided by observed complete cases; counts are printed above each bar. No confidence intervals are implied by the bars.",
            "長條是各組完整個案的事件比例，保留分子與分母；追蹤時間可能不同，不能當成固定時間的存活風險。",
            data,
        )
        for key, title, null in [
            ("risk_difference", "Risk difference", 0),
            ("risk_ratio", "Risk ratio", 1),
            ("odds_ratio", "Odds ratio", 1),
        ]:
            estimate = evidence["estimates"][key]
            fig, ax = new(64)
            value, lo, hi = (estimate[k] for k in ["estimate", "ci_lower", "ci_upper"])
            ratio = null == 1

            def coordinate(v):
                return math.log(v) if ratio else v

            valid = value is not None and (not ratio or value > 0)
            interval = lo is not None and hi is not None and (not ratio or (lo > 0 and hi > 0))
            if valid:
                ax.plot(coordinate(value), 0, "o", color=COLORS[0])
            if interval:
                ax.plot([coordinate(lo), coordinate(hi)], [0, 0], color=COLORS[0])
            ax.axvline(0, color="#777777", linestyle="--", linewidth=0.8)
            ax.set_yticks([])
            ax.set_ylim(-1, 1)
            ax.set_xlabel(title + (" (log scale)" if ratio else " (probability units)"))
            if ratio:
                ratio_ticks(ax)
            if not valid or not interval:
                ax.text(
                    0.5,
                    0.8,
                    "Estimate / CI not fully estimable",
                    transform=ax.transAxes,
                    ha="center",
                    fontsize=8,
                )
            save(
                fig,
                key,
                title + " and saved uncertainty.",
                risk_note
                + f"Saved {evidence['confidence_level']:.1%} interval method: {estimate.get('ci_method', 'not available; see saved estimation warnings')}. "
                + (
                    "The horizontal axis uses logarithmic spacing with ratio labels; the reference line is ratio=1. CSV retains untransformed ratios. "
                    if ratio
                    else "Comparison minus reference; zero denotes no difference. "
                )
                + "Missing or zero ratio limits are reported as unavailable on the log axis, never replaced by clipped positive values.",
                "使用原收據的效果與區間；比值圖使用對數間距，刻度仍顯示原始比值，參考線為 1。不可估計或無法取對數的界限不會被換成任意數字。",
                [{"measure": key, **estimate}],
            )
    else:
        policy, rows = analysis["diagnostic_policy"], analysis["propensity_scores"]
        note = (
            "The model outcome is group assignment, not a clinical outcome. No outcome effect was estimated. "
            "Treatment coding: "
            + json.dumps(analysis["treatment_coding"], ensure_ascii=False)
            + ". "
            "Saved diagnostic policy: " + json.dumps(policy, ensure_ascii=False) + ". "
        )
        fig, ax = new()
        data = []
        for group in [0, 1]:
            selected = sorted(
                [r for r in rows if r["treatment"] == group],
                key=lambda r: (r["propensity_score"], r["row_position"]),
            )
            points = [
                {**r, "cumulative_fraction": (i + 1) / len(selected)}
                for i, r in enumerate(selected)
            ]
            data.extend(points)
            ax.step(
                [0, *[r["propensity_score"] for r in points], 1],
                [0, *[r["cumulative_fraction"] for r in points], 1],
                where="post",
                color=COLORS[group],
                linestyle="-" if group == 0 else "--",
                label=f"A={group} (n={len(points)})",
            )
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.04)
        ax.set_xlabel("Saved propensity score")
        ax.set_ylabel("Within-group cumulative fraction")
        ax.legend(loc="best", fontsize=7)
        save(
            fig,
            "propensity",
            "Saved propensity score distributions by group.",
            note
            + "Empirical cumulative fractions display all saved scores without binning or smoothing. Marginal overlap does not establish positivity for all covariate patterns.",
            "每組的累積分布保留全部傾向分數；重疊只是描述，不代表所有特徵都有可比較的對象，也不是治療效果。",
            data,
        )
        terms = list(analysis["balance_diagnostics"])
        stages = [
            ("balance_diagnostics", "Observed", "o"),
            ("weighted_balance_diagnostics", "IPTW", "s"),
            ("matched_balance_diagnostics", "Matched", "^"),
        ]
        for start in range(0, len(terms), 6):
            block = terms[start : start + 6]
            fig, ax = new(max(85, 40 + len(block) * 8))
            data = []
            for i, term in enumerate(block):
                for j, (field, name, marker) in enumerate(stages):
                    item = analysis[field].get(term)
                    if item is None:
                        continue
                    smd = item["standardized_mean_difference"]
                    if smd is not None:
                        ax.plot(
                            abs(smd),
                            i,
                            marker,
                            color=COLORS[j],
                            label=name if i == 0 else None,
                            markersize=4,
                        )
                    data.append({"term": term, "stage": name, **item})
            ax.set_yticks(
                range(len(block)),
                [textwrap.fill(label(t, f"P{start+i+1}", 20), 20) for i, t in enumerate(block)],
            )
            ax.set_ylim(len(block) - 0.5, -0.5)
            ax.set_xlim(left=0)
            ax.set_xlabel("Absolute standardized\nmean difference")
            ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=1, fontsize=7)
            save(
                fig,
                f"balance_{start // 6 + 1}",
                "Covariate balance across saved diagnostic stages.",
                note
                + "Each stage uses its own pooled group standard deviation; unweighted variances use ddof=1 and weighted variances use the saved population-weighted formula. "
                "Thus these are stage-specific standardized contrasts, not changes on one fixed denominator. Missing values are undefined, not zero imbalance. "
                "Signed contrasts, group means, variances and denominators remain in CSV. No significance test or balance pass threshold is applied. "
                + "Encoded terms: "
                + json.dumps(analysis["encoded_covariate_map"], ensure_ascii=False)
                + ".",
                "圖顯示絕對 SMD，資料表保留正負方向、平均數與分母。每個階段使用自己的標準差，不能當成固定分母下的改善幅度；平衡也不代表因果關係成立。",
                data,
            )
        fig, ax = new()
        for group in [0, 1]:
            selected = [r for r in rows if r["treatment"] == group]
            ax.scatter(
                [r["propensity_score"] for r in selected],
                [r["iptw_weight"] for r in selected],
                color=COLORS[group],
                s=10,
                alpha=0.6,
                marker="o" if group == 0 else "^",
                label=f"A={group}",
            )
        ax.set_xlabel("Saved propensity score")
        ax.set_ylabel("Stabilized ATE weight")
        ax.set_xlim(0, 1)
        ax.legend(fontsize=7)
        save(
            fig,
            "weights",
            "Saved stabilized inverse-probability weights.",
            note
            + "Each point is one retained observation; weights are read from the receipt, not recalculated. Extreme weights are not trimmed by rendering.",
            "顯示全部已保存權重，沒有在繪圖時截尾或重新計算。極端權重提示估計可能不穩定，但此圖尚未估計臨床效果。",
            rows,
        )
        pairs = analysis["matched_pairs"]
        if pairs:
            fig, ax = new()
            data = [
                {"pair_rank": i + 1, **p}
                for i, p in enumerate(
                    sorted(pairs, key=lambda p: (p["score_distance"], p["treated_row_position"]))
                )
            ]
            ax.plot(
                [p["pair_rank"] for p in data],
                [p["score_distance"] for p in data],
                ".",
                color=COLORS[0],
                markersize=3,
            )
            ax.set_xlabel("Pair rank by score distance")
            ax.set_ylabel("Absolute propensity-score distance")
            save(
                fig,
                "pairs",
                "Score distances for all retained matched pairs.",
                note
                + "Every saved pair is shown in increasing score-distance order; matching is not rerun. Without a caliper, large distances are not automatically excluded. "
                "A close score pair does not establish close agreement on every covariate.",
                "保留所有配對的距離與兩端列位置；沒有重新配對，未設定距離上限也不會在繪圖時偷偷刪除較遠配對。",
                data,
            )
    return records
