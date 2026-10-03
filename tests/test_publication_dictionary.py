"""Real MCP display editions: reviewed labels cannot rewrite source data or fitted results."""

import asyncio
import copy
import csv
import json
import uuid
from pathlib import Path

import pytest

from rde.interface.mcp.server import create_server
from test_publication_editions import call, completed


def display_dictionary(record):
    return {
        "schema": "publication-dictionary-v1",
        "source_sha256": record["source"]["sha256"],
        "source_sheet": record["source"].get("sheet"),
        "dictionary_sha256": "a" * 64,
        "dictionary_revision": 3,
        "basis": {"kind": "reviewed_revision"},
        "reviewed_at": "2026-10-03T00:00:00.000Z",
        "no_conversion_confirmed": True,
        "entries": [
            {"column": "time", "unit": "days", "source": "Synthetic QA definition", "levels": []},
            {
                "column": "x",
                "label_en": "Serum α-marker",
                "unit": "µg/L",
                "source": "Synthetic QA definition; numerical values stay unchanged",
                "levels": [],
            },
            {
                "column": "group",
                "label_en": "Study group",
                "source": "Synthetic QA definition",
                "levels": [
                    {"value": "control", "label_en": "Reference group"},
                    {"value": "treated", "label_en": "Exposed group"},
                ],
            },
            {
                "column": "status",
                "source": "Synthetic QA definition",
                "levels": [
                    {"value": "D", "label_en": "Target event"},
                    {"value": "C", "label_en": "Right censored"},
                ],
            },
        ],
    }


def numerical_rows(path):
    with Path(path).open(newline="", encoding="utf-8") as file:
        return [
            {k: v for k, v in row.items() if k != "display_label"} for row in csv.DictReader(file)
        ]


def regression_dictionary(record):
    value = display_dictionary(record)
    spec = record["result"]["spec"]
    value["entries"] = [
        {
            "column": "y",
            "label_en": "Observed response",
            "unit": spec["outcome_unit"],
            "source": "Synthetic QA definition",
            "levels": [
                {"value": code, "label_en": f"Response category {i + 1}"}
                for i, code in enumerate(spec["outcome_levels"])
            ],
        },
        {
            "column": "x",
            "label_en": "Serum α-marker",
            "unit": "unit",
            "source": "Synthetic QA definition; original comparison increment retained",
            "levels": [],
        },
        {
            "column": "group",
            "label_en": "Study group",
            "source": "Synthetic QA definition",
            "levels": [
                {"value": "A", "label_en": "Reference"},
                {"value": "B", "label_en": "Exposed"},
            ],
        },
    ]
    if spec["exposure"]:
        value["entries"].append(
            {
                "column": spec["exposure"],
                "label_en": "Observation duration",
                "unit": "years",
                "source": "Synthetic QA definition; years is an alias of year, not a conversion",
                "levels": [],
            }
        )
    return value


@pytest.mark.parametrize(
    "distribution", ["gaussian", "binary", "poisson", "negative_binomial", "ordinal"]
)
def test_regression_dictionary_keeps_order_increment_offset_interaction_and_saved_evidence(
    tmp_path, monkeypatch, distribution
):
    project, source, record, args = completed(tmp_path, f"regression_{distribution}")
    frozen = {
        p: p.read_bytes()
        for p in [source, *(project.output_dir / a["path"] for a in record["artifacts"])]
    }
    from rde.infrastructure.clinical import regression
    from matplotlib.backends.backend_pdf import RendererPdf

    original_draw_path = RendererPdf.draw_path
    hatches = []

    def check_vector_hatch(renderer, gc, path, transform, rgbFace=None):
        if gc.get_hatch():
            # A transparent edge makes the entire PDF pattern invisible even
            # though the raster backend draws its independently colored hatch.
            assert gc.get_rgb()[3] > 0, "PDF pattern has transparent stroking alpha"
            hatches.append(gc.get_hatch())
        return original_draw_path(renderer, gc, path, transform, rgbFace)

    monkeypatch.setattr(RendererPdf, "draw_path", check_vector_hatch)

    monkeypatch.setattr(
        regression, "run_regression", lambda *a, **kw: pytest.fail("Refitted regression")
    )
    dictionary = regression_dictionary(record)
    if distribution == "ordinal":
        # A long meaning must remain accessible even when a narrow panel uses L#.
        dictionary["entries"][0]["levels"][0]["label_en"] = (
            "First response category with a deliberately long reviewed source meaning"
        )
        dictionary["entries"][2]["levels"][1]["label_en"] = (
            "Exposed study participants with a long reviewed meaning"
        )
    if distribution == "gaussian":
        dictionary["entries"][1]["label_en"] = (
            "Serum α-marker with a deliberately long original source definition"
        )
    args.update(
        display_dictionary=dictionary,
        captions={"2": {"caption_en": "Author-reviewed coefficient caption."}},
    )
    edition = call("render_publication_figures", args)
    assert edition == call("render_publication_figures", args)
    assert edition["request"]["options"]["display_dictionary"] == dictionary
    assert edition["source_numerical_receipt_sha256"] == record["result"]["receipt_sha256"]
    for original, rendered in zip(record["figures"], edition["figures"], strict=True):
        pub = rendered["publication"]
        assert pub["dictionary_sha256"] == dictionary["dictionary_sha256"]
        assert pub["caption_en"].count("Display labels follow") == 1
        assert not pub["text_outside_canvas"]
        assert numerical_rows(original["publication"]["files"]["data"]) == numerical_rows(
            pub["files"]["data"]
        )
    effects = edition["figures"][1]["publication"]
    assert "Author-reviewed coefficient caption." in effects["caption_en"]
    assert "code 'B' denotes 'Exposed" in effects["caption_en"]
    assert "Serum α-marker" in effects["caption_en"]
    coefficient_csvs = "\n".join(
        Path(f["publication"]["files"]["data"]).read_text() for f in edition["figures"]
    )
    assert (
        "B vs Reference" if distribution == "ordinal" else "Exposed vs Reference"
    ) in coefficient_csvs
    if distribution == "gaussian":
        curve = next(f for f in edition["figures"] if f["plot_type"].endswith("_curve_P1"))
        assert "P1 P1" not in Path(curve["publication"]["files"]["svg"]).read_text()
        assert dictionary["entries"][1]["label_en"] in curve["publication"]["caption_en"]
    if distribution in {"poisson", "negative_binomial"}:
        assert "Observation duration" in effects["caption_en"]
        assert "unit 'years'" in effects["caption_en"]
    if distribution == "ordinal":
        categories = next(
            f["publication"] for f in edition["figures"] if f["plot_type"].endswith("_categories")
        )
        assert "deliberately long reviewed source meaning" in categories["caption_en"]
        assert [r["label"] for r in numerical_rows(categories["files"]["data"])] == record[
            "result"
        ]["spec"]["outcome_levels"]
        assert len(hatches) >= len(record["result"]["spec"]["outcome_levels"]) + 1
    assert all(p.read_bytes() == before for p, before in frozen.items())


def test_regression_dictionary_rejects_false_units_before_any_render_or_commit(
    tmp_path, monkeypatch
):
    project, _, record, args = completed(tmp_path, "regression_poisson")
    from rde.infrastructure.clinical import regression_publication

    monkeypatch.setattr(
        regression_publication, "figures", lambda *a, **kw: pytest.fail("Rendered invalid units")
    )
    original = regression_dictionary(record)
    for index, unit in [(0, "percent"), (1, "ten units"), (3, "days")]:
        dictionary = copy.deepcopy(original)
        dictionary["entries"][index]["unit"] = unit
        edition_id = str(uuid.uuid4())
        response = asyncio.run(
            create_server().call_tool(
                "render_publication_figures",
                {
                    **args,
                    "edition_id": edition_id,
                    "display_dictionary": dictionary,
                },
            )
        )
        assert (
            response.is_error
            and "cannot convert source values or comparison increments" in response.content[0].text
        )
        assert not (project.output_dir / "figures/editions" / edition_id).exists()


@pytest.mark.parametrize("family", ["survival", "survival_competing"])
def test_reviewed_dictionary_labels_preserve_every_numerical_value_and_original_file(
    tmp_path, monkeypatch, family
):
    project, source, record, args = completed(tmp_path, family)
    frozen = {
        p: p.read_bytes()
        for p in [source, *(project.output_dir / a["path"] for a in record["artifacts"])]
    }
    import lifelines

    monkeypatch.setattr(
        lifelines.CoxPHFitter, "fit", lambda *a, **kw: pytest.fail("Refitted Cox model")
    )
    dictionary = display_dictionary(record)
    args.update(
        display_dictionary=dictionary,
        captions={"1": {"caption_en": "Reviewed caption with fixed original participants."}},
    )
    edition = call("render_publication_figures", args)
    assert edition["request"]["options"]["display_dictionary"] == dictionary
    assert edition["source_numerical_receipt_sha256"] == record["result"]["receipt_sha256"]
    assert edition == call("render_publication_figures", args)
    for original, rendered in zip(record["figures"], edition["figures"], strict=True):
        publication = rendered["publication"]
        assert publication["dictionary_sha256"] == dictionary["dictionary_sha256"]
        assert publication["caption_en"].count("Display labels follow") == 1
        assert dictionary["dictionary_sha256"] not in publication["caption_en"]
        assert "no conversion or refitting" in publication["caption_en"]
        assert not publication["text_outside_canvas"]
        assert numerical_rows(original["publication"]["files"]["data"]) == numerical_rows(
            publication["files"]["data"]
        )
    cox = next(f for f in edition["figures"] if f["plot_type"] == "clinical_cox_1")
    assert "Serum α-marker (µg/L)" in Path(cox["publication"]["files"]["data"]).read_text()
    if family == "survival":
        km = next(f for f in edition["figures"] if f["plot_type"] == "clinical_survival")
        assert "Code 'D' denotes 'Target event'" in km["publication"]["caption_en"]
    report = project.output_dir / "figures/editions" / args["edition_id"] / "publication-edition.md"
    assert "後續人工審閱" in report.read_text() and "Synthetic QA definition" in report.read_text()
    assert all(p.read_bytes() == before for p, before in frozen.items())
    conflict = copy.deepcopy(dictionary)
    conflict["entries"][1]["label_en"] = "A newer label"
    response = asyncio.run(
        create_server().call_tool(
            "render_publication_figures", {**args, "display_dictionary": conflict}
        )
    )
    assert response.is_error and "another rendering request" in response.content[0].text


def test_dictionary_source_unit_scope_and_review_errors_cannot_publish_partial_editions(
    tmp_path, monkeypatch
):
    project, _, record, args = completed(tmp_path, "survival")
    from rde.infrastructure.clinical import survival_publication

    monkeypatch.setattr(
        survival_publication, "figures", lambda *a, **kw: pytest.fail("Rendered invalid dictionary")
    )
    original = display_dictionary(record)
    cases = []
    for key, value in (
        ("source_sha256", "b" * 64),
        ("source_sheet", "wrong"),
        ("no_conversion_confirmed", False),
        ("dictionary_sha256", "bad"),
    ):
        cases.append({**original, key: value})
    for change in (
        lambda d: d["entries"][0].update(unit="years"),
        lambda d: d["entries"][1].update(column="foreign-column"),
        lambda d: d["entries"][1].update(label_en="未翻譯標籤"),
        lambda d: d["entries"].append(d["entries"][0]),
        lambda d: d["entries"][2]["levels"].append(d["entries"][2]["levels"][0]),
    ):
        value = copy.deepcopy(original)
        change(value)
        cases.append(value)
    for value in cases:
        edition_id = str(uuid.uuid4())
        response = asyncio.run(
            create_server().call_tool(
                "render_publication_figures",
                {**args, "edition_id": edition_id, "display_dictionary": value},
            )
        )
        assert response.is_error, json.dumps(value)
        assert not (project.output_dir / "figures/editions" / edition_id).exists()
