"""Finite evidence requirements for prespecified OLS and two-group screens.

This is a reporting contract, not an estimator, a causal design validator, or
permission to infer missing research definitions. Other families retain their
own contracts. Plot counts are recommendations, never substitutes for evidence.
"""

import hashlib
import json


POLICY = {
    "schema": "generic-ols-evidence-policy-v1",
    "models": ["multiple_regression"],
    "supporting_comparison": "independent_two_group_numeric_rank_screen",
    "required_model_evidence": [
        "exact_approved_model",
        "source_and_case_ledger",
        "full_rank_design",
        "coefficient_intervals",
        "saved_fitted_and_residual_rows",
        "immutable_model_figures",
        "all_approved_figures",
    ],
    "recommended_analytical_figures": 6,
    "rank_interval_scope": "Rank-screen effects have no effect interval in the legacy tool; OLS intervals describe a separate mean-model estimand, never the rank effect.",
    "limitations": [
        "Independent observations and the scientific design require review; figures do not prove assumptions.",
        "OLS model-based intervals are unadjusted across model coefficients and models.",
        "The supporting rank comparison is limited to two groups. OLS may include recorded numeric or treatment-dummy categorical predictors; this does not add an omnibus multi-group comparison.",
        "No paired, repeated, multilevel, logistic, vendor-only or unspecified model is included.",
    ],
}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def policy_sha256():
    return digest(POLICY)


def names(value):
    if isinstance(value, str):
        return [value] if value else []
    return (
        list(value)
        if isinstance(value, list) and all(isinstance(x, str) and x for x in value)
        else []
    )


def arguments(entry):
    extra = entry.get("execution_arguments")
    return {**entry, **extra} if isinstance(extra, dict) else entry


def figure_binding(entry):
    args = arguments(entry)
    return {
        "plot_type": str(args.get("plot_type") or "").lower(),
        "variables": names(args.get("variables")),
        "group_var": args.get("group_var", args.get("group_variable")),
        "include_tests": args.get("include_tests", False),
        "missing_strategy": args.get("missing_strategy", "listwise"),
        "subject_variable": args.get("subject_variable"),
        "labels": args.get("labels"),
        "ylabel": args.get("ylabel"),
    }


def plan_requirements(analyses, variables):
    """Return None outside this finite policy; otherwise an exact draft review.

    `variables` contains schema names, variable types and observed unique counts.
    A recognized but incomplete plan gets explicit errors, never auto-expansion.
    """
    if (
        not isinstance(analyses, list)
        or not analyses
        or not all(isinstance(e, dict) for e in analyses)
    ):
        return None
    supporting = {
        "analyze_variable",
        "generate_table_one",
        "table_one",
        "correlation_matrix",
        "visualization",
        "create_visualization",
    }
    methods = [str(e.get("type") or e.get("analysis_type") or "") for e in analyses]
    if not any(
        m in {"compare_groups", "multiple_regression", "run_advanced_analysis"} for m in methods
    ):
        return None
    for entry, method in zip(analyses, methods, strict=True):
        if method not in supporting | {
            "compare_groups",
            "multiple_regression",
            "run_advanced_analysis",
        }:
            return None
        if (
            method == "run_advanced_analysis"
            and arguments(entry).get("analysis_type") != "multiple_regression"
        ):
            return None
    index = {
        v["name"]: v for v in variables if isinstance(v, dict) and isinstance(v.get("name"), str)
    }
    numeric = {
        name
        for name, v in index.items()
        if v.get("variable_type") in {"continuous", "numeric", "integer", "biomarker"}
    }
    errors, models, comparisons, figures = [], [], [], []
    for entry, method in zip(analyses, methods, strict=True):
        args = arguments(entry)
        if (
            "type" not in entry
            or method == "create_visualization"
            or not names(entry.get("variables"))
        ):
            errors.append(
                "Every exact plan entry needs its registered type and explicit variables; use type=visualization for figure entries."
            )
        if any(v not in index for v in names(entry.get("variables"))):
            errors.append("Exact plan variables must exist in the source schema.")
        if method in {"visualization", "create_visualization"}:
            binding = figure_binding(entry)
            if (
                binding["plot_type"]
                not in {"histogram", "boxplot", "scatter", "bar", "violin", "heatmap"}
                or not binding["variables"]
                or any(v not in index for v in binding["variables"])
            ):
                errors.append(
                    "Every approved figure needs a supported unpaired descriptive plot_type and existing variables."
                )
            if binding["group_var"] is not None and binding["group_var"] not in index:
                errors.append("Approved figure group_var must identify an existing variable.")
            if (
                binding["include_tests"] is not False
                or binding["subject_variable"] is not None
                or binding["missing_strategy"] != "listwise"
                or binding["labels"] is not None
            ):
                errors.append(
                    "Finite-policy supplemental plots are descriptive, listwise and unpaired; additional visual tests need a separate prespecified inference contract."
                )
            if any(key in args for key in ("filter", "row_filter", "transform")):
                errors.append(
                    "Filtered/transformed generic figures require a separate reviewed data contract."
                )
            if binding not in figures:
                figures.append(binding)
        elif method == "compare_groups":
            if args.get("is_paired") or args.get("subject_variable"):
                return None
            group = args.get("group_variable", args.get("group_var"))
            outcomes = names(args.get("outcome_variables", args.get("variables")))
            if not isinstance(group, str) or index.get(group, {}).get("n_unique") != 2:
                return None
            if not outcomes or any(o not in numeric for o in outcomes):
                return None
            comparisons.append({"group_variable": group, "outcome_variables": outcomes})
        elif method in {"multiple_regression", "run_advanced_analysis"}:
            target, covariates = args.get("target_variable"), names(args.get("covariates"))
            if (
                target not in numeric
                or not covariates
                or target in covariates
                or len(set(covariates)) != len(covariates)
                or any(v not in index for v in covariates)
            ):
                errors.append(
                    "OLS needs one exact continuous target_variable and a unique explicit nonempty covariates list; no role inference is permitted."
                )
            if args.get("family") not in (None, "gaussian") or args.get("regularized"):
                return None
            if any(
                args.get(key)
                for key in (
                    "vendor_options",
                    "clinical_options",
                    "subject_variable",
                    "time_variable",
                    "score_variable",
                    "endpoint",
                    "test_type",
                    "problem_type",
                )
            ):
                errors.append(
                    "Finite OLS uses explicit target/covariates only; vendor, repeated, endpoint or clinical overrides require their own contract."
                )
            model = {
                "analysis_type": "multiple_regression",
                "target_variable": target,
                "covariates": covariates,
            }
            if model not in models:
                models.append(model)
    if not models:
        errors.append(
            "Pure compare_groups rank screening has no effect confidence interval. Use the typed comparison contract or explicitly plan a separate OLS mean model; its interval never describes the rank effect."
        )
    for comparison in comparisons:
        for outcome in comparison["outcome_variables"]:
            if not any(
                m["target_variable"] == outcome and comparison["group_variable"] in m["covariates"]
                for m in models
            ):
                errors.append(
                    f"Rank screen {outcome!r} by {comparison['group_variable']!r} requires a separately prespecified OLS mean model including that group, or the typed comparison contract."
                )
    return {
        "schema": POLICY["schema"],
        "policy_sha256": policy_sha256(),
        "eligible": not errors,
        "errors": list(dict.fromkeys(errors)),
        "models": models,
        "comparisons": comparisons,
        "approved_figures": figures,
        "recommendations": [
            "Six analytical figures are an optional editorial recommendation; duplicate plots cannot satisfy missing model evidence."
        ],
        "limitations": POLICY["limitations"] + [POLICY["rank_interval_scope"]],
    }
