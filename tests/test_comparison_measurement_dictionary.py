"""MCP editions cannot alter directional contrasts, paired populations or diagnostic rules."""

import asyncio
import copy
from pathlib import Path
import uuid

import pytest

from rde.interface.mcp.server import create_server
from test_publication_dictionary import display_dictionary, numerical_rows
from test_publication_editions import completed, call


def reviewed(record):
    value = display_dictionary(record)
    spec = record["result"]["spec"]
    entries = []

    def entry(column, label, unit=None, levels=()):
        entries.append(
            dict(
                column=column,
                label_en=label,
                source="Synthetic reviewed QA definition; original scale retained",
                levels=[dict(value=code, label_en=meaning) for code, meaning in levels],
                **({"unit": unit} if unit else {}),
            )
        )

    if spec["family"] == "comparison":
        entry(
            spec["outcome"],
            "Recorded endpoint",
            spec["outcome_unit"],
            [(v, f"Outcome meaning {i + 1}") for i, v in enumerate(spec["outcome_levels"])],
        )
        entry(
            spec["group"],
            "Study group",
            levels=[(v, f"Reviewed group {i + 1}") for i, v in enumerate(spec["group_levels"])],
        )
    elif spec["family"] == "repeated":
        for i, m in enumerate(spec["measurements"]):
            entry(m["column"], f"Visit {i + 1}", spec["outcome_unit"])
        entries[-1]["label_en"] = (
            "A deliberately long occasion definition that must remain traceable in the caption"
        )
    else:
        for i, column in enumerate([spec["first"], spec["second"]]):
            entry(
                column,
                ["Reference measurement", "Reviewed test"][i],
                spec["agreement"]["unit"] if spec["agreement"] else None,
                [(v, f"Category {j + 1}") for j, v in enumerate(spec["categories"])],
            )
        if spec["diagnostic"]:
            d = spec["diagnostic"]
            entries[0]["levels"] = [
                dict(value=d["positive"], label_en="Reference positive"),
                dict(value=d["negative"], label_en="Reference negative"),
            ]
            entries[1]["unit"] = "source score unit"
    value["entries"] = entries
    return value


@pytest.mark.parametrize(
    "family",
    [
        "comparison_mean",
        "comparison_rank",
        "comparison_binary",
        "paired_mean",
        "paired_signed",
        "diagnostic_accuracy",
        "bland_altman",
        "cohens_kappa",
    ],
)
def test_reviewed_editions_preserve_every_saved_value_and_direction(tmp_path, monkeypatch, family):
    project, source, record, args = completed(tmp_path, family)
    frozen = {
        p: p.read_bytes()
        for p in [source, *(project.output_dir / a["path"] for a in record["artifacts"])]
    }
    from rde.infrastructure.clinical import comparison, repeated, measurement

    def refit(*args, **kwargs):
        pytest.fail("Recomputed a saved clinical analysis")

    for module, name in [
        (comparison, "run_comparison"),
        (repeated, "run_repeated"),
        (measurement, "run_measurement"),
    ]:
        monkeypatch.setattr(module, name, refit)
    dictionary = reviewed(record)
    args.update(
        display_dictionary=dictionary,
        captions={"2": {"caption_en": "Author reviewed this display."}},
    )
    edition = call("render_publication_figures", args)
    assert call("render_publication_figures", args) == edition
    assert edition["source_numerical_receipt_sha256"] == record["result"]["receipt_sha256"]
    for original, figure in zip(record["figures"], edition["figures"], strict=True):
        p = figure["publication"]
        assert not p["text_outside_canvas"]
        assert p["dictionary_sha256"] == dictionary["dictionary_sha256"]
        assert p["caption_en"].count("Display labels follow") == 1
        for e in dictionary["entries"]:
            assert e["label_en"] in p["caption_en"]
        assert numerical_rows(original["publication"]["files"]["data"]) == numerical_rows(
            p["files"]["data"]
        )
    caption = edition["figures"][1]["publication"]["caption_en"]
    assert "Author reviewed this display." in caption
    if family.startswith("comparison"):
        assert "first group minus second; ratios are first / second" in caption
        if family.endswith("binary"):
            assert "Source event='event'; non-event='none'" in caption
            assert any(
                "positive_infinity" in Path(f["publication"]["files"]["data"]).read_text()
                for f in edition["figures"]
            )
    elif family.startswith("paired"):
        assert "first occasion minus second" in caption
        assert "common complete subjects n=" in caption
        assert "T1=" in caption
    elif family == "diagnostic_accuracy":
        assert "locked score >= 5" in caption
        assert "does not declare a score unit" in caption
        assert "Reference positive" in caption
    elif family == "bland_altman":
        assert "measurement 1 minus measurement 2" in caption
        assert "U1 denotes this same source unit" in caption
    else:
        assert "Shared raw categories and table direction are unchanged" in caption
    assert all(p.read_bytes() == b for p, b in frozen.items())


@pytest.mark.parametrize(
    "family", ["comparison_mean", "paired_mean", "bland_altman", "cohens_kappa"]
)
def test_conflicting_scale_or_shared_rating_meanings_fail_before_rendering(
    tmp_path, monkeypatch, family
):
    project, _, record, args = completed(tmp_path, family)
    dictionary = reviewed(record)
    from rde.infrastructure.clinical import (
        comparison_publication,
        repeated_publication,
        measurement_publication,
    )

    def render(*args, **kwargs):
        pytest.fail("Rendered an invalid display dictionary")

    for module in [comparison_publication, repeated_publication, measurement_publication]:
        monkeypatch.setattr(module, "figures", render)
    indices = (
        range(len(dictionary["entries"])) if family in {"paired_mean", "bland_altman"} else [0]
    )
    for index in indices:
        changed = copy.deepcopy(dictionary)
        if family == "cohens_kappa":
            changed["entries"][1]["levels"][0]["label_en"] = "A different clinical category"
            expected = "shared category meanings"
        else:
            changed["entries"][index]["unit"] = "different scale"
            expected = "cannot convert"
        identifier = str(uuid.uuid4())
        response = asyncio.run(
            create_server().call_tool(
                "render_publication_figures",
                {**args, "edition_id": identifier, "display_dictionary": changed},
            )
        )
        assert response.is_error and expected in response.content[0].text
        assert not (project.output_dir / "figures/editions" / identifier).exists()
