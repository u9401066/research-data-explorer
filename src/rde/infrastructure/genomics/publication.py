"""Publication figures from frozen DESeq2 values; no inference or model loading."""

import math
from pathlib import Path

import numpy as np

from rde.infrastructure.prediction.splits import digest
from rde.infrastructure.visualization.publication import publication_style, save_publication_figure
from .contract import require, validate_result

PAGE = 20
COLORS = {"Numerator": "#216f9b", "Reference": "#ab5926", "Other condition": "#727272"}


def figures(result, directory: Path, prefix, preset_id="journal-neutral-english-v1", edition=None):
    import matplotlib

    matplotlib.use("Agg")
    require(
        digest({k: v for k, v in result.items() if k != "receipt_sha256"})
        == result["receipt_sha256"],
        "numerical receipt changed before rendering",
    )
    validate_result(result["analysis"])
    with publication_style(preset_id) as profile:
        if edition:
            profile["edition"] = edition
        return _figures(result, directory, prefix, profile)


def _figures(result, directory, prefix, profile):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    a, records = result["analysis"], []
    o, summary = a["options"], a["summary"]
    samples = a["samples"]
    codes = {s["sample_id"]: f"S{i + 1:03}" for i, s in enumerate(samples)}
    context = (
        f"Bulk RNA-seq: organism={o['organism']!r}, reference={o['referenceVersion']!r}, "
        f"gene namespace={o['geneNamespace']!r}. Numerator={o['numerator']!r}; reference={o['reference']!r}. "
        f"Design={a['design']['formula']!r}; {summary['samples']} samples and {summary['inputGenes']} input genes. "
        f"DESeq2 {a['package']['DESeq2']}, R {a['package']['R']}. "
        "Sample codes refer to the original count-column order; exact sample IDs and conditions are retained in plot data. "
    )
    if o["organism"] == "synthetic":
        context += "Synthetic engineering fixture; these are not biological observations. "
    inference = (
        f"Unshrunken maximum-likelihood log2 fold change, numerator/reference. "
        f"Wald test of |log2 fold change| > {o['lfcThreshold']:g}, BH adjusted p < {o['alpha']:g}. "
        "Significance uses this prespecified null; the effect-size lines are not an additional post hoc filter. "
        "Missing adjusted p values are unavailable, not zero. Statistical significance does not establish biological importance. "
    )
    saved = "These figures use saved numerical results; no refitting, reclustering or new hypothesis tests are performed."

    def emit(fig, key, title, caption, explanation, data):
        number = len(records) + 1
        publication = save_publication_figure(
            fig,
            directory,
            f"{prefix}_genomics_{key}",
            number=number,
            title=title,
            caption=context + caption + " " + saved,
            explanation=explanation,
            data=data,
            profile=profile,
            receipt_sha256=result["receipt_sha256"],
        )
        records.append(
            {
                "path": publication["files"]["png"],
                "plot_type": f"genomics_{key}",
                "publication": publication,
            }
        )

    def new(height=4.8):
        return plt.subplots(figsize=(180 / 25.4, height))

    def empty(ax, message):
        ax.axis("off")
        ax.text(0.5, 0.5, message, transform=ax.transAxes, ha="center", va="center", wrap=True)

    def category(condition):
        return (
            "Numerator"
            if condition == o["numerator"]
            else "Reference"
            if condition == o["reference"]
            else "Other condition"
        )

    flow = [
        ("All zero", "allZero"),
        ("Low count", "lowCount"),
        ("Cook's outlier", "cooksOutlier"),
        ("Not estimable", "notEstimable"),
        ("Independent filtered", "independentFiltered"),
        ("Tested (BH available)", "tested"),
    ]
    fig, ax = new(3.8)
    values = [summary[k] for _, k in flow]
    ax.barh(range(len(flow)), values, color="#477c90")
    ax.set_yticks(range(len(flow)), [label for label, _ in flow])
    ax.invert_yaxis()
    ax.set_xlim(0, max(values) * 1.3 or 1)
    ax.set_xlabel("Genes")
    ax.xaxis.set_major_locator(MaxNLocator(4, integer=True))
    for i, value in enumerate(values):
        ax.annotate(str(value), (value, i), xytext=(4, 0), textcoords="offset points", va="center")
    emit(
        fig,
        "flow",
        "Gene inclusion and estimability",
        (
            f"Mutually exclusive outcomes for every input gene. Count filter: at least {o['minCount']} counts "
            f"in at least {o['minSamples']} samples. Independent filtering={o['independentFiltering']}. "
            "Cook's filtering follows the saved DESeq2 replicate pattern; automatic count replacement was disabled."
        ),
        "每個輸入基因都保留在結果表。圖中區分篩除與無法估計；缺失的 p 值不能解讀為零或顯著。",
        [{"record": "gene", **g} for g in a["genes"]],
    )

    for start in range(0, len(samples), PAGE):
        subset = samples[start : start + PAGE]
        fig, axes = plt.subplots(
            1, 2, figsize=(180 / 25.4, max(3.2, len(subset) * 0.21 + 1.4)), sharey=True
        )
        for index, (ax, key, label) in enumerate(
            zip(
                axes,
                ["total_counts", "detected_genes"],
                ["Total counts", "Detected genes"],
                strict=True,
            )
        ):
            values = [s[key] for s in subset]
            ax.scatter(
                values,
                range(len(subset)),
                c=[COLORS[category(s["condition"])] for s in subset],
                s=22,
            )
            ax.set_yticks(range(len(subset)), [codes[s["sample_id"]] for s in subset])
            ax.set_xlabel(label)
            upper = max(s[key] for s in samples) or 1
            ax.set_xlim(-upper * 0.04, upper * 1.12)
            ax.xaxis.set_major_locator(MaxNLocator(3, integer=True))
            if max(values) >= 100_000:
                ax.ticklabel_format(axis="x", style="sci", scilimits=(0, 0))
            ax.grid(axis="y", alpha=0.15)
            if index == 0:
                ax.invert_yaxis()
        emit(
            fig,
            f"sample_qc_{start // PAGE + 1}",
            "Library size and detected genes",
            (
                f"Samples {start + 1}–{start + len(subset)} of {len(samples)}; each point is one sample. "
                "Counts are original totals, not normalized values. Blue=numerator; orange=reference; grey=other conditions. "
                "A detected gene has at least one raw count; no sample is excluded by these displays."
            ),
            "圖中逐一列出原始 library counts 與有讀數的基因數；以固定樣本代碼對照原始名稱，不因圖形外觀刪除樣本。",
            [{"sample_code": codes[s["sample_id"]], **s} for s in subset],
        )

    fig, ax = new()
    pca_rows = [{"sample_code": codes[r["sample_id"]], **r} for r in a["pca_coordinates"]]
    if a["pca"]["status"] == "completed":
        for cat, color in COLORS.items():
            subset = [r for r in pca_rows if category(r["condition"]) == cat]
            if subset:
                ax.scatter(
                    [r["PC1"] for r in subset],
                    [r["PC2"] for r in subset],
                    color=color,
                    marker={"Numerator": "o", "Reference": "s", "Other condition": "^"}[cat],
                    s=24,
                    label=cat,
                    alpha=0.8,
                )
        ax.legend(loc="best", markerscale=0.8)
        ax.set_xlabel(f"PC1 ({a['pca']['PC1'] * 100:.1f}%)")
        ax.set_ylabel(f"PC2 ({a['pca']['PC2'] * 100:.1f}%)")
        ax.xaxis.set_major_locator(MaxNLocator(4))
        ax.yaxis.set_major_locator(MaxNLocator(4))
        pca_caption = (
            f"Each point is one sample; {len(a['pca']['genes'])} saved high-variance genes. "
        )
    else:
        empty(ax, "PCA not estimable\nSee the preserved reason in the caption")
        pca_rows = [{"status": a["pca"]["status"], "reason": a["pca"]["reason"]}]
        pca_caption = f"PCA unavailable: {a['pca']['reason']}. "
    emit(
        fig,
        "pca",
        "Sample principal components",
        pca_caption
        + (
            "Saved DESeq2 variance-stabilizing transformation with blind=FALSE; centered PCA without scaling. "
            "Percentages are saved explained-variance fractions. Batch effects have not been removed. "
            "Colors group additional conditions as 'Other condition'; exact condition labels remain in the CSV."
        ),
        "PCA 使用分析時保存的座標與解釋變異，不重新估計；批次差異仍可能存在，分群不能單獨證明處理效果。",
        pca_rows,
    )

    fig, ax = new(5.3)
    matrix = np.asarray([r["values"] for r in a["sample_distances"]])
    im = ax.imshow(
        matrix, cmap="Blues", vmin=0, vmax=float(matrix.max()) or 1, interpolation="nearest"
    )
    ticks = np.unique(np.linspace(0, len(samples) - 1, min(len(samples), 8), dtype=int))
    ax.set_xticks(ticks, [codes[samples[i]["sample_id"]] for i in ticks], rotation=90)
    ax.set_yticks(ticks, [codes[samples[i]["sample_id"]] for i in ticks])
    ax.set_xlabel("Samples in original count-column order")
    ax.set_ylabel("Samples in original count-column order")
    fig.colorbar(im, ax=ax, label="Euclidean distance", shrink=0.8)
    emit(
        fig,
        "distances",
        "Sample distances after variance stabilization",
        (
            "Saved Euclidean distances using all retained VST genes; original sample order, no clustering. "
            "All matrix cells are drawn; at most eight ticks per axis are labeled for legibility. "
            "The CSV contains every sample pair, including zero diagonal entries."
        ),
        "樣本距離保留原始樣本順序，沒有重新分群。圖上簡化刻度標籤，但完整矩陣及原始樣本名称均可下載。",
        [
            {
                "sample_x_code": codes[samples[j]["sample_id"]],
                "sample_x_id": samples[j]["sample_id"],
                "sample_y_code": codes[samples[i]["sample_id"]],
                "sample_y_id": samples[i]["sample_id"],
                "distance": value,
            }
            for i, row in enumerate(matrix)
            for j, value in enumerate(row.tolist())
        ],
    )

    for kind in ("ma", "volcano"):
        fig, ax = new()
        plot_rows = []
        for g in a["genes"]:
            valid = g["log2FoldChange"] is not None and (kind == "ma" or g["padj"] is not None)
            row = {**g, "plotted": valid, "x": None, "y": None, "display_capped": False}
            if valid:
                row["x"] = math.log10(g["baseMean"] + 1) if kind == "ma" else g["log2FoldChange"]
                row["y"] = (
                    g["log2FoldChange"] if kind == "ma" else -math.log10(max(g["padj"], 1e-300))
                )
                row["display_capped"] = kind == "volcano" and g["padj"] < 1e-300
            plot_rows.append(row)
        for selected, color, label in [
            (
                False,
                "#8a8a8a",
                "Not selected / unavailable" if kind == "ma" else "Not selected by BH",
            ),
            (True, "#a93d43", "Selected by BH"),
        ]:
            subset = [g for g in plot_rows if g["plotted"] and g["significant"] == selected]
            if subset:
                ax.scatter(
                    [g["x"] for g in subset],
                    [g["y"] for g in subset],
                    s=7,
                    alpha=0.65,
                    linewidths=0,
                    color=color,
                    label=label,
                )
        if any(g["plotted"] for g in plot_rows):
            ax.legend(loc="best", markerscale=1.4)
            ax.set_xlabel(
                "log10(normalized mean + 1)" if kind == "ma" else "Unshrunken log2 fold change"
            )
            ax.set_ylabel(
                "Unshrunken log2 fold change" if kind == "ma" else "-log10(BH adjusted p)"
            )
            ax.axhline(
                0 if kind == "ma" else -math.log10(o["alpha"]), ls="--", color="#333333", lw=0.8
            )
            if kind == "volcano" and o["lfcThreshold"] > 0:
                for x in (-o["lfcThreshold"], o["lfcThreshold"]):
                    ax.axvline(x, ls=":", color="#333333", lw=0.8)
            ax.xaxis.set_major_locator(MaxNLocator(4))
            ax.yaxis.set_major_locator(MaxNLocator(4))
        else:
            empty(ax, "No estimable values for this display")
        emit(
            fig,
            kind,
            "Mean expression and fold change"
            if kind == "ma"
            else "Differential expression and adjusted significance",
            inference
            + (
                "All finite fold changes are drawn; grey includes genes with unavailable adjusted p. "
                if kind == "ma"
                else "Only finite fold changes with finite adjusted p are drawn; missing values are not plotted. "
                "For display only, adjusted p below 1e-300 (including numerical zero) is capped at height 300. "
            )
            + f"{sum(g['plotted'] for g in plot_rows)} plotted genes; all input rows and exclusion states remain in the CSV.",
            "圖中保留未收縮的效果量，顏色由核准的 BH 門檻決定。無法估計不等於沒有差異；火山圖的極小 p 僅在顯示時設上限，原值不變。",
            plot_rows,
        )

    fig, ax = new()
    dispersion_rows = []
    for row in a["dispersion"]:
        dispersion_rows.append(
            {
                **row,
                **{
                    f"{k}_plotted": row["baseMean"] > 0 and row[k] is not None and row[k] > 0
                    for k in ("geneWise", "fitted", "final")
                },
            }
        )
    for key, color, label, marker in [
        ("geneWise", "#999999", "Gene-wise", "."),
        ("final", "#246e9a", "Final", "."),
    ]:
        selected = [d for d in dispersion_rows if d[f"{key}_plotted"]]
        if selected:
            ax.scatter(
                [d["baseMean"] for d in selected],
                [d[key] for d in selected],
                color=color,
                s=8,
                alpha=0.5,
                marker=marker,
                label=label,
            )
    fitted = sorted(
        [d for d in dispersion_rows if d["fitted_plotted"]], key=lambda d: d["baseMean"]
    )
    if fitted:
        ax.plot(
            [d["baseMean"] for d in fitted],
            [d["fitted"] for d in fitted],
            color="#a54235",
            label="Fitted trend",
            lw=1,
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Mean normalized counts")
    ax.set_ylabel("Dispersion")
    ax.legend(loc="best", markerscale=1.4)
    emit(
        fig,
        "dispersion",
        "Gene-wise, fitted and final dispersions",
        (
            f"Saved gene-wise estimates, fitted trend and final DESeq2 dispersions. Requested fit={o['fitType']!r}; "
            f"actual fit={a['method']['fitActual']!r}. Trend coordinates are connected in mean-count order, without refitting. "
            "Only positive finite values can appear on logarithmic axes; all retained genes and explicit plot flags are in the CSV."
        ),
        "離散度圖取自當次 DESeq2 模型的原始、趨勢與最終估計；變更期刊樣式不重新擬合趨勢。",
        dispersion_rows,
    )

    if "geneSets" in o:
        sets = a["gene_sets"]
        eligible = [(i, s) for i, s in enumerate(sets) if s["status"] == "tested"]
        ora_max = max(
            [-math.log10(o["alpha"]), *[-math.log10(max(s["padj"], 1e-300)) for _, s in eligible]]
        )
        pages = [eligible[i : i + PAGE] for i in range(0, len(eligible), PAGE)] or [[]]
        for page, rows in enumerate(pages, 1):
            fig, ax = new(max(3.2, len(rows) * 0.21 + 1.4))
            if rows:
                x = [-math.log10(max(s["padj"], 1e-300)) for _, s in rows]
                ax.scatter(
                    x,
                    range(len(rows)),
                    s=24,
                    color=["#a93d43" if s["padj"] < o["alpha"] else "#777777" for _, s in rows],
                )
                ax.set_yticks(range(len(rows)), [f"GS{i + 1:04}" for i, _ in rows])
                ax.invert_yaxis()
                ax.set_xlabel("-log10(BH adjusted p)")
                ax.set_xlim(-ora_max * 0.04, ora_max * 1.08 or 1)
                ax.axvline(-math.log10(o["alpha"]), ls="--", color="#333333", lw=0.8)
                ax.xaxis.set_major_locator(MaxNLocator(4))
            else:
                empty(ax, "No size-eligible gene sets\nNo enrichment significance is available")
            displayed = {i for i, _ in rows}
            emit(
                fig,
                f"ora_{page}",
                "Over-representation of prespecified gene sets",
                (
                    f"Page {page}/{len(pages)}; eligible sets in original input order, without significance-based selection. "
                    f"Set source={o['geneSets']['source']!r}; version={o['geneSets']['version']!r}. "
                    f"Direction={o['geneSets']['direction']}; universe={a['enrichment']['universeSize']} genes with finite gene-level adjusted p; "
                    f"selected={a['enrichment']['selected']}. Right-tail hypergeometric test; BH over all {a['enrichment']['tested']} size-eligible sets. "
                    "The line marks the prespecified BH threshold; display heights are capped at 300. "
                    "Every set and exclusion state is retained in the CSV. No gene-length correction; enrichment does not establish pathway activity or causation."
                ),
                "基因集合使用事先指定的來源、版本、方向與實際背景，集合層級另外做 BH 校正。圖中包含所有符合大小條件的集合，不只挑顯著者。",
                [
                    {
                        "set_code": f"GS{i + 1:04}",
                        **s,
                        "plotted_on_page": i in displayed,
                        "display_height": -math.log10(max(s["padj"], 1e-300))
                        if i in displayed
                        else None,
                        "display_capped": i in displayed and s["padj"] < 1e-300,
                    }
                    for i, s in enumerate(sets)
                ],
            )
    return records
