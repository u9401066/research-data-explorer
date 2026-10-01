"""Publication figures derived only from persisted prediction evidence."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure

BLUE = "#0072B2"
ORANGE = "#D55E00"
GRAY = "#656565"


def figures(result: dict, directory: Path, prefix: str) -> list[dict]:
    import matplotlib

    matplotlib.use("Agg")
    with publication_style() as profile:
        return _figures(result, directory, prefix, profile)


def _figures(result, directory, prefix, profile):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from sklearn.metrics import precision_recall_curve, roc_curve

    spec, validation = result["spec"], result["validation"]
    scores, uncertainty = validation["metrics"], validation["uncertainty"]
    n = validation["n"]
    y = np.asarray([r["observed"] for r in validation["predictions"]])
    prediction = np.asarray([r["prediction"] for r in validation["predictions"]])
    model_labels = {
        "linear": "Penalized logistic regression"
        if spec["task"] == "binary"
        else "Ridge regression",
        "random_forest": "Random forest",
    }
    selected = model_labels[result["selection"]["selected"]]
    records = []
    ci = f"{spec['confidence_level']:.1%}"
    population_note = (
        "Sampling was outcome-selected or unconfirmed; probability scores, predictive values and calibration describe this sample, not validated population risk. "
        if spec["sampling"] != "single_gate"
        else "Declared single-gate sampling does not by itself establish population representativeness. "
    )
    common = (
        f"The outcome was {spec['target']}. {selected} was selected using training data only. "
        f"The internal holdout comprised {n} observations. "
        + population_note
        + "This analysis is not external or clinical-use validation."
    )

    def estimate(key):
        v = scores.get(key)
        if v is None:
            return "not estimable"
        bounds = uncertainty["intervals"].get(key, {})
        return (
            f"{v:.3f} ({ci} CI {bounds['lower']:.3f}–{bounds['upper']:.3f})"
            if bounds.get("lower") is not None
            else f"{v:.3f} (CI not estimated)"
        )

    bootstrap = (
        f"Confidence intervals use {uncertainty['replicates_requested']} percentile bootstrap draws "
        f"of {'whole subjects' if uncertainty['unit']=='subject_cluster' else 'observations'}, "
        "conditional on the fixed fitted model. They exclude training/model-selection uncertainty and are not multiplicity-adjusted."
    )

    def new(height=115):
        return plt.subplots(figsize=(180 / 25.4, height / 25.4))

    def save(fig, kind, title, caption, explanation, data):
        publication = save_publication_figure(
            fig,
            directory,
            f"{prefix}_{kind}",
            number=len(records) + 1,
            title=title,
            caption=caption,
            explanation=explanation,
            data=data,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
        )
        records.append(
            {
                "path": publication["files"]["png"],
                "plot_type": f"prediction_{kind}",
                "caption": publication["caption_en"] + "\n\n中文解釋：" + explanation,
                "fonts": {"family": profile["font_family"], "font_sha256": profile["font_sha256"]},
                "publication": publication,
            }
        )

    outer = result["outer_split"]
    excluded = result["n_source"] - result["n_eligible"]
    purged = len(outer["purged_train_positions"])
    fig, ax = new(120)
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    boxes = [
        (0.50, 0.90, f"Source observations\nn = {result['n_source']}"),
        (0.50, 0.61, f"Eligible observations\nn = {result['n_eligible']}"),
        (0.23, 0.20, f"Final training set\nn = {outer['n_train']}"),
        (0.77, 0.20, f"Internal holdout\nn = {outer['n_validation']}"),
    ]
    for x, yy, label in boxes:
        ax.text(
            x,
            yy,
            label,
            ha="center",
            va="center",
            fontsize=10,
            bbox={
                "boxstyle": "round,pad=0.6",
                "facecolor": "white",
                "edgecolor": BLUE,
                "linewidth": 1,
            },
        )
    for start, end in [
        ((0.50, 0.80), (0.50, 0.71)),
        ((0.50, 0.51), (0.23, 0.30)),
        ((0.50, 0.51), (0.77, 0.30)),
    ]:
        ax.annotate(
            "", xy=end, xytext=start, arrowprops={"arrowstyle": "->", "color": GRAY, "linewidth": 1}
        )
    ax.text(
        0.79, 0.76, f"Missing/invalid outcome\nor split key: {excluded}", ha="center", va="center"
    )
    ax.text(
        0.22,
        0.43,
        f"Cross-boundary training\nobservations removed: {purged}",
        ha="center",
        va="center",
    )
    save(
        fig,
        "participants",
        "Observation eligibility and validation split.",
        f"Of {result['n_source']} source observations, {excluded} were excluded for missing/invalid outcomes or split keys. "
        f"The {spec['split']} split retained {outer['n_train']} training and {outer['n_validation']} validation observations; "
        f"{purged} training observations spanning a temporal subject boundary were removed. Counts refer to rows, not necessarily unique participants. "
        "Prespecified subject grouping prevents the same subject from appearing in both sets when a subject key is provided. Exclusion reasons and original row positions accompany the report.",
        "原始、排除、訓練與保留觀察列分開呈現；同人多列時，列數不等於受試者數。",
        [
            {"stage": label.replace("\n", " "), "n": count}
            for label, count in zip(
                ["source", "excluded", "eligible", "purged_training", "training", "holdout"],
                [result["n_source"], excluded, result["n_eligible"], purged, outer["n_train"], n],
                strict=True,
            )
        ],
    )

    candidates = [c for c in result["candidates"] if c["status"] == "completed"]
    criterion = result["selection"]["criterion"]
    fig, ax = new()
    points = []
    for i, candidate in enumerate(candidates):
        values = [f["metrics"][criterion] for f in candidate["folds"]]
        ys = i + np.linspace(-0.12, 0.12, len(values))
        ax.scatter(
            values,
            ys,
            marker="o",
            facecolors="white",
            edgecolors=BLUE,
            s=32,
            label="Training-fold score" if i == 0 else None,
        )
        ax.scatter(
            [candidate["cv_score"]],
            [i],
            marker="D",
            color=ORANGE,
            s=38,
            label="Mean across folds" if i == 0 else None,
            zorder=3,
        )
        points += [
            {
                "model": candidate["name"],
                "fold": f["split"],
                "score": f["metrics"][criterion],
                "mean": candidate["cv_score"],
                "selected": candidate["name"] == result["selection"]["selected"],
            }
            for f in candidate["folds"]
        ]
    labels = [
        model_labels[c["name"]]
        + ("\n(selected)" if c["name"] == result["selection"]["selected"] else "")
        for c in candidates
    ]
    ax.set(
        yticks=range(len(candidates)),
        yticklabels=labels,
        xlabel=f"Training-fold {criterion.upper()}",
        ylim=(-0.6, len(candidates) - 0.4),
    )
    if spec["task"] == "binary":
        ax.set_xlim(0, 1.03)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2)
    save(
        fig,
        "cv",
        "Prespecified model comparison within the training set.",
        f"Open circles show individual scores from {spec['cv_folds']} training folds; diamonds show the unweighted means. "
        f"Selection used {'maximum' if spec['task']=='binary' else 'minimum'} mean {criterion.upper()}, with ties resolved by the prespecified candidate order. "
        "Folds share training observations and are not independent replicates; their spread is not a confidence interval. "
        "Preprocessing was fitted separately in each training fold. The holdout did not contribute to selection. "
        f"Selected model: {selected}.",
        "圓點是各訓練折結果、菱形是平均值；各折不是獨立重複，散布不是信賴區間。保留集不參與選模。",
        points,
    )

    if spec["task"] == "binary":
        fig, ax = new(130)
        matrix = np.asarray([[scores["tn"], scores["fn"]], [scores["fp"], scores["tp"]]])
        abbreviations = [["TN", "FN"], ["FP", "TP"]]
        for (row, col), count in np.ndenumerate(matrix):
            color = plt.cm.Blues(0.08 + 0.8 * count / max(1, matrix.max()))
            ax.add_patch(
                Rectangle(
                    (col - 0.5, row - 0.5), 1, 1, facecolor=color, edgecolor="white", linewidth=1
                )
            )
            ax.text(
                col,
                row,
                f"{abbreviations[row][col]}\n{count}",
                ha="center",
                va="center",
                fontsize=12,
                color="white" if count > matrix.max() * 0.5 else "#202020",
            )
        ax.set(
            xticks=[0, 1],
            xticklabels=["Observed negative", "Observed positive"],
            yticks=[0, 1],
            yticklabels=["Predicted negative", "Predicted positive"],
            xlim=(-0.5, 1.5),
            ylim=(1.5, -0.5),
            aspect="equal",
        )
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        save(
            fig,
            "confusion",
            "Classification at the prespecified threshold.",
            common
            + f" Positive outcome code: {spec['positive_class']}; predicted positive requires a score ≥ {spec['threshold']}. "
            f"True positive (TP)={scores['tp']}, false positive (FP)={scores['fp']}, false negative (FN)={scores['fn']}, true negative (TN)={scores['tn']}. "
            f"Sensitivity={estimate('sensitivity')}; specificity={estimate('specificity')}. "
            + bootstrap,
            "以事先閾值分類，列為模型判定、欄為原始結果。原始診斷標籤不表示參照標準或盲判已獲驗證。",
            [
                {"predicted": row, "observed": col, "count": int(matrix[row, col])}
                for row in range(2)
                for col in range(2)
            ],
        )

        fig, ax = new(125)
        roc_data = []
        if len(np.unique(y)) == 2:
            fpr, tpr, thresholds = roc_curve(y, prediction, drop_intermediate=False)
            ax.plot(fpr, tpr, color=BLUE, label=f"AUROC {estimate('auroc')}")
            roc_data = [
                {
                    "false_positive_rate": float(x),
                    "sensitivity": float(yy),
                    "threshold": float(t) if np.isfinite(t) else "above_all_scores",
                }
                for x, yy, t in zip(fpr, tpr, thresholds, strict=True)
            ]
        else:
            ax.text(0.5, 0.5, "ROC not estimable: one outcome class", ha="center")
        ax.plot([0, 1], [0, 1], "--", color=GRAY, linewidth=1)
        ax.set(
            xlabel="False-positive rate (1 − specificity)",
            ylabel="Sensitivity",
            xlim=(0, 1),
            ylim=(0, 1.02),
        )
        ax.legend(loc="lower right", fontsize=8)
        save(
            fig,
            "roc",
            "Discrimination in the internal holdout.",
            common
            + f" The empirical receiver operating characteristic (ROC) curve gives sensitivity against the false-positive rate. "
            f"The dashed diagonal represents no discrimination. Area under the ROC curve (AUROC)={estimate('auroc')}. "
            "The interval refers to the scalar AUROC, not a confidence band for the curve. "
            + bootstrap,
            "ROC 表示區辨能力；AUC 的區間不是整條曲線的信賴帶，高 AUC 也不能證明校準或臨床效益。",
            roc_data,
        )

        fig, ax = new(125)
        pr_data = []
        if len(np.unique(y)) == 2:
            precision, recall, thresholds = precision_recall_curve(y, prediction)
            ax.step(
                recall,
                precision,
                where="post",
                color=BLUE,
                label=f"AP {estimate('average_precision')}",
            )
            pr_data = [
                {
                    "recall": float(r),
                    "precision": float(p),
                    "threshold": float(thresholds[i]) if i < len(thresholds) else "endpoint",
                }
                for i, (r, p) in enumerate(zip(recall, precision, strict=True))
            ]
        else:
            ax.text(0.5, 0.5, "PR not estimable: one outcome class", ha="center")
        ax.axhline(
            y.mean(),
            linestyle="--",
            color=GRAY,
            linewidth=1,
            label=f"Holdout positive fraction {y.mean():.3f}",
        )
        ax.set(
            xlabel="Recall (sensitivity)",
            ylabel="Precision (sample positive predictive value)",
            xlim=(0, 1),
            ylim=(0, 1.03),
        )
        ax.legend(loc="lower left", fontsize=8)
        save(
            fig,
            "pr",
            "Precision and recall in the internal holdout.",
            common
            + f" The step curve shows precision against recall; the dashed horizontal line is the observed positive fraction ({int(y.sum())}/{n}). "
            f"Average precision (AP)={estimate('average_precision')}; AP is not trapezoidal PR area. "
            + bootstrap,
            "精確率是本樣本的陽性預測值；虛線只代表本保留樣本的陽性比例，不能當成臨床母群盛行率。",
            pr_data,
        )

        fig, ax = new(125)
        bins = validation["calibration_bins"]
        ax.plot([0, 1], [0, 1], "--", color=GRAY, linewidth=1, label="Identity")
        ax.scatter(
            [b["mean_prediction"] for b in bins],
            [b["observed_fraction"] for b in bins],
            color=BLUE,
            s=30,
            label="Nonempty fixed-width bins",
        )
        for b in bins:
            right = b["mean_prediction"] > 0.85
            ax.annotate(
                f"n={b['n']}",
                (b["mean_prediction"], b["observed_fraction"]),
                xytext=(-5 if right else 5, 7),
                textcoords="offset points",
                ha="right" if right else "left",
                fontsize=8,
            )
        ax.set(
            xlabel="Mean predicted probability score",
            ylabel="Observed positive fraction",
            xlim=(-0.03, 1.03),
            ylim=(-0.03, 1.1),
        )
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2, fontsize=8)
        save(
            fig,
            "calibration",
            "Descriptive calibration within the sampled holdout.",
            common
            + " Scores were assigned to ten prespecified equal-width bins ([0,0.1), …, [0.9,1]). "
            "Points show each nonempty bin's mean score and observed positive fraction; labels give its observation count. "
            "The dashed line is identity. No curve, recalibration model or binwise confidence interval was fitted. "
            "Sparse bins can be unstable; no line interpolates them. Sample calibration does not establish calibration in another population.",
            "每點是固定分箱的平均分數與陽性比例，標示實際人數。沒有重校準、分箱信賴區間或擬合連線；少量個案的點不能當成穩定校準證據。",
            bins,
        )

        curve = validation["decision_curve"]
        if curve:
            fig, ax = new(125)
            points = curve["points"]
            thresholds = np.asarray([r["threshold"] for r in points])
            ax.plot(
                thresholds,
                [r["model"] for r in points],
                "o-",
                color=BLUE,
                label="Model-guided action",
            )
            ax.plot(
                thresholds,
                [r["treat_all"] for r in points],
                "D--",
                color=ORANGE,
                label="Act on all",
            )
            ax.axhline(0, color=GRAY, linestyle=":", label="Act on none")
            for r in points:
                interval = r["intervals"]["model"]
                if interval["lower"] is not None:
                    ax.vlines(
                        r["threshold"],
                        interval["lower"],
                        interval["upper"],
                        color=BLUE,
                        linewidth=0.9,
                    )
                    ax.plot(
                        [r["threshold"]] * 2,
                        [interval["lower"], interval["upper"]],
                        "_",
                        color=BLUE,
                        markersize=6,
                    )
            ax.set(
                xlabel="Prespecified threshold probability", ylabel="Net benefit per observation"
            )
            ax.legend(loc="best", fontsize=8)
            data = [
                {
                    **{k: v for k, v in r.items() if k != "intervals"},
                    **{
                        f"{k}_{bound}": v[bound]
                        for k, v in r["intervals"].items()
                        for bound in ["lower", "upper"]
                    },
                }
                for r in points
            ]
            save(
                fig,
                "decision_curve",
                "Net benefit at prespecified decision thresholds.",
                common
                + " At threshold t, model-guided action is taken when the score ≥ t. Net benefit = TP/n − FP/n × t/(1−t). "
                "Circles denote the model strategy, diamonds action for all, and the dotted line action for none. "
                f"Vertical bars are {ci} pointwise model-net-benefit intervals, not a simultaneous band. Lines join evaluated thresholds only; no threshold was optimized. "
                "Model-minus-all intervals in the accompanying table use paired bootstrap differences. Extra test costs are not modeled. "
                + bootstrap,
                "只比較事先指定行動與閾值；直線區間是固定模型各點的不確定性，不是同時信賴帶，也不證明採用模型能改善病人結局。",
                data,
            )
    else:
        fig, ax = new(125)
        ax.scatter(y, prediction, s=15, alpha=0.7, color=BLUE, edgecolors="none")
        low, high = min(y.min(), prediction.min()), max(y.max(), prediction.max())
        ax.plot([low, high], [low, high], "--", color=GRAY, linewidth=1)
        ax.set(
            xlabel="Observed outcome (original scale)", ylabel="Predicted outcome (original scale)"
        )
        save(
            fig,
            "observed",
            "Observed and predicted outcomes in the internal holdout.",
            common
            + f" Each point is one holdout observation; the dashed line is identity. RMSE={estimate('rmse')}; MAE={estimate('mae')}. "
            + bootstrap,
            "每點為保留觀察列；誤差沿用原始結果尺度，不猜測未提供的單位。",
            validation["predictions"],
        )
        fig, ax = new(125)
        ax.scatter(prediction, y - prediction, s=15, alpha=0.7, color=BLUE, edgecolors="none")
        ax.axhline(0, color=GRAY, linestyle="--", linewidth=1)
        ax.set(
            xlabel="Predicted outcome (original scale)", ylabel="Residual (observed − predicted)"
        )
        save(
            fig,
            "residual",
            "Residuals in the internal holdout.",
            common
            + " Residuals equal observed minus predicted outcomes. The dashed line denotes zero. This descriptive plot does not certify model assumptions or estimate a trend.",
            "殘差為實際值減預測值；檢查誤差型態，不把此描述圖視為模型假設已成立。",
            [{**r, "residual": r["observed"] - r["prediction"]} for r in validation["predictions"]],
        )
    return records
