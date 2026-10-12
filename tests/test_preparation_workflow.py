"""Approval, immutable evidence, restarts and source drift are separate gates."""

import json
import uuid
from types import SimpleNamespace

import pytest

from rde.infrastructure.preparation import workflow
from test_preparation_engine import fixture


def setup(tmp_path):
    inputs, spec, _ = fixture(tmp_path)
    inputs = [s.model_copy(update={"synthetic": True}).model_dump() for s in inputs]
    project = SimpleNamespace(id="123abcde", output_dir=tmp_path / "output")
    request = {
        "op": "draft",
        "preparation_id": str(uuid.uuid4()),
        "sources": inputs,
        "specification": spec,
        "reason": "Prewritten synthetic multi-table acceptance case",
        "author": "test-agent",
    }
    return project, request


def approve(project, plan):
    page = workflow.execute(
        project,
        {
            "op": "page",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "section": "units",
            "limit": 2,
        },
    )
    return workflow.execute(
        project,
        {
            "op": "approve",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "acknowledged_warnings": plan["summary"]["warnings"],
            "reviewer": "synthetic-oracle",
            "review": {
                "kind": "synthetic_oracle",
                "denominator_confirmed": True,
                "reviewed_unit_ids": [r["unit_id"] for r in page["records"]],
                "notes": "Compared with predeclared truth and independent SQLite; not clinical validation",
            },
        },
    )


def test_immutable_draft_approval_release_and_restart(tmp_path):
    project, request = setup(tmp_path)
    plan = workflow.execute(project, request)
    assert plan["summary"]["population"]["subjects"] == 6
    assert workflow.execute(project, request) == plan
    approval = approve(project, plan)
    release_request = {
        "op": "release",
        "preparation_id": plan["preparation_id"],
        "expected_sha256": plan["receipt_sha256"],
        "approval_sha256": approval["receipt_sha256"],
    }
    released = workflow.execute(project, release_request)
    assert released["clinical_validation"] == "synthetic_only"
    # A new project object/process needs no in-memory workflow state.
    restarted = SimpleNamespace(id=project.id, output_dir=project.output_dir)
    assert workflow.execute(restarted, release_request) == released
    read = workflow.execute(restarted, {"op": "read", "preparation_id": plan["preparation_id"]})
    assert read == {"plan": plan, "approval": approval, "release": released}


def test_agent_preview_executes_the_contract_without_approving_or_saving_a_version(tmp_path):
    project, request = setup(tmp_path)
    result = workflow.execute(
        project,
        {"op": "preview", "sources": request["sources"], "specification": request["specification"]},
    )
    assert result["advisory_only"] is True
    assert result["summary"]["population"]["subjects"] == 6
    assert not (workflow.directory(project) / "versions").exists()
    assert not any("values" in issue for issue in result["issues"])
    request["specification"]["relations"][0]["filters"] = [
        {"column": "known_at", "op": "lte", "value": "${index_at}"}
    ]
    with pytest.raises(ValueError, match="date comparisons.*window"):
        workflow.execute(
            project,
            {
                "op": "preview",
                "sources": request["sources"],
                "specification": request["specification"],
            },
        )


def test_changed_source_blocks_approval_but_retained_trace_remains_readable(tmp_path):
    project, request = setup(tmp_path)
    plan = workflow.execute(project, request)
    from pathlib import Path

    Path(request["sources"][1]["path"]).write_text("changed source\n")
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        approve(project, plan)
    units = workflow.execute(
        project,
        {
            "op": "page",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "section": "output",
        },
    )
    patient = next(
        r for r in units["records"] if r["values"]["site"] == "A" and r["values"]["pid"] == "001"
    )
    trace = workflow.execute(
        project,
        {
            "op": "trace",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "unit_id": patient["unit_id"],
            "column": "lab_mean",
            "limit": 2,
        },
    )
    assert trace["value"] == 20
    assert [r["values"]["value"] for r in trace["source_records"]] == ["10", "20"]
    assert trace["next_offset"] == 2


def test_source_and_recipe_revisions_never_mutate_parent(tmp_path):
    project, request = setup(tmp_path)
    parent = workflow.execute(project, request)
    original = workflow.inventory(
        project.output_dir / "artifacts/data_preparation/versions" / parent["preparation_id"]
    )
    request["specification"]["relations"][0]["window"]["start_days"] = -2
    with pytest.raises(ValueError, match="IMMUTABLE_CONFLICT"):
        workflow.execute(project, request)
    request["preparation_id"] = str(uuid.uuid4())
    request["parent"] = {
        "preparation_id": parent["preparation_id"],
        "receipt_sha256": parent["receipt_sha256"],
    }
    revised = workflow.execute(project, request)
    assert revised["parent"] == request["parent"]
    assert revised["files"]["analysis.csv"]["sha256"] != parent["files"]["analysis.csv"]["sha256"]
    assert (
        workflow.inventory(
            project.output_dir / "artifacts/data_preparation/versions" / parent["preparation_id"]
        )
        == original
    )


@pytest.mark.parametrize(
    "file", ["analysis.csv", "trace.jsonl", "validation.json", "specification.json"]
)
def test_tampered_evidence_cannot_be_approved_or_read_as_verified(tmp_path, file):
    project, request = setup(tmp_path)
    plan = workflow.execute(project, request)
    path = (
        project.output_dir / "artifacts/data_preparation/versions" / plan["preparation_id"] / file
    )
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="CORRUPT_PREPARATION"):
        workflow.execute(project, {"op": "read", "preparation_id": plan["preparation_id"]})


def test_foreign_project_and_stale_review_are_rejected(tmp_path):
    project, request = setup(tmp_path)
    plan = workflow.execute(project, request)
    with pytest.raises(ValueError, match="ownership"):
        workflow.execute(
            SimpleNamespace(id="another", output_dir=project.output_dir),
            {"op": "read", "preparation_id": plan["preparation_id"]},
        )
    with pytest.raises(ValueError, match="STALE_PREPARATION"):
        workflow.execute(
            project,
            {"op": "page", "preparation_id": plan["preparation_id"], "expected_sha256": "0" * 64},
        )


def test_interrupted_draft_resumes_without_duplicate_final_version(tmp_path, monkeypatch):
    project, request = setup(tmp_path)
    actual = workflow.engine.Evaluation.evaluate

    def fail(_self):
        raise RuntimeError("simulated worker interruption")

    monkeypatch.setattr(workflow.engine.Evaluation, "evaluate", fail)
    with pytest.raises(RuntimeError, match="interruption"):
        workflow.execute(project, request)
    monkeypatch.setattr(workflow.engine.Evaluation, "evaluate", actual)
    result = workflow.execute(project, request)
    assert result["summary"]["ready_for_approval"]
    root = project.output_dir / "artifacts/data_preparation"
    assert len(list((root / "versions").iterdir())) == 1
    assert len(list((root / "attempts" / request["preparation_id"]).iterdir())) == 2
    failures = list((root / "attempts").rglob("failed.json"))
    assert len(failures) == 1 and "interruption" in json.loads(failures[0].read_text())["message"]


def test_missing_definitions_cannot_be_approved(tmp_path):
    project, request = setup(tmp_path)
    request["specification"]["definitions"] = {}
    plan = workflow.execute(project, request)
    assert plan["summary"]["blockers"] == 4
    with pytest.raises(ValueError, match="QUALITY_BLOCKED"):
        approve(project, plan)
