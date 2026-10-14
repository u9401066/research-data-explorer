"""Fixed descriptive graphics over saved summaries, without fitting or inference."""

from pathlib import Path
import os
import re
import tempfile

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure


def descriptive_figures(result, directory: Path, receipt_sha256: str, units=None):
    """Plot only declared-column summaries; identifiers never receive value plots."""
    if not isinstance(receipt_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", receipt_sha256):
        raise ValueError("A full numerical receipt SHA256 is required")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    units = units or {}
    records = []
    columns = [(f"V{i + 1}", row) for i, row in enumerate(result["columns"])]
    prefix = f"descriptive_{receipt_sha256[:20]}"
    directory.mkdir(parents=True, exist_ok=True)
    with publication_style() as profile:

        def save(fig, kind, page, title, caption, explanation, selected, data):
            mapping = "; ".join(f"{code} = {row['column']!r}" for code, row in selected)
            stem = f"{prefix}_{kind}_{page}"
            targets = [
                directory / f"{stem}.{suffix}"
                for suffix in ("png", "pdf", "svg", "tif", "caption.md", "plot-data.csv")
            ]

            def check_targets():
                for target in targets:
                    if target.is_symlink() or (
                        target.exists() and (not target.is_file() or target.stat().st_nlink != 1)
                    ):
                        plt.close(fig)
                        raise ValueError(
                            "Descriptive figure target must be a single-link regular file"
                        )

            check_targets()
            # Render new bytes in a private stage; never follow a preexisting target link.
            with tempfile.TemporaryDirectory(prefix=".descriptive-", dir=directory) as temporary:
                publication = save_publication_figure(
                    fig,
                    Path(temporary),
                    stem,
                    number=len(records) + 1,
                    title=title,
                    caption=caption + " Column mapping: " + mapping + ".",
                    explanation=explanation,
                    data=data,
                    profile=profile,
                    receipt_sha256=receipt_sha256,
                )
                check_targets()
                files = {}
                for key, value in publication["files"].items():
                    target = directory / Path(value).name
                    os.replace(value, target)
                    files[key] = str(target)
                publication["files"] = files
            records.append(
                dict(
                    path=publication["files"]["png"],
                    plot_type=f"descriptive_{kind}",
                    variables=[row["column"] for _, row in selected],
                    caption=publication["caption_en"] + "\n\n中文解釋：" + explanation,
                    publication=publication,
                )
            )

        for start in range(0, len(columns), 16):
            selected = columns[start : start + 16]
            fig, ax = plt.subplots(figsize=(180 / 25.4, max(100, 40 + 7 * len(selected)) / 25.4))
            positions = list(range(len(selected)))
            observed = [row["observed"] for _, row in selected]
            missing = [row["missing"] for _, row in selected]
            ax.barh(positions, observed, color="#0072B2", label="Observed")
            ax.barh(positions, missing, left=observed, color="#D55E00", label="Missing")
            ax.set_yticks(positions, [code for code, _ in selected])
            ax.invert_yaxis()
            ax.set_xlabel("Source rows (not necessarily independent people)")
            ax.set_xlim(0, max(1, result["input_rows"]) * 1.02)
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.set_title("Observed and missing values by column", pad=32)
            ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
            save(
                fig,
                "availability",
                start // 16 + 1,
                "Observed and missing values by column.",
                f"Each bar covers the same {result['input_rows']} input rows. Observed values include nonfinite numeric entries where present; those are excluded from finite-value summaries. Missing values are not imputed or reclassified as negative. Equal missing counts need not represent the same rows. No independence, clinical missingness mechanism or complete export coverage is established.",
                "每欄以全部輸入列為分母，區分有值與缺失，不補值、不把未觀測當成陰性；相同缺失數不表示相同資料列，也不證明病人獨立或資料完整涵蓋。",
                selected,
                [
                    dict(
                        code=code,
                        column=row["column"],
                        rows=row["rows"],
                        observed=row["observed"],
                        missing=row["missing"],
                    )
                    for code, row in selected
                ],
            )

        numeric = [(code, row) for code, row in columns if row["kind"] == "numeric"]
        for start in range(0, len(numeric), 4):
            selected = numeric[start : start + 4]
            fig, axes = plt.subplots(
                len(selected),
                1,
                squeeze=False,
                figsize=(180 / 25.4, max(90, 55 * len(selected)) / 25.4),
            )
            data = []
            for ax, (code, row) in zip(axes[:, 0], selected):
                summary = row["summary"]
                unit = units.get(row["column"])
                ax.set_title(f"{code}: finite n = {row['finite']}; missing = {row['missing']}")
                ax.set_yticks([])
                ax.set_xlabel(
                    f"Source scale ({unit})"
                    if unit and unit.isascii() and len(unit) <= 24
                    else "Source scale (see caption for units)"
                )
                if row["finite"]:
                    ax.hlines(0, summary["min"], summary["max"], color="#656565", linewidth=1.2)
                    ax.hlines(0, summary["q1"], summary["q3"], color="#0072B2", linewidth=8)
                    ax.plot(summary["median"], 0, marker="o", color="#D55E00", markersize=5)
                    ax.plot(
                        [summary["min"], summary["max"]],
                        [0, 0],
                        linestyle="none",
                        marker="|",
                        color="#656565",
                        markersize=10,
                    )
                    ax.set_ylim(-1, 1)
                else:
                    ax.text(
                        0.5, 0.5, "No finite observed values", transform=ax.transAxes, ha="center"
                    )
                    ax.set_xticks([])
                data.append(
                    dict(
                        code=code,
                        column=row["column"],
                        unit=unit or "not declared to the plot",
                        finite=row["finite"],
                        missing=row["missing"],
                        nonfinite=row["nonfinite"],
                        **summary,
                    )
                )
            unit_note = "; ".join(
                f"{code}: {units.get(row['column']) or 'unit not declared to the plot'}"
                for code, row in selected
            )
            save(
                fig,
                "quantiles",
                start // 4 + 1,
                "Finite observed values: range and quartiles.",
                "Thin lines and end caps show the observed minimum and maximum, thick blue segments the first to third quartiles, and orange dots the median. These are range-and-quartile summaries, not Tukey whiskers, outlier decisions or confidence intervals. Each panel has its own original numeric scale and finite-value denominator; no scaling, imputation or row removal was applied to the analysis dataset. Numeric codes do not establish clinical events. Units: "
                + unit_note
                + ".",
                "細線為最小至最大值，粗線為第一至第三四分位數，圓點為中位數；不是離群值判定或信賴區間。各圖保留自己的原始尺度及有限數值分母，識別欄位不繪製數值分布。",
                selected,
                data,
            )
    return records
