"""Evidence gates for an explicitly scoped wide repeated-measures study."""

from __future__ import annotations

import hashlib
import json
import math
from itertools import combinations
from pathlib import Path

from rde.application.pipeline import PipelinePhase


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def repeated_spec(analyses: list) -> dict | None:
    scoped = [entry for entry in analyses if entry.get("scope") == "repeated-wide-v1"]
    if not scoped:
        return None
    if (
        len(analyses) != 2
        or len(scoped) != 2
        or [e.get("type") for e in scoped] != ["run_repeated_measures", "visualization"]
    ):
        raise ValueError(
            "Scoped repeated plans require one repeated test followed by its complete-case figure."
        )
    test, plot = [entry.get("execution_arguments", {}) for entry in scoped]
    variables = test.get("variables", "").split(",")
    subject = test.get("subject_variable")
    labels = plot.get("labels", [])
    if (
        not 2 <= len(variables) <= 8
        or len(set(variables)) != len(variables)
        or any(not v or v != v.strip() for v in variables)
    ):
        raise ValueError("Repeated plans require 2–8 unique ordered measurement columns.")
    if not isinstance(subject, str) or not subject.strip() or subject in variables:
        raise ValueError("Repeated plans require a separate subject identifier.")
    if not 0 < test.get("alpha", 0) < 1 or test.get("posthoc_case_strategy") not in {
        "complete",
        "pairwise",
    }:
        raise ValueError("Invalid repeated inference policy.")
    if len(variables) == 2 and test["posthoc_case_strategy"] != "complete":
        raise ValueError("A single paired comparison has no separate post-hoc case strategy.")
    if any(entry.get("variables") != variables for entry in scoped):
        raise ValueError("Plan variables must exactly preserve the measurement order.")
    if (
        plot.get("variables") != variables
        or plot.get("subject_variable") != subject
        or plot.get("plot_type") != ("paired" if len(variables) == 2 else "line")
        or plot.get("include_tests") is not False
        or plot.get("missing_strategy") != "listwise"
    ):
        raise ValueError(
            "Repeated figure must use the same subjects/measurements, complete cases and no extra tests."
        )
    if (
        len(labels) != len(variables)
        or len(set(labels)) != len(labels)
        or any(
            not isinstance(label, str) or not label.strip() or len(label) > 120 for label in labels
        )
        or not plot.get("ylabel")
    ):
        raise ValueError(
            "Repeated figure requires ordered unique labels and a measurement/unit axis."
        )
    filename = plot.get("output_filename", "")
    if not filename.endswith(".png") or Path(filename).name != filename or "\\" in filename:
        raise ValueError("Repeated figure requires a safe PNG filename.")
    return {"test": test, "plot": plot, "variables": variables}


def repeated_plan(store) -> dict | None:
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
    spec = repeated_spec(plan.get("analyses", []))
    if spec and (
        plan.get("alpha") != spec["test"]["alpha"]
        or plan.get("missing_strategy") != "listwise"
        or plan.get("multiple_comparison_method") != "bonferroni"
    ):
        raise ValueError("Locked repeated policy differs from the scoped specification.")
    return spec


def repeated_record(store) -> dict | None:
    records = []
    for filename in store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION):
        if filename.startswith("repeated_measures_") and filename.endswith(".json"):
            record = store.load(PipelinePhase.EXECUTE_EXPLORATION, filename)
            if isinstance(record, dict) and record.get("receipt_sha256"):
                records.append({**record, "artifact": filename})
    return max(records, key=lambda r: r.get("created_at_ns", 0)) if records else None


def repeated_readiness(store, *, data_quality: dict, require_report_generation=True) -> dict:
    spec = repeated_plan(store)
    record = repeated_record(store) or {}
    result = record.get("result", {})
    ledger = result.get("case_ledger", {})
    checks = []

    def check(key, passed, evidence):
        checks.append({"id": key, "passed": bool(passed), "evidence": evidence})

    check(
        "receipt_integrity",
        bool(record)
        and digest({k: v for k, v in record.items() if k not in {"receipt_sha256", "artifact"}})
        == record.get("receipt_sha256"),
        [record.get("artifact", "missing repeated receipt")],
    )
    check(
        "locked_specification",
        all(record.get(k) == v for k, v in spec["test"].items() if k != "variables")
        and record.get("variables") == spec["variables"],
        ["analysis_plan.yaml"],
    )
    review = store.load(PipelinePhase.PLAN_COMPLETENESS_REVIEW, "analysis_plan_review.json") or {}
    check(
        "confirmed_repeated_scope",
        review.get("confirmed")
        and review.get("scope") == "repeated_specification_review"
        and review.get("status") == "pass",
        ["analysis_plan_review.json"],
    )
    n = ledger.get("input_rows", 0)
    masks = ledger.get("observed_bitmask_by_data_row", [])
    variables = spec["variables"]
    full_mask = (1 << len(variables)) - 1
    complete = [i + 1 for i, mask in enumerate(masks) if mask == full_mask]
    excluded = [i + 1 for i, mask in enumerate(masks) if mask != full_mask]
    check(
        "subject_and_case_coverage",
        n >= 10
        and len(masks) == n
        and len(complete) >= 5
        and all(isinstance(m, int) and 0 <= m <= full_mask for m in masks)
        and ledger.get("subject_variable") == spec["test"]["subject_variable"]
        and bool(ledger.get("subject_order_sha256"))
        and ledger.get("complete_data_rows") == complete
        and ledger.get("excluded_data_rows") == excluded
        and result.get("n_complete", result.get("n_pairs")) == len(complete),
        ["case_ledger"],
    )
    check(
        "finite_estimate",
        all(
            isinstance(result.get(k), (int, float)) and math.isfinite(result[k])
            for k in ["p_value", "statistic", "effect_size"]
        )
        and 0 <= result.get("p_value", -1) <= 1,
        ["result"],
    )
    pairs = result.get("posthoc", [])
    need_pairs = len(variables) > 2 and result.get("p_value", 1) < spec["test"]["alpha"]
    expected_pairs = list(combinations(range(len(variables)), 2)) if need_pairs else []
    valid_pairs = len(pairs) == len(expected_pairs)
    for pair, (i, j) in zip(pairs, expected_pairs, strict=False):
        pair_n = (
            sum((mask & ((1 << i) | (1 << j))) == ((1 << i) | (1 << j)) for mask in masks)
            if spec["test"]["posthoc_case_strategy"] == "pairwise"
            else len(complete)
        )
        valid_pairs = (
            valid_pairs
            and pair.get("var_1") == variables[i]
            and pair.get("var_2") == variables[j]
            and pair.get("n_pairs") == pair_n
            and pair.get("case_strategy") == spec["test"]["posthoc_case_strategy"]
            and 0 <= pair.get("p_value", -1) <= 1
            and pair.get("p_adjusted") == min(1, pair.get("p_value", -1) * len(expected_pairs))
        )
    check(
        "posthoc_family_and_denominators",
        valid_pairs,
        ["result.posthoc", "case_ledger.observed_bitmask_by_data_row"],
    )
    root = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "unused").parents[2]
    figure = root / "figures" / spec["plot"]["output_filename"]
    manifest = store.load(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json") or []
    matching = [
        entry
        for entry in manifest
        if entry.get("output_path") == f"figures/{spec['plot']['output_filename']}"
    ]
    check(
        "complete_case_figure_integrity",
        len(matching) == 1
        and figure.is_file()
        and matching[0].get("sha256") == hashlib.sha256(figure.read_bytes()).hexdigest()
        and matching[0].get("execution_arguments")
        == {k: v for k, v in spec["plot"].items() if k != "output_filename"}
        and f"n={len(complete)}" in matching[0].get("stats_summary", ""),
        ["visualization_manifest.json", figure.name],
    )
    check(
        "data_quality_review",
        not data_quality.get("missing_requirements"),
        ["quality_report.json", "readiness_checklist.json"],
    )
    if require_report_generation:
        report = str(store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md") or "")
        check(
            "report_contains_cases_and_limits",
            all(
                s in report
                for s in [
                    "Case-set ledger",
                    "時間差異不等於組間治療效果",
                    record.get("receipt_sha256") or "missing receipt",
                ]
            ),
            ["eda_report.md"],
        )
    missing = [c["id"] for c in checks if not c["passed"]]
    return {
        "ready": not missing,
        "scope": "repeated_report_evidence",
        "target_tier": "repeated_measurement",
        "current_tier": "repeated_measurement"
        if not missing
        else "incomplete_repeated_measurement",
        "review_status": "pass" if not missing else "incomplete",
        "publication_bundle_met": not missing,
        "data_quality": data_quality,
        "analysis_depth": {"ready": not missing, "checks": checks, "missing_requirements": missing},
        "semantic_report_quality": {
            "ready": "report_contains_cases_and_limits" not in missing,
            "missing_requirements": [m for m in missing if m.startswith("report_")],
        },
        "core_goal_audit": {
            "scope": "repeated_report_evidence",
            "ready": not missing,
            "checks": checks,
            "missing_goals": missing,
        },
        "missing_requirements": missing,
        "applicability": "Evidence completeness for the specified within-subject comparison, not proof of assumptions, treatment efficacy or clinical importance.",
    }


def repeated_deliverables(project, store) -> dict:
    ready = repeated_readiness(store, data_quality={}, require_report_generation=False)
    spec = repeated_plan(store)
    return {
        "scope": "repeated_measurement",
        "minimum_publication_bundle_met": ready["ready"],
        "total_figures": int(
            (project.output_dir / "figures" / spec["plot"]["output_filename"]).is_file()
        ),
        "analytical_figures": int(
            (project.output_dir / "figures" / spec["plot"]["output_filename"]).is_file()
        ),
        "descriptive_figures": 0,
        "required_analytical_figures": 1,
        "required_descriptive_figures": 0,
        "table_one_required": False,
        "figure_files": [spec["plot"]["output_filename"]],
        "missing_components": ready["missing_requirements"],
    }
