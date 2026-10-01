import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.visualization.presets import DEFAULT_PRESET, list_presets, resolve_preset
from rde.interface.mcp.server import create_server


def call(name, args, *, json_result=True):
    response = asyncio.run(create_server().call_tool(name, args))
    assert not response.is_error, response.content
    return json.loads(response.content[0].text) if json_result else response.content[0].text


def completed(tmp_path, family):
    if family.startswith("prediction"):
        from test_prediction_validation import decision_options, prediction_project
        from rde.interface.mcp.tools.prediction_tools import persisted_predictions

        options = (
            {"decision_curve": decision_options()}
            if family == "prediction_dca"
            else {"task": "regression", "target": "continuous"}
            if family == "prediction_regression"
            else {}
        )
        project, store, dataset, spec = prediction_project(tmp_path, **options)
        call(
            "run_prediction_study",
            {"dataset_id": dataset.id, "prediction_options": spec.to_dict()},
            json_result=False,
        )
        record = persisted_predictions(store)[0]
    elif family.startswith("survival"):
        from test_clinical_survival import clinical_project
        from rde.interface.mcp.tools.clinical_tools import clinical_records

        project, store, dataset, spec = clinical_project(
            tmp_path, competing=family == "survival_competing"
        )
        call(
            "run_clinical_study",
            {"dataset_id": dataset.id, "clinical_options": spec.to_dict()},
            json_result=False,
        )
        record = clinical_records(store)[0]
    elif family.startswith("longitudinal"):
        from test_longitudinal_workflow import longitudinal_project
        from rde.interface.mcp.tools.clinical_tools import clinical_records

        project, store, dataset, spec = longitudinal_project(tmp_path, family)
        call(
            "run_clinical_study",
            {"dataset_id": dataset.id, "clinical_options": spec.to_dict()},
            json_result=False,
        )
        record = clinical_records(store)[0]
    else:
        from test_clinical_measurement import measurement_project
        from rde.interface.mcp.tools.clinical_tools import clinical_records

        project, store, dataset, spec = measurement_project(tmp_path, family)
        call(
            "run_clinical_study",
            {"dataset_id": dataset.id, "clinical_options": spec.to_dict()},
            json_result=False,
        )
        record = clinical_records(store)[0]
    source = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    args = dict(
        project_id=project.id,
        study_artifact=source.name,
        expected_record_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        preset_id=DEFAULT_PRESET,
        edition_id=str(uuid.uuid4()),
        start_number=7,
    )
    return project, source, record, args


@pytest.mark.parametrize(
    "family",
    [
        "diagnostic_accuracy",
        "bland_altman",
        "cohens_kappa",
        "prediction",
        "survival",
        "survival_competing",
        "longitudinal_gaussian",
        "longitudinal_binomial",
    ],
)
def test_mcp_creates_immutable_edition_without_refitting_or_changing_originals(
    tmp_path, monkeypatch, family
):
    project, source, record, args = completed(tmp_path, family)
    frozen = {
        str(source): source.read_bytes(),
        **{
            str(project.output_dir / a["path"]): (project.output_dir / a["path"]).read_bytes()
            for a in record["artifacts"]
        },
    }
    from rde.interface.mcp.tools import clinical_tools
    from rde.infrastructure.prediction import engine

    from rde.infrastructure.clinical import survival

    monkeypatch.setattr(survival, "run_survival", lambda *a, **kw: pytest.fail("Refitted survival"))

    monkeypatch.setattr(
        clinical_tools, "run_measurement", lambda *a, **kw: pytest.fail("Re-estimated measurements")
    )
    monkeypatch.setattr(
        engine, "run_prediction", lambda *a, **kw: pytest.fail("Refitted predictions")
    )
    args["captions"] = {
        "1": {"title": "Study participants.", "explanation_zh": "研究者核對後的中文解釋。"}
    }
    edition = call("render_publication_figures", args)
    assert edition["source_numerical_receipt_sha256"] == record["result"]["receipt_sha256"]
    assert len(edition["figures"]) == len(record["figures"])
    first = edition["figures"][0]["publication"]
    assert first["figure_number"] == 7 and first["caption_edited"]
    assert first["caption_en"].startswith("Fig 7. Study participants.")
    assert first["original_caption"]["title"] != "Study participants."
    assert "研究者核對後的中文解釋。" in edition["figures"][0]["caption"]
    assert Path(first["files"]["tiff"]).name == "Fig7.tif"
    for item in edition["artifacts"]:
        assert (
            hashlib.sha256((project.output_dir / item["path"]).read_bytes()).hexdigest()
            == item["sha256"]
        )
    again = call("render_publication_figures", args)
    assert again == edition
    for path, data in frozen.items():
        assert Path(path).read_bytes() == data
    conflict = asyncio.run(
        create_server().call_tool("render_publication_figures", {**args, "start_number": 8})
    )
    assert conflict.is_error and "already belongs" in conflict.content[0].text
    assert all(Path(path).read_bytes() == data for path, data in frozen.items())


def test_edition_rejects_changed_source_and_exports_and_cleans_failed_render(tmp_path, monkeypatch):
    project, source, record, args = completed(tmp_path, "cohens_kappa")
    editions = project.output_dir / "figures" / "editions"
    denied = asyncio.run(
        create_server().call_tool(
            "render_publication_figures", {**args, "expected_record_sha256": "0" * 64}
        )
    )
    assert denied.is_error and not editions.exists()
    from rde.infrastructure.clinical import measurement_publication

    original = measurement_publication.figures

    def broken(result, directory, *a, **kw):
        (directory / "partial.png").write_bytes(b"partial")
        raise ValueError("Simulated renderer failure")

    monkeypatch.setattr(measurement_publication, "figures", broken)
    denied = asyncio.run(create_server().call_tool("render_publication_figures", args))
    assert denied.is_error and "Simulated renderer" in denied.content[0].text
    assert list(editions.iterdir()) == []
    monkeypatch.setattr(measurement_publication, "figures", original)
    edition = call("render_publication_figures", args)
    image = Path(edition["figures"][0]["path"])
    image.write_bytes(b"changed")
    denied = asyncio.run(create_server().call_tool("render_publication_figures", args))
    assert denied.is_error and "integrity verification" in denied.content[0].text
    assert image.read_bytes() == b"changed"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == args["expected_record_sha256"]


def test_catalog_reports_missing_font_without_substitution(monkeypatch):
    from matplotlib import font_manager

    monkeypatch.delenv("RDE_PUBLICATION_FONT_DIR", raising=False)
    real = font_manager.findfont

    def missing(prop, **kwargs):
        if prop == "Arial":
            raise ValueError("Arial absent")
        return real(prop, **kwargs)

    monkeypatch.setattr(font_manager, "findfont", missing)
    catalog = {p["profile"]: p for p in list_presets()}
    assert catalog[DEFAULT_PRESET]["available"]
    assert not catalog["nature-single-v1"]["available"]
    assert "does not substitute" in catalog["plos-column-v1"]["unavailable_reason"]


def test_edition_receipt_corruption_does_not_bypass_artifact_verification(tmp_path):
    project, source, record, args = completed(tmp_path, "cohens_kappa")
    edition = call("render_publication_figures", args)
    path = project.output_dir / edition["receipt_path"]
    edition["artifacts"] = []
    path.write_text(json.dumps(edition))
    denied = asyncio.run(create_server().call_tool("render_publication_figures", args))
    assert denied.is_error and "integrity verification" in denied.content[0].text
    assert json.loads(path.read_text())["artifacts"] == []


@pytest.mark.skipif(not os.environ.get("RDE_JOURNAL_TEST_FONT_DIR"), reason="Local Arial required")
def test_plos_title_length_rejects_oversized_title_without_partial_edition(tmp_path, monkeypatch):
    monkeypatch.setenv("RDE_PUBLICATION_FONT_DIR", os.environ["RDE_JOURNAL_TEST_FONT_DIR"])
    project, source, record, args = completed(tmp_path, "cohens_kappa")
    denied = asyncio.run(
        create_server().call_tool(
            "render_publication_figures",
            {
                **args,
                "preset_id": "plos-column-v1",
                "captions": {"1": {"title": "word " * 16}},
            },
        )
    )
    assert denied.is_error and "15 words" in denied.content[0].text
    assert not list((project.output_dir / "figures" / "editions").iterdir())


@pytest.mark.skipif(
    not os.environ.get("RDE_JOURNAL_TEST_FONT_DIR"),
    reason="An authorized local Arial fixture is required",
)
@pytest.mark.parametrize(
    "preset", ["nature-single-v1", "nature-double-v1", "plos-column-v1", "plos-full-v1"]
)
@pytest.mark.parametrize(
    "family",
    [
        "diagnostic_accuracy",
        "bland_altman",
        "cohens_kappa",
        "prediction",
        "prediction_dca",
        "prediction_regression",
        "survival",
        "survival_competing",
        "longitudinal_gaussian",
        "longitudinal_binomial",
    ],
)
def test_actual_journal_exports_keep_exact_data_and_meet_format_dimensions(
    tmp_path, monkeypatch, preset, family
):
    monkeypatch.setenv("RDE_PUBLICATION_FONT_DIR", os.environ["RDE_JOURNAL_TEST_FONT_DIR"])
    project, source, record, args = completed(tmp_path, family)
    profile = resolve_preset(preset)
    edition = call("render_publication_figures", {**args, "preset_id": preset})
    for old, new in zip(record["figures"], edition["figures"], strict=True):
        publication = new["publication"]
        assert (
            Path(old["publication"]["files"]["data"]).read_bytes()
            == Path(publication["files"]["data"]).read_bytes()
        )
        assert publication["source_receipt_sha256"] == record["result"]["receipt_sha256"]
        assert publication["dimensions_mm"][0] == profile["width_mm"]
        assert publication["text_outside_canvas"] == []
        with Image.open(publication["files"]["tiff"]) as raster:
            assert raster.mode == "RGB" and raster.n_frames == 1
            assert raster.info["dpi"] == (profile["raster_dpi"],) * 2
            assert abs(raster.width - profile["width_mm"] / 25.4 * profile["raster_dpi"]) <= 1
        svg = ET.parse(publication["files"]["svg"]).getroot()
        texts = list(svg.iter("{http://www.w3.org/2000/svg}text"))
        assert bool(texts) == preset.startswith("nature")
        assert not list(svg.iter("{http://www.w3.org/2000/svg}image"))
        for text in texts:
            sizes = re.findall(r"([\d.]+)px", text.attrib.get("style", ""))
            assert sizes and all(5 <= float(size) <= 7 for size in sizes), text.attrib
            assert "Arial" in text.attrib.get("style", ""), text.attrib
        assert b"/FontFile2" in Path(publication["files"]["pdf"]).read_bytes()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == args["expected_record_sha256"]
