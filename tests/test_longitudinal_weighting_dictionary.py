"""Actual MCP editions preserve follow-up times, weighting direction and saved estimates."""

import asyncio
import copy
from pathlib import Path
import uuid

import pytest

from rde.interface.mcp.server import create_server
from test_publication_dictionary import display_dictionary, numerical_rows
from test_publication_editions import completed, call


def dictionary_for(record):
    dictionary = display_dictionary(record)
    s = record["result"]["spec"]
    entries = []

    def entry(column, label, unit=None, levels=()):
        entries.append(
            {
                "column": column,
                "label_en": label,
                "source": "Synthetic QA definitions only; no source conversion",
                "levels": [{"value": code, "label_en": meaning} for code, meaning in levels],
                **({"unit": unit} if unit else {}),
            }
        )

    entry(s["outcome"], "Recorded endpoint", s["outcome_unit"])
    if s["family"] == "longitudinal":
        entry(s["time"], "Follow-up time", "years", [("0", "Reference visit")])
        entry(s["group"], "Study group", levels=[("0", "Reference"), ("1", "Exposed")])
        if s["exposure"]:
            entry(s["exposure"], "Observation duration", "year")
    else:
        entry(
            s["treatment"],
            "Source exposure",
            levels=[("Control", "Reference"), ("Treated", "Exposed")],
        )
        entry(
            "stratum",
            "Baseline stratum with a deliberately long reviewed definition",
            levels=[
                ("Low", "Reference stratum"),
                ("High", "Higher source stratum with a deliberately long reviewed label"),
            ],
        )
    dictionary["entries"] = entries
    return dictionary


@pytest.mark.parametrize(
    "family",
    [
        "longitudinal_gaussian",
        "longitudinal_mixed",
        "longitudinal_binomial",
        "longitudinal_poisson",
        "weighting_binary",
        "weighting_continuous",
    ],
)
def test_mcp_reviewed_editions_preserve_all_numerical_csv_fields_and_originals(
    tmp_path, monkeypatch, family
):
    project, source, record, args = completed(tmp_path, family)
    frozen = {
        p: p.read_bytes()
        for p in [source, *(project.output_dir / a["path"] for a in record["artifacts"])]
    }
    from rde.infrastructure.clinical import longitudinal, weighting

    def refit(*args, **kwargs):
        pytest.fail("Refitted a saved numerical study")

    monkeypatch.setattr(longitudinal, "run_longitudinal", refit)
    monkeypatch.setattr(weighting, "run_weighting", refit)
    dictionary = dictionary_for(record)
    if family == "longitudinal_gaussian":
        dictionary["entries"][1]["label_en"] = (
            "Follow-up time with a deliberately long reviewed source definition"
        )
    args.update(
        display_dictionary=dictionary, captions={"2": {"caption_en": "Author-reviewed caption."}}
    )
    edition = call("render_publication_figures", args)
    assert edition == call("render_publication_figures", args)
    assert edition["source_numerical_receipt_sha256"] == record["result"]["receipt_sha256"]
    assert edition["request"]["options"]["display_dictionary"] == dictionary
    for original, rendered in zip(record["figures"], edition["figures"], strict=True):
        pub = rendered["publication"]
        assert pub["dictionary_sha256"] == dictionary["dictionary_sha256"]
        assert not pub["text_outside_canvas"]
        assert pub["caption_en"].count("Display labels follow") == 1
        assert "Recorded endpoint" in pub["caption_en"]
        assert "denotes 'Exposed'" in pub["caption_en"]
        assert numerical_rows(original["publication"]["files"]["data"]) == numerical_rows(
            pub["files"]["data"]
        )
    assert "Author-reviewed caption." in edition["figures"][1]["publication"]["caption_en"]
    if family.startswith("weighting"):
        balance = next(
            f["publication"]
            for f in edition["figures"]
            if f["plot_type"] == "clinical_weighting_balance_1"
        )
        assert "deliberately long reviewed" in balance["caption_en"]
        assert "High" in Path(balance["files"]["data"]).read_text()
        effect = next(
            f["publication"] for f in edition["figures"] if f["plot_type"].endswith("_effect")
        )
        assert "G1 minus G0" in effect["caption_en"]
        assert "G0 (A=0)='Control'; G1 (A=1)='Treated'" in effect["caption_en"]
        if family == "weighting_binary":
            assert "Probability difference" in Path(effect["files"]["svg"]).read_text()
            assert record["result"]["effect"]["estimate"] < 0
    else:
        csvs = "\n".join(
            Path(f["publication"]["files"]["data"]).read_text() for f in edition["figures"]
        )
        assert "Exposed vs Reference" in csvs
        if family == "longitudinal_gaussian":
            assert "time: -2 vs 0" in csvs
            assert "time_L1: -2 vs 0" not in csvs
        if family == "longitudinal_poisson":
            assert "unit 'year'" in edition["figures"][1]["publication"]["caption_en"]
    assert all(p.read_bytes() == before for p, before in frozen.items())


@pytest.mark.parametrize("family", ["longitudinal_poisson", "weighting_continuous"])
def test_wrong_units_are_rejected_before_rendering_an_edition(tmp_path, monkeypatch, family):
    project, _, record, args = completed(tmp_path, family)
    from rde.infrastructure.clinical import longitudinal_publication, weighting_publication

    def render(*args, **kwargs):
        pytest.fail("Rendered a dictionary that changes saved source units")

    monkeypatch.setattr(longitudinal_publication, "figures", render)
    monkeypatch.setattr(weighting_publication, "figures", render)
    original = dictionary_for(record)
    for index, entry in enumerate(original["entries"]):
        if "unit" not in entry:
            continue
        changed = copy.deepcopy(original)
        changed["entries"][index]["unit"] = "converted scale"
        edition_id = str(uuid.uuid4())
        response = asyncio.run(
            create_server().call_tool(
                "render_publication_figures",
                {
                    **args,
                    "edition_id": edition_id,
                    "display_dictionary": changed,
                },
            )
        )
        assert response.is_error and "cannot convert" in response.content[0].text
        assert not (project.output_dir / "figures/editions" / edition_id).exists()
