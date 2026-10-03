"""Actual MCP boundaries: separate source meanings retain the complete frozen DESeq2 evidence."""

import copy
import uuid
from pathlib import Path

import pytest
from test_genomics_workflow import prepare, tool
from test_publication_dictionary import display_dictionary

from rde.infrastructure.prediction.splits import digest


def seal(value):
    value["dictionary_sha256"] = digest(
        [
            [v["role"], v["dataset_id"], v["dictionary"]["dictionary_sha256"]]
            for v in value["dictionaries"]
        ]
    )
    return value


def saved_study():
    project, _, args = prepare()
    source = tool("import_genomics_source", args)
    study = tool(
        "render_genomics_study",
        {
            "project_id": project.id,
            "source_id": args["source_id"],
            "expected_source_sha256": source["receipt_sha256"],
            "render_id": str(uuid.uuid4()),
        },
    )
    entries = {
        "counts": [
            {
                "column": "gene_id",
                "label_en": "Original gene accession",
                "levels": [
                    {"value": "gene0001", "label_en": "Synthetic gene Alpha"},
                ],
            },
            {"column": "S01", "label_en": "Sample Alpha", "unit": "counts", "levels": []},
        ],
        "sample_metadata": [
            {
                "column": "sample_id",
                "label_en": "Original sample accession",
                "levels": [
                    {"value": "S01", "label_en": "Sample Alpha"},
                    {
                        "value": "S02",
                        "label_en": "A long source sample name kept in the caption without losing its identity",
                    },
                ],
            },
            {
                "column": "condition",
                "label_en": "Experimental condition",
                "levels": [
                    {"value": "control", "label_en": "Vehicle"},
                    {"value": "treated", "label_en": "Treatment"},
                ],
            },
            {
                "column": "batch",
                "label_en": "Sequencing batch",
                "levels": [
                    {"value": "batchA", "label_en": "Batch Alpha"},
                ],
            },
        ],
        "gene_sets": [
            {
                "column": "set_id",
                "label_en": "Prespecified gene set",
                "levels": [
                    {"value": "up_program", "label_en": "Synthetic up"},
                ],
            },
            {
                "column": "gene_id",
                "label_en": "Original gene accession",
                "levels": [
                    {"value": "gene0001", "label_en": "Synthetic gene Alpha"},
                ],
            },
        ],
    }
    dictionaries = []
    for role in ["counts", "sample_metadata", "gene_sets"]:
        original = source["source"][role]
        dictionary = display_dictionary({"source": original})
        dictionary["entries"] = [
            dict(e, source="Synthetic engineering QA; no biological claims") for e in entries[role]
        ]
        dictionaries.append(
            {"role": role, "dataset_id": original["dataset_id"], "dictionary": dictionary}
        )
    value = seal(
        {
            "schema": "publication-genomics-dictionary-v1",
            "basis": {"kind": "reviewed_revision"},
            "dictionaries": dictionaries,
        }
    )
    return (
        project,
        source,
        study,
        {
            "project_id": project.id,
            "source_id": args["source_id"],
            "render_id": study["render_id"],
            "expected_study_sha256": study["receipt_sha256"],
            "edition_id": str(uuid.uuid4()),
            "preset_id": "journal-neutral-english-v1",
            "display_dictionary": value,
            "captions": {"1": {"caption_en": "Author-reviewed synthetic gene disposition."}},
        },
    )


@pytest.mark.parametrize("basis", ["approved_plan", "reviewed_revision", "metadata_only"])
def test_multi_source_dictionary_preserves_all_r_bytes_and_survives_author_caption_override(
    basis, monkeypatch
):
    project, source, study, args = saved_study()
    value = args["display_dictionary"]
    if basis == "approved_plan":
        value["basis"] = {"kind": basis, "plan_id": source["identity"]["plan_id"]}
        for item in value["dictionaries"]:
            item["dictionary"]["basis"] = value["basis"]
    if basis == "metadata_only":
        for item in value["dictionaries"]:
            if item["role"] != "sample_metadata":
                item["dictionary"].update(entries=[], dictionary_revision=0, reviewed_at=None)
    seal(value)
    frozen = {
        p: p.read_bytes()
        for p in project.output_dir.rglob("*")
        if p.is_file() and p.name != "decision_log.jsonl"
    }
    import subprocess

    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **kw: pytest.fail("Edition launched an external executor")
    )
    edition = tool("render_genomics_publication", args)
    assert tool("render_genomics_publication", args) == edition
    assert len(edition["figures"]) == len(study["figures"]) == 8
    for original, figure in zip(study["figures"], edition["figures"], strict=True):
        p = figure["publication"]
        assert p["dictionary_sha256"] == value["dictionary_sha256"]
        assert p["text_outside_canvas"] == []
        assert (
            Path(p["files"]["data"]).read_bytes()
            == Path(original["publication"]["files"]["data"]).read_bytes()
        )
        for phrase in [
            "no conversion or refitting",
            "Original sample accession",
            "Treatment",
            "original R contract",
            "do not merge genes",
            "not a complete gene annotation",
            "Synthetic engineering fixture",
            "BH adjusted p",
            "numerator/reference",
        ]:
            assert phrase in p["caption_en"]
    assert (
        "Author-reviewed synthetic gene disposition"
        in edition["figures"][0]["publication"]["caption_en"]
    )
    assert all(p.read_bytes() == data for p, data in frozen.items())


def test_mcp_rejects_cross_source_identity_units_absent_codes_and_conflicting_meanings(monkeypatch):
    project, _, _, args = saved_study()
    from rde.infrastructure.genomics import publication

    monkeypatch.setattr(
        publication, "figures", lambda *a, **kw: pytest.fail("Invalid dictionary reached renderer")
    )
    original = args["display_dictionary"]
    variants = []
    for role, field, bad in [
        (0, "source_sha256", "f" * 64),
        (1, "source_sheet", "Other sheet"),
        (2, "no_conversion_confirmed", False),
    ]:
        v = copy.deepcopy(original)
        v["dictionaries"][role]["dictionary"][field] = bad
        variants.append(v)
    for role, column, changes in [
        (0, "S01", {"unit": "TPM"}),
        (0, "S01", {"levels": [{"value": "73", "label_en": "High"}]}),
        (0, "gene_id", {"unit": "mg/dL"}),
        (1, "condition", {"levels": [{"value": "not in source", "label_en": "Treatment"}]}),
        (1, "batch", {"column": "age"}),
        (1, "sample_id", {"levels": [{"value": "S01", "label_en": "Different sample"}]}),
        (2, "gene_id", {"levels": [{"value": "gene0001", "label_en": "Different gene"}]}),
    ]:
        v = copy.deepcopy(original)
        next(
            e for e in v["dictionaries"][role]["dictionary"]["entries"] if e["column"] == column
        ).update(changes)
        variants.append(v)
    v = copy.deepcopy(original)
    v["dictionaries"][0]["dataset_id"] = str(uuid.uuid4())
    variants.append(seal(v))
    v = copy.deepcopy(original)
    v["dictionaries"].pop()
    variants.append(seal(v))
    v = copy.deepcopy(original)
    v["dictionaries"].reverse()
    variants.append(seal(v))
    v = copy.deepcopy(original)
    v["basis"] = {"kind": "approved_plan", "plan_id": str(uuid.uuid4())}
    for item in v["dictionaries"]:
        item["dictionary"]["basis"] = v["basis"]
    variants.append(v)
    variants.append({**original, "dictionary_sha256": "0" * 64})
    for dictionary in variants:
        tool("render_genomics_publication", {**args, "display_dictionary": dictionary}, error=True)
    assert not (project.output_dir / "figures/editions").exists()
