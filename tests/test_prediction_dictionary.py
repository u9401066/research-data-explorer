"""Reviewed prediction displays preserve the held-out evidence and original fit."""

import asyncio
import copy
import hashlib
import uuid

import pytest

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.server import create_server
from test_prediction_validation import prediction_project, decision_options
from test_publication_dictionary import display_dictionary, numerical_rows
from test_publication_editions import call


def completed_prediction(tmp_path, options):
    from rde.interface.mcp.tools.prediction_tools import persisted_predictions

    project, store, dataset, spec = prediction_project(tmp_path, **options)
    call(
        "run_prediction_study",
        {"dataset_id": dataset.id, "prediction_options": spec.to_dict()},
        json_result=False,
    )
    record = persisted_predictions(store)[0]
    source = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    args = dict(
        project_id=project.id,
        study_artifact=source.name,
        expected_record_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        preset_id="journal-neutral-english-v1",
        edition_id=str(uuid.uuid4()),
    )
    return project, source, record, args


def reviewed(record):
    value = display_dictionary(record)
    spec = record["result"]["spec"]
    value["entries"] = [
        {
            "column": spec["target"],
            "label_en": "Recorded response",
            "source": "Synthetic source; reviewed raw scale only",
            "levels": [],
        },
        {
            "column": "category",
            "label_en": "Prespecified category",
            "source": "Synthetic QA codes",
            "levels": [
                {"value": "a", "label_en": "Category A"},
                {"value": "b", "label_en": "Category B"},
            ],
        },
        {
            "column": "x",
            "label_en": "A long predictor description retained without substituting the fitted feature",
            "unit": "µg/L",
            "source": "Synthetic original source unit",
            "levels": [],
        },
    ]
    if spec["task"] == "binary":
        value["entries"][0]["levels"] = [
            {"value": code, "label_en": "Event recorded" if encoded else "Event absent"}
            for code, encoded in record["result"]["target_encoding"].items()
        ]
    else:
        value["entries"][0]["unit"] = "%"
    for key in ["subject_variable", "time_variable"]:
        if spec[key]:
            value["entries"].append(
                {
                    "column": spec[key],
                    "label_en": "Original split key",
                    "source": "Synthetic split identity, unchanged",
                    "levels": [],
                }
            )
    return value


@pytest.mark.parametrize(
    "options",
    [
        {"study_design": "diagnostic_accuracy", "sampling": "unknown"},
        {"decision_curve": decision_options()},
        {"task": "regression", "target": "continuous"},
        {"split": "group", "subject_variable": "subject"},
        {
            "split": "temporal",
            "subject_variable": "subject",
            "time_variable": "date",
            "cutoff": "2020-06-20",
        },
    ],
)
def test_dictionary_keeps_model_split_classes_probabilities_and_every_exported_number(
    tmp_path, monkeypatch, options
):
    project, source, record, args = completed_prediction(tmp_path, options)
    from rde.infrastructure.prediction import engine, metrics, publication

    original_save = publication.save_publication_figure

    def check_layout(fig, directory, name, **kwargs):
        saved = original_save(fig, directory, name, **kwargs)
        renderer = fig.canvas.get_renderer()
        ax = fig.axes[0]
        if name.endswith(("_roc", "_pr", "_decision_curve")):
            # Weak discrimination / low precision must not be hidden by a legend.
            assert ax.get_legend().get_window_extent(renderer).y0 > ax.bbox.y1
        if name.endswith("_participants"):
            note = next(t for t in ax.texts if t.get_text().startswith("Cross-boundary"))
            lower_boxes = [
                t
                for t in ax.texts
                if t.get_text().startswith(("Final training", "Internal holdout"))
            ]
            assert note.get_window_extent(renderer).y1 < min(
                t.get_bbox_patch().get_window_extent(renderer).y0 for t in lower_boxes
            )
        return saved

    monkeypatch.setattr(publication, "save_publication_figure", check_layout)

    def refit(*args, **kwargs):
        pytest.fail("Prediction display must not train or repeat bootstrap")

    monkeypatch.setattr(engine, "run_prediction", refit)
    monkeypatch.setattr(metrics, "bootstrap_intervals", refit)
    frozen = {
        p: p.read_bytes()
        for p in [source, *(project.output_dir / a["path"] for a in record["artifacts"])]
    }
    dictionary = reviewed(record)
    args.update(
        display_dictionary=dictionary, captions={"2": {"caption_en": "Author-reviewed figure."}}
    )
    edition = call("render_publication_figures", args)
    assert call("render_publication_figures", args) == edition
    assert edition["source_numerical_receipt_sha256"] == record["result"]["receipt_sha256"]
    for original, figure in zip(record["figures"], edition["figures"], strict=True):
        p = figure["publication"]
        assert p["text_outside_canvas"] == []
        assert p["dictionary_sha256"] == dictionary["dictionary_sha256"]
        assert numerical_rows(p["files"]["data"]) == numerical_rows(
            original["publication"]["files"]["data"]
        )
        caption = p["caption_en"]
        assert caption.count("Display labels follow") == 1
        assert "does not declare physical units" in caption
        assert "not external or clinical-use validation" in caption
        assert f"Saved split={record['result']['spec']['split']!r}" in caption
        for entry in dictionary["entries"]:
            assert entry["label_en"] in caption
        if options.get("task") == "regression":
            assert "percentage points" in caption
        else:
            assert "Positive class remains '1'" in caption
            assert "dimensionless" in caption
        if options.get("sampling") == "unknown":
            assert "not validated population risk" in caption
        if options.get("decision_curve"):
            assert "evaluated probability thresholds=[0.2, 0.8, 0.95]" in caption
            assert "no clinical utility claim" in caption
    assert "Author-reviewed figure." in edition["figures"][1]["publication"]["caption_en"]
    assert all(p.read_bytes() == before for p, before in frozen.items())


def test_prediction_dictionary_rejects_unrelated_columns_and_changed_source_before_render(
    tmp_path, monkeypatch
):
    project, source, record, args = completed_prediction(tmp_path, {})
    from rde.infrastructure.prediction import publication

    monkeypatch.setattr(
        publication, "figures", lambda *a, **kw: pytest.fail("Invalid dictionary reached renderer")
    )
    value = reviewed(record)
    invalid = []
    for key, wrong in [
        ("source_sha256", "f" * 64),
        ("source_sheet", "Another sheet"),
        ("no_conversion_confirmed", False),
    ]:
        invalid.append({**value, key: wrong})
    foreign = copy.deepcopy(value)
    foreign["entries"][0]["column"] = "unused_outcome"
    invalid.append(foreign)
    for dictionary in invalid:
        response = asyncio.run(
            create_server().call_tool(
                "render_publication_figures",
                {**args, "edition_id": str(uuid.uuid4()), "display_dictionary": dictionary},
            )
        )
        assert response.is_error
    assert not (project.output_dir / "figures" / "editions").exists()
