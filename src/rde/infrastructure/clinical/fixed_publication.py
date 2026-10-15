"""Small publication scaffolding for frozen clinical receipts; no estimation."""

from pathlib import Path

from rde.infrastructure.visualization.publication import publication_style, save_publication_figure


def render(result, directory, prefix, family, draw, preset_id, edition):
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
