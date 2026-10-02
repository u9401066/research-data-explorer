from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

from rde.infrastructure.evidence.contract import publication_result, validate_result
from rde.infrastructure.evidence.publication import figures
from rde.infrastructure.visualization.presets import PRESETS, resolve_preset


FIXTURE = Path(__file__).parent / "fixtures" / "evidence-publication"


def saved_result():
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == expected
    analysis = json.loads((FIXTURE / "network-v2.json").read_text())
    payload = json.loads((FIXTURE / "network-input.json").read_text())
    assert analysis["options"] == payload["options"]
    assert analysis["review"]["inputHash"] == payload["review"]["inputHash"]
    for before, after in zip(payload["rows"], analysis["observations"], strict=True):
        assert all(after[k] == v for k, v in before.items())
    return publication_result(analysis, manifest)


@pytest.mark.parametrize("preset", list(PRESETS))
def test_actual_evidence_journal_exports_preserve_all_original_rows_and_estimates(
    tmp_path, preset, monkeypatch
):
    from rde.infrastructure.evidence import publication

    save = publication.save_publication_figure

    def checked_save(fig, *args, **kwargs):
        result = save(fig, *args, **kwargs)
        for ax in fig.axes:
            if not ax.axison:
                continue
            renderer = fig.canvas.get_renderer()
            labels = [
                t.label1
                for t in ax.xaxis.get_major_ticks()
                if min(ax.get_xlim()) <= t.get_loc() <= max(ax.get_xlim())
            ]
            bounds = [label.get_window_extent(renderer) for label in labels if label.get_text()]
            bounds.sort(key=lambda b: b.x0)
            assert all(
                a.x1 < b.x0 for a, b in zip(bounds, bounds[1:])
            ), "Overlapping x-axis tick labels"
        return result

    monkeypatch.setattr(publication, "save_publication_figure", checked_save)
    try:
        profile = resolve_preset(preset)
    except ValueError as error:
        pytest.skip(str(error))
    result = saved_result()
    before = deepcopy(result)
    rendered = figures(result, tmp_path, "saved", preset_id=preset)
    assert len(rendered) == 9
    assert result == before
    rows_seen = []
    for figure in rendered:
        p = figure["publication"]
        assert p["text_outside_canvas"] == []
        assert p["source_receipt_sha256"] == result["receipt_sha256"]
        assert p["dimensions_mm"][0] == pytest.approx(profile["width_mm"], abs=0.01)
        assert p["dimensions_mm"][1] <= profile["max_height_mm"]
        assert set(p["files"]) == {"png", "pdf", "svg", "tiff", "caption", "data"}
        for name in p["files"].values():
            assert Path(name).stat().st_size > 0
        with Image.open(p["files"]["png"]) as image:
            assert image.info["dpi"][0] == pytest.approx(profile["raster_dpi"], abs=0.01)
        with Image.open(p["files"]["tiff"]) as image:
            assert image.mode == "RGB"
            assert image.info["compression"] == "tiff_lzw"
        data = list(csv.DictReader(Path(p["files"]["data"]).open()))
        if figure["plot_type"].startswith("evidence_direct_"):
            for row in data:
                if row["record"] != "study":
                    continue
                original = next(
                    v for v in result["analysis"]["observations"] if v["row"] == int(row["row"])
                )
                rows_seen.append(int(row["row"]))
                assert row["source_treatment"] == original["treatment"]
                assert float(row["source_effect"]) == original["effect"]
                assert row["source_locator"] == original["locator"]
                saved = next(
                    v
                    for v in result["analysis"]["direct_observations"]
                    if v["row"] == int(row["row"])
                )
                assert float(row["estimate"]) == saved["estimate"]
                assert float(row["lower"]) == saved["lower"]
                assert float(row["weight_percent"]) == saved["weight_percent"]
        if figure["plot_type"] == "evidence_inconsistency_1":
            assert "not an OR" in p["caption_en"]
            for v in data:
                assert float(v["estimate"]) == float(v["effect"])
        if figure["plot_type"] == "evidence_flow":
            assert len(data) == result["analysis"]["review"]["inputRows"]
            assert "not a PRISMA" in p["caption_en"]
    assert sorted(rows_seen) == sorted(v["row"] for v in result["analysis"]["observations"])


@pytest.mark.parametrize(
    "problem",
    ["source", "weight", "direction", "split", "unavailable", "node", "decision", "multiarm"],
)
def test_receipt_refuses_changed_membership_direction_and_unavailable_diagnostics(problem):
    r = saved_result()["analysis"]
    if problem == "source":
        r["observations"][0]["source"] = "synthetic://different"
    elif problem == "weight":
        r["direct_observations"][0]["weight_percent"] += 1
    elif problem == "direction":
        r["direct_observations"][0]["source_direction_reversed"] = False
    elif problem == "split":
        row = next(v for v in r["diagnostics"]["local"]["rows"] if v["component"] == "compare")
        row["estimate"] = 1  # A log-ratio difference is not back-transformed into a ratio.
    elif problem == "unavailable":
        r["diagnostics"]["local"]["rows"][0]["status"] = "not_estimable"
    elif problem == "node":
        r["topology"]["nodes"][0]["studies"] += 1
    elif problem == "decision":
        r["review"]["decisions"].pop()
    elif problem == "multiarm":
        r["observations"][1]["risk_of_bias"] = "high"
    with pytest.raises(ValueError):
        validate_result(r)


def test_changed_numerical_receipt_cannot_render_even_if_individual_fields_are_valid(tmp_path):
    result = saved_result()
    result["analysis"]["options"]["outcome"] = "a different endpoint"
    with pytest.raises(ValueError, match="changed before rendering"):
        figures(result, tmp_path, "tampered")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["tree-v2", "paged-pairwise", "dense-network"])
def test_actual_md_receipts_keep_missing_diagnostics_dense_cells_and_paged_studies(tmp_path, name):
    root = FIXTURE / name
    manifest = json.loads((root / "manifest.json").read_text())
    for file, expected in manifest["files"].items():
        assert hashlib.sha256((root / file).read_bytes()).hexdigest() == expected
    analysis = json.loads((root / "numeric-result.json").read_text())
    result = publication_result(analysis, manifest)
    try:
        resolve_preset("nature-single-v1")
        preset = "nature-single-v1"
    except ValueError:
        preset = "journal-neutral-english-v1"
    rendered = figures(result, tmp_path, name, preset_id=preset)
    rows_seen, cells, unavailable = [], [], []
    for figure in rendered:
        data = list(csv.DictReader(Path(figure["publication"]["files"]["data"]).open()))
        assert figure["publication"]["text_outside_canvas"] == []
        if figure["plot_type"].startswith("evidence_direct_"):
            rows_seen.extend(int(v["row"]) for v in data if v["record"] == "study")
        if figure["plot_type"].startswith("evidence_network_"):
            cells.extend(data)
        if figure["plot_type"].startswith("evidence_inconsistency_"):
            unavailable.extend(v for v in data if v["status"] == "not_estimable")
    assert sorted(rows_seen) == sorted(v["row"] for v in analysis["observations"])
    if name == "paged-pairwise":
        assert len(rows_seen) == 20
        direct = [v for v in rendered if v["plot_type"].startswith("evidence_direct_")]
        assert len(direct) == 2
        for figure in direct:
            data = list(csv.DictReader(Path(figure["publication"]["files"]["data"]).open()))
            pooled = next(v for v in data if v["record"] == "pooled_all_studies_in_pair")
            assert int(pooled["studies"]) == 20
            assert float(pooled["effect"]) == analysis["pairwise"][0]["effect"]
        assert analysis["reference"][0]["effect"] < 0
    elif name == "dense-network":
        assert len(cells) == 9 * 9
        assert len({(v["treatment_code"], v["comparator_code"]) for v in cells}) == len(cells)
        assert sum(v["studies"] == "" for v in cells) == 9
    else:
        assert len(unavailable) == 3
        assert all(
            v["estimate"] == "" and v["lower"] == "" and v["upper"] == "" for v in unavailable
        )
