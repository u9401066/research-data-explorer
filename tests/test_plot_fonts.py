"""Chinese plot labels must use a configured local font, including a fresh font cache."""

import hashlib
import os
from pathlib import Path
import shutil
import warnings

import matplotlib
import pytest

from rde.infrastructure.visualization.fonts import configure_plot_fonts


def test_explicit_missing_font_fails_instead_of_silently_substituting_boxes(monkeypatch, tmp_path):
    monkeypatch.setenv("RDE_PLOT_FONT", str(tmp_path / "missing.otf"))
    with pytest.raises(FileNotFoundError):
        configure_plot_fonts()


def test_explicit_font_is_registered_even_when_not_in_the_system_cache(monkeypatch, tmp_path):
    from matplotlib import font_manager

    path = tmp_path / "private-font.ttf"
    shutil.copyfile(font_manager.findfont("DejaVu Sans"), path)
    monkeypatch.setattr(
        font_manager.fontManager,
        "ttflist",
        [font for font in font_manager.fontManager.ttflist if font.name != "DejaVu Sans"],
    )
    assert "DejaVu Sans" not in {font.name for font in font_manager.fontManager.ttflist}
    monkeypatch.setenv("RDE_PLOT_FONT", str(path))
    with matplotlib.rc_context():
        result = configure_plot_fonts()
        assert (
            result["configured_font_sha256"] == hashlib.sha256(Path(path).read_bytes()).hexdigest()
        )
        assert result["sans_serif"][0] == "DejaVu Sans"
        assert matplotlib.rcParams["font.family"] == ["sans-serif"]
        assert any(font.fname == str(path) for font in font_manager.fontManager.ttflist)


@pytest.mark.skipif(
    not os.environ.get("RDE_CJK_TEST_FONT"), reason="Optional local CJK font fixture"
)
def test_chinese_survival_labels_render_without_missing_glyphs(monkeypatch, tmp_path):
    import pandas as pd
    from rde.infrastructure.clinical.survival import SurvivalSpec, run_survival
    from rde.infrastructure.clinical.report import figures

    monkeypatch.setenv("RDE_PLOT_FONT", os.environ["RDE_CJK_TEST_FONT"])
    data = pd.DataFrame(
        {
            "時間": [1, 2, 3, 4, 5, 6],
            "結果": ["死亡", "設限"] * 3,
            "組別": ["對照"] * 3 + ["治療"] * 3,
        }
    )
    spec = SurvivalSpec.parse(
        {
            "time": "時間",
            "event": "結果",
            "event_value": "死亡",
            "censor_value": "設限",
            "time_origin": "研究開始時",
            "time_unit": "天",
            "independent_rows": True,
            "group": "組別",
            "risk_times": [0, 2, 4],
        }
    )
    with matplotlib.rc_context(), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        records = figures(run_survival(data, spec), tmp_path, "chinese")
    assert len(records) == 2
    assert not any("Glyph" in str(w.message) and "missing" in str(w.message) for w in caught)
    for record in records:
        assert Path(record["path"]).stat().st_size > 1000
        assert record["fonts"]["configured_font_sha256"]
