"""Real approved preparation bundles, full-population checks and SQL oracle.

These tests call native preparation/validation components. They do not claim a
new MCP endpoint or a completed clinical target-trial analysis.
"""

import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import uuid
import zipfile

import pandas as pd
import pytest

from rde.domain.models.dataset import DatasetMetadata
from rde.domain.models.preparation import Source
from rde.infrastructure.preparation import portable, sources, workflow as w
from rde.infrastructure.clinical.survival import digest
from rde.infrastructure.clinical.target_trial_contract import TargetTrialProtocol
from rde.infrastructure.clinical.target_trial_source import (
    target_trial_binding,
    validate_target_trial_source,
)
from rde.infrastructure.clinical.weighting_contract import WeightingSpec, weighting_preflight


def write_source(tmp_path, name, rows):
    path = tmp_path / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return Source(
        id=name,
        path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bytes=path.stat().st_size,
        synthetic=True,
    )


def case(tmp_path, *, outcome="binary", mutate=None, after_sources=None, automated=False):
    root = [
        dict(
            pid=f"P{i:03}",
            index_at="2025-01-01T00:00:00Z",
            age=17 if i == 0 else 30 + i % 20,
            age_at="2024-12-30T00:00:00Z",
            age_known="2024-12-30T01:00:00Z",
            treatment="control" if i % 3 else "treated",
            treatment_at="2025-01-01T00:00:00Z",
            treatment_known="2025-01-01T00:00:00Z",
            coverage_start="2024-12-01T00:00:00Z",
            coverage_end="2025-02-05T00:00:00Z",
            exported="yes",
            intercurrent="none",
        )
        for i in range(61)
    ]
    baseline = [
        dict(
            lab_id=f"L{i}-{j}",
            pid=r["pid"],
            taken_at=f"2024-12-{29+j}T00:00:00Z",
            known_at=f"2024-12-{29+j}T01:00:00Z",
            value=1 + (i * 7 + j) % 19,
            units="U",
        )
        for i, r in enumerate(root)
        for j in [0, 1]
    ]
    events = [
        dict(
            event_id=f"E{i}",
            pid=r["pid"],
            event_at="2025-01-30T00:00:00Z",
            known_at="2025-01-30T01:00:00Z",
            value=2 + (i * 11) % 23,
            units="mg/dL",
        )
        for i, r in enumerate(root)
        if outcome == "continuous" or i % 4 == 0
    ]
    preparation = {
        "unit": {
            "kind": "patient",
            "source_id": "people",
            "keys": ["pid"],
            "subject_keys": ["pid"],
            "index_column": "index_at",
            "columns": {"age": {"value_type": "number"}},
        },
        "relations": [
            {
                "id": "baseline",
                "source_id": "labs",
                "left_keys": ["pid"],
                "right_keys": ["pid"],
                "kind": "events",
                "record_keys": ["lab_id"],
                "coverage": {"mode": "complete"},
                "window": {
                    "event_column": "taken_at",
                    "available_column": "known_at",
                    "start_days": -7,
                    "end_days": 0,
                    "purpose": "baseline",
                },
                "features": [
                    {
                        "output": "baseline_value",
                        "column": "value",
                        "aggregate": "mean",
                        "value_type": "number",
                        "unit_column": "units",
                        "unit_conversions": {"U": {"scale": 1, "offset": 0}},
                        "output_unit": "U",
                    }
                ],
                "reason": "Prespecified synthetic baseline lab average",
            },
            {
                "id": "outcomes",
                "source_id": "outcomes",
                "left_keys": ["pid"],
                "right_keys": ["pid"],
                "kind": "events",
                "record_keys": ["event_id"],
                "coverage": {
                    "mode": "by_column",
                    "column": "exported",
                    "exported_values": ["yes"],
                    "not_exported_values": ["no"],
                },
                "window": {
                    "event_column": "event_at",
                    "available_column": "known_at",
                    "start_days": 0 if outcome == "binary" else 25,
                    "end_days": 30,
                    "bounds": "right",
                    "purpose": "followup",
                    "followup_end_column": "coverage_end",
                },
                "features": [{"output": "endpoint", "aggregate": "exists"}]
                if outcome == "binary"
                else [
                    {
                        "output": "endpoint",
                        "column": "value",
                        "aggregate": "last",
                        "value_type": "number",
                        "unit_column": "units",
                        "unit_conversions": {"mg/dL": {"scale": 1, "offset": 0}},
                        "output_unit": "mg/dL",
                    }
                ],
                "reason": "Prespecified complete fixed-horizon synthetic outcome",
            },
        ],
        "cohort": [
            {
                "id": "adult",
                "reason": "Age eligibility defined before any follow-up",
                "keep": {"column": "age", "op": "gte", "value": 18},
            }
        ],
        "definitions": {
            "unit": "One independent synthetic person per root record",
            "linkage": "Synthetic pid identifies the same person in all three sources",
            "time": "Synthetic UTC baseline with explicit known-at timestamps",
            "missingness": "No imputation or deletion after baseline eligibility",
        },
    }
    if mutate:
        mutate(root, baseline, events, preparation)
    inputs = [
        write_source(tmp_path, name, rows)
        for name, rows in [("people", root), ("labs", baseline), ("outcomes", events)]
    ]
    if after_sources:
        after_sources(inputs, preparation)
    project = SimpleNamespace(id="tte-source-project", output_dir=tmp_path / "source-project")
    plan = w.execute(
        project,
        {
            "op": "draft",
            "preparation_id": str(uuid.uuid4()),
            "sources": [s.model_dump() for s in inputs],
            "specification": preparation,
            "reason": "Prespecified synthetic source validation",
            "author": "synthetic-fixture",
        },
    )
    assert plan["summary"]["ready_for_approval"], plan["summary"]
    traces = list(
        w.lines(
            project.output_dir
            / "artifacts/data_preparation/versions"
            / plan["preparation_id"]
            / "trace.jsonl"
        )
    )
    review = {
        "kind": "synthetic_oracle",
        "denominator_confirmed": True,
        "reviewed_unit_ids": [traces[0]["unit_id"]],
        "notes": "Synthetic fixture; independent SQL checked in separate test",
    }
    if automated:
        auto = w.execute(
            project,
            {
                "op": "automated_review",
                "preparation_id": plan["preparation_id"],
                "expected_sha256": plan["receipt_sha256"],
            },
        )
        review = {
            "kind": "automated_checks",
            "denominator_confirmed": True,
            "reviewed_unit_ids": auto["reviewed_unit_ids"],
            "automated_receipt_sha256": auto["receipt_sha256"],
            "notes": "Technical consistency only, no clinical validation",
        }
    approval = w.execute(
        project,
        {
            "op": "approve",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "acknowledged_warnings": plan["summary"]["warnings"],
            "reviewer": "synthetic-fixture",
            "review": review,
        },
    )
    release = w.execute(
        project,
        {
            "op": "release",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "approval_sha256": approval["receipt_sha256"],
        },
    )
    bundle = w.execute(
        project,
        {
            "op": "bundle",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "release_sha256": release["receipt_sha256"],
        },
    )
    target = SimpleNamespace(id="tte-analysis-project", output_dir=tmp_path / "analysis-project")
    binding = portable.import_bundle(
        target, bundle["path"], bundle["sha256"], release["receipt_sha256"]
    )
    metadata = DatasetMetadata(
        Path(release["dataset"]["path"]), "csv", release["dataset"]["bytes"], preparation=binding
    )
    frame = portable.load_prepared(metadata)[0]
    spec = WeightingSpec(
        treatment="treatment",
        treatment_levels=["control", "treated"],
        treatment_definition="Synthetic point assignment at time zero",
        outcome="endpoint",
        outcome_type=outcome,
        outcome_unit="event indicator" if outcome == "binary" else "mg/dL",
        outcome_definition="Prespecified observed fixed-horizon endpoint",
        time_origin="Source index_at defines one baseline assignment",
        outcome_window="Complete observation to 30 days after time zero",
        study_design="observational_cohort",
        context="Synthetic source-contract test; no clinical causal claim",
        estimand="ATE",
        independent_rows=True,
        pretreatment_covariates=True,
        subject="_rde_subject_id",
        outcome_levels=["0", "1"] if outcome == "binary" else [],
        covariates=[
            {
                "column": "baseline_value",
                "kind": "continuous",
                "label": "Baseline measure",
                "unit": "U",
                "reference": 10,
                "increment": 1,
                "knots": [],
                "pre_exposure_basis": "Available baseline records with actual source known_at times",
            }
        ],
    )

    def timed(column, source, event, available):
        return {
            "column": column,
            "source_id": source,
            "event_column": event,
            "available_column": available,
            "definition": "Synthetic source field with explicit event and availability times",
        }

    protocol = {
        "schema_version": "rde-baseline-target-trial-v1",
        "binding": target_trial_binding(target, metadata),
        "eligibility": {
            "definition": "All synthetic adults at time zero",
            "rule_ids": [r["id"] for r in preparation["cohort"]],
            "fields": [timed("age", "people", "age_at", "age_known")],
            "missing_policy": "only_prespecified_baseline_eligibility_rules",
        },
        "time_zero": {
            "index_column": "index_at",
            "timezone": "UTC",
            "selection": "one_prespecified_root_record_per_person",
            "subject_column": "_rde_subject_id",
            "definition": "One prespecified source index per independent person",
        },
        "treatment": {
            "strategy": "baseline_point_treatment",
            "field": timed("treatment", "people", "treatment_at", "treatment_known"),
            "levels": ["control", "treated"],
            "definitions": [
                "Prespecified synthetic control point treatment",
                "Prespecified synthetic active point treatment",
            ],
        },
        "assignment": {
            "hypothetical_trial": "random_assignment_at_time_zero",
            "observational_mapping": "recorded_treatment_at_time_zero",
            "selection_basis": "Observed baseline treatment; no claim of actual randomization",
            "confounder_selection_basis": "Synthetic baseline variable declared before analysis",
        },
        "followup": {
            "mode": "complete_fixed_horizon",
            "horizon_days": 30,
            "coverage_start_column": "coverage_start",
            "coverage_end_column": "coverage_end",
            "export_status_column": "exported",
            "complete_export_value": "yes",
            "intercurrent_status_column": "intercurrent",
            "no_intercurrent_value": "none",
            "intercurrent_policy": "reject_any_recorded_intercurrent_event",
            "definition": "Known synthetic source coverage and no intercurrent events",
        },
        "outcome": {
            "kind": outcome,
            "column": "endpoint",
            "relation_id": "outcomes",
            "assessment_start_days": 0 if outcome == "binary" else 25,
            "assessment_end_days": 30,
            "bounds": "right",
            "unit": spec.outcome_unit,
            "definition": "Prespecified endpoint within the complete follow-up horizon",
        },
        "estimand": {
            "kind": "ATE",
            "contrast": "baseline_level_1_minus_level_0",
            "target_population": "All eligible synthetic adults with no further exclusion",
            "interpretation": "baseline_point_treatment_effect",
        },
        "baseline": [timed("baseline_value", "labs", "taken_at", "known_at")],
        "analysis": {
            "weighting_spec_sha256": digest(spec.to_dict()),
            "population_policy": "all_prepared_eligible_no_further_exclusion",
            "missing_policy": "reject_any_missing_analysis_role",
            "consistency_basis": "Recorded point treatments are predefined in this synthetic case",
            "exchangeability_basis_and_limitations": "Not verified by source checks or causal-effect inference",
            "positivity_basis_and_limitations": "Must be checked during ordinary weighting estimation",
        },
    }
    return SimpleNamespace(
        project=target,
        metadata=metadata,
        frame=frame,
        spec=spec,
        protocol=protocol,
        root=root,
        baseline=baseline,
        events=events,
        plan=plan,
        release=release,
        bundle=bundle,
    )


def validate(c):
    return validate_target_trial_source(c.project, c.metadata, c.frame, c.spec, c.protocol)


def test_binary_three_table_population_and_values_match_independent_sql(tmp_path, monkeypatch):
    c = case(tmp_path)
    import rde.infrastructure.clinical.weighting as kernel

    monkeypatch.setattr(
        kernel,
        "run_weighting",
        lambda *a, **kw: pytest.fail("source validation must not fit an effect"),
    )
    sql = sqlite3.connect(":memory:")
    for name, rows in [("people", c.root), ("labs", c.baseline), ("outcomes", c.events)]:
        pd.DataFrame(rows).to_sql(name, sql, index=False)
    oracle = sql.execute(
        """SELECT p.pid, (SELECT AVG(l.value) FROM labs l WHERE l.pid=p.pid AND julianday(l.taken_at)<=julianday(p.index_at) AND julianday(l.taken_at)>=julianday(p.index_at)-7 AND julianday(l.known_at)<=julianday(p.index_at)), EXISTS(SELECT 1 FROM outcomes o WHERE o.pid=p.pid AND julianday(o.event_at)>julianday(p.index_at) AND julianday(o.event_at)<=julianday(p.index_at)+30) FROM people p WHERE p.age>=18 ORDER BY p.pid"""
    ).fetchall()
    assert [
        tuple(v)
        for v in c.frame[["pid", "baseline_value", "endpoint"]].itertuples(index=False, name=None)
    ] == oracle
    receipt = validate(c)
    assert receipt["population"]["root_records"] == 61
    assert receipt["population"]["analysis_n"] == 60
    assert len(receipt["rows"]) == 61
    assert receipt["population"]["excluded_by_baseline_eligibility"] == 1
    assert sum(r.get("outcome_contributing_records", 0) for r in receipt["rows"]) == 15
    assert receipt["weighting_preflight"] == weighting_preflight(c.frame, c.spec)
    assert receipt["execution_authorized"] is False
    assert receipt["clinical_validation"] == "synthetic_only"
    assert validate(c) == receipt  # Read-only, deterministic, no hidden current timestamp.


def test_continuous_measurements_and_automated_review_keep_their_limits(tmp_path):
    c = case(tmp_path, outcome="continuous", automated=True)
    receipt = validate(c)
    assert receipt["population"]["analysis_n"] == 60
    assert receipt["clinical_validation"] == "not_performed"
    assert receipt["preparation_review_kind"] == "automated_checks"
    assert all(r.get("outcome_contributing_records") == 1 for r in receipt["rows"] if r["included"])


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("age_known", "2025-01-02T00:00:00Z", "TTE_FUTURE_BASELINE"),
        ("treatment_at", "2024-12-31T00:00:00Z", "TTE_ASSIGNMENT_TIME"),
        ("treatment_known", "2025-01-02T00:00:00Z", "TTE_FUTURE_BASELINE"),
        ("coverage_start", "2025-01-02T00:00:00Z", "TTE_INCOMPLETE_FOLLOWUP"),
        ("coverage_end", "2025-01-30T00:00:00Z", "TTE_INCOMPLETE_FOLLOWUP"),
        ("exported", "unknown", "TTE_UNKNOWN_EXPORT"),
        ("intercurrent", "death", "TTE_INTERCURRENT_EVENT"),
        ("intercurrent", "unknown", "TTE_INTERCURRENT_EVENT"),
        ("age_known", "2024-12-30T01:00:00", "TTE_TIMESTAMP"),
    ],
)
def test_last_person_beyond_first_page_cannot_hide_invalid_time_or_coverage(
    tmp_path, field, value, match
):
    c = case(tmp_path, mutate=lambda roots, labs, events, spec: roots[-1].update({field: value}))
    with pytest.raises(ValueError, match=match):
        validate(c)


def test_baseline_sample_before_index_but_late_result_is_not_available(tmp_path):
    def mutate(roots, labs, events, spec):
        for row in labs:
            if row["pid"] == roots[-1]["pid"]:
                row["known_at"] = "2025-01-02T00:00:00Z"

    c = case(tmp_path, mutate=mutate)
    assert c.frame.iloc[-1]["_rde_baseline_status"] == "not_available"
    with pytest.raises(ValueError, match="TTE_BASELINE_PROVENANCE|TTE_BASELINE_LINKAGE"):
        validate(c)


def test_future_outcome_availability_and_missing_continuous_endpoint_block(tmp_path):
    late = tmp_path / "late"
    late.mkdir()
    c = case(
        late,
        mutate=lambda roots, labs, events, spec: events[-1].update(known_at="2025-02-06T00:00:00Z"),
    )
    with pytest.raises(ValueError, match="TTE_OUTCOME_TIME"):
        validate(c)
    missing = tmp_path / "missing"
    missing.mkdir()
    c = case(
        missing,
        outcome="continuous",
        mutate=lambda roots, labs, events, spec: events[-1].update(value=""),
    )
    with pytest.raises(ValueError, match="TTE_MISSING_OUTCOME"):
        validate(c)


def test_weighting_complete_case_exclusion_cannot_change_target(tmp_path):
    c = case(tmp_path, mutate=lambda roots, labs, events, spec: roots[-1].update(treatment=""))
    with pytest.raises(ValueError, match="TTE_ANALYSIS_EXCLUSION"):
        validate(c)


def test_manual_root_exclusion_is_not_an_eligibility_rule(tmp_path):
    def change(inputs, spec):
        row = sources.load(inputs[0]).rows[-1]
        spec["excluded_rows"] = [
            {
                "source_id": "people",
                "record_index": row.index,
                "row_sha256": row.sha256,
                "reason": "An outcome-driven deletion cannot be a baseline eligibility rule",
            }
        ]

    c = case(tmp_path, after_sources=change)
    with pytest.raises(ValueError, match="TTE_SOURCE_EXCLUSION"):
        validate(c)


def test_future_feature_cannot_select_even_a_numerically_unchanged_population(tmp_path):
    def change(roots, labs, events, spec):
        spec["relations"][1]["features"].append({"output": "future_count", "aggregate": "count"})
        spec["cohort"].append(
            {
                "id": "future_selection",
                "reason": "Unsupported outcome-driven eligibility",
                "stage": "after_links",
                "keep": {"column": "future_count", "op": "gte", "value": 0},
            }
        )

    c = case(tmp_path, mutate=change)
    c.protocol["eligibility"]["fields"].append(
        {
            "column": "future_count",
            "source_id": "outcomes",
            "event_column": "event_at",
            "available_column": "known_at",
            "definition": "An invalid future-dependent selection field",
        }
    )
    with pytest.raises(ValueError, match="TTE_FUTURE_ELIGIBILITY"):
        validate(c)


@pytest.mark.parametrize(
    "field",
    [
        "bundle_sha256",
        "plan_sha256",
        "approval_sha256",
        "review_sha256",
        "source_set_sha256",
        "specification_sha256",
        "trace_sha256",
        "dataset_sha256",
        "schema_sha256",
        "inventory_sha256",
    ],
)
def test_each_exact_approved_source_identity_is_bound(tmp_path, field):
    c = case(tmp_path)
    c.protocol["binding"][field] = "0" * 64
    with pytest.raises(ValueError, match="TTE_STALE_BINDING"):
        validate(c)


def test_closure_missing_trace_changed_source_and_frame_cannot_pass(tmp_path):
    c = case(tmp_path)
    original = c.frame.copy(deep=True)
    c.frame = c.frame.iloc[:-1]
    with pytest.raises(ValueError, match="TTE_DATAFRAME_CHANGED"):
        validate(c)
    c.frame = original
    folder = Path(c.metadata.preparation["folder"])
    trace = folder / "trace.jsonl"
    saved = trace.read_bytes()
    trace.write_bytes(b"\n".join(saved.splitlines()[:-1]) + b"\n")
    with pytest.raises(ValueError, match="CORRUPT_PREPARATION"):
        validate(c)
    trace.write_bytes(saved)
    raw = next((folder / "sources").glob("*.csv"))
    raw.write_bytes(raw.read_bytes() + b" ")
    with pytest.raises(ValueError, match="CORRUPT_PREPARATION"):
        validate(c)


def test_other_project_and_unprepared_inputs_cannot_claim_approval(tmp_path):
    c = case(tmp_path)
    other = SimpleNamespace(id="other", output_dir=tmp_path / "other")
    with pytest.raises(ValueError, match="TTE_INTAKE_OWNERSHIP"):
        validate_target_trial_source(other, c.metadata, c.frame, c.spec, c.protocol)
    c.metadata.preparation = None
    with pytest.raises(ValueError, match="TTE_PREPARED_REQUIRED"):
        validate(c)


def test_dynamic_strategies_and_boolean_approval_are_not_contracts(tmp_path):
    c = case(tmp_path)
    for section, field, value in [
        ("treatment", "strategy", "sustained_per_protocol"),
        ("followup", "mode", "censoring_weighted"),
        ("time_zero", "selection", "multiple_index"),
        ("analysis", "approved", True),
    ]:
        modified = json.loads(json.dumps(c.protocol))
        modified[section][field] = value
        with pytest.raises(ValueError):
            TargetTrialProtocol.parse(modified)
    changed = replace(c.spec, estimand="ATT")
    with pytest.raises(ValueError, match="TTE_WEIGHTING_SPEC"):
        validate_target_trial_source(c.project, c.metadata, c.frame, changed, c.protocol)


def resealed_intake(c, tmp_path):
    """Rebuild an internally sealed bundle after a simulated upstream error.

    This is test-only corruption, not an approval API. Byte checks alone should
    pass so the independent retained-evidence replay is what rejects the error.
    """
    folder = Path(c.metadata.preparation["folder"])
    plan = w.read_sealed(folder / "plan.json")
    plan["files"] = {
        name: {"sha256": sources.file_hash(folder / name), "bytes": (folder / name).stat().st_size}
        for name in plan["files"]
    }

    def reseal(name, value):
        value.pop("receipt_sha256", None)
        (folder / name).unlink()  # test-only resealing of this temporary fixture
        return w.seal(folder / name, value)

    plan = reseal("plan.json", plan)
    approval = w.read_sealed(folder / "approval.json")
    approval["plan_sha256"] = plan["receipt_sha256"]
    approval = reseal("approval.json", approval)
    release = w.read_sealed(folder / "release.json")
    release.update(plan_sha256=plan["receipt_sha256"], approval_sha256=approval["receipt_sha256"])
    release = reseal("release.json", release)
    portable.verify_bundle_folder(folder, release["receipt_sha256"])
    archive = tmp_path / "resealed.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(folder).as_posix())
    c.metadata.preparation = portable.import_bundle(
        c.project, str(archive), sources.file_hash(archive), release["receipt_sha256"]
    )
    c.protocol["binding"] = target_trial_binding(c.project, c.metadata)


@pytest.mark.parametrize("corruption", ["omit_last_person", "swap_last_source", "false_flow"])
def test_resealed_full_closure_cannot_hide_semantically_wrong_trace(tmp_path, corruption):
    c = case(tmp_path)
    folder = Path(c.metadata.preparation["folder"])
    if corruption == "false_flow":
        path = folder / "validation.json"
        validation = json.loads(path.read_text())
        validation["population"]["included_units"] = 999
        path.write_text(json.dumps(validation))
        expected = "TTE_POPULATION_FLOW"
    else:
        path = folder / "trace.jsonl"
        rows = list(w.lines(path))
        if corruption == "omit_last_person":
            rows = rows[:-1]
        else:
            rows[-1]["root"] = rows[-2]["root"]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        expected = "TTE_EVIDENCE_REPLAY"
    resealed_intake(c, tmp_path)
    with pytest.raises(ValueError, match=expected):
        validate(c)


def test_reordered_sources_require_new_binding_but_preserve_patient_answers(tmp_path):
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    a = case(first)

    def reorder(roots, labs, events, spec):
        roots.reverse()
        labs.reverse()
        events.reverse()

    b = case(second, mutate=reorder)
    ra, rb = validate(a), validate(b)
    assert (
        ra["population"]["included_unit_set_sha256"] == rb["population"]["included_unit_set_sha256"]
    )
    columns = ["_rde_unit_id", "baseline_value", "endpoint"]
    pd.testing.assert_frame_equal(
        a.frame[columns].sort_values("_rde_unit_id").reset_index(drop=True),
        b.frame[columns].sort_values("_rde_unit_id").reset_index(drop=True),
    )
    assert a.protocol["binding"] != b.protocol["binding"]
    with pytest.raises(ValueError, match="TTE_STALE_BINDING"):
        validate_target_trial_source(b.project, b.metadata, b.frame, b.spec, a.protocol)


def test_actual_encounter_unit_is_not_a_patient_target_trial(tmp_path):
    def mutate(roots, labs, events, spec):
        spec["unit"].update(kind="encounter", keys=["pid", "index_at"])

    c = case(tmp_path, mutate=mutate)
    with pytest.raises(ValueError, match="TTE_ANALYSIS_UNIT"):
        validate(c)


def test_analysis_filter_and_unmapped_covariate_cannot_silently_shrink_scope(tmp_path):
    c = case(tmp_path)
    changed = replace(
        c.spec, cohort_filter={"column": "treatment", "values": ["control", "treated"]}
    )
    c.protocol["analysis"]["weighting_spec_sha256"] = digest(changed.to_dict())
    with pytest.raises(ValueError, match="TTE_ANALYSIS_POPULATION"):
        validate_target_trial_source(c.project, c.metadata, c.frame, changed, c.protocol)
    c.protocol["analysis"]["weighting_spec_sha256"] = digest(c.spec.to_dict())
    c.protocol["baseline"][0]["column"] = "age"
    with pytest.raises(ValueError, match="TTE_BASELINE_ROLES"):
        validate(c)


def test_receipt_binds_validator_implementation_without_private_paths(tmp_path):
    c = case(tmp_path)
    receipt = validate(c)
    assert set(receipt["implementation"]["files"]) == {
        "target_trial_contract.py",
        "target_trial_study.py",
        "weighting.py",
        "target_trial_source.py",
        "weighting_contract.py",
        "regression_contract.py",
        "survival.py",
        "measurement.py",
        "privacy.py",
        "dataframe_lineage.py",
    }
    for value in receipt["implementation"]["files"].values():
        assert len(value) == 64
    assert str(tmp_path) not in json.dumps(receipt)
    recorded = receipt.pop("receipt_sha256")
    assert recorded == sources.digest(receipt)


@pytest.mark.parametrize("future_before_links", [False, True])
def test_cohort_checks_follow_native_stage_order_even_when_spec_is_interleaved(
    tmp_path, future_before_links
):
    def mutate(roots, labs, events, spec):
        # Native preparation applies before_links first despite serialized order.
        spec["cohort"].insert(
            0,
            {
                "id": "baseline_threshold",
                "reason": "Prespecified baseline measurement eligibility",
                "stage": "after_links",
                "keep": {"column": "baseline_value", "op": "gte", "value": 5},
            },
        )
        if future_before_links:
            roots[-1]["age_known"] = "2025-01-02T00:00:00Z"

    c = case(tmp_path, mutate=mutate)
    c.protocol["eligibility"]["fields"].append(
        {
            "column": "baseline_value",
            "source_id": "labs",
            "event_column": "taken_at",
            "available_column": "known_at",
            "definition": "The observed pre-index measurement eligibility",
        }
    )
    if future_before_links:
        # Last person is excluded by the after-links rule. Earlier executed
        # eligibility still cannot rely on a future fact and escape review.
        with pytest.raises(ValueError, match="TTE_FUTURE_BASELINE"):
            validate(c)
    else:
        receipt = validate(c)
        assert receipt["population"]["root_records"] == 61
        assert receipt["population"]["excluded_by_baseline_eligibility"] > 1
        assert all(row["eligibility_time_checks"][0]["column"] == "age" for row in receipt["rows"])
