"""Local plot font discovery, including an explicitly configured CJK font."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import matplotlib
from matplotlib import font_manager


def configure_plot_fonts() -> dict:
    """Configure an installed font or a pinned local file; never download at render time."""
    configured = os.environ.get("RDE_PLOT_FONT")
    explicit_name = None
    receipt = {}
    if configured:
        path = Path(configured).expanduser().resolve(strict=True)
        # Register directly: matplotlib's persistent system-font cache may predate installation.
        font_manager.fontManager.addfont(str(path))
        explicit_name = font_manager.FontProperties(fname=str(path)).get_name()
        receipt = {
            "configured_font": path.name,
            "configured_font_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    available = {font.name for font in font_manager.fontManager.ttflist}
    preferred = [
        explicit_name,
        "Microsoft JhengHei",
        "Microsoft YaHei",
        "Noto Sans CJK TC",
        "Noto Sans CJK SC",
        "PingFang TC",
        "PingFang SC",
    ]
    selected = [name for name in preferred if name and name in available]
    if selected:
        existing = list(matplotlib.rcParams.get("font.sans-serif", []))
        matplotlib.rcParams["font.family"] = ["sans-serif"]
        matplotlib.rcParams["font.sans-serif"] = list(dict.fromkeys(selected + existing))
        matplotlib.rcParams["axes.unicode_minus"] = False
    return {**receipt, "sans_serif": list(matplotlib.rcParams["font.sans-serif"])}
