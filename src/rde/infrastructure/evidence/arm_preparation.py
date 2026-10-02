"""Review explicit binary arm decisions, then derive complete study contrasts.

No study selection, denominator substitution, imputation, rounding or dose
classification is inferred here. A preparation is not a meta-analysis.
"""

import math
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from itertools import combinations

from rde.domain.models.evidence_arms import BinaryArmSpec

COLUMNS = [
    "study_id",
    "report_id",
    "treatment",
    "comparator",
    "effect",
    "se",
    "outcome",
    "timepoint",
    "decision",
    "reason",
    "source",
    "locator",
    "risk_of_bias",
    "bias_reason",
    "design",
    "population",
    "effect_modifiers",
    "effect_measure",
]
METHOD = {
    "schema": "binary-arm-method-v1",
    "scope": "Independent parallel randomized binary arms; no meta-analysis or clinical eligibility inference.",
    "OR": "log(eA / fA) - log(eB / fB); variance = 1/eA + 1/fA + 1/eB + 1/fB",
    "RR": "log(eA / nA) - log(eB / nB); variance = fA/(eA*nA) + fB/(eB*nB)",
    "correction": "If explicitly selected: add 0.5 to events AND non-events of EVERY retained merged arm of an affected study, once before all pairs; n increases by 1.",
    "merge": "If explicitly selected: sum disjoint raw arms of the same treatment before correction; preserve every raw row.",
    "multiarm": "All unordered treatment pairs, with consistent study-level arm contributions; downstream engine must account for shared-arm covariance.",
    "direction": "Treatment minus comparator on the natural log scale. Clinical benefit direction is not inferred.",
    "study_records": "Exact raw study text maps one-to-one to an explicit short ID. Never trims, merges or truncates source identities automatically. Each background replacement retains the original value, reason and reviewer-provided citation. Endpoint time, trial duration, dose context and original bias domains are review context, not automatic selection or model covariates.",
    "limits": "5000 source rows; 500 included studies; 40 treatments; 2000 comparisons; counts <= 2^53-1, at most 24 significant digits and 20 decimal places.",
    "limitations": [
        "Wald inverse-variance contrasts, including corrected sparse cells, differ from a binomial likelihood model.",
        "Author-imputed fractional events are estimates, not observed integer responders; their extra uncertainty is not modeled.",
        "Multiple source reports must be reconciled upstream; source identity and arithmetic do not prove study independence.",
        "Approval records the reviewer's assertions; dose eligibility, denominators, follow-up, bias and original source truth require substantive review.",
        "External study citations and optional SHA256 values are reviewer-provided assertions; this preparation tool does not retrieve or verify those external documents.",
    ],
}


def _label(value):
    return (
        bool(value.strip())
        and value == value.strip()
        and len(value) <= 80
        and not re.search(r"[\x00-\x1f\x7f]", value)
    )


def _number(value, *, total=False):
    # Deliberately no commas, implicit percentages, Unicode digits or missing->0.
    if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
        raise ValueError("Expected an explicit decimal count.")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("Invalid decimal count.") from error
    if not number.is_finite() or number < 0 or number > 2**53 - 1:
        raise ValueError("Count must be finite, nonnegative and <= 2^53-1.")
    if len(number.as_tuple().digits) > 24 or number.as_tuple().exponent < -20:
        raise ValueError("Count exceeds supported decimal precision; do not silently round.")
    if total and (number <= 0 or number != number.to_integral_value()):
        raise ValueError("Denominator must be a positive integer.")
    return number


def _review(grid, spec):
    errors, arms, studies = [], [], []

    def issue(code, message, **location):
        errors.append({"code": code, "message": message, **location})

    columns = spec.columns.model_dump()
    metadata = spec.metadata.model_dump()
    used = {v for v in columns.values() if v is not None}
    used.update(v["column"] for v in metadata.values() if v["kind"] == "column")
    if max(used) > grid["column_count"]:
        issue("column_outside_source", "A mapped column is absent from the source.")
    for cell in grid["formula_cells"]:
        if spec.first_data_row <= cell["row"] <= spec.last_data_row and cell["column"] in used:
            issue(
                "formula_cell",
                "Mapped source formulas require a separately verified values source.",
                **cell,
            )
    for merge in grid["merged_ranges"]:
        if (
            merge["first_row"] <= spec.last_data_row
            and merge["last_row"] >= spec.first_data_row
            and any(merge["first_column"] <= c <= merge["last_column"] for c in used)
        ):
            issue(
                "merged_cell",
                "Mapped body cells may not use implicit merged-cell filling.",
                **merge,
            )
    missing = {m.value: m.meaning for m in spec.missing_codes}
    vocabulary = {t.raw: t for t in spec.treatments}
    overrides = {r.row: r for r in spec.row_decisions}
    records = {r.source_study: r for r in spec.study_records}
    raw_studies = list(
        dict.fromkeys(
            values[spec.columns.study - 1] if spec.columns.study <= len(values) else ""
            for values in grid["rows"][spec.first_data_row - 1 : spec.last_data_row]
        )
    )
    for raw_id in records:
        if raw_id not in raw_studies:
            issue(
                "unknown_study_record",
                "A study review refers to no exact raw study in the selected range.",
                source_study_id=raw_id,
            )
        if raw_id in missing:
            issue(
                "missing_study_record",
                "A missing-value code cannot identify a study review.",
                source_study_id=raw_id,
            )
    resolved = defaultdict(list)
    for raw_id in raw_studies:
        resolved[records[raw_id].study_id if raw_id in records else raw_id].append(raw_id)
    for label, raw_ids in resolved.items():
        if len(raw_ids) > 1:
            issue(
                "study_identity_collision",
                "Reviewed IDs would merge distinct source studies; use separate IDs and reconcile reports explicitly.",
                study_id=label,
                source_study_ids=sorted(raw_ids),
            )
    identities, groups = set(), defaultdict(list)
    for row in range(spec.first_data_row, spec.last_data_row + 1):
        values = grid["rows"][row - 1]

        def cell(column, values=values):
            return values[column - 1] if column <= len(values) else ""

        raw = {name: cell(column) for name, column in columns.items() if column is not None}
        record = records.get(raw["study"])
        original_metadata = {
            name: value["value"] if value["kind"] == "constant" else cell(value["column"])
            for name, value in metadata.items()
        }
        effective_metadata = dict(original_metadata)
        effective_sources = dict(metadata)
        for field in record.fields if record else []:
            if field.field in metadata:
                effective_metadata[field.field] = field.value
                effective_sources[field.field] = {
                    "kind": "study_record",
                    "source_study": raw["study"],
                    **field.model_dump(),
                    "external_source_verification": "reviewer_provided_not_verified_by_executor",
                }
        treatment = vocabulary.get(raw["treatment"])
        override = overrides.get(row)
        choice = override or treatment
        decision = choice.decision if choice else "unresolved"
        arm = {
            "row": row,
            "raw": raw,
            "coordinates": {
                name: {"row": row, "column": col}
                for name, col in columns.items()
                if col is not None
            },
            "study_id": record.study_id if record else raw["study"],
            "study_record": record.model_dump() if record else None,
            "arm_id": raw["arm"],
            "treatment": treatment.treatment if treatment else None,
            "decision": decision,
            "reason": choice.reason if choice else "No explicit treatment or row decision.",
            "decision_source": "row" if override else "treatment" if treatment else "unresolved",
            "missing": {name: missing[value] for name, value in raw.items() if value in missing},
            "original_metadata": original_metadata,
            "metadata": effective_metadata,
            "metadata_sources": effective_sources,
        }
        arms.append(arm)
        if decision == "exclude":
            if raw["study"]:
                groups[raw["study"]].append(arm)
            continue
        before = len(errors)
        if decision == "unresolved":
            issue(
                "unresolved_eligibility",
                "Source arm eligibility remains unreviewed; no automatic inclusion or exclusion.",
                row=row,
            )
        if treatment is None:
            issue(
                "unknown_treatment",
                "Included rows require an exact treatment vocabulary mapping.",
                row=row,
            )
        for key in ("study", "arm"):
            value = arm["study_id"] if key == "study" else raw[key]
            if not _label(value) or raw[key] in missing or value in missing:
                issue(
                    "invalid_identity",
                    f"{key} must be an explicit, trimmed label (1-80 characters).",
                    row=row,
                )
        identity = (arm["study_id"], raw["arm"])
        if identity in identities:
            issue(
                "duplicate_arm",
                "The same study/arm identity occurs more than once; reconcile reports first.",
                row=row,
            )
        identities.add(identity)
        for name, value in arm["metadata"].items():
            if not value.strip() or value in missing or len(value) > 2000:
                issue("missing_metadata", f"Included arm needs explicit {name}.", row=row)
        if not _label(arm["metadata"]["report_id"]):
            issue(
                "invalid_report", "Report ID must be a trimmed label of 1-80 characters.", row=row
            )
        if arm["metadata"]["design"] != "parallel_rct":
            issue(
                "unsupported_design",
                "Only independent parallel randomized arms are supported.",
                row=row,
            )
        if arm["metadata"]["risk_of_bias"] not in {"low", "some_concerns", "high", "unclear"}:
            issue(
                "invalid_bias",
                "Bias category requires an explicit supported mapping and explanation.",
                row=row,
            )
        if not re.fullmatch(
            r"(?:https?://\S+|doi:10\.\d{4,9}/\S+|pmid:\d+|synthetic://\S+)",
            arm["metadata"]["source"],
            re.IGNORECASE,
        ):
            issue(
                "invalid_source",
                "Source must identify a DOI, PMID, HTTP URL, or explicit synthetic fixture.",
                row=row,
            )
        imputed = None
        if spec.imputation_codes:
            flag = raw["author_imputed"]
            if flag in spec.imputation_codes.imputed:
                imputed = True
            elif flag in spec.imputation_codes.reported:
                imputed = False
            else:
                issue(
                    "unknown_imputation", "Author-imputation flag has no explicit meaning.", row=row
                )
        arm["author_imputed"] = imputed
        try:
            events, total = _number(raw["events"]), _number(raw["total"], total=True)
            if events > total:
                raise ValueError("Events exceed the selected denominator.")
            if events != events.to_integral_value() and not (
                spec.fractional_events == "author_imputed" and imputed is True
            ):
                raise ValueError(
                    "Fractional events require both the explicit policy and an author-imputed flag."
                )
            arm["counts"] = {
                "events": str(events),
                "total": str(total),
                "non_events": str(total - events),
            }
        except ValueError as error:
            issue("invalid_counts", str(error), row=row)
        arm["valid"] = len(errors) == before
        groups[raw["study"]].append(arm)

    for source_study_id, source_arms in groups.items():
        study_id = source_arms[0]["study_id"]
        selected = [a for a in source_arms if a["decision"] == "include"]
        study = {
            "study_id": study_id,
            "source_study_id": source_study_id,
            "study_record": records[source_study_id].model_dump()
            if source_study_id in records
            else None,
            "source_rows": [a["row"] for a in source_arms],
            "excluded_rows": [a["row"] for a in source_arms if a["decision"] == "exclude"],
            "decision": "exclude",
            "reason": "All source arms explicitly excluded.",
            "arms": [],
        }
        studies.append(study)
        if any(a["decision"] == "unresolved" for a in source_arms):
            study.update(
                decision="unresolved", reason="At least one source arm has unresolved eligibility."
            )
            continue
        if not selected:
            continue
        if any(not a.get("valid") for a in selected):
            study.update(decision="unresolved", reason="Resolve invalid included source arms.")
            continue
        study["metadata"] = selected[0]["metadata"]
        if any(a["metadata"] != study["metadata"] for a in selected):
            issue(
                "inconsistent_metadata",
                "Included arms have conflicting study metadata; reconcile them explicitly.",
                study_id=study_id,
            )
        buckets = defaultdict(list)
        for arm in selected:
            buckets[arm["treatment"]].append(arm)
        for treatment, bucket in buckets.items():
            if len(bucket) > 1 and spec.merge_policy == "reject":
                issue(
                    "merge_not_approved",
                    "Repeated treatment arms need an explicit disjoint-arm merge policy.",
                    study_id=study_id,
                    treatment=treatment,
                )
            e = sum(Decimal(a["counts"]["events"]) for a in bucket)
            n = sum(Decimal(a["counts"]["total"]) for a in bucket)
            if n > 2**53 - 1:
                issue(
                    "merged_count_limit",
                    "Merged denominator exceeds the exact supported count range.",
                    study_id=study_id,
                )
            study["arms"].append(
                {
                    "treatment": treatment,
                    "source_rows": [a["row"] for a in bucket],
                    "source_arm_ids": [a["arm_id"] for a in bucket],
                    "author_imputed_rows": [
                        a["row"] for a in bucket if a["author_imputed"] is True
                    ],
                    "events": str(e),
                    "total": str(n),
                    "non_events": str(n - e),
                }
            )
        study["arms"].sort(key=lambda a: a["treatment"])
        if len(buckets) < 2:
            study["reason"] = "Fewer than two distinct retained treatments."
            if spec.insufficient_treatments == "reject":
                issue("insufficient_treatments", study["reason"], study_id=study_id)
            continue
        if all(Decimal(a["events"]) == 0 for a in study["arms"]) or all(
            Decimal(a["non_events"]) == 0 for a in study["arms"]
        ):
            study["reason"] = (
                "No between-arm outcome information: every retained participant has the same binary outcome."
            )
            if spec.uninformative_studies == "reject":
                issue("uninformative_study", study["reason"], study_id=study_id)
            continue
        affected = [
            a["treatment"]
            for a in study["arms"]
            if Decimal(a["events"]) == 0 or Decimal(a["non_events"]) == 0
        ]
        study["zero_cell_treatments"] = affected
        study["planned_correction"] = "add_half_all_arms_in_affected_study" if affected else "none"
        if affected and spec.zero_cells == "reject":
            issue(
                "zero_cells",
                "Retained study has zero events or non-events; correction is not authorized.",
                study_id=study_id,
            )
        study.update(
            decision="include",
            reason="Explicit source decisions and study policies retain at least two treatments.",
        )

    included = [s for s in studies if s["decision"] == "include"]
    treatments = sorted({a["treatment"] for s in included for a in s["arms"]})
    pairs = sum(len(s["arms"]) * (len(s["arms"]) - 1) // 2 for s in included)
    if len(included) < 2 or len(included) > 500 or len(treatments) > 40 or pairs > 2000:
        issue(
            "network_limits",
            "Need 2-500 independent included studies, <=40 treatments and <=2000 complete contrasts.",
        )
    if spec.reference not in treatments:
        issue(
            "reference_absent", "The selected reference is absent after arm and study exclusions."
        )
    reached = {spec.reference}
    while True:
        before = len(reached)
        for study in included:
            names = {a["treatment"] for a in study["arms"]}
            if reached & names:
                reached.update(names)
        if len(reached) == before:
            break
    if set(treatments) - reached:
        issue("disconnected_network", "Retained trials form disconnected treatment networks.")
    return {
        "schema": "binary-arm-review-v1",
        "ready_for_approval": not errors,
        "source_sha256": grid["source_sha256"],
        "errors": errors,
        "arms": arms,
        "studies": studies,
        "summary": {
            "source_rows": len(arms),
            "arm_decisions": dict(Counter(a["decision"] for a in arms)),
            "included_studies": len(included),
            "included_treatments": treatments,
            "planned_contrasts": pairs,
            "excluded_studies": sum(s["decision"] == "exclude" for s in studies),
        },
        "outside_data": {
            "before": [1, spec.first_data_row - 1] if spec.first_data_row > 1 else None,
            "after": [spec.last_data_row + 1, grid["row_count"]]
            if spec.last_data_row < grid["row_count"]
            else None,
            "reason": spec.outside_data_reason,
        },
    }


def review(grid, spec: BinaryArmSpec):
    with localcontext() as context:
        context.prec = 60  # Exact sums/differences for the bounded input counts.
        return _review(grid, spec)


def calculate(reviewed, spec: BinaryArmSpec):
    """Called only by the approved workflow; pure arithmetic supports independent QA."""
    if reviewed.get("ready_for_approval") is not True:
        raise ValueError("Unresolved source review cannot be calculated.")
    contrasts, derivations = [], []
    with localcontext() as context:
        context.prec = 60
        for study in reviewed["studies"]:
            if study["decision"] != "include":
                continue
            correction = Decimal("0.5") if study["zero_cell_treatments"] else Decimal(0)
            contributions = []
            for arm in study["arms"]:
                e, f = Decimal(arm["events"]) + correction, Decimal(arm["non_events"]) + correction
                n = e + f
                log_value = float(e.ln() - (f.ln() if spec.measure == "OR" else n.ln()))
                variance = float(1 / e + 1 / f if spec.measure == "OR" else f / (e * n))
                if not math.isfinite(log_value) or not math.isfinite(variance) or variance <= 0:
                    raise ValueError("Arm contribution is nonfinite or numerically degenerate.")
                contributions.append(
                    {
                        **arm,
                        "corrected_events": str(e),
                        "corrected_non_events": str(f),
                        "corrected_total": str(n),
                        "log_contribution": log_value,
                        "variance_contribution": variance,
                    }
                )
            derivation = {
                "study_id": study["study_id"],
                "source_study_id": study["source_study_id"],
                "study_record": study["study_record"],
                "correction_per_cell": str(correction),
                "arms": contributions,
            }
            derivations.append(derivation)
            for a, b in combinations(contributions, 2):
                effect = a["log_contribution"] - b["log_contribution"]
                se = math.sqrt(a["variance_contribution"] + b["variance_contribution"])
                if not math.isfinite(effect) or not math.isfinite(se) or se <= 0:
                    raise ValueError("Contrast is nonfinite or numerically degenerate.")
                contrasts.append(
                    {
                        "study_id": study["study_id"],
                        **study["metadata"],
                        "treatment": a["treatment"],
                        "comparator": b["treatment"],
                        "effect": effect,
                        "se": se,
                        "outcome": spec.outcome,
                        "timepoint": spec.timepoint,
                        "decision": "include",
                        "reason": study["reason"],
                        "locator": f"sha256:{reviewed['source_sha256']}; sheet={spec.sheet!r}; source rows={','.join(map(str, a['source_rows'] + b['source_rows']))}; one-based logical coordinates",
                        "effect_measure": "log_" + spec.measure,
                    }
                )
    return {
        "schema": "binary-arm-result-v1",
        "source_sha256": reviewed["source_sha256"],
        "measure": spec.measure,
        "reference": spec.reference,
        "outcome": spec.outcome,
        "timepoint": spec.timepoint,
        "columns": COLUMNS,
        "contrasts": contrasts,
        "derivations": derivations,
        "summary": reviewed["summary"],
        "limitations": METHOD["limitations"],
    }
