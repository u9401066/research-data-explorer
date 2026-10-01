"""Versioned journal figure specifications; explicit fonts, never silent substitution."""

from copy import deepcopy
import hashlib
import os
from pathlib import Path

DEFAULT_PRESET = "journal-neutral-english-v1"
PLOS_SOURCE = "https://journals.plos.org/plosone/s/figures"
NATURE_SOURCE = "https://www.nature.com/nature/for-authors/final-submission"
NATURE_GUIDE = "https://www.nature.com/documents/Final_guide_to_authors.pdf"
CHECKED = "2026-10-01"


def _journal(name, width, *, nature):
    return dict(
        name=name,
        width_mm=width,
        max_height_mm=170 if nature else 222.3,
        font_family="Arial",
        font_size=6.5 if nature else 9,
        font_min=5 if nature else 8,
        font_max=7 if nature else 12,
        line_min=0.25 if nature else 0.5,
        line_max=1.0 if nature else 1.5,
        raster_dpi=300 if nature else 600,
        svg_fonts="editable text" if nature else "outlined paths",
        submission_format="pdf" if nature else "tiff",
        max_file_bytes=None if nature else 10_000_000,
        sources=[NATURE_SOURCE, NATURE_GUIDE] if nature else [PLOS_SOURCE],
        source_checked=CHECKED,
        scope="Nature main print figures" if nature else "PLOS One main article figures",
        note=(
            "PDF keeps embedded, editable text. SVG is an editable companion; raster files are previews. "
            "170 mm height leaves room for a legend; not the full page depth."
            if nature
            else "Submit the RGB LZW TIFF. PDF/SVG are companions. Put captions in the manuscript."
        ),
    )


PRESETS = {
    DEFAULT_PRESET: dict(
        name="一般期刊 · 180 mm",
        width_mm=180,
        max_height_mm=250,
        font_family="DejaVu Sans",
        font_size=9,
        font_min=8,
        font_max=12,
        line_min=0.5,
        line_max=1.5,
        raster_dpi=300,
        svg_fonts="outlined paths",
        submission_format="pdf",
        max_file_bytes=None,
        sources=[],
        source_checked=CHECKED,
        scope="Journal-neutral",
        note="Apply the target journal's requirements before submission.",
    ),
    "nature-single-v1": _journal("Nature · 單欄 89 mm", 89, nature=True),
    "nature-double-v1": _journal("Nature · 雙欄 183 mm", 183, nature=True),
    "plos-column-v1": _journal("PLOS One · 文字欄 132 mm", 132, nature=False),
    "plos-full-v1": _journal("PLOS One · 全寬 190.5 mm", 190.5, nature=False),
}


def resolve_preset(preset_id=DEFAULT_PRESET):
    from matplotlib import font_manager

    if preset_id not in PRESETS:
        raise ValueError(f"Unknown publication preset: {preset_id}")
    spec = deepcopy(PRESETS[preset_id])
    directory = os.environ.get("RDE_PUBLICATION_FONT_DIR")
    if directory:
        root = Path(directory)
        if not root.is_dir():
            raise ValueError("RDE_PUBLICATION_FONT_DIR must be an existing font directory.")
        for path in sorted(root.iterdir()):
            if path.is_file() and path.suffix.lower() in {".ttf", ".otf"}:
                font_manager.fontManager.addfont(str(path))
    try:
        font = Path(font_manager.findfont(spec["font_family"], fallback_to_default=False))
    except ValueError as error:
        raise ValueError(
            f"Preset requires {spec['font_family']}. Configure an authorized local font in "
            "RDE_PUBLICATION_FONT_DIR; this preset does not substitute a different font."
        ) from error
    if font_manager.FontProperties(fname=str(font)).get_name() != spec["font_family"]:
        raise ValueError("Resolved font family differs from the publication preset.")
    return {
        **spec,
        "profile": preset_id,
        "font_sha256": hashlib.sha256(font.read_bytes()).hexdigest(),
    }


def list_presets():
    values = []
    for key, spec in PRESETS.items():
        try:
            resolved = resolve_preset(key)
            values.append({**resolved, "available": True, "unavailable_reason": None})
        except ValueError as error:
            values.append(
                {
                    **deepcopy(spec),
                    "profile": key,
                    "available": False,
                    "unavailable_reason": str(error),
                }
            )
    return values


def apply_preset(fig, profile):
    """Re-layout original vector artists at the final physical dimensions."""
    from matplotlib import font_manager
    from matplotlib.collections import PathCollection
    from matplotlib.ft2font import FT2Font
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.text import Text
    import textwrap

    if profile["profile"] == DEFAULT_PRESET:
        return
    width, height = fig.get_size_inches() * 25.4
    target = profile["width_mm"]
    fig.set_size_inches(
        target / 25.4, min(profile["max_height_mm"], height * target / width) / 25.4
    )
    scale = profile["font_size"] / 9
    fig.canvas.draw()
    font = font_manager.findfont(profile["font_family"], fallback_to_default=False)
    glyphs = FT2Font(font).get_charmap()
    missing = set()
    for artist in fig.findobj():
        if isinstance(artist, Text):
            artist.set_fontfamily(profile["font_family"])
            artist.set_fontsize(
                max(profile["font_min"], min(profile["font_max"], artist.get_fontsize() * scale))
            )
            if artist.get_visible():
                missing.update(
                    c for c in artist.get_text() if not c.isspace() and ord(c) not in glyphs
                )
        elif isinstance(artist, (Line2D, Patch)):
            weight = artist.get_linewidth()
            if weight:
                artist.set_linewidth(
                    max(profile["line_min"], min(profile["line_max"], weight * scale))
                )
            if isinstance(artist, Line2D):
                artist.set_markersize(artist.get_markersize() * scale)
        elif isinstance(artist, PathCollection):
            artist.set_sizes(artist.get_sizes() * scale**2)
    if missing:
        raise ValueError(
            f"Preset font has no glyphs for {sorted(missing)!r}; provide English display labels or a suitable preset."
        )
    for ax in fig.axes:
        ax.tick_params(axis="both", labelsize=profile["font_size"])
    if target < 100:
        for ax in fig.axes:
            for artist in [ax.xaxis.label, ax.yaxis.label]:
                artist.set_text(
                    "\n".join(
                        textwrap.fill(
                            line, width=38, break_long_words=False, break_on_hyphens=False
                        )
                        for line in artist.get_text().splitlines()
                    )
                )
