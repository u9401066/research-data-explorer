"""Native automatic checks cannot masquerade as clinical or independent review."""

import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from rde.domain.models.preparation import Review
from rde.infrastructure.preparation import portable, workflow
from test_preparation_engine import source
from test_preparation_workflow import approve as synthetic_approve, setup


def prepared(tmp_path):
    project, request = setup(tmp_path)
    # Deliberately use the real-source policy, not the synthetic-oracle bypass.
    for value in request["sources"]:
        value["synthetic"] = False
    return project, workflow.execute(project, request), request


def call(project, plan, op, **kwargs):
    return workflow.execute(
        project,
        {
            "op": op,
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            **kwargs,
        },
    )


def approval_request(plan, audit):
    return {
        "op": "approve",
        "preparation_id": plan["preparation_id"],
        "expected_sha256": plan["receipt_sha256"],
        "acknowledged_warnings": plan["summary"]["warnings"],
        "reviewer": "test-automatic-agent",
        "review": {
            "kind": "automated_checks",
            "denominator_confirmed": True,
            "automated_receipt_sha256": audit["receipt_sha256"],
            "reviewed_unit_ids": audit["reviewed_unit_ids"],
            "notes": "Complete technical consistency checks; no clinical or human attestation.",
        },
    }


def version_folder(project, plan):
    return workflow.directory(project) / "versions" / plan["preparation_id"]


def reseal_test_file(path, payload):
    """Adversarial fixture only: make a hash-consistent but inconsistent claim."""
    path.write_text(
        workflow.canonical({**payload, "receipt_sha256": workflow.digest(payload)}) + "\n"
    )


def rebind_test_plan(project, plan, filename=None):
    folder = version_folder(project, plan)
    if filename:
        path = folder / filename
        plan["files"][filename] = {"sha256": workflow.file_hash(path), "bytes": path.stat().st_size}
    reseal_test_file(folder / "plan.json", {k: v for k, v in plan.items() if k != "receipt_sha256"})
    return workflow.read_sealed(folder / "plan.json")


def test_real_source_technical_review_restarts_and_releases_without_clinical_attestation(tmp_path):
    project, plan, _ = prepared(tmp_path)
    with pytest.raises(ValueError, match="real sources cannot be approved"):
        synthetic_approve(project, plan)
    audit = call(project, plan, "automated_review")
    assert audit["schema"] == "rde-preparation-automated-checks-v1"
    assert audit["clinical_validation"] == "not_performed"
    assert audit["review_scope"] == "automated_checks_only"
    assert audit["population"] == plan["summary"]["population"]
    assert audit["checked_counts"] == {
        "trace_units": 7,
        "included_units": 6,
        "analysis_jsonl_rows": 6,
        "analysis_csv_rows": 6,
    }
    assert len(audit["reviewed_unit_ids"]) == 6
    assert audit["reviewed_unit_ids"] == sorted(set(audit["reviewed_unit_ids"]))
    assert call(project, plan, "automated_review") == audit
    # A genuinely separate process can reuse the immutable audit, without memory state.
    child = """
import json, sys
from pathlib import Path
from types import SimpleNamespace
from rde.infrastructure.preparation.workflow import execute
payload=json.loads(sys.stdin.read())
p=SimpleNamespace(id=payload['project_id'], output_dir=Path(payload['output_dir']))
print(json.dumps(execute(p,payload['request'])))
"""
    response = subprocess.run(
        [sys.executable, "-c", child],
        input=json.dumps(
            {
                "project_id": project.id,
                "output_dir": str(project.output_dir),
                "request": {
                    "op": "automated_review",
                    "preparation_id": plan["preparation_id"],
                    "expected_sha256": plan["receipt_sha256"],
                },
            }
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert json.loads(response.stdout) == audit
    approval = workflow.execute(project, approval_request(plan, audit))
    assert approval["clinical_validation"] == "not_performed"
    assert workflow.execute(project, approval_request(plan, audit)) == approval
    release = call(project, plan, "release", approval_sha256=approval["receipt_sha256"])
    assert release["clinical_validation"] == "not_performed"
    assert release["population"]["subjects"] == 6


def test_every_encounter_checked_but_sample_is_bounded_and_subjects_not_rows(tmp_path):
    project, request = setup(tmp_path)
    encounters = source(
        tmp_path,
        "encounters",
        ["visit", "patient", "age", "note"],
        [
            [f"v{i:03}", f"p{i//2:03}", 17 if i == 0 else 40, 'a,"b"\nNA']
            for i in reversed(range(130))
        ],
    )
    request["sources"] = [encounters.model_dump()]
    request["specification"] = {
        "unit": {
            "source_id": "encounters",
            "kind": "encounter",
            "keys": ["visit"],
            "subject_keys": ["patient"],
        },
        "cohort": [
            {
                "id": "adult",
                "reason": "Fixed adult cohort",
                "keep": {"column": "age", "op": "gte", "value": 18},
            }
        ],
        "definitions": {
            key: "Declared fixture definition" for key in ("unit", "linkage", "time", "missingness")
        },
    }
    plan = workflow.execute(project, request)
    audit = call(project, plan, "automated_review")
    assert audit["population"] == {
        "rows": 129,
        "units": 129,
        "subjects": 65,
        "unit_kind": "encounter",
        "encounters": 129,
        "events": None,
    }
    trace = list(workflow.lines(version_folder(project, plan) / "trace.jsonl"))
    included = sorted(row["unit_id"] for row in trace if row["included"])
    assert audit["reviewed_unit_ids"] == included[:100]
    assert audit["checked_counts"]["analysis_csv_rows"] == 129
    assert not set(audit["reviewed_unit_ids"]) & {r["unit_id"] for r in trace if not r["included"]}


@pytest.mark.parametrize("kind", ["data_manager", "synthetic_oracle"])
@pytest.mark.parametrize("value", [None, "0" * 64])
def test_other_review_kinds_reject_an_automatic_receipt_even_null(kind, value):
    with pytest.raises(ValueError, match="only automated_checks"):
        Review.model_validate(
            {
                "kind": kind,
                "denominator_confirmed": True,
                "reviewed_unit_ids": ["u_actual"],
                "notes": "Review",
                "automated_receipt_sha256": value,
            }
        )


def test_missing_hash_or_missing_server_audit_cannot_be_replaced_by_caller_true(tmp_path):
    project, plan, _ = prepared(tmp_path)
    unit = next(
        r for r in workflow.lines(version_folder(project, plan) / "trace.jsonl") if r["included"]
    )
    request = approval_request(
        plan, {"receipt_sha256": "0" * 64, "reviewed_unit_ids": [unit["unit_id"]]}
    )
    with pytest.raises(ValueError, match="AUTOMATED_REVIEW_REQUIRED"):
        workflow.execute(project, request)
    del request["review"]["automated_receipt_sha256"]
    with pytest.raises(ValueError, match="requires a server-generated"):
        workflow.execute(project, request)
    assert not (version_folder(project, plan) / "approval.json").exists()
    with pytest.raises(ValueError, match="unknown preparation operation or fields"):
        call(project, plan, "automated_review", checks_passed=True)


@pytest.mark.parametrize(
    "change", ["wrong_hash", "wrong_units", "reordered_units", "not_confirmed", "warnings"]
)
def test_automatic_approval_pins_exact_hash_sample_and_existing_review_gates(tmp_path, change):
    project, plan, _ = prepared(tmp_path)
    audit = call(project, plan, "automated_review")
    request = approval_request(plan, audit)
    expected = "AUTOMATED_REVIEW_SAMPLE"
    if change == "wrong_hash":
        request["review"]["automated_receipt_sha256"] = "0" * 64
        expected = "STALE_AUTOMATED_REVIEW"
    elif change == "wrong_units":
        request["review"]["reviewed_unit_ids"] = audit["reviewed_unit_ids"][:-1]
    elif change == "reordered_units":
        request["review"]["reviewed_unit_ids"] = list(reversed(audit["reviewed_unit_ids"]))
    elif change == "not_confirmed":
        request["review"]["denominator_confirmed"] = False
        expected = "review the source"
    else:
        request["acknowledged_warnings"] = []
        expected = "exact current warning list"
    with pytest.raises(ValueError, match=expected):
        workflow.execute(project, request)
    assert not (version_folder(project, plan) / "approval.json").exists()


@pytest.mark.parametrize(
    "mutation", ["source", "snapshot", "csv", "audit", "audit_resealed", "implementation"]
)
def test_stale_or_tampered_evidence_blocks_auto_approval(tmp_path, monkeypatch, mutation):
    project, plan, request = prepared(tmp_path)
    audit = call(project, plan, "automated_review")
    folder = version_folder(project, plan)
    expected = "CORRUPT_PREPARATION"
    if mutation == "source":
        Path(request["sources"][0]["path"]).write_text("changed\n")
        expected = "SOURCE_CHANGED"
    elif mutation == "snapshot":
        (workflow.directory(project) / plan["source_snapshots"][0]["snapshot"]).write_text(
            "changed\n"
        )
    elif mutation == "csv":
        (folder / "analysis.csv").write_text("changed\n")
    elif mutation in {"audit", "audit_resealed"}:
        audit["clinical_validation"] = "manager_attestation"
        if mutation == "audit":
            (folder / "automated_review.json").write_text(json.dumps(audit))
        else:
            reseal_test_file(
                folder / "automated_review.json",
                {k: v for k, v in audit.items() if k != "receipt_sha256"},
            )
            expected = "STALE_AUTOMATED_REVIEW"
    else:
        monkeypatch.setattr(workflow, "implementation", lambda: {"different": True})
        expected = "IMPLEMENTATION_CHANGED"
    with pytest.raises(ValueError, match=expected):
        workflow.execute(project, approval_request(plan, audit))
    assert not (folder / "approval.json").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "csv_value",
        "csv_missing",
        "csv_duplicate",
        "typed_value",
        "trace_duplicate",
        "population",
        "schema_type",
        "schema_identifier",
        "schema_header",
    ],
)
def test_hash_consistent_but_inconsistent_population_or_rows_are_not_accepted(tmp_path, mutation):
    project, plan, _ = prepared(tmp_path)
    folder = version_folder(project, plan)
    filename = None
    if mutation.startswith("csv"):
        filename = "analysis.csv"
        with (folder / filename).open(newline="") as stream:
            rows = list(csv.reader(stream))
        if mutation == "csv_value":
            rows[1][rows[0].index("lab_mean")] = "9999"
        elif mutation == "csv_missing":
            rows.pop()
        else:
            rows.append(rows[1])
        text = io.StringIO(newline="")
        csv.writer(text, lineterminator="\n").writerows(rows)
        (folder / filename).write_text(text.getvalue())
    elif mutation == "typed_value":
        filename = "analysis.jsonl"
        rows = list(workflow.lines(folder / filename))
        rows[0]["lab_mean"] = 9999
        (folder / filename).write_text("".join(workflow.canonical(row) + "\n" for row in rows))
    elif mutation == "trace_duplicate":
        filename = "trace.jsonl"
        with (folder / filename).open("a") as stream:
            stream.write(workflow.canonical(next(workflow.lines(folder / filename))) + "\n")
    elif mutation == "population":
        filename = "validation.json"
        plan["summary"]["population"]["subjects"] += 1
        (folder / filename).write_text(workflow.canonical(plan["summary"]) + "\n")
    else:
        filename = "analysis.schema.json"
        schema = json.loads((folder / filename).read_text())
        column = schema["columns"][0]
        column[
            {"schema_type": "type", "schema_identifier": "identifier", "schema_header": "name"}[
                mutation
            ]
        ] = {
            "schema_type": "number",
            "schema_identifier": False,
            "schema_header": "pretend_id",
        }[mutation]
        (folder / filename).write_text(workflow.canonical(schema) + "\n")
    plan = rebind_test_plan(project, plan, filename)
    with pytest.raises(ValueError, match="AUTOMATED_CHECK_FAILED"):
        call(project, plan, "automated_review")
    assert not (folder / "automated_review.json").exists()


def test_audit_from_old_plan_is_stale_even_if_new_retained_bytes_are_consistent(tmp_path):
    project, plan, _ = prepared(tmp_path)
    call(project, plan, "automated_review")
    plan["reason"] = "Adversarial changed plan identity"
    changed = rebind_test_plan(project, plan)
    with pytest.raises(ValueError, match="STALE_AUTOMATED_REVIEW"):
        call(project, changed, "automated_review")


def test_native_schema_rejects_hash_consistent_trace_type_drift(tmp_path):
    project, plan, _ = prepared(tmp_path)
    folder = version_folder(project, plan)
    rows = list(workflow.lines(folder / "trace.jsonl"))
    row = next(r for r in rows if r["included"] and r["values"]["lab_mean"] is not None)
    row["values"]["lab_mean"] = "20"  # A numeric-looking string is not a native number.
    (folder / "trace.jsonl").write_text("".join(workflow.canonical(r) + "\n" for r in rows))
    changed = rebind_test_plan(project, plan, "trace.jsonl")
    with pytest.raises(ValueError, match="trace value differs from native output schema"):
        call(project, changed, "automated_review")


def test_manager_attestation_is_unchanged_and_cannot_silently_replace_auto_approval(tmp_path):
    project, plan, _ = prepared(tmp_path)
    audit = call(project, plan, "automated_review")
    request = approval_request(plan, audit)
    request["review"]["kind"] = "data_manager"
    del request["review"]["automated_receipt_sha256"]
    approved = workflow.execute(project, request)
    assert approved["clinical_validation"] == "manager_attestation"
    assert "automated_receipt_sha256" not in approved["review"]
    assert workflow.execute(project, request) == approved
    with pytest.raises(ValueError, match="IMMUTABLE_APPROVAL"):
        workflow.execute(project, approval_request(plan, audit))


def test_automatic_review_cannot_bypass_quality_blocker(tmp_path):
    project, request = setup(tmp_path)
    request["specification"]["cohort"][0]["keep"]["value"] = 999
    plan = workflow.execute(project, request)
    assert not plan["summary"]["ready_for_approval"]
    with pytest.raises(ValueError, match="QUALITY_BLOCKED"):
        call(project, plan, "automated_review")


def test_portable_release_preserves_auto_evidence_without_replaying_old_implementation(
    tmp_path, monkeypatch
):
    project, plan, _ = prepared(tmp_path)
    audit = call(project, plan, "automated_review")
    approval = workflow.execute(project, approval_request(plan, audit))
    release = call(project, plan, "release", approval_sha256=approval["receipt_sha256"])
    bundle = call(project, plan, "bundle", release_sha256=release["receipt_sha256"])
    with zipfile.ZipFile(bundle["path"]) as archive:
        assert json.loads(archive.read("automated_review.json")) == audit
    target = SimpleNamespace(id="second-project", output_dir=tmp_path / "second-output")
    # Historical immutable imports verify their saved implementation, not today's.
    monkeypatch.setattr(workflow, "implementation", lambda: {"future_version": True})
    binding = portable.import_bundle(
        target, bundle["path"], bundle["sha256"], release["receipt_sha256"]
    )
    assert binding["clinical_validation"] == "not_performed"
    folder = Path(binding["folder"])
    assert workflow.read_sealed(folder / "automated_review.json") == audit
    assert (
        portable.import_bundle(target, bundle["path"], bundle["sha256"], release["receipt_sha256"])
        == binding
    )
    (folder / "automated_review.json").unlink()
    with pytest.raises(ValueError, match="automatic review evidence is missing"):
        portable.verify_bundle_folder(folder, release["receipt_sha256"])


def test_release_rechecks_auto_audit_instead_of_trusting_old_approval(tmp_path):
    project, plan, _ = prepared(tmp_path)
    audit = call(project, plan, "automated_review")
    approval = workflow.execute(project, approval_request(plan, audit))
    (version_folder(project, plan) / "automated_review.json").unlink()
    with pytest.raises(ValueError, match="AUTOMATED_REVIEW_REQUIRED"):
        call(project, plan, "release", approval_sha256=approval["receipt_sha256"])


def test_contract_advertises_technical_scope_and_exact_wire():
    contract = workflow.execute(None, {"op": "contract"})
    assert "automated_review" in contract["operations"]
    assert "automated_checks" in contract["review"]["properties"]["kind"]["enum"]
    assert "not_performed" in contract["execution_semantics"]["automated_approval"]
    assert "not independent recomputation" in contract["execution_semantics"]["automated_review"]
