"""Journal-neutral vector/raster exports with captions, plot data and provenance."""

from __future__ import annotations

from contextlib import contextmanager
import csv
import hashlib
from pathlib import Path


@contextmanager
def publication_style():
    import matplotlib as mpl
    from matplotlib import font_manager

    settings = {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.labelsize": 10,
        "axes.titlesize": 11,
        "axes.linewidth": 0.7,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "legend.fontsize": 9,
        "legend.frameon": False,
        "lines.linewidth": 1.5,
        "lines.markersize": 5,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "path",
        "svg.hashsalt": "rde-publication-english-v1",
    }
    with mpl.rc_context(settings):
        font = Path(font_manager.findfont("DejaVu Sans", fallback_to_default=False))
        yield {
            "profile": "journal-neutral-english-v1",
            "font_family": "DejaVu Sans",
            "font_sha256": hashlib.sha256(font.read_bytes()).hexdigest(),
            "matplotlib": mpl.__version__,
            "language": "en",
            "raster_dpi": 300,
            "pdf_fonts": "embedded TrueType",
            "svg_fonts": "outlined paths",
            "journal_specific_compliance": "not assessed; apply the target journal's requirements",
        }


def save_publication_figure(
    fig,
    directory: Path,
    stem: str,
    *,
    number: int,
    title: str,
    caption: str,
    explanation: str,
    data: list[dict],
    profile: dict,
    receipt_sha256: str,
) -> dict:
    """Save actual plotted geometry, never upsample an existing low-resolution image."""
    import matplotlib.pyplot as plt
    from matplotlib.text import Text
    from PIL import Image

    directory.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=1.2)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas = fig.bbox
    overflow = []
    undrawn = set()
    for ax in fig.axes:
        for axis, limits in [(ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())]:
            for tick in [*axis.get_major_ticks(), *axis.get_minor_ticks()]:
                if not ax.axison or not min(limits) <= tick.get_loc() <= max(limits):
                    undrawn.update([tick.label1, tick.label2])
        if not ax.axison:
            undrawn.update(
                [ax.xaxis.label, ax.yaxis.label, ax.xaxis.offsetText, ax.yaxis.offsetText]
            )
    for artist in fig.findobj(match=Text):
        if artist in undrawn or not artist.get_visible() or not artist.get_text().strip():
            continue
        bounds = artist.get_window_extent(renderer)
        if (
            bounds.width
            and bounds.height
            and (
                bounds.x0 < canvas.x0 - 1
                or bounds.x1 > canvas.x1 + 1
                or bounds.y0 < canvas.y0 - 1
                or bounds.y1 > canvas.y1 + 1
            )
        ):
            overflow.append(artist.get_text())
    if overflow:
        plt.close(fig)
        raise ValueError(f"Publication text extends beyond the canvas: {overflow}")
    paths = {
        key: directory / f"{stem}.{ext}"
        for key, ext in [
            ("png", "png"),
            ("pdf", "pdf"),
            ("svg", "svg"),
            ("tiff", "tif"),
            ("caption", "caption.md"),
            ("data", "plot-data.csv"),
        ]
    }
    try:
        fig.savefig(paths["png"], dpi=300)
        fig.savefig(paths["pdf"], metadata={"Title": title, "CreationDate": None, "ModDate": None})
        fig.savefig(paths["svg"], metadata={"Title": title, "Date": None})
        with Image.open(paths["png"]) as raster:
            raster.convert("RGB").save(paths["tiff"], compression="tiff_lzw", dpi=(300, 300))
        legend = f"Fig {number}. {title}\n\n{caption}"
        paths["caption"].write_text(
            f"# {legend}\n\n中文解釋：{explanation}\n\n"
            f"Source numerical receipt SHA256: `{receipt_sha256}`.\n"
            "The caption belongs in the manuscript; figure numbering follows this analysis bundle. "
            "Match final numbering and typography to the target journal.\n",
            encoding="utf-8",
        )
        with paths["data"].open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(
                file, fieldnames=list(dict.fromkeys(key for row in data for key in row))
            )
            writer.writeheader()
            writer.writerows(data)
        width, height = fig.get_size_inches()
        return {
            **profile,
            "dimensions_mm": [round(width * 25.4, 2), round(height * 25.4, 2)],
            "text_outside_canvas": overflow,
            "source_receipt_sha256": receipt_sha256,
            "caption_en": legend,
            "explanation_zh": explanation,
            "files": {key: str(path) for key, path in paths.items()},
        }
    finally:
        plt.close(fig)
