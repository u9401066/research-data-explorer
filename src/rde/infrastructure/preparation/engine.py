"""Evaluate approved-shaped specifications without multiplying analysis units.

Execution is independent of pandas/SQL joins: each relation reduces records for
one declared unit to scalar features. SQL is used separately in oracle tests.
"""

import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from rde.domain.models.preparation import ColumnRule, Specification
from rde.infrastructure.preparation.sources import canonical, digest, empty, key


def timestamp(value, zone):
    if empty(value):
        raise ValueError("missing timestamp")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("timestamps must use unambiguous ISO dates/times") from None
    if parsed.tzinfo is None:
        tz = ZoneInfo(zone)
        first, second = parsed.replace(tzinfo=tz, fold=0), parsed.replace(tzinfo=tz, fold=1)
        if (
            first.utcoffset() != second.utcoffset()
            or first.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != parsed
        ):
            raise ValueError("ambiguous or nonexistent local time; supply an explicit UTC offset")
        parsed = first
    return parsed.astimezone(timezone.utc)


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite numeric value")
    return result


def matches(values, rule):
    if rule.column not in values:
        raise ValueError(f"unknown filter column: {rule.column}")
    actual = values[rule.column]
    if rule.op == "missing":
        return empty(actual)
    if rule.op == "present":
        return not empty(actual)
    if empty(actual):
        return False  # Missing is not automatically 'not equal' or 'not in'.
    if rule.op in {"gt", "gte", "lt", "lte"}:
        a, b = number(actual), number(rule.value)
        return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[rule.op]
    if rule.op in {"in", "not_in"}:
        if not isinstance(rule.value, list):
            raise ValueError("in/not_in requires an explicit list")
        found = str(actual) in rule.value
        return found if rule.op == "in" else not found
    if isinstance(rule.value, (int, float)):
        equal = number(actual) == rule.value
    else:
        equal = str(actual) == rule.value
    return equal if rule.op == "eq" else not equal


class Evaluation:
    def __init__(self, tables, specification: Specification, namespace="preparation"):
        self.tables = tables
        self.spec = specification
        self.namespace = namespace
        self.issues = []
        self.exceptions = []
        self.flow = []
        self.relationships = []
        self.trace = {}
        self.rows = []
        self.columns = []

    def issue(
        self, code, message, *, severity="blocker", source_id=None, records=None, unit_id=None
    ):
        record = {"code": code, "message": message, "severity": severity}
        if source_id:
            record["source_id"] = source_id
        if unit_id:
            record["unit_id"] = unit_id
        if records:
            record["records"] = records
        self.issues.append(record)

    def exception(self, table, row, reason, action, relation=None):
        self.exceptions.append(
            {"source": table.ref(row), "reason": reason, "action": action, "relation": relation}
        )

    def population(self, values):
        u = self.spec.unit
        units = {key(v, u.keys, u.key_normalization) for v in values}
        people = {key(v, u.subject_keys, u.key_normalization) for v in values}
        units.discard(None)
        people.discard(None)
        return {
            "rows": len(values),
            "units": len(units),
            "subjects": len(people),
            "unit_kind": u.kind,
            "encounters": len(units) if u.kind == "encounter" else None,
            "events": len(units) if u.kind == "event" else None,
        }

    def step(self, name, before, after, reason):
        self.flow.append(
            {
                "step": name,
                "reason": reason,
                "before": self.population(before),
                "after": self.population(after),
                "excluded_rows": len(before) - len(after),
            }
        )

    def valid_rows(
        self, table, columns, policy, null_policy="block", normalization="exact", relation=None
    ):
        table.require_columns(columns)
        excluded = {
            (e.record_index, e.row_sha256): e
            for e in self.spec.excluded_rows
            if e.source_id == table.source.id
        }
        seen_exclusions = set()
        groups = defaultdict(list)
        rejected = []
        for row in table.rows:
            token = (row.index, row.sha256)
            if token in excluded:
                seen_exclusions.add(token)
                rejected.append(row)
                self.exception(table, row, excluded[token].reason, "explicit_exclusion", relation)
                continue
            k = key(row.values, columns, normalization) if columns else (row.index,)
            if k is None:
                rejected.append(row)
                self.exception(table, row, "null_key", null_policy, relation)
                if null_policy == "block":
                    self.issue(
                        "NULL_KEY",
                        "Null keys never match one another.",
                        source_id=table.source.id,
                        records=[table.ref(row)],
                    )
                continue
            groups[k].append(row)
        if seen_exclusions != excluded.keys():
            raise ValueError("explicit row exclusion no longer matches its exact source row")
        result = []
        for group in groups.values():
            if len(group) == 1:
                result.extend(group)
            elif policy == "drop_identical" and len({r.sha256 for r in group}) == 1:
                result.append(group[0])
                for row in group[1:]:
                    self.exception(table, row, "identical_duplicate", "deduplicated", relation)
            else:
                rejected.extend(group)
                for row in group:
                    self.exception(
                        table,
                        row,
                        "duplicate_key",
                        "excluded_conflict" if policy == "exclude_conflicts" else "blocked",
                        relation,
                    )
                if policy != "exclude_conflicts":
                    self.issue(
                        "DUPLICATE_KEY",
                        "A declared key has conflicting/multiple records; resolve or explicitly exclude it.",
                        source_id=table.source.id,
                        records=[table.ref(r) for r in group],
                    )
        return result, rejected

    def coverage(self, relation, root):
        declaration = relation.coverage
        if declaration.mode != "by_column":
            return declaration.mode
        value = root[declaration.column]
        if value in declaration.exported_values:
            return "complete"
        if value in declaration.not_exported_values:
            return "not_exported"
        return "unknown"

    def select_window(self, relation, rows, values):
        if not relation.window:
            return rows, {"outside_window": [], "not_available": []}, {}
        window = relation.window
        index = timestamp(values[self.spec.unit.index_column], self.spec.unit.timezone)
        followup_end = (
            timestamp(values[window.followup_end_column], self.spec.unit.timezone)
            if window.followup_end_column
            else None
        )
        if followup_end is not None and followup_end < index:
            raise ValueError("follow-up end precedes the index time")
        selected, outside, unavailable, times = [], [], [], {}
        for row in rows:
            event = timestamp(row.values[window.event_column], self.spec.unit.timezone)
            available = (
                timestamp(row.values[window.available_column], self.spec.unit.timezone)
                if window.available_column
                else event
            )
            delta = (event - index).total_seconds() / 86400
            lower = (
                delta >= window.start_days
                if window.bounds in {"both", "left"}
                else delta > window.start_days
            )
            upper = (
                delta <= window.end_days
                if window.bounds in {"both", "right"}
                else delta < window.end_days
            )
            if not lower or not upper or (followup_end is not None and event > followup_end):
                outside.append(row)
            elif window.purpose == "baseline" and available > index:
                unavailable.append(row)
            else:
                selected.append(row)
                times[row.index] = event
        return selected, {"outside_window": outside, "not_available": unavailable}, times

    def feature(self, feature, rows, times, index, coverage, status):
        if not rows:
            known_absence = coverage == "complete" and status in {
                "no_record",
                "outside_window",
                "filtered_out",
            }
            return (0 if feature.aggregate in {"count", "exists"} and known_absence else None), []
        if feature.aggregate == "count":
            return len(rows), rows
        if feature.aggregate == "exists":
            return 1, rows
        if feature.aggregate == "days_to_first":
            first = min(times[r.index] for r in rows)
            return (first - index).total_seconds() / 86400, [
                r for r in rows if times[r.index] == first
            ]
        values = []
        for row in rows:
            value = row.values[feature.column]
            if empty(value) or value in feature.missing_tokens:
                continue
            if feature.value_type == "number":
                value = number(value)
            elif feature.value_type == "datetime":
                value = timestamp(value, self.spec.unit.timezone).isoformat()
            if feature.unit_column:
                unit = row.values[feature.unit_column]
                conversion = feature.unit_conversions.get(unit)
                if conversion is None or feature.value_type != "number":
                    raise ValueError("unmapped unit or nonnumeric unit conversion")
                value = number(value * conversion.scale + conversion.offset)
            values.append((value, row))
        if not values:
            return None, rows
        if feature.aggregate in {"first", "last"}:
            target = (min if feature.aggregate == "first" else max)(
                times[row.index] for _, row in values
            )
            selected = [(v, r) for v, r in values if times[r.index] == target]
            if len({canonical(v) for v, _ in selected}) != 1:
                raise ValueError(
                    "conflicting values at the same event time; no row-order tie breaking"
                )
            return selected[0][0], [r for _, r in selected]
        if feature.aggregate == "unique":
            if len({canonical(v) for v, _ in values}) != 1:
                raise ValueError("lookup/unique has conflicting values")
            value = values[0][0]
        elif feature.aggregate in {"sum", "mean"}:
            value = math.fsum(sorted(v for v, _ in values))
            if feature.aggregate == "mean":
                value /= len(values)
        else:
            value = (min if feature.aggregate == "min" else max)(v for v, _ in values)
        return value, [r for _, r in values]

    def apply_cohort(self, units, stage):
        for rule in [r for r in self.spec.cohort if r.stage == stage]:
            before = [u["values"] for u in units]
            kept = []
            for unit in units:
                try:
                    include = matches(unit["values"], rule.keep)
                except (ValueError, TypeError) as exc:
                    self.issue("INVALID_COHORT_VALUE", str(exc), unit_id=unit["id"])
                    include = False
                if include:
                    kept.append(unit)
                else:
                    self.trace[unit["id"]]["exclusions"].append(
                        {"step": rule.id, "reason": rule.reason}
                    )
            units = kept
            self.step(rule.id, before, [u["values"] for u in units], rule.reason)
        return units

    def evaluate(self):
        spec, unit = self.spec, self.spec.unit
        root = self.tables[unit.source_id]
        used = {unit.source_id, *(r.source_id for r in spec.relations)}
        if (
            used | spec.omitted_sources.keys() != self.tables.keys()
            or used & spec.omitted_sources.keys()
            or any(not reason.strip() for reason in spec.omitted_sources.values())
        ):
            raise ValueError("every source must be used or explicitly omitted with a reason")
        if any(e.source_id not in used for e in spec.excluded_rows):
            raise ValueError("row exclusions must address a used source")
        root.require_columns(
            unit.keys + unit.subject_keys + ([unit.index_column] if unit.index_column else [])
        )
        ZoneInfo(unit.timezone)
        retained = unit.retain_columns if unit.retain_columns is not None else root.columns
        root.require_columns(retained)
        root.require_columns(list(unit.columns))
        feature_names = [f.output for r in spec.relations for f in r.features]
        if set(feature_names) & set(root.columns):
            raise ValueError("derived outputs cannot overwrite source columns")
        self.columns = [
            "_rde_unit_id",
            "_rde_subject_id",
            *retained,
            *[
                name
                for r in spec.relations
                for name in [f"_rde_{r.id}_status", *(f.output for f in r.features)]
            ],
        ]
        for name, answer in spec.definitions.model_dump().items():
            if not answer.strip():
                self.issue(
                    "DEFINITION_" + name.upper(),
                    f"Confirm the research definition of {name}; data alone cannot answer this.",
                )
        root_rows, _ = self.valid_rows(
            root, unit.keys, unit.duplicates, unit.null_keys, unit.key_normalization
        )
        subjects = Counter(
            key(row.values, unit.subject_keys, unit.key_normalization) for row in root_rows
        )
        if None in subjects:
            self.issue("NULL_SUBJECT", "Every retained unit needs an explicit subject identity.")
        if unit.kind == "patient" and any(
            count > 1 for subject, count in subjects.items() if subject is not None
        ):
            self.issue(
                "REPEATED_PATIENT",
                "Patient-level analysis cannot contain multiple units for the same subject.",
            )
        for column in set(unit.keys + unit.subject_keys):
            if root.numeric_cells.get(column):
                self.issue(
                    "NUMERIC_IDENTIFIER_" + root.source.id,
                    "Excel stores identifier cells as numbers; verify leading zeros/precision at the source.",
                    severity="warning",
                    source_id=root.source.id,
                )
        units = []
        for row in root_rows:
            uid = "u_" + digest(
                [self.namespace, unit.kind, key(row.values, unit.keys, unit.key_normalization)]
            )
            sid = "s_" + digest(
                [self.namespace, key(row.values, unit.subject_keys, unit.key_normalization)]
            )
            values = {**row.values, "_rde_unit_id": uid, "_rde_subject_id": sid}
            self.trace[uid] = {
                "unit_id": uid,
                "subject_id": sid,
                "root": root.ref(row),
                "values": values,
                "cells": {
                    **{c: {"rule": "source_copy", "sources": [root.ref(row, c)]} for c in retained},
                    "_rde_unit_id": {
                        "rule": "sha256_project_unit_keys",
                        "sources": [root.ref(row, c) for c in unit.keys],
                    },
                    "_rde_subject_id": {
                        "rule": "sha256_project_subject_keys",
                        "sources": [root.ref(row, c) for c in unit.subject_keys],
                    },
                },
                "relations": {},
                "exclusions": [],
                "included": False,
            }
            units.append({"id": uid, "row": row, "values": values})
        units.sort(key=lambda u: canonical(key(u["values"], unit.keys, unit.key_normalization)))
        self.step(
            "source_keys",
            [r.values for r in root.rows],
            [u["values"] for u in units],
            "Declared unit keys, duplicate policy and explicit source-row exclusions",
        )
        units = self.apply_cohort(units, "before_links")
        for relation in spec.relations:
            units = self.apply_relation(units, root, relation)
        units = self.apply_cohort(units, "after_links")
        for u in units:
            self.trace[u["id"]]["included"] = True
        # Apply declared output types only after lexical identity, windows and
        # eligibility have been evaluated. Raw keys never undergo numeric coercion.
        for record in self.trace.values():
            for column in retained:
                rule = unit.columns.get(column, ColumnRule())
                raw = record["values"][column]
                try:
                    value = (
                        None
                        if raw in rule.missing_tokens
                        else number(raw)
                        if rule.value_type == "number"
                        else raw
                    )
                except (ValueError, TypeError, OverflowError):
                    self.issue(
                        "INVALID_OUTPUT_TYPE",
                        "Value does not match the declared output type",
                        unit_id=record["unit_id"],
                        column=column,
                    )
                    value = None
                record["values"][column] = value
                record["cells"][column]["rule"] = {"source_copy": True, **rule.model_dump()}
        self.rows = [{column: u["values"].get(column) for column in self.columns} for u in units]
        if not units:
            self.issue(
                "EMPTY_COHORT",
                "No eligible analysis units remain; do not publish an empty analysis dataset.",
            )
        return self

    def apply_relation(self, units, root, relation):
        table = self.tables[relation.source_id]
        root.require_columns(
            relation.left_keys + ([relation.coverage.column] if relation.coverage.column else [])
        )
        table.require_columns(
            relation.right_keys
            + relation.record_keys
            + [f.column for f in relation.features if f.column]
            + [f.unit_column for f in relation.features if f.unit_column]
            + [f.column for f in relation.filters]
        )
        if relation.window:
            if not self.spec.unit.index_column:
                raise ValueError("event windows require a declared root index timestamp")
            table.require_columns(
                [relation.window.event_column]
                + ([relation.window.available_column] if relation.window.available_column else [])
            )
            root.require_columns(
                [relation.window.followup_end_column] if relation.window.followup_end_column else []
            )
        identity = relation.right_keys if relation.kind == "lookup" else relation.record_keys
        source_rows, rejected = self.valid_rows(
            table,
            identity,
            relation.duplicates,
            normalization=relation.key_normalization,
            relation=relation.id,
        )
        if relation.kind == "events" and not relation.record_keys:
            self.issue(
                "NO_EVENT_KEY_" + relation.id,
                "No natural event key was declared. Confirm that physical export rows are distinct events; duplicate exports cannot be inferred.",
                severity="warning",
                source_id=table.source.id,
            )
        for column in set(relation.right_keys + relation.record_keys):
            if table.numeric_cells.get(column):
                self.issue(
                    "NUMERIC_IDENTIFIER_" + relation.id,
                    "Verify the meaning and original precision of numeric Excel identifiers.",
                    severity="warning",
                    source_id=table.source.id,
                )
        index, invalid_links = defaultdict(list), []
        for row in source_rows:
            k = key(row.values, relation.right_keys, relation.key_normalization)
            if k is None:
                invalid_links.append(row)
                self.exception(table, row, "null_foreign_key", "unlinked", relation.id)
            else:
                index[k].append(row)
        rejected_keys = {
            key(r.values, relation.right_keys, relation.key_normalization) for r in rejected
        }
        invalid_count = len(invalid_links) + sum(
            key(r.values, relation.right_keys, relation.key_normalization) is None for r in rejected
        )
        if invalid_count:
            self.issue(
                "UNLINKABLE_ROWS_" + relation.id,
                "Some records lack a link key; an absent match cannot establish that no record exists.",
                severity="warning",
                source_id=table.source.id,
            )
        left_keys = {
            key(u["values"], relation.left_keys, relation.key_normalization) for u in units
        }
        left_keys.discard(None)
        orphans = [r for k, rows in index.items() if k not in left_keys for r in rows]
        for row in orphans:
            self.exception(table, row, "no_eligible_root_key", "unlinked", relation.id)
        before = [u["values"].copy() for u in units]
        counts = Counter()
        consumed = Counter()
        direct_rows = 0
        for u in units:
            uid, values = u["id"], u["values"]
            k = key(values, relation.left_keys, relation.key_normalization)
            all_matches = index.get(k, []) if k is not None else []
            direct_rows += len(all_matches)
            coverage = self.coverage(relation, values)
            selected, excluded, times = [], {"outside_window": [], "not_available": []}, {}
            try:
                filtered = [
                    r
                    for r in all_matches
                    if all(matches(r.values, predicate) for predicate in relation.filters)
                ]
                selected, excluded, times = self.select_window(relation, filtered, values)
                if coverage == "not_exported" and all_matches:
                    raise ValueError("export coverage says not exported but matching records exist")
                if k is None:
                    status = "link_failed"
                elif selected:
                    status = "matched_partial" if k in rejected_keys else "matched"
                elif k in rejected_keys:
                    status = "link_failed"
                elif coverage == "not_exported":
                    status = "not_exported"
                elif excluded["not_available"]:
                    status = "not_available"
                elif excluded["outside_window"]:
                    status = "outside_window"
                elif all_matches:
                    status = "filtered_out"
                elif invalid_count:
                    status = "link_failed"
                else:
                    status = "no_record" if coverage == "complete" else "unknown_coverage"
                for feature in relation.features:
                    instant = (
                        timestamp(values[self.spec.unit.index_column], self.spec.unit.timezone)
                        if relation.window
                        else None
                    )
                    value, members = self.feature(
                        feature, selected, times, instant, coverage, status
                    )
                    values[feature.output] = value
                    self.trace[uid]["cells"][feature.output] = {
                        "rule": feature.model_dump(),
                        "relation": relation.id,
                        "status": status,
                        "sources": [table.ref(r, feature.column) for r in members],
                    }
                consumed.update(r.index for r in selected)
            except (ValueError, TypeError, OverflowError) as exc:
                self.issue("RELATION_VALUE_ERROR", str(exc), source_id=table.source.id, unit_id=uid)
                status = "link_failed"
                for feature in relation.features:
                    values[feature.output] = None
            values[f"_rde_{relation.id}_status"] = status
            self.trace[uid]["cells"][f"_rde_{relation.id}_status"] = {
                "rule": "linkage_and_coverage_status",
                "relation": relation.id,
                "sources": [root.ref(u["row"]), *[table.ref(r) for r in all_matches]],
            }
            counts[status] += 1
            self.trace[uid]["relations"][relation.id] = {
                "status": status,
                "coverage": coverage,
                "matched_records": [table.ref(r) for r in all_matches],
                "selected_records": [table.ref(r) for r in selected],
                "excluded": {
                    reason: [table.ref(r) for r in rows] for reason, rows in excluded.items()
                },
            }
        reused = [i for i, count in consumed.items() if count > 1]
        if relation.kind == "events" and reused and relation.reuse_events != "allow":
            self.issue(
                "REUSED_EVENTS_" + relation.id,
                "Events contribute to more than one unit. Confirm overlapping windows/bridge semantics or revise the keys/windows.",
                source_id=table.source.id,
                records=[table.ref(r) for r in source_rows if r.index in reused],
            )
        kept = []
        for u in units:
            if u["values"][f"_rde_{relation.id}_status"] in relation.exclude_statuses:
                self.trace[u["id"]]["exclusions"].append(
                    {
                        "step": relation.id,
                        "reason": relation.reason,
                        "status": u["values"][f"_rde_{relation.id}_status"],
                    }
                )
            else:
                kept.append(u)
        self.step("relation:" + relation.id, before, [u["values"] for u in kept], relation.reason)
        self.relationships.append(
            {
                "id": relation.id,
                "source_id": table.source.id,
                "source_rows": len(table.rows),
                "eligible_source_rows": len(source_rows),
                "null_link_rows": invalid_count,
                "unmatched_source_rows": len(orphans),
                "rejected_source_rows": len(rejected),
                "analysis_units_before": len(units),
                "analysis_units_after": len(kept),
                "matched_pairs_before_aggregation": direct_rows,
                "selected_distinct_source_records": len(consumed),
                "reused_source_records": len(reused),
                "statuses": dict(counts),
                "aggregation_prevents_row_expansion": True,
            }
        )
        return kept

    def summary(self):
        population = [record["values"] for record in self.trace.values() if record["included"]]
        return {
            "schema": "rde-preparation-validation-v1",
            "ready_for_approval": not any(i["severity"] == "blocker" for i in self.issues),
            "flow": self.flow,
            "relationships": self.relationships,
            "population": self.population(population),
            "output_columns": self.columns,
            "blockers": sum(i["severity"] == "blocker" for i in self.issues),
            "warnings": sorted({i["code"] for i in self.issues if i["severity"] == "warning"}),
            "exception_count": len(self.exceptions),
            "trace_units": len(self.trace),
            "model_denominator_note": "These are preparation denominators; model-specific exclusions must still be reported separately.",
        }
