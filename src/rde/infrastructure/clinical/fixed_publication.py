"""Small publication scaffolding for frozen clinical receipts; no estimation."""

import json
from pathlib import Path

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure


def render(result, directory, prefix, family, draw, preset_id, edition, source_context=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with publication_style(preset_id) as profile:
        if edition:
            profile["edition"] = edition
        records = []

        def new(height=85, rows=1):
            fig, axes = plt.subplots(
                rows,
                1,
                squeeze=False,
                figsize=(180 / 25.4, height * 180 / profile["width_mm"] / 25.4),
            )
            return fig, axes[:, 0]

        def save(fig, key, title, caption, explanation, data):
            publication = save_publication_figure(
                fig,
                Path(directory),
                f"{prefix}_{family}_{key}",
                number=len(records) + 1,
                title=title,
                caption=caption,
                explanation=explanation,
                data=data,
                profile=profile,
                receipt_sha256=result["receipt_sha256"],
                required_caption=caption,
            )
            # User-authored source definitions are evidence, not an English
            # translation. Retain them separately from the submission caption.
            context = {
                key: result["spec"][key]
                for key in [
                    "context",
                    "population_definition",
                    "treatment_definition",
                    "outcome_definition",
                    "outcome_window",
                    "outcome_unit",
                    "margin_basis",
                    "missingness_basis",
                    "imputation_scope",
                ]
                if key in result["spec"]
            }
            context.update(source_context or {})
            publication["source_context"] = context
            with Path(publication["files"]["caption"]).open("a", encoding="utf-8") as stream:
                stream.write(
                    "\n## 研究原文情境／Source context (original language)\n\n"
                    "以下保留原始研究定義與代碼；不屬於英文圖說，也未自動翻譯或驗證。\n\n```json\n"
                    + json.dumps(context, ensure_ascii=False, indent=2)
                    + "\n```\n"
                )
            records.append(
                {
                    "path": publication["files"]["png"],
                    "plot_type": f"clinical_{family}_{key}",
                    "caption": publication["caption_en"]
                    + "\n\n中文解釋："
                    + publication["explanation_zh"],
                    "fonts": {
                        "family": profile["font_family"],
                        "font_sha256": profile["font_sha256"],
                    },
                    "publication": publication,
                }
            )

        draw(new, save)
        return records


def flow_table(ax, rows):
    ax.axis("off")
    table = ax.table(
        cellText=[[row["stage"], row["subjects"]] for row in rows],
        colLabels=["Population step", "Subjects"],
        colWidths=[0.76, 0.24],
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2)
    for (row, _), item in table.get_celld().items():
        item.set_edgecolor("#c4cbd0")
        if row == 0:
            item.set_facecolor("#eef3f6")


def blocks(rows, size):
    return [
        (str(start // size + 1), rows[start : start + size]) for start in range(0, len(rows), size)
    ]
