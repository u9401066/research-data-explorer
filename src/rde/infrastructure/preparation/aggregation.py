"""Native declarative aggregation editing, with one immutable rule authority.

This module edits typed specifications, not source data or executable programs.
Preview and draft use the existing preparation engine and approval gates.
"""

from copy import deepcopy
import hashlib
import os
import uuid
from pathlib import Path
from typing import get_args

from pydantic import ValidationError

from rde.domain.models import preparation as rules
from rde.domain.models import preparation_edit as edits
from rde.infrastructure.evidence.workflow import safe_path
from rde.infrastructure.preparation import sources


class EditRejected(ValueError):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__("; ".join(item["message"] for item in diagnostics))


def diagnostic(code, message, stage="schema", severity="blocker", **location):
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "errorStage": stage,
        "occurrence_count": 1,
        **{k: v for k, v in location.items() if v is not None},
    }


def method_registry():
    descriptions = {
        "unique": "One distinct nonmissing typed/converted value across the entire selected relation/window; not a list. Unequal values at different times still conflict.",
        "count": "Counts selected event records, including records whose feature value is missing. Does not count nonmissing or distinct values.",
        "exists": "Returns 1 when at least one event record is selected, independent of feature-value missingness.",
        "sum": "Sum of finite nonmissing numeric values after declared unit conversion.",
        "mean": "Arithmetic mean of finite nonmissing numeric values; denominator is contributing values, not all selected records.",
        "min": "Minimum of declared typed values; text order is lexical and does not infer clinical or date meaning.",
        "max": "Maximum of declared typed values; text order is lexical and does not infer clinical or date meaning.",
        "first": "Earliest event timestamp with a nonmissing typed/converted value. All values at that timestamp must agree; other timestamps may differ. Never uses physical row order.",
        "last": "Latest event timestamp with a nonmissing typed/converted value. All values at that timestamp must agree; other timestamps may differ. Never uses physical row order.",
        "days_to_first": "Earliest selected event timestamp minus unit index in fractional 24-hour days. Baseline values may be negative; feature-value missingness is not consulted.",
    }
    ids = get_args(rules.Feature.model_fields["aggregate"].annotation)
    assert set(ids) == set(descriptions), "Aggregation registry must cover the exact native enum"
    methods = []
    for name in ids:
        record_based = name in {"count", "exists", "days_to_first"}
        numeric = record_based or name in {"sum", "mean"}
        methods.append(
            {
                "id": name,
                "description": descriptions[name],
                "relation_kinds": ["lookup", "events"] if name == "unique" else ["events"],
                "input_types": ["event_time"]
                if name == "days_to_first"
                else (
                    ["record"]
                    if record_based
                    else (["number"] if numeric else ["text", "number", "datetime"])
                ),
                "column_required": not record_based,
                "window_required": name in {"first", "last", "days_to_first"},
                "output_type": "number"
                if numeric
                else "declared_value_type_datetime_stored_as_iso_text",
                "cardinality": "one scalar per analysis unit; no Cartesian row expansion",
                "null_behavior": "No usable value -> null. Only count/exists can yield zero for no selected records, and only with complete coverage and no_record/outside_window/filtered_out status. Unknown, not_exported, link_failed and not_available never establish zero.",
                "ties": "All equal-valued source records at the selected timestamp retained; conflicting values block"
                if name in {"first", "last"}
                else (
                    "All selected nonmissing values must agree"
                    if name == "unique"
                    else "No row-order arbitration"
                ),
                "trace": "All selected-time contributors"
                if name in {"first", "last", "days_to_first"}
                else (
                    "All selected records"
                    if record_based
                    else "All nonmissing compared/contributing records; min/max retain comparisons, not only extremum witnesses. All-missing retains selected records as missingness evidence."
                ),
                "output_role": "window.purpose or explicit at_index_basis; otherwise descriptive. Method names never establish availability or clinical meaning.",
            }
        )
    return methods


def contract():
    payload = {
        "schema": "rde-aggregation-contract-v1",
        "methods": method_registry(),
        "unit_schema": rules.Unit.model_json_schema(),
        "definitions_schema": rules.Definitions.model_json_schema(),
        "operation_schema": edits.operation_adapter.json_schema(),
        "reference_schema": edits.CandidateReference.model_json_schema(),
        "compose_schema": edits.ComposeRequest.model_json_schema(),
        "patch_schema": edits.PatchRequest.model_json_schema(),
        "rejected_schema": "rde-aggregation-edit-rejected-v1",
        "operations": [
            "aggregation_compose",
            "aggregation_patch",
            "aggregation_read",
            "aggregation_preview",
            "aggregation_diff",
        ],
        "execution_semantics": {
            "unit_conversion": rules.UNIT_CONVERSION_SEMANTICS,
            "identity": "Use exact candidate_ref and stable relation.id/feature.output/cohort.id targets. Sources are immutable; changes to source bytes/parser need a new candidate. Never use array offsets or arbitrary JSON pointers.",
            "compose": "Supply a declared unit and known definitions, or import from_specification. Unspecified definitions and unhandled sources remain incomplete diagnostics; no automatic facts or omission reasons.",
            "patch": "1..32 typed operations applied atomically to the exact latest base. Unmentioned rules remain unchanged. Whole resulting specification is validated before a new revision is saved. Repeating the exact revision_id and request returns the same receipt; reusing an ID for different intent fails.",
            "preview": "Executes the existing native engine, reports all denominators and precise grouped diagnostics. ready_for_draft means technical completeness only, never clinical validation or independent research-intent alignment. Source drift blocks execution.",
            "approval": "Candidate revisions have no approval state. Draft resolves exact candidate_ref; original semantic review, immutable draft, automated/human review and exact approval/release gates remain required. A patch never inherits approval.",
            "missing": "Unknown coverage is not zero. One-to-many events are independently aggregated before joining each unit. Do not delete units or replace latest with extrema merely to remove a blocker.",
            "programs": "Only declared typed operations and existing methods. No Python, SQL, expression evaluation, raw joins or implicit source edits.",
        },
    }
    return {**payload, "contract_sha256": sources.digest(payload)}


def location_errors(error, raw):
    result = []
    for item in error.errors(include_url=False, include_input=False):
        loc = list(item["loc"])
        relation = None
        feature = None
        if "operations" in loc and isinstance(raw, dict):
            at = loc.index("operations")
            index = loc[at + 1] if len(loc) > at + 1 else None
            operations = raw.get("operations", [])
            if (
                isinstance(operations, list)
                and isinstance(index, int)
                and 0 <= index < len(operations)
            ):
                operation = operations[index]
                if isinstance(operation, dict):
                    relation = operation.get("relation")
                    if not isinstance(relation, dict):
                        relation = {"id": operation.get("relation_id")}
                    feature = operation.get("feature")
                    if not isinstance(feature, dict):
                        feature = {"output": operation.get("feature_output")}
        if "relations" in loc:
            at = loc.index("relations")
            index = loc[at + 1] if len(loc) > at + 1 else None
            entries = raw.get("relations", []) if isinstance(raw, dict) else []
            if isinstance(entries, list) and isinstance(index, int) and 0 <= index < len(entries):
                relation = entries[index] if isinstance(entries[index], dict) else None
        if relation and "features" in loc:
            at = loc.index("features")
            index = loc[at + 1] if len(loc) > at + 1 else None
            entries = relation.get("features", [])
            if isinstance(index, int) and isinstance(entries, list) and 0 <= index < len(entries):
                feature = entries[index] if isinstance(entries[index], dict) else None
        result.append(
            diagnostic(
                "INVALID_RULE",
                item["msg"],
                relation_id=relation.get("id") if relation else None,
                source_id=relation.get("source_id") if relation else None,
                feature_output=feature.get("output") if feature else None,
                rule_path=[str(v) for v in loc],
            )
        )
    return result


def validate_spec(raw):
    # Expose validator constraints at a stable feature target, before Pydantic
    # reduces a relation-level error to relations.N.
    diagnostics = []
    for relation in raw.get("relations", []):
        if not isinstance(relation, dict):
            continue
        for feature in relation.get("features", []):
            if not isinstance(feature, dict):
                continue
            name = feature.get("aggregate")
            loc = {
                "relation_id": relation.get("id"),
                "feature_output": feature.get("output"),
                "source_id": relation.get("source_id"),
            }
            if relation.get("kind") == "lookup" and name != "unique":
                diagnostics.append(
                    diagnostic(
                        "LOOKUP_AGGREGATE_UNSUPPORTED",
                        "Lookup features require unique; first/last are event aggregations, not physical row selection.",
                        allowed_methods=["unique"],
                        **loc,
                    )
                )
            if (
                relation.get("kind") == "events"
                and name in {"first", "last", "days_to_first"}
                and not relation.get("window")
            ):
                diagnostics.append(
                    diagnostic(
                        "AGGREGATE_WINDOW_REQUIRED",
                        "This aggregation requires an explicit event-time window.",
                        **loc,
                    )
                )
    if diagnostics:
        raise EditRejected(diagnostics)
    try:
        return rules.Specification.model_validate(raw)
    except ValidationError as error:
        raise EditRejected(location_errors(error, raw)) from error


def apply_operations(specification, operations):
    raw = deepcopy(specification)

    def target(relation_id):
        relation = next((r for r in raw["relations"] if r["id"] == relation_id), None)
        if relation is None:
            raise EditRejected(
                [
                    diagnostic(
                        "UNKNOWN_RELATION",
                        "No relation with this stable ID.",
                        relation_id=relation_id,
                    )
                ]
            )
        return relation

    for operation in operations:
        op = operation.model_dump(mode="json")
        name = op["op"]
        if name == "unit_set":
            raw["unit"] = op["unit"]
        elif name == "definition_set":
            raw["definitions"][op["field"]] = op["value"]
        elif name == "relation_add":
            if any(r["id"] == op["relation"]["id"] for r in raw["relations"]):
                raise EditRejected(
                    [
                        diagnostic(
                            "RELATION_EXISTS",
                            "relation_add cannot replace an existing relation.",
                            relation_id=op["relation"]["id"],
                        )
                    ]
                )
            raw["relations"].append(op["relation"])
        elif name == "relation_remove":
            raw["relations"].remove(target(op["relation_id"]))
        elif name == "relation_update":
            target(op["relation_id"]).update(
                operation.changes.model_dump(mode="json", exclude_unset=True)
            )
        elif name == "feature_set":
            relation = target(op["relation_id"])
            index = next(
                (
                    i
                    for i, f in enumerate(relation["features"])
                    if f["output"] == op["feature"]["output"]
                ),
                None,
            )
            if index is None:
                relation["features"].append(op["feature"])
            else:
                relation["features"][index] = op["feature"]
        elif name == "feature_remove":
            relation = target(op["relation_id"])
            feature = next(
                (f for f in relation["features"] if f["output"] == op["feature_output"]), None
            )
            if feature is None:
                raise EditRejected(
                    [
                        diagnostic(
                            "UNKNOWN_FEATURE",
                            "No feature with this stable output name.",
                            relation_id=op["relation_id"],
                            feature_output=op["feature_output"],
                        )
                    ]
                )
            relation["features"].remove(feature)
        elif name in {"window_set", "filters_set"}:
            field = "window" if name == "window_set" else "filters"
            target(op["relation_id"])[field] = op[field]
        elif name == "cohort_set":
            index = next(
                (i for i, r in enumerate(raw["cohort"]) if r["id"] == op["rule"]["id"]), None
            )
            if index is None:
                raw["cohort"].append(op["rule"])
            else:
                raw["cohort"][index] = op["rule"]
        elif name == "cohort_remove":
            index = next((i for i, r in enumerate(raw["cohort"]) if r["id"] == op["rule_id"]), None)
            if index is None:
                raise EditRejected(
                    [diagnostic("UNKNOWN_COHORT_RULE", "No cohort rule with this ID.")]
                )
            raw["cohort"].pop(index)
        elif name == "cohort_order":
            by_id = {r["id"]: r for r in raw["cohort"]}
            if len(op["rule_ids"]) != len(by_id) or set(op["rule_ids"]) != set(by_id):
                raise EditRejected(
                    [diagnostic("INVALID_COHORT_ORDER", "Supply every cohort ID exactly once.")]
                )
            raw["cohort"] = [by_id[k] for k in op["rule_ids"]]
        elif name == "omission_set":
            raw["omitted_sources"][op["source_id"]] = op["reason"]
        elif name == "omission_remove":
            if op["source_id"] not in raw["omitted_sources"]:
                raise EditRejected(
                    [
                        diagnostic(
                            "UNKNOWN_OMISSION",
                            "No omission for this source.",
                            source_id=op["source_id"],
                        )
                    ]
                )
            del raw["omitted_sources"][op["source_id"]]
        elif name == "exclusion_add":
            key = (op["row"]["source_id"], op["row"]["record_index"])
            if any((r["source_id"], r["record_index"]) == key for r in raw["excluded_rows"]):
                raise EditRejected(
                    [diagnostic("EXCLUSION_EXISTS", "Source row already has an exclusion.")]
                )
            raw["excluded_rows"].append(op["row"])
        elif name == "exclusion_remove":
            row = next(
                (
                    r
                    for r in raw["excluded_rows"]
                    if all(r[k] == op[k] for k in ("source_id", "record_index", "row_sha256"))
                ),
                None,
            )
            if row is None:
                raise EditRejected(
                    [diagnostic("UNKNOWN_EXCLUSION", "No exclusion with this exact row identity.")]
                )
            raw["excluded_rows"].remove(row)
    return validate_spec(raw)


def rule_diff(before, after):
    changes = []

    def compare(a, b, location):
        if a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                if key in a and key in b:
                    compare(
                        a[key],
                        b[key],
                        {**location, "field": ".".join(filter(None, [location.get("field"), key]))},
                    )
                else:
                    changes.append(
                        {**location, "field": key, "before": a.get(key), "after": b.get(key)}
                    )
        else:
            changes.append({**location, "before": a, "after": b})

    for field in ["unit", "definitions", "omitted_sources", "excluded_rows"]:
        compare(before[field], after[field], {"component": field})
    for field, identity in [("relations", "id"), ("cohort", "id")]:
        a = {v[identity]: v for v in before[field]}
        b = {v[identity]: v for v in after[field]}
        for key in sorted(set(a) | set(b)):
            location = {
                "component": field,
                "relation_id" if field == "relations" else "rule_id": key,
            }
            if key not in a or key not in b:
                changes.append({**location, "before": a.get(key), "after": b.get(key)})
            elif field == "relations":
                compare(
                    {k: v for k, v in a[key].items() if k != "features"},
                    {k: v for k, v in b[key].items() if k != "features"},
                    location,
                )
                aa = {f["output"]: f for f in a[key]["features"]}
                bb = {f["output"]: f for f in b[key]["features"]}
                for output in sorted(set(aa) | set(bb)):
                    compare(aa.get(output), bb.get(output), {**location, "feature_output": output})
            else:
                compare(a[key], b[key], location)
        order_a, order_b = [v[identity] for v in before[field]], [v[identity] for v in after[field]]
        if order_a != order_b:
            changes.append(
                {"component": field, "field": "order", "before": order_a, "after": order_b}
            )
    return {
        "schema": "rde-aggregation-rule-diff-v1",
        "changes": changes,
        "requires_new_review": before != after,
    }


def binding_diagnostics(spec, tables):
    result = []

    def require(source_id, columns, **location):
        if source_id not in tables:
            result.append(
                diagnostic(
                    "UNKNOWN_SOURCE",
                    "Rule refers to a source outside the frozen source set.",
                    source_id=source_id,
                    **location,
                )
            )
            return
        for column in dict.fromkeys(c for c in columns if c is not None):
            if column not in tables[source_id].columns:
                result.append(
                    diagnostic(
                        "UNKNOWN_COLUMN",
                        "Column is not in the native verified source schema.",
                        source_id=source_id,
                        column=column,
                        **location,
                    )
                )

    unit = spec.unit
    require(
        unit.source_id,
        unit.keys
        + unit.subject_keys
        + list(unit.columns)
        + (unit.retain_columns or [])
        + ([unit.index_column] if unit.index_column else []),
    )
    root_columns = tables[unit.source_id].columns if unit.source_id in tables else []
    output_columns = set(root_columns)
    for relation in spec.relations:
        loc = {"relation_id": relation.id}
        require(
            unit.source_id,
            relation.left_keys + ([relation.coverage.column] if relation.coverage.column else []),
            **loc,
        )
        require(relation.source_id, relation.right_keys + relation.record_keys, **loc)
        output_columns.add("_rde_" + relation.id + "_status")
        for feature in relation.features:
            require(
                relation.source_id,
                [feature.column, feature.unit_column],
                feature_output=feature.output,
                **loc,
            )
            if feature.output in root_columns:
                result.append(
                    diagnostic(
                        "OUTPUT_OVERWRITES_SOURCE",
                        "Derived output cannot replace an original source column.",
                        feature_output=feature.output,
                        **loc,
                    )
                )
            output_columns.add(feature.output)
        for predicate in relation.filters:
            require(relation.source_id, [predicate.column], **loc)
        if relation.window:
            require(
                relation.source_id,
                [relation.window.event_column, relation.window.available_column],
                **loc,
            )
            require(unit.source_id, [relation.window.followup_end_column], **loc)
            if not unit.index_column:
                result.append(
                    diagnostic(
                        "INDEX_REQUIRED",
                        "Event windows require a declared unit index column.",
                        **loc,
                    )
                )
    for rule in spec.cohort:
        available = set(root_columns) if rule.stage == "before_links" else output_columns
        if rule.keep.column not in available:
            result.append(
                diagnostic(
                    "COHORT_DEPENDENCY_MISSING",
                    "Cohort rule refers to an unavailable column at its declared stage.",
                    "cohort",
                    column=rule.keep.column,
                    rule_id=rule.id,
                )
            )
    used = {unit.source_id, *(r.source_id for r in spec.relations)}
    for source_id in set(spec.omitted_sources) - set(tables):
        result.append(
            diagnostic(
                "UNKNOWN_SOURCE", "Omitted source is outside frozen inputs.", source_id=source_id
            )
        )
    for source_id, reason in spec.omitted_sources.items():
        if source_id in used or not reason.strip():
            result.append(
                diagnostic(
                    "INVALID_OMISSION",
                    "A used source cannot be omitted, and omissions require a nonblank reason.",
                    source_id=source_id,
                )
            )
    for row in spec.excluded_rows:
        if row.source_id not in used or row.source_id not in tables:
            result.append(
                diagnostic(
                    "INVALID_EXCLUSION",
                    "Exclusion must identify a used source.",
                    source_id=row.source_id,
                )
            )
        elif (
            row.record_index >= len(tables[row.source_id].rows)
            or tables[row.source_id].rows[row.record_index].sha256 != row.row_sha256
        ):
            result.append(
                diagnostic(
                    "SOURCE_ROW_CHANGED",
                    "Exclusion row identity does not match actual source bytes.",
                    source_id=row.source_id,
                )
            )
    return result


def completeness(spec, source_ids):
    result = [
        diagnostic(
            "DEFINITION_" + name.upper(),
            "Research definition remains unknown; do not invent it from column names.",
            "definitions",
            field=name,
        )
        for name, value in spec.definitions.model_dump().items()
        if not value.strip()
    ]
    used = {spec.unit.source_id, *(r.source_id for r in spec.relations)}
    for source_id in sorted(set(source_ids) - used - set(spec.omitted_sources)):
        result.append(
            diagnostic(
                "SOURCE_RULE_REQUIRED",
                "Source still needs an explicit relation or a reasoned omission.",
                source_id=source_id,
            )
        )
    return result


def grouped_issues(issues, specification):
    result = {}
    relations = specification["relations"]
    for issue in issues:
        item = {k: v for k, v in issue.items() if k not in {"records", "unit_id"}}
        if not item.get("relation_id"):
            matches = [
                r
                for r in relations
                if issue["code"].endswith("_" + r["id"])
                or any(f["output"] == issue.get("column") for f in r["features"])
            ]
            if len(matches) == 1:
                item["relation_id"] = matches[0]["id"]
                item.setdefault("source_id", matches[0]["source_id"])
        if not item.get("feature_output") and issue.get("column"):
            if any(f["output"] == issue["column"] for r in relations for f in r["features"]):
                item["feature_output"] = issue["column"]
        item.setdefault(
            "errorStage", "definitions" if issue["code"].startswith("DEFINITION_") else "linkage"
        )
        key = sources.canonical(item)
        group = result.setdefault(key, {**item, "occurrence_count": 0, "unit_ids": []})
        group["occurrence_count"] += 1
        if issue.get("unit_id") and len(group["unit_ids"]) < 20:
            group["unit_ids"].append(issue["unit_id"])
    return list(result.values())


def _w():
    # Lazy: workflow includes aggregation in its implementation fingerprint.
    from rde.infrastructure.preparation import workflow

    return workflow


def _folder(project, candidate_id):
    from rde.infrastructure.evidence.workflow import canonical_id

    canonical_id(candidate_id)
    return safe_path(_w().directory(project), "candidates/" + candidate_id)


def _source_hash(inputs):
    return sources.digest(sorted(inputs, key=lambda s: s["id"]))


def _ref(receipt):
    return {
        key: receipt[key]
        for key in (
            "candidate_id",
            "revision_id",
            "revision",
            "receipt_sha256",
            "specification_sha256",
            "source_set_sha256",
        )
    }


def _head(project, candidate_id):
    folder = _folder(project, candidate_id)
    if not folder.exists():
        return None
    records = [_w().read_sealed(p) for p in folder.glob("*.json")]
    if not records:
        return None
    by_revision = {}
    for record in records:
        if record.get("project_id") != project.id or record.get("candidate_id") != candidate_id:
            raise ValueError("CANDIDATE_OWNERSHIP: invalid revision owner")
        number = record.get("revision")
        if type(number) is not int or number < 1 or number in by_revision:
            raise ValueError("CORRUPT_CANDIDATE: invalid revision chain")
        by_revision[number] = record
    if sorted(by_revision) != list(range(1, len(by_revision) + 1)):
        raise ValueError("CORRUPT_CANDIDATE: missing revision")
    for number, record in by_revision.items():
        if number > 1 and record.get("parent") != _ref(by_revision[number - 1]):
            raise ValueError("CORRUPT_CANDIDATE: parent reference mismatch")
    return by_revision[len(by_revision)]


def read_candidate(project, reference, live=False):
    ref = edits.CandidateReference.model_validate(reference)
    path = safe_path(_folder(project, ref.candidate_id), ref.revision_id + ".json")
    receipt = _w().read_sealed(path)
    if (
        receipt.get("schema") != "rde-aggregation-candidate-receipt-v1"
        or receipt.get("project_id") != project.id
        or _ref(receipt) != ref.model_dump()
    ):
        raise ValueError("STALE_CANDIDATE: reference or ownership differs")
    if (
        sources.digest(receipt["specification"]) != ref.specification_sha256
        or _source_hash(receipt["sources"]) != ref.source_set_sha256
    ):
        raise ValueError("CORRUPT_CANDIDATE: source/specification digest mismatch")
    _head(project, ref.candidate_id)  # Verify the retained parent chain, even for historical reads.
    snapshots = [item["source"] for item in receipt["source_snapshots"]]
    if _source_hash(snapshots) != ref.source_set_sha256:
        raise ValueError("CORRUPT_CANDIDATE: snapshot inventory differs from pinned sources")
    root = _w().directory(project)
    for item in receipt["source_snapshots"]:
        path = safe_path(root, item["snapshot"])
        source = rules.Source.model_validate(item["source"])
        if path.stat().st_size != source.bytes or sources.file_hash(path) != source.sha256:
            raise ValueError("CORRUPT_CANDIDATE: original source snapshot changed")
        if live:
            source_path = Path(source.path)
            if (
                not source_path.is_file()
                or source_path.stat().st_size != source.bytes
                or sources.file_hash(source_path) != source.sha256
            ):
                raise ValueError("SOURCE_CHANGED: create a new candidate from current sources")
    if live and receipt["implementation"] != _w().implementation():
        raise ValueError(
            "STALE_CANDIDATE_IMPLEMENTATION: create a new candidate under current contract"
        )
    return receipt


def _tables(project, receipt, live=False):
    return {
        item["source"]["id"]: sources.load(
            rules.Source.model_validate(item["source"]),
            None if live else safe_path(_w().directory(project), item["snapshot"]),
        )
        for item in receipt["source_snapshots"]
    }


def candidate_result(receipt, diff=None):
    result = {
        "schema": "rde-aggregation-candidate-v1",
        "project_id": receipt["project_id"],
        "candidate_ref": _ref(receipt),
        "specification": receipt["specification"],
        "diagnostics": completeness(
            rules.Specification.model_validate(receipt["specification"]),
            [s["id"] for s in receipt["sources"]],
        ),
    }
    if diff is not None:
        result["diff"] = diff
    return result


def compose(project, raw):
    request = edits.ComposeRequest.model_validate(raw)
    spec = request.from_specification or rules.Specification(
        unit=request.unit, definitions=request.definitions or rules.Definitions()
    )
    spec = validate_spec(spec.model_dump())
    inputs = [s.model_dump() for s in request.sources]
    intent = {"request": request.model_dump(mode="json"), "implementation": _w().implementation()}
    path = safe_path(_folder(project, request.candidate_id), request.revision_id + ".json")
    if path.exists():
        receipt = _w().read_sealed(path)
        if receipt.get("intent_sha256") != sources.digest(intent):
            raise ValueError("IMMUTABLE_CONFLICT: revision ID has different compose intent")
        read_candidate(project, _ref(receipt), live=True)
        return candidate_result(receipt)
    if _head(project, request.candidate_id):
        raise ValueError("CANDIDATE_EXISTS: use patch with its exact reference")
    tables = {s.id: sources.load(s) for s in request.sources}
    diagnostics = binding_diagnostics(spec, tables)
    if diagnostics:
        raise EditRejected(diagnostics)
    snapshots = []
    for source in request.sources:
        relative = "sources/" + source.sha256 + Path(source.path).suffix.lower()
        data = Path(source.path).read_bytes()
        if len(data) != source.bytes or hashlib.sha256(data).hexdigest() != source.sha256:
            raise ValueError("SOURCE_CHANGED during candidate snapshot")
        _w().write_bytes(safe_path(_w().directory(project), relative), data)
        snapshots.append({"source": source.model_dump(), "snapshot": relative})
    receipt = _w().seal(
        path,
        {
            "schema": "rde-aggregation-candidate-receipt-v1",
            "project_id": project.id,
            "candidate_id": request.candidate_id,
            "revision_id": request.revision_id,
            "revision": 1,
            "parent": None,
            "specification": spec.model_dump(),
            "specification_sha256": sources.digest(spec.model_dump()),
            "sources": inputs,
            "source_set_sha256": _source_hash(inputs),
            "source_snapshots": snapshots,
            "implementation": intent["implementation"],
            "contract_sha256": contract()["contract_sha256"],
            "intent_sha256": sources.digest(intent),
            "author": request.author,
            "reason": request.reason,
            "created_at": _w().now(),
            "operations": [],
        },
    )
    return candidate_result(receipt)


def patch(project, raw):
    request = edits.PatchRequest.model_validate(raw)
    base = read_candidate(project, request.candidate_ref.model_dump(), live=True)
    intent = request.model_dump(mode="json")
    path = safe_path(
        _folder(project, request.candidate_ref.candidate_id), request.revision_id + ".json"
    )
    if path.exists():
        receipt = _w().read_sealed(path)
        if receipt.get("intent_sha256") != sources.digest(intent):
            raise ValueError("IMMUTABLE_CONFLICT: revision ID has different patch intent")
        read_candidate(project, _ref(receipt), live=True)
        return candidate_result(receipt, rule_diff(base["specification"], receipt["specification"]))
    if (
        _ref(_head(project, request.candidate_ref.candidate_id))
        != request.candidate_ref.model_dump()
    ):
        raise ValueError("STALE_CANDIDATE: patch must use the latest exact base revision")
    spec = apply_operations(base["specification"], request.operations)
    diagnostics = binding_diagnostics(spec, _tables(project, base, live=True))
    if diagnostics:
        raise EditRejected(diagnostics)
    receipt = _w().seal(
        path,
        {
            **{k: v for k, v in base.items() if k not in {"receipt_sha256"}},
            "revision_id": request.revision_id,
            "revision": base["revision"] + 1,
            "parent": request.candidate_ref.model_dump(),
            "specification": spec.model_dump(),
            "specification_sha256": sources.digest(spec.model_dump()),
            "intent_sha256": sources.digest(intent),
            "author": request.author,
            "reason": request.reason,
            "created_at": _w().now(),
            "operations": [
                op.model_dump(mode="json", exclude_unset=True) for op in request.operations
            ],
        },
    )
    return candidate_result(receipt, rule_diff(base["specification"], receipt["specification"]))


def preview(project, reference):
    from rde.infrastructure.preparation.engine import Evaluation

    receipt = read_candidate(project, reference, live=True)
    retained = _preview_path(project, receipt)
    if (retained / "preview.json").exists():
        return _preview_result(_read_preview(project, receipt))
    spec = rules.Specification.model_validate(receipt["specification"])
    tables = _tables(project, receipt, live=True)
    diagnostics = binding_diagnostics(spec, tables) + completeness(spec, tables)
    summary = None
    result = None
    if not any(d["code"] == "SOURCE_RULE_REQUIRED" for d in diagnostics):
        try:
            result = Evaluation(tables, spec, project.id).evaluate()
            summary = result.summary()
            diagnostics = grouped_issues(result.issues, receipt["specification"])
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            diagnostics.append(diagnostic("PREVIEW_RULE_ERROR", str(error), "preview"))
    payload = {
        "schema": "rde-aggregation-preview-v1",
        "candidate_ref": _ref(receipt),
        "ready_for_draft": summary is not None
        and summary["ready_for_approval"]
        and not any(d["severity"] == "blocker" for d in diagnostics),
        "advisory_only": True,
        "clinical_validation": "not_performed",
        "summary": summary,
        "diagnostics": diagnostics,
    }
    stage = retained.with_name(".preview-" + str(uuid.uuid4()))
    stage.mkdir(parents=True, mode=0o700)
    issues = result.issues if result is not None else diagnostics
    trace = result.trace.values() if result is not None else []
    for name, entries in (("issues", issues), ("trace", trace)):
        _w().write_bytes(
            stage / (name + ".jsonl"),
            "".join(sources.canonical(item) + "\n" for item in entries).encode(),
        )
    _w().write_bytes(stage / "validation.json", (sources.canonical(summary) + "\n").encode())
    saved = _w().seal(stage / "preview.json", {**payload, "files": _w().inventory(stage)})
    retained.parent.mkdir(parents=True, exist_ok=True)
    os.replace(stage, retained)
    return _preview_result(saved)


def _preview_path(project, candidate):
    return safe_path(
        _folder(project, candidate["candidate_id"]), "previews/" + candidate["revision_id"]
    )


def _read_preview(project, candidate, expected=None):
    folder = _preview_path(project, candidate)
    receipt = _w().read_sealed(folder / "preview.json")
    if (
        receipt.get("schema") != "rde-aggregation-preview-v1"
        or receipt.get("candidate_ref") != _ref(candidate)
        or (expected is not None and receipt["receipt_sha256"] != expected)
    ):
        raise ValueError("STALE_PREVIEW: candidate or preview hash differs")
    _w().verify_files(folder, receipt["files"])
    return receipt


def _preview_result(receipt):
    return {
        **{k: v for k, v in receipt.items() if k not in {"receipt_sha256", "files"}},
        "preview_sha256": receipt["receipt_sha256"],
    }


def preview_page(project, candidate, request):
    expected = request.get("preview_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("preview_sha256 is required to read retained preview evidence")
    preview_receipt = _read_preview(project, candidate, expected)
    section = request.get("section")
    if section not in {"issues", "units", "output", "trace"}:
        raise ValueError("unknown aggregation preview section")
    offset, limit = request.get("offset", 0), request.get("limit", 30)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid preview page offset/limit")
    folder = _preview_path(project, candidate)
    common = {
        "schema": "rde-aggregation-preview-page-v1",
        "candidate_ref": _ref(candidate),
        "preview_sha256": preview_receipt["receipt_sha256"],
        "section": section,
    }
    if section != "trace":
        selected, total = [], 0
        for record in _w().lines(
            folder / ("issues.jsonl" if section == "issues" else "trace.jsonl")
        ):
            if section == "output" and not record["included"]:
                continue
            if offset <= total < offset + limit:
                selected.append(
                    record
                    if section == "issues"
                    else {
                        k: record[k]
                        for k in (
                            "unit_id",
                            "subject_id",
                            "root",
                            "included",
                            "exclusions",
                            "values",
                        )
                    }
                )
            total += 1
        return {
            **common,
            "records": selected,
            "offset": offset,
            "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
        }
    unit_id = request.get("unit_id")
    record = next(
        (item for item in _w().lines(folder / "trace.jsonl") if item["unit_id"] == unit_id), None
    )
    if record is None:
        raise ValueError("unit does not belong to this exact preview")
    column = request.get("column")
    if column is None:
        return {
            **common,
            **{
                k: record[k]
                for k in ("unit_id", "subject_id", "root", "included", "exclusions", "values")
            },
            "traceable_columns": list(record["cells"]),
        }
    if column not in record["cells"]:
        raise ValueError("column has no trace in this preview")
    cell = record["cells"][column]
    refs = cell["sources"]
    tables = {}
    values = []
    for ref in refs[offset : offset + limit]:
        source_id = ref["source_id"]
        if source_id not in tables:
            source = next(
                s for s in candidate["source_snapshots"] if s["source"]["id"] == source_id
            )
            tables[source_id] = sources.load(
                rules.Source.model_validate(source["source"]),
                safe_path(_w().directory(project), source["snapshot"]),
            )
        row = tables[source_id].rows[ref["record_index"]]
        if (
            row.sha256 != ref["row_sha256"]
            or tables[source_id].source.sha256 != ref["source_sha256"]
        ):
            raise ValueError("CORRUPT_TRACE: source identity differs")
        values.append({"reference": ref, "values": row.values})
    relation = cell.get("relation")
    linkage = record["relations"].get(relation) if relation else None
    return {
        **common,
        "unit_id": unit_id,
        "column": column,
        "value": record["values"].get(column),
        "rule": {k: v for k, v in cell.items() if k != "sources"},
        "root_reference": record["root"],
        "relation_rule": next(
            (r for r in candidate["specification"]["relations"] if r["id"] == relation), None
        ),
        "linkage_evidence": {
            "status": linkage["status"],
            "coverage": linkage["coverage"],
            "matched_count": len(linkage["matched_records"]),
            "selected_count": len(linkage["selected_records"]),
            "excluded_counts": {reason: len(rows) for reason, rows in linkage["excluded"].items()},
        }
        if linkage
        else None,
        "source_records": values,
        "offset": offset,
        "total": len(refs),
        "next_offset": offset + limit if offset + limit < len(refs) else None,
    }


def preview_diff(project, before, after):
    paths = [_preview_path(project, candidate) for candidate in (before, after)]
    if not all((path / "preview.json").exists() for path in paths):
        return {
            "status": "not_evaluated",
            "reason": "Both exact candidates need retained previews before comparing outcomes.",
        }
    previews = [_read_preview(project, candidate) for candidate in (before, after)]
    if any(p["summary"] is None for p in previews):
        return {
            "status": "not_evaluated",
            "reason": "An incomplete candidate has no computed population.",
        }
    rows = [
        {r["unit_id"]: r for r in _w().lines(path / "trace.jsonl") if r["included"]}
        for path in paths
    ]
    a, b = rows
    common = set(a) & set(b)
    changed_values = {}
    changed_members = {}
    for uid in common:
        for column in set(a[uid]["values"]) | set(b[uid]["values"]):
            if (column in a[uid]["values"]) != (column in b[uid]["values"]) or a[uid]["values"].get(
                column
            ) != b[uid]["values"].get(column):
                changed_values[column] = changed_values.get(column, 0) + 1
        for column in set(a[uid]["cells"]) | set(b[uid]["cells"]):
            aa = sorted(
                sources.canonical(r) for r in a[uid]["cells"].get(column, {}).get("sources", [])
            )
            bb = sorted(
                sources.canonical(r) for r in b[uid]["cells"].get(column, {}).get("sources", [])
            )
            if aa != bb:
                changed_members[column] = changed_members.get(column, 0) + 1
    return {
        "status": "compared",
        "before_preview_sha256": previews[0]["receipt_sha256"],
        "after_preview_sha256": previews[1]["receipt_sha256"],
        "population": {
            "before": previews[0]["summary"]["population"],
            "after": previews[1]["summary"]["population"],
        },
        "added_units": len(set(b) - set(a)),
        "removed_units": len(set(a) - set(b)),
        "changed_value_units_by_column": changed_values,
        "changed_member_units_by_column": changed_members,
        "relationships": {
            "before": previews[0]["summary"]["relationships"],
            "after": previews[1]["summary"]["relationships"],
        },
    }


def resolve_draft(project, reference):
    receipt = read_candidate(project, reference, live=True)
    result = preview(project, reference)
    if not result["ready_for_draft"]:
        raise EditRejected(
            result["diagnostics"]
            or [diagnostic("CANDIDATE_NOT_READY", "Candidate needs review before draft.")]
        )
    return receipt


def execute(project, request):
    operation = request.get("op")
    try:
        if operation == "aggregation_compose":
            return compose(project, request)
        if operation == "aggregation_patch":
            return patch(project, request)
        if operation == "aggregation_read":
            candidate = read_candidate(project, request["candidate_ref"])
            if "section" in request or "preview_sha256" in request:
                return preview_page(project, candidate, request)
            return candidate_result(candidate)
        if operation == "aggregation_preview":
            return preview(project, request["candidate_ref"])
        if operation == "aggregation_diff":
            before = read_candidate(project, request["before"])
            after = read_candidate(project, request["after"])
            if before["source_set_sha256"] != after["source_set_sha256"]:
                raise ValueError(
                    "SOURCE_SCOPE_DIFFERS: explicit source revision comparison required"
                )
            return {
                **rule_diff(before["specification"], after["specification"]),
                "before": _ref(before),
                "after": _ref(after),
                "outcomes": preview_diff(project, before, after),
            }
    except (EditRejected, ValidationError) as error:
        diagnostics = (
            error.diagnostics
            if isinstance(error, EditRejected)
            else location_errors(error, request.get("from_specification", request))
        )
        return {
            "schema": "rde-aggregation-edit-rejected-v1",
            "status": "rejected",
            **({"candidate_ref": request["candidate_ref"]} if "candidate_ref" in request else {}),
            "diagnostics": diagnostics,
        }
    raise ValueError("unknown aggregation operation")
