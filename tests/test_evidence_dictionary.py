"""Actual MCP: comparison annotations cannot change treatment identity or frozen R evidence."""

import copy
import uuid
from pathlib import Path

import pytest
from test_evidence_workflow import prepare, tool
from test_publication_dictionary import display_dictionary


def saved_study():
    project, _, args = prepare()
    source = tool("import_evidence_source", args)
    study = tool(
        "render_evidence_study",
        {
            "project_id": project.id,
            "source_id": args["source_id"],
            "expected_source_sha256": source["receipt_sha256"],
            "render_id": str(uuid.uuid4()),
        },
    )
    dictionary = display_dictionary({"source": source["source"]})
    dictionary["entries"] = [
        {
            "column": "treatment",
            "label_en": "Assigned treatment",
            "source": "Synthetic QA source, not clinical evidence",
            "levels": [
                {"value": "A", "label_en": "Alpha"},
                {
                    "value": "B",
                    "label_en": "A very long reviewed treatment description retained completely in the caption",
                },
            ],
        },
        {
            "column": "comparator",
            "label_en": "Comparison treatment",
            "source": "Same synthetic treatment identities",
            "levels": [
                {"value": "Control", "label_en": "Control"},
                {
                    "value": "B",
                    "label_en": "A very long reviewed treatment description retained completely in the caption",
                },
            ],
        },
        {
            "column": "effect",
            "label_en": "Original log odds ratio",
            "unit": "log OR",
            "source": "Original natural-log input scale",
            "levels": [],
        },
        {
            "column": "se",
            "label_en": "Original standard error",
            "unit": "log OR",
            "source": "SE of original log odds ratio",
            "levels": [],
        },
        {
            "column": "outcome",
            "label_en": "Prespecified response",
            "source": "Synthetic study endpoint",
            "levels": [{"value": "response", "label_en": "Synthetic response"}],
        },
    ]
    options = {
        "project_id": project.id,
        "source_id": args["source_id"],
        "render_id": study["render_id"],
        "expected_study_sha256": study["receipt_sha256"],
        "edition_id": str(uuid.uuid4()),
        "preset_id": "journal-neutral-english-v1",
        "display_dictionary": dictionary,
        "captions": {"1": {"caption_en": "Author-reviewed comparison rows."}},
    }
    return project, source, study, options


@pytest.mark.parametrize("basis", ["reviewed_revision", "approved_plan"])
def test_fixed_r_comparison_dictionary_preserves_all_numbers_source_and_author_override(
    basis, monkeypatch
):
    project, source, study, args = saved_study()
    if basis == "approved_plan":
        args["display_dictionary"]["basis"] = {
            "kind": basis,
            "plan_id": source["identity"]["plan_id"],
        }
    frozen = {
        p: p.read_bytes()
        for p in project.output_dir.rglob("*")
        if p.is_file() and p.name != "decision_log.jsonl"
    }
    # Rendering must not launch R or any other new executor process.
    import subprocess

    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **kw: pytest.fail("Edition launched an external executor")
    )
    edition = tool("render_evidence_publication", args)
    assert tool("render_evidence_publication", args) == edition
    assert len(edition["figures"]) == len(study["figures"]) == 9
    for original, figure in zip(study["figures"], edition["figures"], strict=True):
        p = figure["publication"]
        assert p["dictionary_sha256"] == args["display_dictionary"]["dictionary_sha256"]
        assert p["text_outside_canvas"] == []
        assert (
            Path(p["files"]["data"]).read_bytes()
            == Path(original["publication"]["files"]["data"]).read_bytes()
        )
        assert "Original log odds ratio" in p["caption_en"]
        assert "A very long reviewed treatment description" in p["caption_en"]
        assert "no conversion or refitting" in p["caption_en"]
        assert "Synthetic software-validation" in p["caption_en"]
        assert "do not merge treatments" in p["caption_en"]
        assert "not adjusted across comparisons" in p["caption_en"]
        assert "not a PRISMA" in p["caption_en"]
        assert "log-ratio scale" in p["caption_en"]
    assert "Author-reviewed comparison rows." in edition["figures"][0]["publication"]["caption_en"]
    assert all(p.read_bytes() == data for p, data in frozen.items())


def test_mcp_rejects_wrong_source_unit_plan_control_fields_and_conflicting_treatment_meanings(
    monkeypatch,
):
    project, _source, _study, args = saved_study()
    from rde.infrastructure.evidence import publication

    monkeypatch.setattr(
        publication, "figures", lambda *a, **kw: pytest.fail("Invalid dictionary reached renderer")
    )
    original = args["display_dictionary"]
    variants = [
        {**original, "source_sha256": "f" * 64},
        {**original, "source_sheet": "wrong sheet"},
        {**original, "basis": {"kind": "approved_plan", "plan_id": str(uuid.uuid4())}},
        {**original, "no_conversion_confirmed": False},
    ]
    for column, changes in [
        ("effect", {"unit": "OR"}),
        ("se", {"unit": "mg/dL"}),
        ("treatment", {"levels": [{"value": "Not a source treatment", "label_en": "Alpha"}]}),
        ("comparator", {"levels": [{"value": "B", "label_en": "Different treatment"}]}),
        ("outcome", {"column": "decision"}),
    ]:
        changed = copy.deepcopy(original)
        next(e for e in changed["entries"] if e["column"] == column).update(changes)
        variants.append(changed)
    for dictionary in variants:
        tool("render_evidence_publication", {**args, "display_dictionary": dictionary}, error=True)
    assert not (project.output_dir / "figures/editions").exists()
