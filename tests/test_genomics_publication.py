"""Real saved R output and damaged-evidence edges, not simulated DESeq2 estimates."""

from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

from rde.infrastructure.genomics.contract import publication_result, validate_result
from rde.infrastructure.genomics.publication import figures
from rde.infrastructure.visualization.presets import PRESETS, resolve_preset

FIXTURE = Path(__file__).parent / "fixtures" / "genomics-publication"


def saved_result():
    source = (FIXTURE / "publication-data.json").read_bytes()
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    assert hashlib.sha256(source).hexdigest() == manifest["file_sha256"]
    return publication_result(json.loads(source), manifest)


@pytest.mark.parametrize("preset", list(PRESETS))
def test_saved_deseq2_journal_figures_preserve_every_gene_sample_and_set(tmp_path, preset):
    try:
        profile = resolve_preset(preset)
    except ValueError as error:
        pytest.skip(str(error))
    result = saved_result()
    before = deepcopy(result)
    outputs = figures(result, tmp_path, "qa", preset_id=preset)
    assert len(outputs) == 8
    assert result == before
    a = result["analysis"]
    for figure in outputs:
        p = figure["publication"]
        assert p["text_outside_canvas"] == []
        assert p["source_receipt_sha256"] == result["receipt_sha256"]
        assert p["dimensions_mm"][0] == pytest.approx(profile["width_mm"], abs=0.01)
        assert p["dimensions_mm"][1] <= profile["max_height_mm"]
        assert set(p["files"]) == {"png", "pdf", "svg", "tiff", "caption", "data"}
        for path in p["files"].values():
            assert Path(path).stat().st_size > 0
        with Image.open(p["files"]["png"]) as im:
            assert im.info["dpi"][0] == pytest.approx(profile["raster_dpi"], abs=0.01)
        with Image.open(p["files"]["tiff"]) as im:
            assert im.mode == "RGB" and im.info["compression"] == "tiff_lzw"
        data = list(csv.DictReader(Path(p["files"]["data"]).open()))
        kind = figure["plot_type"]
        if kind in {"genomics_flow", "genomics_ma", "genomics_volcano"}:
            assert [g["gene_id"] for g in data] == [g["gene_id"] for g in a["genes"]]
            for row, gene in zip(data, a["genes"], strict=True):
                assert row["status"] == gene["status"]
                assert row["padj"] == ("" if gene["padj"] is None else str(gene["padj"]))
                assert row["log2FoldChange"] == (
                    "" if gene["log2FoldChange"] is None else str(gene["log2FoldChange"])
                )
            if kind == "genomics_volcano":
                assert sum(r["plotted"] == "True" for r in data) == 600
                assert data[-1]["plotted"] == "False"  # Cook's outlier never becomes p=0.
        if kind == "genomics_distances":
            assert len(data) == len(a["samples"]) ** 2
            for row in data:
                i, j = int(row["sample_y_code"][1:]) - 1, int(row["sample_x_code"][1:]) - 1
                assert float(row["distance"]) == a["sample_distances"][i]["values"][j]
                assert row["sample_x_id"] == a["samples"][j]["sample_id"]
        if kind == "genomics_pca":
            assert [r["sample_id"] for r in data] == a["design"]["sampleOrder"]
            assert [float(r["PC1"]) for r in data] == [r["PC1"] for r in a["pca_coordinates"]]
        if kind == "genomics_dispersion":
            assert [float(r["fitted"]) for r in data] == [r["fitted"] for r in a["dispersion"]]
        if kind == "genomics_ora_1":
            assert [r["set_id"] for r in data] == [r["set_id"] for r in a["gene_sets"]]
            assert any(
                r["status"] == "below_min_size" and r["plotted_on_page"] == "False" for r in data
            )


@pytest.mark.parametrize(
    "edge",
    [
        "direction",
        "missing_p",
        "selected",
        "sample_order",
        "distance",
        "dispersion",
        "pca_gene",
        "pca_group",
        "universe",
        "unrequested",
    ],
)
def test_inconsistent_display_evidence_is_rejected_before_creating_files(tmp_path, edge):
    a = saved_result()["analysis"]
    if edge == "direction":
        a["options"]["numerator"] = "different condition"
    elif edge == "missing_p":
        a["genes"][-1]["pvalue"] = 0
    elif edge == "selected":
        a["genes"][0]["significant"] = not a["genes"][0]["significant"]
    elif edge == "sample_order":
        a["samples"].reverse()
    elif edge == "distance":
        a["sample_distances"][0]["values"][1] += 1
    elif edge == "dispersion":
        a["dispersion"][0]["final"] *= 2
    elif edge == "pca_gene":
        a["pca"]["genes"][0] = "excluded-gene"
    elif edge == "pca_group":
        a["pca_coordinates"][0]["condition"] = "treated"
    elif edge == "universe":
        a["enrichment"]["universeSize"] += 1
    else:
        del a["options"]["geneSets"]
    with pytest.raises(ValueError):
        publication_result(a, {"scope": "damaged QA"})
    assert list(tmp_path.iterdir()) == []


def test_receipt_change_is_rejected_and_caption_edits_leave_original_values(tmp_path):
    result = saved_result()
    result["analysis"]["options"]["organism"] = "a different organism"
    with pytest.raises(ValueError, match="changed before rendering"):
        figures(result, tmp_path, "bad")
    assert list(tmp_path.iterdir()) == []
    result = saved_result()
    outputs = figures(
        result,
        tmp_path,
        "edited",
        edition={
            "start_number": 11,
            "captions": {
                "1": {
                    "title": "Reviewed synthetic gene flow",
                    "caption_en": "Synthetic software QA only.",
                }
            },
        },
    )
    assert outputs[0]["publication"]["figure_number"] == 11
    assert "Synthetic software QA only." in outputs[0]["publication"]["caption_en"]
    assert "Mutually exclusive" in outputs[0]["publication"]["original_caption"]["caption_en"]
    assert outputs[-1]["publication"]["figure_number"] == 18


def test_unavailable_pca_no_sets_and_numerical_zero_have_explicit_display_states(tmp_path):
    a = saved_result()["analysis"]
    a["pca"] = {"status": "not_estimable", "reason": "Fewer than two variable transformed genes"}
    a["pca_coordinates"] = []
    del a["options"]["geneSets"]
    a["enrichment"] = {"status": "not_requested"}
    a["gene_sets"] = []
    gene = next(g for g in a["genes"] if g["significant"])
    gene["pvalue"] = gene["padj"] = 0
    result = publication_result(a, {"scope": "Synthetic display edge, not a refitted model"})
    outputs = figures(result, tmp_path, "edge")
    assert len(outputs) == 7
    volcano = next(f for f in outputs if f["plot_type"] == "genomics_volcano")
    rows = list(csv.DictReader(Path(volcano["publication"]["files"]["data"]).open()))
    plotted = next(g for g in rows if g["gene_id"] == gene["gene_id"])
    assert float(plotted["y"]) == 300 and plotted["display_capped"] == "True"
    assert plotted["padj"] == "0"
    validate_result(a)


def test_narrow_column_pages_keep_long_source_names_and_every_eligible_set(tmp_path, monkeypatch):
    """Synthetic display stress only; duplication here is never treated as new inference."""
    try:
        resolve_preset("nature-single-v1")
    except ValueError as error:
        pytest.skip(str(error))
    from rde.infrastructure.genomics import publication

    save = publication.save_publication_figure
    qc_limits, ora_limits = [], []

    def checked_save(fig, *args, **kwargs):
        if kwargs["title"] == "Library size and detected genes":
            qc_limits.append([ax.get_xlim() for ax in fig.axes])
        elif kwargs["title"] == "Over-representation of prespecified gene sets":
            ora_limits.append(fig.axes[0].get_xlim())
        if kwargs["title"] in {
            "Library size and detected genes",
            "Over-representation of prespecified gene sets",
        }:
            for ax in fig.axes:
                for collection in ax.collections:
                    if len(collection.get_offsets()):
                        assert min(collection.get_offsets()[:, 0]) > ax.get_xlim()[0]
                        assert max(collection.get_offsets()[:, 0]) < ax.get_xlim()[1]
        return save(fig, *args, **kwargs)

    monkeypatch.setattr(publication, "save_publication_figure", checked_save)
    a = saved_result()["analysis"]
    originals = deepcopy(a)
    for i in range(12, 24):
        sample = deepcopy(originals["samples"][i % 12])
        sample["sample_id"] = f"第 {i + 1} 號樣本 " + "long-original-name-" * 8
        a["samples"].append(sample)
        coordinate = deepcopy(originals["pca_coordinates"][i % 12])
        coordinate["sample_id"] = sample["sample_id"]
        a["pca_coordinates"].append(coordinate)
    a["design"]["sampleOrder"] = [s["sample_id"] for s in a["samples"]]
    a["design"]["n"] = a["summary"]["samples"] = 24
    a["design"]["residualDf"] = 24 - a["design"]["rank"]
    a["sample_distances"] = [
        {
            "sample_id": s["sample_id"],
            "values": [originals["sample_distances"][i % 12]["values"][j % 12] for j in range(24)],
        }
        for i, s in enumerate(a["samples"])
    ]
    template = next(s for s in a["gene_sets"] if s["status"] == "tested")
    for i in range(42):
        row = deepcopy(template)
        row["set_id"] = f"集合 {i + 1} " + "long source name " * 9
        a["gene_sets"].append(row)
    a["enrichment"]["sets"] = len(a["gene_sets"])
    a["enrichment"]["tested"] = sum(s["status"] == "tested" for s in a["gene_sets"])
    a["enrichment"]["significant"] = sum(
        s["padj"] is not None and s["padj"] < a["options"]["alpha"] for s in a["gene_sets"]
    )
    result = publication_result(
        a, {"scope": "Synthetic display stress; duplicated geometry is not new biological evidence"}
    )
    outputs = figures(result, tmp_path, "paged", preset_id="nature-single-v1")
    seen_samples, seen_sets = [], []
    for figure in outputs:
        rows = list(csv.DictReader(Path(figure["publication"]["files"]["data"]).open()))
        if figure["plot_type"].startswith("genomics_sample_qc_"):
            assert len(rows) <= 20
            seen_samples.extend(r["sample_id"] for r in rows)
        if figure["plot_type"].startswith("genomics_ora_"):
            shown = [r["set_id"] for r in rows if r["plotted_on_page"] == "True"]
            assert len(shown) <= 20
            seen_sets.extend(shown)
    assert seen_samples == [s["sample_id"] for s in a["samples"]]
    assert seen_sets == [s["set_id"] for s in a["gene_sets"] if s["status"] == "tested"]
    assert len(qc_limits) == 2 and qc_limits[0] == qc_limits[1]
    assert len(ora_limits) == 3 and ora_limits[0] == ora_limits[1] == ora_limits[2]
