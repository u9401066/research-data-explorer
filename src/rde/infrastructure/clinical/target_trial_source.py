"""Read-only, source-backed checks for a finite baseline target-trial protocol.

No effect estimator is implemented here. A passing receipt is not clinical
validation, protocol approval or permission to execute a weighting analysis.
"""

from datetime import timedelta
from importlib.metadata import version
from pathlib import Path
import json

import pandas as pd

from rde.domain.models.preparation import Review, Source, Specification
from rde.infrastructure.evidence.workflow import safe_path
from rde.infrastructure.preparation import engine, portable, sources, workflow as w
from . import measurement, regression_contract, survival, target_trial_contract, weighting_contract
from .survival import digest, level
from .target_trial_contract import PreparedBinding, TargetTrialProtocol
from .weighting_contract import WeightingSpec, weighting_preflight


def implementation():
    """Bind source-check and unchanged analysis contract versions for later reuse."""
    from . import target_trial_study, weighting

    return {
        "schema": "rde-target-trial-validator-implementation-v1",
        "files": {
            "target_trial_contract.py": sources.file_hash(Path(target_trial_contract.__file__)),
            "target_trial_source.py": sources.file_hash(Path(__file__)),
            "target_trial_study.py": sources.file_hash(Path(target_trial_study.__file__)),
            "weighting.py": sources.file_hash(Path(weighting.__file__)),
            "weighting_contract.py": sources.file_hash(Path(weighting_contract.__file__)),
            "regression_contract.py": sources.file_hash(Path(regression_contract.__file__)),
            "survival.py": sources.file_hash(Path(survival.__file__)),
            "measurement.py": sources.file_hash(Path(measurement.__file__)),
        },
        "dependencies": {name: version(name) for name in ("numpy", "pandas", "statsmodels")},
        "preparation": w.implementation(),
    }


def require(condition, code, explanation):
    if not condition:
        raise ValueError(f"{code}: {explanation}")


def _context(project, metadata):
    binding = getattr(metadata, "preparation", None)
    require(
        isinstance(binding, dict),
        "TTE_PREPARED_REQUIRED",
        "Use a server-imported approved preparation bundle",
    )
    bundle_sha = binding.get("bundle_sha256", "")
    require(
        isinstance(bundle_sha, str)
        and len(bundle_sha) == 64
        and all(c in "0123456789abcdef" for c in bundle_sha),
        "TTE_BUNDLE_ID",
        "Invalid server intake bundle identity",
    )
    expected = safe_path(
        project.output_dir.resolve(), "artifacts/data_preparation/imports/" + bundle_sha
    )
    folder = Path(binding.get("folder", ""))
    require(
        folder.is_absolute() and folder == expected and folder.is_dir(),
        "TTE_INTAKE_OWNERSHIP",
        "Prepared evidence must be the current project's exact imported bundle",
    )
    require(
        not folder.is_symlink() and not any(p.is_symlink() for p in folder.rglob("*")),
        "TTE_SOURCE_LINK",
        "Evidence closure cannot contain filesystem links",
    )
    plan, release = portable.verify_bundle_folder(folder, binding.get("release_sha256"))
    approval = w.read_sealed(folder / "approval.json")
    review = Review.model_validate(approval["review"])
    expected_validation = {
        "synthetic_oracle": "synthetic_only",
        "data_manager": "manager_attestation",
        "automated_checks": "not_performed",
    }[review.kind]
    require(
        approval.get("schema") == "rde-preparation-approval-v1"
        and approval.get("reviewer", "").strip()
        and review.denominator_confirmed
        and len(set(review.reviewed_unit_ids)) == len(review.reviewed_unit_ids)
        and approval.get("clinical_validation") == expected_validation
        and release.get("clinical_validation") == expected_validation,
        "TTE_APPROVAL",
        "Exact attributed preparation review is required; a caller boolean is not approval",
    )
    require(
        review.kind != "synthetic_oracle"
        or all(s["source"]["synthetic"] for s in plan["source_snapshots"]),
        "TTE_APPROVAL",
        "Real sources cannot carry synthetic approval",
    )
    required = {
        "analysis.csv",
        "analysis.jsonl",
        "analysis.schema.json",
        "trace.jsonl",
        "validation.json",
        "exceptions.jsonl",
        "issues.jsonl",
        "specification.json",
    }
    require(
        required <= set(plan["files"]),
        "TTE_EVIDENCE_CLOSURE",
        "The full trace, validation and exception ledgers are required",
    )
    for key, value in {
        "schema": "rde-prepared-intake-v1",
        "project_id": plan["project_id"],
        "preparation_id": plan["preparation_id"],
        "dataset": release["dataset"],
        "column_roles": release["column_roles"],
        "unit": release["unit"],
        "population": release["population"],
        "clinical_validation": release["clinical_validation"],
    }.items():
        require(
            binding.get(key) == value,
            "TTE_INTAKE_BINDING",
            f"Stored intake differs from release: {key}",
        )
    require(
        release["source_set_sha256"] == sources.digest(plan["source_snapshots"])
        and release["specification_sha256"] == sources.digest(plan["specification"]),
        "TTE_RELEASE_BINDING",
        "Release source/specification hashes differ",
    )
    hashes = plan["files"]
    pinned = PreparedBinding(
        preparation_id=plan["preparation_id"],
        preparation_project_id=plan["project_id"],
        bundle_sha256=bundle_sha,
        release_sha256=release["receipt_sha256"],
        plan_sha256=plan["receipt_sha256"],
        approval_sha256=approval["receipt_sha256"],
        review_sha256=sources.digest(approval["review"]),
        source_set_sha256=release["source_set_sha256"],
        specification_sha256=release["specification_sha256"],
        files_sha256=sources.digest(hashes),
        inventory_sha256=sources.digest(w.inventory(folder)),
        dataset_sha256=hashes["analysis.csv"]["sha256"],
        schema_sha256=hashes["analysis.schema.json"]["sha256"],
        typed_rows_sha256=hashes["analysis.jsonl"]["sha256"],
        trace_sha256=hashes["trace.jsonl"]["sha256"],
        validation_sha256=hashes["validation.json"]["sha256"],
        exceptions_sha256=hashes["exceptions.jsonl"]["sha256"],
    )
    return folder, plan, release, approval, pinned


def target_trial_binding(project, metadata):
    """Return exact existing source identities for a draft, without approving it."""
    return _context(project, metadata)[4].model_dump()


def target_trial_source_contract(project, metadata):
    """Read actual approved definitions/schema for drafting; expose no source rows."""
    folder, plan, release, approval, binding = _context(project, metadata)
    catalog = []
    for snapshot in plan["source_snapshots"]:
        source = Source.model_validate(snapshot["source"])
        table = sources.load(source, safe_path(folder, snapshot["snapshot"]))
        catalog.append(
            {
                "id": source.id,
                "sha256": source.sha256,
                "bytes": source.bytes,
                "columns": table.columns,
            }
        )
    return {
        "schema": "rde-target-trial-contract-v1",
        "family": "target_trial",
        "protocol_schema": TargetTrialProtocol.model_json_schema(),
        "source_binding": binding.model_dump(),
        "preparation_specification": plan["specification"],
        "sources": catalog,
        "population": release["population"],
        "clinical_validation": release["clinical_validation"],
        "preparation_review_kind": approval["review"]["kind"],
        "scope": "Drafting metadata only: preserve actual approved preparation rules and source identities. Supply research definitions and typed time/coverage roles, then inspect the full protocol; no clinical approval or effect estimation is granted here.",
    }


def _replay(folder, plan, metadata, dataframe):
    # Reuse the existing preparation engine to check its complete retained
    # evidence, not a second aggregation implementation or any effect estimator.
    require(
        plan["implementation"] == w.implementation(),
        "TTE_PREPARATION_IMPLEMENTATION",
        "Review/release with the current preparation implementation before target-trial validation",
    )
    prepared, _, _, _ = portable.load_prepared(metadata)
    try:
        pd.testing.assert_frame_equal(
            dataframe.reset_index(drop=True), prepared, check_dtype=True, check_exact=True
        )
    except AssertionError as error:
        raise ValueError(
            "TTE_DATAFRAME_CHANGED: all current columns/rows must equal the exact typed release"
        ) from error
    tables = {}
    for snapshot in plan["source_snapshots"]:
        source = Source.model_validate(snapshot["source"])
        require(source.id not in tables, "TTE_SOURCE_ID", "Source identities cannot repeat")
        tables[source.id] = sources.load(source, safe_path(folder, snapshot["snapshot"]))
    specification = Specification.model_validate(plan["specification"])
    result = engine.Evaluation(tables, specification, plan["project_id"]).evaluate()
    for name, expected in (
        ("analysis.jsonl", result.rows),
        ("trace.jsonl", list(result.trace.values())),
        ("exceptions.jsonl", result.exceptions),
        ("issues.jsonl", result.issues),
    ):
        actual = list(w.lines(folder / name))
        require(
            actual == expected,
            "TTE_EVIDENCE_REPLAY",
            f"Complete retained evidence differs from its source/rules: {name}",
        )
    require(
        json.loads((folder / "validation.json").read_text()) == result.summary() == plan["summary"],
        "TTE_POPULATION_FLOW",
        "All source and cohort-flow denominators must reproduce",
    )
    require(
        json.loads((folder / "specification.json").read_text()) == specification.model_dump(),
        "TTE_PREPARATION_SPEC",
        "Retained specification differs",
    )
    review = Review.model_validate(w.read_sealed(folder / "approval.json")["review"])
    require(
        set(review.reviewed_unit_ids) <= result.trace.keys(),
        "TTE_REVIEW_UNITS",
        "Review must reference this full trace",
    )
    return specification, tables, result


def _time(value):
    # Require an actual offset, not a date or ambiguous naive timestamp. UTC is
    # the explicit protocol clock; offsets are normalized by the native parser.
    require(
        isinstance(value, str) and "T" in value,
        "TTE_TIMESTAMP",
        "Use explicit ISO timestamps with UTC offsets",
    )
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("TTE_TIMESTAMP: invalid ISO timestamp") from error
    require(parsed.tzinfo is not None, "TTE_TIMESTAMP", "Naive timestamps cannot prove ordering")
    return engine.timestamp(value, "UTC")


def _source_row(ref, tables):
    table = tables.get(ref.get("source_id"))
    require(table is not None, "TTE_TRACE_SOURCE", "Trace references an unknown source")
    index = ref.get("record_index")
    require(
        type(index) is int and 0 <= index < len(table.rows),
        "TTE_TRACE_ROW",
        "Trace row index is outside the exact source",
    )
    row = table.rows[index]
    require(
        ref == table.ref(row, ref.get("column")),
        "TTE_TRACE_IDENTITY",
        "Trace row/column/source hash differs",
    )
    return row


def _timed_field(record, field, tables, preparation, index, *, treatment=False):
    cell = record["cells"].get(field.column)
    require(
        cell is not None and cell.get("sources"),
        "TTE_BASELINE_PROVENANCE",
        f"{field.column}: observed source contributors and timestamps are required",
    )
    relation_id = cell.get("relation")
    if relation_id:
        relation = next(r for r in preparation.relations if r.id == relation_id)
        require(
            relation.window is not None
            and relation.window.purpose == "baseline"
            and relation.window.available_column == field.available_column
            and relation.window.event_column == field.event_column,
            "TTE_BASELINE_WINDOW",
            f"{field.column}: explicit baseline event/availability columns must match preparation",
        )
        require(
            record["relations"][relation_id]["status"] == "matched"
            and record["relations"][relation_id]["coverage"] == "complete",
            "TTE_BASELINE_LINKAGE",
            f"{field.column}: partial/failed baseline linkage cannot be hidden",
        )
    times = []
    for ref in cell["sources"]:
        require(
            ref["source_id"] == field.source_id,
            "TTE_ROLE_SOURCE",
            f"{field.column}: role source differs from actual contributors",
        )
        row = _source_row(ref, tables)
        require(
            field.event_column in row.values and field.available_column in row.values,
            "TTE_TIME_COLUMN",
            f"{field.column}: source timestamp columns do not exist",
        )
        event, available = (
            _time(row.values[field.event_column]),
            _time(row.values[field.available_column]),
        )
        require(
            available >= event,
            "TTE_AVAILABILITY_ORDER",
            f"{field.column}: availability precedes event time",
        )
        require(
            event <= index and available <= index,
            "TTE_FUTURE_BASELINE",
            f"{field.column}: event or availability follows time zero",
        )
        require(
            not treatment or event == index,
            "TTE_ASSIGNMENT_TIME",
            "Point-treatment assignment and time zero must coincide",
        )
        times.append((event, available))
    return {
        "column": field.column,
        "contributing_records": len(times),
        "event_latest": max(t[0] for t in times).isoformat(),
        "available_latest": max(t[1] for t in times).isoformat(),
        "source_refs_sha256": sources.digest(cell["sources"]),
    }


def _recipe_scope(preparation, protocol, spec):
    unit = preparation.unit
    require(
        unit.kind == "patient"
        and unit.keys == unit.subject_keys
        and unit.index_column == protocol.time_zero.index_column
        and unit.timezone == "UTC",
        "TTE_ANALYSIS_UNIT",
        "One patient, one fixed index, identical unit/subject keys and UTC are required",
    )
    require(
        unit.null_keys == "block"
        and unit.duplicates == "block"
        and unit.key_normalization == "exact"
        and not preparation.excluded_rows,
        "TTE_SOURCE_EXCLUSION",
        "No manual row deletion, key normalization or duplicate/null-key repair in this v1",
    )
    require(
        all(
            not r.exclude_statuses and r.duplicates == "block" and r.reuse_events == "block"
            for r in preparation.relations
        ),
        "TTE_RELATION_EXCLUSION",
        "Relation exclusions, duplicate repair or shared events cannot select the target population",
    )
    require(
        protocol.eligibility.rule_ids == [r.id for r in preparation.cohort],
        "TTE_ELIGIBILITY_RULES",
        "Include every preparation eligibility rule in its exact order",
    )
    fields = {f.column: f for f in protocol.eligibility.fields}
    require(
        set(fields) == {r.keep.column for r in preparation.cohort},
        "TTE_ELIGIBILITY_FIELDS",
        "Each eligibility dependency must have exactly one timed source mapping",
    )
    outcomes = {
        f.output
        for r in preparation.relations
        if r.window and r.window.purpose == "followup"
        for f in r.features
    }
    require(
        not (set(fields) & (outcomes | {spec.outcome, spec.treatment})),
        "TTE_FUTURE_ELIGIBILITY",
        "Eligibility cannot depend on outcome, treatment selection or follow-up features",
    )
    require(
        not spec.cohort_filter and spec.subject == protocol.time_zero.subject_column,
        "TTE_ANALYSIS_POPULATION",
        "Use prepared subject identity with no additional weighting cohort filter",
    )
    require(
        digest(spec.to_dict()) == protocol.analysis.weighting_spec_sha256,
        "TTE_WEIGHTING_SPEC",
        "Protocol must bind the exact unchanged weighting specification",
    )
    require(
        spec.estimand == protocol.estimand.kind
        and spec.treatment == protocol.treatment.field.column
        and spec.treatment_levels == protocol.treatment.levels
        and spec.outcome == protocol.outcome.column
        and spec.outcome_type == protocol.outcome.kind
        and spec.outcome_unit == protocol.outcome.unit,
        "TTE_ANALYSIS_ROLES",
        "Estimand, direction, coding, outcome and units must agree with weighting",
    )
    require(
        [f.column for f in protocol.baseline] == [c["column"] for c in spec.covariates],
        "TTE_BASELINE_ROLES",
        "Every propensity covariate must have an ordered timed source mapping",
    )
    require(
        protocol.treatment.field.source_id == unit.source_id,
        "TTE_TREATMENT_SOURCE",
        "This v1 supports the root's recorded point treatment, not treatment inferred from future records",
    )
    relation = next(
        (r for r in preparation.relations if r.id == protocol.outcome.relation_id), None
    )
    require(
        relation is not None,
        "TTE_OUTCOME_RELATION",
        "Outcome must name a real prepared event relation",
    )
    feature = next((f for f in relation.features if f.output == spec.outcome), None)
    window = relation.window
    require(
        feature is not None
        and relation.kind == "events"
        and window is not None
        and window.purpose == "followup"
        and window.available_column is not None
        and window.availability == "column",
        "TTE_OUTCOME_PROVENANCE",
        "Outcome requires an explicit follow-up event relation with event/available timestamps",
    )
    require(
        (window.start_days, window.end_days, window.bounds)
        == (
            protocol.outcome.assessment_start_days,
            protocol.outcome.assessment_end_days,
            protocol.outcome.bounds,
        ),
        "TTE_OUTCOME_WINDOW",
        "Outcome window must exactly match the approved preparation",
    )
    followup = protocol.followup
    require(
        window.followup_end_column == followup.coverage_end_column
        and relation.coverage.mode == "by_column"
        and relation.coverage.column == followup.export_status_column
        and relation.coverage.exported_values == [followup.complete_export_value],
        "TTE_COVERAGE_MAPPING",
        "Outcome coverage must be a real root export flag and observation end column",
    )
    if spec.outcome_type == "binary":
        require(
            feature.aggregate == "exists" and spec.outcome_levels == ["0", "1"],
            "TTE_BINARY_OUTCOME",
            "Binary outcome is the prepared existence of a qualifying event, 0/1; not an unverified absence flag",
        )
    else:
        require(
            feature.value_type == "number"
            and feature.aggregate in {"unique", "first", "last", "mean"}
            and feature.output_unit == spec.outcome_unit,
            "TTE_CONTINUOUS_OUTCOME",
            "Continuous outcomes require a prespecified measurement summary and explicit output unit",
        )
    return relation


def validate_target_trial_source(project, metadata, dataframe, weighting_spec, protocol):
    """Return a deterministic complete source-check receipt; never fit an effect.

    Native integration must call this before BOTH inspect and locked run/reuse.
    Protocol approval remains the existing exact clinical-plan lock, not this
    function. Callers must persist/reverify the receipt in the run inventory.
    """
    protocol = TargetTrialProtocol.parse(protocol) if isinstance(protocol, dict) else protocol
    require(
        isinstance(protocol, TargetTrialProtocol) and isinstance(weighting_spec, WeightingSpec),
        "TTE_TYPED_CONTRACT",
        "Use TargetTrialProtocol and the existing WeightingSpec",
    )
    weighting_spec.validate()
    folder, plan, release, approval, binding = _context(project, metadata)
    require(
        binding == protocol.binding,
        "TTE_STALE_BINDING",
        "Every approved preparation/release/source/trace hash must match the protocol",
    )
    preparation, tables, result = _replay(folder, plan, metadata, dataframe)
    relation = _recipe_scope(preparation, protocol, weighting_spec)
    root = tables[preparation.unit.source_id]
    require(
        len(result.trace) == len(root.rows),
        "TTE_ROOT_POPULATION",
        "Every original root record must remain in the full trace",
    )
    subjects = [record["subject_id"] for record in result.trace.values()]
    require(
        len(set(subjects)) == len(subjects),
        "TTE_REPEATED_INDEX",
        "Multiple entries per person require another contract",
    )
    cohort_fields = {field.column: field for field in protocol.eligibility.fields}
    rows = []
    for record in result.trace.values():
        root_row = _source_row(record["root"], tables)
        index = _time(root_row.values[protocol.time_zero.index_column])
        eligibility_checks = []
        # Before-links rules inspect root fields; after-links rules can only use
        # a known baseline feature when that unit actually reaches the rule.
        exclusions = {e["step"] for e in record["exclusions"]}
        ordered_rules = [
            rule
            for stage in ("before_links", "after_links")
            for rule in preparation.cohort
            if rule.stage == stage
        ]
        for rule in ordered_rules:
            require(
                rule.keep.column in record["cells"],
                "TTE_ELIGIBILITY_PROVENANCE",
                "Every reached eligibility rule needs an actual timed source cell",
            )
            eligibility_checks.append(
                _timed_field(record, cohort_fields[rule.keep.column], tables, preparation, index)
            )
            if rule.id in exclusions:
                break
        row = {
            "unit_id": record["unit_id"],
            "subject_id": record["subject_id"],
            "root": record["root"],
            "included": record["included"],
            "exclusions": record["exclusions"],
            "time_zero": index.isoformat(),
            "eligibility_time_checks": eligibility_checks,
        }
        if record["included"]:
            followup = protocol.followup
            raw = root_row.values
            for column in [
                followup.coverage_start_column,
                followup.coverage_end_column,
                followup.export_status_column,
                followup.intercurrent_status_column,
            ]:
                require(
                    column in raw, "TTE_COVERAGE_COLUMN", f"Missing root coverage field {column}"
                )
            start, end = (
                _time(raw[followup.coverage_start_column]),
                _time(raw[followup.coverage_end_column]),
            )
            horizon = index + timedelta(days=followup.horizon_days)
            require(
                start <= index and end >= horizon,
                "TTE_INCOMPLETE_FOLLOWUP",
                "Every eligible person needs full observation from time zero to horizon; never drop them",
            )
            require(
                raw[followup.export_status_column] == followup.complete_export_value,
                "TTE_UNKNOWN_EXPORT",
                "Unknown/not-exported outcome sources cannot imply no event",
            )
            require(
                raw[followup.intercurrent_status_column] == followup.no_intercurrent_value,
                "TTE_INTERCURRENT_EVENT",
                "Loss, competing events or unknown intercurrent status require another protocol",
            )
            treatment_check = _timed_field(
                record, protocol.treatment.field, tables, preparation, index, treatment=True
            )
            baseline_checks = [
                _timed_field(record, field, tables, preparation, index)
                for field in protocol.baseline
            ]
            state = record["relations"][relation.id]
            require(
                state["coverage"] == "complete"
                and state["status"] in {"matched", "no_record", "outside_window", "filtered_out"},
                "TTE_OUTCOME_LINKAGE",
                f"Unresolved outcome source status: {state['status']}",
            )
            cell = record["cells"][weighting_spec.outcome]
            value = record["values"][weighting_spec.outcome]
            require(
                value is not None,
                "TTE_MISSING_OUTCOME",
                "Every eligible outcome must be observed/ascertained, with no outcome-driven exclusion",
            )
            require(
                weighting_spec.outcome_type == "binary" or cell["sources"],
                "TTE_CONTINUOUS_MEASUREMENT",
                "A continuous outcome needs observed qualifying measurement records",
            )
            for ref in cell["sources"]:
                source_row = _source_row(ref, tables)
                event = _time(source_row.values[relation.window.event_column])
                available = _time(source_row.values[relation.window.available_column])
                lower = index + timedelta(days=protocol.outcome.assessment_start_days)
                upper = index + timedelta(days=protocol.outcome.assessment_end_days)
                require(
                    (event >= lower if protocol.outcome.bounds == "both" else event > lower)
                    and event <= upper
                    and event <= available <= end,
                    "TTE_OUTCOME_TIME",
                    "Outcome contributors must be in the assessment window and available by observed source end",
                )
            if weighting_spec.outcome_type == "binary":
                require(
                    level(value) == ("1" if cell["sources"] else "0"),
                    "TTE_EVENT_DENOMINATOR",
                    "Binary outcome must equal traced event existence",
                )
            row.update(
                {
                    "horizon_end": horizon.isoformat(),
                    "coverage_start": start.isoformat(),
                    "coverage_end": end.isoformat(),
                    "treatment_time_check": treatment_check,
                    "baseline_time_checks": baseline_checks,
                    "outcome_status": state["status"],
                    "outcome_contributing_records": len(cell["sources"]),
                    "outcome_source_refs_sha256": sources.digest(cell["sources"]),
                }
            )
        rows.append(row)
    preflight = weighting_preflight(dataframe, weighting_spec)
    expected_rows = list(range(1, len(dataframe) + 1))
    ledger = preflight["case_ledger"]
    require(
        ledger["complete_data_rows"] == expected_rows
        and not ledger["missing_excluded_data_rows"]
        and not ledger["filter_excluded_data_rows"]
        and preflight["n"] == len(dataframe),
        "TTE_ANALYSIS_EXCLUSION",
        "Weighting must retain every eligible unit; complete cases cannot redefine the target",
    )
    included = [r["unit_id"] for r in rows if r["included"]]
    excluded = [r["unit_id"] for r in rows if not r["included"]]
    require(
        set(included) == set(dataframe["_rde_unit_id"]) and len(included) == len(dataframe),
        "TTE_ELIGIBLE_SET",
        "The exact eligible unit set, not merely n, must equal the analysis dataset",
    )
    payload = {
        "schema": "rde-target-trial-source-check-v1",
        "status": "passed",
        "execution_authorized": False,
        "implementation": implementation(),
        "protocol_sha256": sources.digest(protocol.to_dict()),
        "protocol": protocol.to_dict(),
        "weighting_spec_sha256": digest(weighting_spec.to_dict()),
        "weighting_spec": weighting_spec.to_dict(),
        "binding": binding.model_dump(),
        "source_bindings": [
            {"id": t.source.id, "sha256": t.source.sha256, "bytes": t.source.bytes}
            for t in tables.values()
        ],
        "clinical_validation": release["clinical_validation"],
        "preparation_review_kind": approval["review"]["kind"],
        "population": {
            "root_records": len(root.rows),
            "included": len(included),
            "excluded_by_baseline_eligibility": len(excluded),
            "included_unit_ids": included,
            "excluded_unit_ids": excluded,
            "included_unit_set_sha256": sources.digest(sorted(included)),
            "input_analysis_rows": len(dataframe),
            "analysis_n": preflight["n"],
        },
        "rows": rows,
        "preparation_flow": result.flow,
        "weighting_preflight": preflight,
        "scope": "One baseline point-treatment decision per person, fixed complete follow-up, binary event existence or continuous measurement summary; current preparation sources/rules replayed without estimating an effect.",
        "limitations": [
            "This checks recorded timestamps, mappings, source closure and row sets; it does not establish source truth or clinical endpoint adjudication.",
            "Prepared coverage and no-intercurrent-event fields remain source assertions, not independently proved completeness.",
            "Consistency, conditional exchangeability, positivity and clinical suitability are not established by this receipt.",
            "Protocol approval, exact locked-run/reuse integration, final causal report and platform are separate gates; a passing source check grants no execution authority.",
        ],
    }
    return {**payload, "receipt_sha256": sources.digest(payload)}
