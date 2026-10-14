"""Native aggregation is typed editing, not another analysis engine."""

import json
import uuid
from copy import deepcopy
from types import SimpleNamespace

import pytest

from rde.infrastructure.preparation import aggregation, workflow
from rde.infrastructure.preparation.sources import canonical, load
from test_preparation_engine import fixture, source


def compose(tmp_path, specification=None):
    inputs, spec, _ = fixture(tmp_path)
    project = SimpleNamespace(id="aggregation-test", output_dir=tmp_path / "output")
    request = {
        "op": "aggregation_compose",
        "candidate_id": str(uuid.uuid4()),
        "revision_id": str(uuid.uuid4()),
        "sources": [s.model_dump() for s in inputs],
        "from_specification": specification or spec,
        "author": "test-agent",
        "reason": "Predeclared synthetic aggregation test",
    }
    return project, request, workflow.execute(project, request)


def patch_request(candidate, operations):
    return {
        "op": "aggregation_patch",
        "candidate_ref": candidate["candidate_ref"],
        "revision_id": str(uuid.uuid4()),
        "operations": operations,
        "author": "test-agent",
        "reason": "Explicit local rule revision",
    }


def test_registry_covers_all_ten_native_methods_and_lookup_constraints(tmp_path):
    contract = workflow.execute(None, {"op": "contract"})["aggregation"]
    methods = {m["id"]: m for m in contract["methods"]}
    assert len(methods) == 10
    assert [k for k, v in methods.items() if "lookup" in v["relation_kinds"]] == ["unique"]
    assert methods["last"]["window_required"]
    assert not methods["count"]["column_required"]
    assert "missing" in methods["count"]["description"]
    assert "not a list" in methods["unique"]["description"]
    assert "at_index_basis" in methods["mean"]["output_role"]
    assert contract["operation_schema"]["discriminator"]["propertyName"] == "op"
    assert not (tmp_path / "output").exists()


def test_minimal_candidate_keeps_unknown_definitions_and_sources_unresolved(tmp_path):
    inputs, spec, _ = fixture(tmp_path)
    project = SimpleNamespace(id="partial-test", output_dir=tmp_path / "out")
    request = {
        "op": "aggregation_compose",
        "candidate_id": str(uuid.uuid4()),
        "revision_id": str(uuid.uuid4()),
        "sources": [s.model_dump() for s in inputs],
        "unit": spec["unit"],
        "author": "agent",
        "reason": "Start with known unit only",
    }
    candidate = workflow.execute(project, request)
    assert candidate["specification"]["omitted_sources"] == {}
    assert all(not value for value in candidate["specification"]["definitions"].values())
    assert len([d for d in candidate["diagnostics"] if d["code"].startswith("DEFINITION_")]) == 4
    preview = workflow.execute(
        project, {"op": "aggregation_preview", "candidate_ref": candidate["candidate_ref"]}
    )
    assert preview["summary"] is None
    assert not preview["ready_for_draft"]
    assert {
        d["source_id"] for d in preview["diagnostics"] if d["code"] == "SOURCE_RULE_REQUIRED"
    } == {"labs", "meds"}
    with pytest.raises(aggregation.EditRejected):
        workflow.execute(
            project,
            {
                "op": "draft",
                "preparation_id": str(uuid.uuid4()),
                "candidate_ref": candidate["candidate_ref"],
                "author": "agent",
                "reason": "cannot bypass",
            },
        )
    assert not (project.output_dir / "artifacts/data_preparation/versions").exists()


def test_patch_is_local_immutable_replayable_and_stale_base_is_rejected(tmp_path):
    project, request, original = compose(tmp_path)
    operation = {
        "op": "feature_set",
        "relation_id": "labs",
        "feature": {
            **original["specification"]["relations"][0]["features"][1],
            "aggregate": "last",
        },
    }
    change = patch_request(original, [operation])
    revised = workflow.execute(project, change)
    assert revised["candidate_ref"]["revision"] == 2
    assert (
        revised["candidate_ref"]["source_set_sha256"]
        == original["candidate_ref"]["source_set_sha256"]
    )
    for field in ["unit", "definitions", "cohort", "excluded_rows", "omitted_sources"]:
        assert canonical(revised["specification"][field]) == canonical(
            original["specification"][field]
        )
    assert revised["specification"]["relations"][1] == original["specification"]["relations"][1]
    assert revised["diff"]["changes"] == [
        {
            "component": "relations",
            "relation_id": "labs",
            "feature_output": "lab_mean",
            "field": "aggregate",
            "before": "mean",
            "after": "last",
        }
    ]
    restarted = SimpleNamespace(id=project.id, output_dir=project.output_dir)
    assert workflow.execute(restarted, change) == revised
    assert workflow.execute(restarted, request) == original
    assert (
        workflow.execute(
            project, {"op": "aggregation_read", "candidate_ref": original["candidate_ref"]}
        )
        == original
    )
    with pytest.raises(ValueError, match="STALE_CANDIDATE"):
        workflow.execute(project, patch_request(original, [operation]))
    with pytest.raises(ValueError, match="IMMUTABLE_CONFLICT"):
        workflow.execute(project, {**change, "reason": "changed intent"})


def test_exact_conflicting_feature_is_reported_without_blaming_lookup(tmp_path):
    inputs, spec, raw = fixture(tmp_path)
    header = load(inputs[1]).columns
    inputs[1] = source(
        tmp_path,
        "labs",
        header,
        raw[1]
        + [
            ["b1", "B", "001", "2025-01-07", "2025-01-07", 15],
            ["b2", "B", "001", "2025-01-08", "2025-01-08", 17],
        ],
    )
    spec["relations"][0]["features"][1]["aggregate"] = "last"
    spec["relations"][0]["features"].append(
        {
            "output": "whole_window_unique",
            "column": "value",
            "aggregate": "unique",
            "value_type": "number",
        }
    )
    spec["relations"].append(
        {
            "id": "patients_lookup",
            "source_id": "people",
            "left_keys": ["site", "pid"],
            "right_keys": ["site", "pid"],
            "kind": "lookup",
            "features": [
                {
                    "output": "linked_age",
                    "column": "age",
                    "aggregate": "unique",
                    "value_type": "number",
                }
            ],
            "reason": "Known self-lookup used only to test rule identity",
        }
    )
    project = SimpleNamespace(id="located-test", output_dir=tmp_path / "out")
    candidate = workflow.execute(
        project,
        {
            "op": "aggregation_compose",
            "candidate_id": str(uuid.uuid4()),
            "revision_id": str(uuid.uuid4()),
            "sources": [s.model_dump() for s in inputs],
            "from_specification": spec,
            "author": "agent",
            "reason": "Predeclared wrong-unique case",
        },
    )
    preview = workflow.execute(
        project, {"op": "aggregation_preview", "candidate_ref": candidate["candidate_ref"]}
    )
    conflicts = [d for d in preview["diagnostics"] if d["code"] == "UNIQUE_VALUE_CONFLICT"]
    assert len(conflicts) == 1
    assert conflicts[0]["relation_id"] == "labs"
    assert conflicts[0]["feature_output"] == "whole_window_unique"
    assert conflicts[0]["errorStage"] == "feature_aggregation"
    assert conflicts[0]["occurrence_count"] == 2
    assert len(conflicts[0]["unit_ids"]) == 2
    wrong = workflow.execute(
        project,
        patch_request(
            candidate,
            [
                {
                    "op": "feature_set",
                    "relation_id": "patients_lookup",
                    "feature": {
                        "output": "linked_age",
                        "column": "age",
                        "aggregate": "first",
                        "value_type": "number",
                    },
                }
            ],
        ),
    )
    assert wrong["schema"] == "rde-aggregation-edit-rejected-v1"
    assert wrong["diagnostics"][0]["relation_id"] == "patients_lookup"
    assert wrong["diagnostics"][0]["feature_output"] == "linked_age"
    assert wrong["diagnostics"][0]["allowed_methods"] == ["unique"]
    fixed = workflow.execute(
        project,
        patch_request(
            candidate,
            [
                {
                    "op": "feature_remove",
                    "relation_id": "labs",
                    "feature_output": "whole_window_unique",
                }
            ],
        ),
    )
    assert fixed["candidate_ref"]["revision"] == 2  # rejected edit never persisted
    assert fixed["specification"]["relations"][-1] == candidate["specification"]["relations"][-1]
    good = workflow.execute(
        project, {"op": "aggregation_preview", "candidate_ref": fixed["candidate_ref"]}
    )
    assert good["ready_for_draft"]
    assert good["summary"]["population"]["subjects"] == 6


def test_complete_candidate_drafts_through_existing_approval_release_and_matches_engine(tmp_path):
    project, _, candidate = compose(tmp_path)
    preview = workflow.execute(
        project, {"op": "aggregation_preview", "candidate_ref": candidate["candidate_ref"]}
    )
    assert preview["ready_for_draft"]
    assert preview["clinical_validation"] == "not_performed"
    request = {
        "op": "draft",
        "preparation_id": str(uuid.uuid4()),
        "candidate_ref": candidate["candidate_ref"],
        "author": "agent",
        "reason": "Freeze exact candidate",
    }
    plan = workflow.execute(project, request)
    assert plan["candidate_ref"] == candidate["candidate_ref"]
    assert plan["specification"] == candidate["specification"]
    assert plan["summary"] == preview["summary"]
    audit = workflow.execute(
        project,
        {
            "op": "automated_review",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
        },
    )
    approval = workflow.execute(
        project,
        {
            "op": "approve",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "acknowledged_warnings": plan["summary"]["warnings"],
            "reviewer": "technical-tests",
            "review": {
                "kind": "automated_checks",
                "denominator_confirmed": True,
                "reviewed_unit_ids": audit["reviewed_unit_ids"],
                "automated_receipt_sha256": audit["receipt_sha256"],
                "notes": "Technical consistency only; not clinical validation",
            },
        },
    )
    release = workflow.execute(
        project,
        {
            "op": "release",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "approval_sha256": approval["receipt_sha256"],
        },
    )
    assert release["clinical_validation"] == "not_performed"
    with pytest.raises(ValueError, match="cannot be mixed"):
        workflow.execute(project, {**request, "specification": candidate["specification"]})


@pytest.mark.parametrize("mutation", ["source", "reference", "owner", "receipt"])
def test_source_hash_project_and_candidate_integrity_guards(tmp_path, mutation):
    project, request, candidate = compose(tmp_path)
    ref = deepcopy(candidate["candidate_ref"])
    if mutation == "source":
        with open(request["sources"][0]["path"], "ab") as stream:
            stream.write(b"\n")
    elif mutation == "reference":
        ref["specification_sha256"] = "0" * 64
    elif mutation == "owner":
        project = SimpleNamespace(id="foreign-project", output_dir=project.output_dir)
    else:
        path = (
            project.output_dir
            / "artifacts/data_preparation/candidates"
            / ref["candidate_id"]
            / (ref["revision_id"] + ".json")
        )
        value = json.loads(path.read_text())
        value["specification"]["unit"]["kind"] = "encounter"
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        workflow.execute(project, {"op": "aggregation_preview", "candidate_ref": ref})


def test_invalid_atomic_edits_do_not_change_previous_candidate(tmp_path):
    project, _, candidate = compose(tmp_path)
    attempts = [
        [
            {"op": "window_set", "relation_id": "labs", "window": None},
            {
                "op": "feature_set",
                "relation_id": "labs",
                "feature": {
                    "output": "lab_mean",
                    "column": "value",
                    "aggregate": "last",
                    "value_type": "number",
                },
            },
        ],
        [
            {"op": "feature_remove", "relation_id": "labs", "feature_output": "lab_count"},
            {"op": "feature_remove", "relation_id": "labs", "feature_output": "lab_mean"},
        ],
        [
            {
                "op": "filters_set",
                "relation_id": "labs",
                "filters": [{"column": "value", "op": "gte", "value": "index_at - 24 hours"}],
            }
        ],
        [{"op": "replace", "path": "/sources/0/path", "value": "arbitrary.py"}],
        [
            {
                "op": "unit_set",
                "unit": {**candidate["specification"]["unit"], "source_id": "foreign"},
            }
        ],
    ]
    for operations in attempts:
        result = workflow.execute(project, patch_request(candidate, operations))
        assert result["status"] == "rejected"
    assert (
        workflow.execute(
            project, {"op": "aggregation_read", "candidate_ref": candidate["candidate_ref"]}
        )
        == candidate
    )
    files = list(
        (
            project.output_dir
            / "artifacts/data_preparation/candidates"
            / candidate["candidate_ref"]["candidate_id"]
        ).glob("*.json")
    )
    assert len(files) == 1


def test_typed_patch_blocks_dangling_after_link_cohort_and_does_not_infer_omissions(tmp_path):
    project, _, candidate = compose(tmp_path)
    linked = workflow.execute(
        project,
        patch_request(
            candidate,
            [
                {
                    "op": "cohort_set",
                    "rule": {
                        "id": "observed",
                        "stage": "after_links",
                        "reason": "Explicit synthetic cohort example",
                        "keep": {"column": "lab_mean", "op": "present"},
                    },
                }
            ],
        ),
    )
    rejected = workflow.execute(
        project,
        patch_request(
            linked, [{"op": "feature_remove", "relation_id": "labs", "feature_output": "lab_mean"}]
        ),
    )
    assert rejected["status"] == "rejected"
    assert rejected["diagnostics"][0]["code"] == "COHORT_DEPENDENCY_MISSING"
    revised = workflow.execute(
        project,
        patch_request(
            linked,
            [
                {"op": "cohort_remove", "rule_id": "observed"},
                {"op": "relation_remove", "relation_id": "labs"},
            ],
        ),
    )
    assert revised["specification"]["omitted_sources"] == {}
    assert any(
        d.get("source_id") == "labs" and d["code"] == "SOURCE_RULE_REQUIRED"
        for d in revised["diagnostics"]
    )


def test_preview_pages_trace_exact_members_and_diff_counts_without_reexecution(
    tmp_path, monkeypatch
):
    project, _, candidate = compose(tmp_path)
    first = workflow.execute(
        project, {"op": "aggregation_preview", "candidate_ref": candidate["candidate_ref"]}
    )
    request = {
        "op": "aggregation_read",
        "candidate_ref": candidate["candidate_ref"],
        "preview_sha256": first["preview_sha256"],
        "section": "output",
        "limit": 100,
    }
    page = workflow.execute(project, request)
    assert page["total"] == 6
    row = next(
        r for r in page["records"] if r["values"]["site"] == "A" and r["values"]["pid"] == "001"
    )
    trace_request = {
        **request,
        "section": "trace",
        "unit_id": row["unit_id"],
        "column": "lab_mean",
        "limit": 2,
    }
    trace = workflow.execute(project, trace_request)
    assert trace["value"] == 20
    assert trace["total"] == 3 and trace["next_offset"] == 2
    rest = workflow.execute(project, {**trace_request, "offset": 2})
    assert {r["values"]["lab_id"] for r in trace["source_records"] + rest["source_records"]} == {
        "l1",
        "l2",
        "l3",
    }
    assert all(r["reference"]["source_sha256"] for r in trace["source_records"])
    assert rest["next_offset"] is None
    revised = workflow.execute(
        project,
        patch_request(
            candidate,
            [
                {
                    "op": "feature_set",
                    "relation_id": "labs",
                    "feature": {
                        "output": "lab_mean",
                        "column": "value",
                        "aggregate": "last",
                        "value_type": "number",
                    },
                }
            ],
        ),
    )
    second = workflow.execute(
        project, {"op": "aggregation_preview", "candidate_ref": revised["candidate_ref"]}
    )
    diff = workflow.execute(
        project,
        {
            "op": "aggregation_diff",
            "before": candidate["candidate_ref"],
            "after": revised["candidate_ref"],
        },
    )
    assert diff["outcomes"]["changed_value_units_by_column"] == {"lab_mean": 1}
    assert diff["outcomes"]["changed_member_units_by_column"] == {"lab_mean": 1}
    assert diff["outcomes"]["added_units"] == diff["outcomes"]["removed_units"] == 0
    with pytest.raises(ValueError, match="STALE_PREVIEW"):
        workflow.execute(project, {**request, "preview_sha256": second["preview_sha256"]})
    from rde.infrastructure.preparation.engine import Evaluation

    monkeypatch.setattr(
        Evaluation, "evaluate", lambda *_: pytest.fail("retained preview must not reevaluate")
    )
    assert (
        workflow.execute(
            project, {"op": "aggregation_preview", "candidate_ref": candidate["candidate_ref"]}
        )
        == first
    )
    assert workflow.execute(project, trace_request) == trace


def test_preview_integrity_rejects_tampered_trace_even_when_metadata_unchanged(tmp_path):
    project, _, candidate = compose(tmp_path)
    result = workflow.execute(
        project, {"op": "aggregation_preview", "candidate_ref": candidate["candidate_ref"]}
    )
    ref = candidate["candidate_ref"]
    path = (
        project.output_dir
        / "artifacts/data_preparation/candidates"
        / ref["candidate_id"]
        / "previews"
        / ref["revision_id"]
        / "trace.jsonl"
    )
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="CORRUPT_PREPARATION"):
        workflow.execute(
            project,
            {
                "op": "aggregation_read",
                "candidate_ref": ref,
                "preview_sha256": result["preview_sha256"],
                "section": "units",
            },
        )


def test_selection_flow_distinguishes_event_pairs_units_and_repeated_subjects(tmp_path):
    people = source(
        tmp_path,
        "encounters",
        ["visit", "pid", "index_at"],
        [["e1", "001", "2025-01-10"], ["e2", "001", "2025-01-10"], ["e3", "002", "2025-01-10"]],
    )
    events = source(
        tmp_path,
        "events",
        ["event", "pid", "time", "available", "code", "value"],
        [
            ["l1", "001", "2025-01-09", "2025-01-09", "A", 10],
            ["l2", "001", "2025-01-09", "2025-01-11", "A", 20],
            ["l3", "001", "2025-01-08", "2025-01-08", "A", 30],
            ["l4", "001", "2025-01-09", "2025-01-09", "B", 40],
            ["l5", "001", "2025-01-09", "2025-01-09", "A", 25],
        ],
    )
    spec = {
        "unit": {
            "source_id": "encounters",
            "kind": "encounter",
            "keys": ["visit"],
            "subject_keys": ["pid"],
            "index_column": "index_at",
        },
        "relations": [
            {
                "id": "lab",
                "source_id": "events",
                "left_keys": ["pid"],
                "right_keys": ["pid"],
                "record_keys": ["event"],
                "kind": "events",
                "reuse_events": "allow",
                "reason": "Explicit identical overlapping encounters for accounting regression",
                "window": {
                    "event_column": "time",
                    "available_column": "available",
                    "start_days": -1,
                    "end_days": 0,
                },
                "filters": [
                    {"column": "code", "op": "eq", "value": "A"},
                    {"column": "value", "op": "gte", "value": 15},
                ],
                "features": [
                    {"output": "events_count", "aggregate": "count"},
                    {
                        "output": "lab_mean",
                        "column": "value",
                        "aggregate": "mean",
                        "value_type": "number",
                    },
                ],
            }
        ],
        "definitions": {
            "unit": "One declared encounter; repeated subjects counted separately",
            "linkage": "Synthetic exact patient namespace",
            "time": "UTC baseline one day and explicit result availability",
            "missingness": "Unknown coverage remains unknown, not zero",
        },
    }
    project = SimpleNamespace(id="flow-test", output_dir=tmp_path / "out")
    candidate = workflow.execute(
        project,
        {
            "op": "aggregation_compose",
            "candidate_id": str(uuid.uuid4()),
            "revision_id": str(uuid.uuid4()),
            "sources": [s.model_dump() for s in [people, events]],
            "from_specification": spec,
            "author": "test",
            "reason": "Predeclared source count truth",
        },
    )
    result = workflow.execute(
        project, {"op": "aggregation_preview", "candidate_ref": candidate["candidate_ref"]}
    )
    assert result["ready_for_draft"]
    summary = result["summary"]
    assert summary["population"]["units"] == 3 and summary["population"]["subjects"] == 2
    flow = summary["relationships"][0]["selection_flow"]
    assert [s["event_pairs"] for s in flow] == [10, 8, 6, 4, 2]
    assert [s["distinct_source_records"] for s in flow] == [5, 4, 3, 2, 1]
    assert [s["stage"] for s in flow] == [
        "linked",
        "filter",
        "filter",
        "event_window",
        "availability",
    ]
    assert all(
        s["analysis_units_with_records"] == 2 and s["subjects_with_records"] == 1 for s in flow
    )
    assert all(
        s["evaluated_analysis_units"] == s["analysis_units_at_relation_start"] == 3 for s in flow
    )
    assert summary["feature_quality"]["lab_mean"] == {"observed": 2, "missing": 1}
    assert summary["relationships"][0]["statuses"] == {"matched_partial": 2, "unknown_coverage": 1}


def test_interrupted_commit_replays_one_exact_candidate_revision(tmp_path, monkeypatch):
    project, _, candidate = compose(tmp_path)
    request = patch_request(
        candidate,
        [
            {
                "op": "definition_set",
                "field": "missingness",
                "value": "Retain unknown linkage and missing values; never turn them into zero",
            }
        ],
    )
    original_seal = workflow.seal
    committed = []

    def lost_response(path, payload):
        result = original_seal(path, payload)
        if path.name == request["revision_id"] + ".json":
            committed.append(result)
            raise OSError("simulated interruption after immutable commit")
        return result

    monkeypatch.setattr(workflow, "seal", lost_response)
    with pytest.raises(OSError, match="simulated interruption"):
        workflow.execute(project, request)
    monkeypatch.setattr(workflow, "seal", original_seal)
    restarted = SimpleNamespace(id=project.id, output_dir=project.output_dir)
    result = workflow.execute(restarted, request)
    assert result["candidate_ref"]["receipt_sha256"] == committed[0]["receipt_sha256"]
    assert result["candidate_ref"]["revision"] == 2
    assert (
        len(
            list(
                (
                    project.output_dir
                    / "artifacts/data_preparation/candidates"
                    / candidate["candidate_ref"]["candidate_id"]
                ).glob("*.json")
            )
        )
        == 2
    )


def test_patch_schema_error_keeps_target_locator_and_history_parent_is_verified(tmp_path):
    project, _, candidate = compose(tmp_path)
    rejected = workflow.execute(
        project,
        patch_request(
            candidate,
            [
                {
                    "op": "feature_set",
                    "relation_id": "labs",
                    "feature": {
                        "output": "lab_mean",
                        "column": "value",
                        "aggregate": "mean",
                        "value_type": "text",
                    },
                }
            ],
        ),
    )
    assert rejected["status"] == "rejected"
    assert rejected["diagnostics"][0]["relation_id"] == "labs"
    assert rejected["diagnostics"][0]["feature_output"] == "lab_mean"
    changed = workflow.execute(
        project,
        patch_request(
            candidate,
            [
                {
                    "op": "definition_set",
                    "field": "unit",
                    "value": "Same unit; explicit revision for history test",
                }
            ],
        ),
    )
    ref = candidate["candidate_ref"]
    (
        project.output_dir
        / "artifacts/data_preparation/candidates"
        / ref["candidate_id"]
        / (ref["revision_id"] + ".json")
    ).unlink()
    with pytest.raises(ValueError, match="CORRUPT_CANDIDATE"):
        workflow.execute(
            project, {"op": "aggregation_read", "candidate_ref": changed["candidate_ref"]}
        )
