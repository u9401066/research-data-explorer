"""Common medical EDA branch suggestion pack.

This service turns schema, variable roles, and the locked plan into a
deterministic set of exploratory branch candidates.  It intentionally lives in
the domain layer so the common medical analysis floor can be tested without
depending on MCP tool wiring.
"""

from __future__ import annotations

import re
from typing import Any

from rde.domain.models.exploration_branch import BranchType


def build_common_medical_eda_suggestions(
    schema: dict[str, Any],
    plan: dict[str, Any],
    roles: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    variables = schema.get("variables") if isinstance(schema, dict) else []
    variables = variables if isinstance(variables, list) else []
    analyses = plan.get("analyses") if isinstance(plan, dict) else []
    analyses = analyses if isinstance(analyses, list) else []
    roles = roles if isinstance(roles, dict) else {}
    variable_index = {
        str(var.get("name")): var for var in variables if isinstance(var, dict) and var.get("name")
    }

    def schema_type(name: str) -> str:
        var = variable_index.get(name) or {}
        return str(var.get("variable_type", "")).lower()

    def schema_unique_count(name: str) -> int | None:
        var = variable_index.get(name) or {}
        raw = var.get("n_unique")
        if raw is None:
            raw = var.get("unique_count")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def is_binary_schema_var(name: str, *, allow_unknown_categorical: bool = False) -> bool:
        var_type = schema_type(name)
        if var_type in {"binary", "boolean"}:
            return True
        if var_type in {"categorical", "factor", "ordinal", "integer", "numeric"}:
            n_unique = schema_unique_count(name)
            if n_unique == 2:
                return True
            if (
                n_unique is None
                and allow_unknown_categorical
                and var_type in {"categorical", "factor"}
            ):
                return True
        return False

    def is_multilevel_treatment_var(name: str) -> bool:
        var_type = schema_type(name)
        if var_type not in {"categorical", "factor", "ordinal", "integer", "numeric"}:
            return False
        n_unique = schema_unique_count(name)
        return n_unique is not None and 3 <= n_unique <= 12

    numeric = [
        str(var.get("name"))
        for var in variables
        if isinstance(var, dict)
        and str(var.get("variable_type", "")).lower() in {"continuous", "numeric", "integer"}
    ]
    categorical = [
        str(var.get("name"))
        for var in variables
        if isinstance(var, dict)
        and str(var.get("variable_type", "")).lower()
        in {"binary", "boolean", "categorical", "factor", "ordinal"}
    ]
    missing = [
        str(var.get("name"))
        for var in variables
        if isinstance(var, dict) and float(var.get("missing_rate") or 0) > 0
    ]
    all_names = [str(var.get("name")) for var in variables if isinstance(var, dict)]
    role_outcomes = _role_values(roles, ("outcome", "target", "dependent", "endpoint"))
    role_groups = _role_values(roles, ("group", "treatment", "exposure"))
    role_covariates = _role_values(
        roles,
        ("covariate", "confounder", "adjuster", "baseline", "predictor"),
    )
    role_times = _role_values(roles, ("time", "duration", "followup", "survival_time"))
    role_events = _role_values(roles, ("event", "censor", "mortality", "relapse", "endpoint"))

    def is_outcome_like_var(name: str) -> bool:
        lowered = name.lower()
        if name in role_outcomes:
            return True
        if name in role_groups or name in role_covariates:
            return False
        if any(
            token in lowered
            for token in (
                "sex",
                "gender",
                "age",
                "height",
                "weight",
                "bmi",
                "baseline",
                "treat",
                "group",
                "arm",
                "exposure",
            )
        ):
            return False
        return any(
            token in lowered or token in name
            for token in (
                "outcome",
                "endpoint",
                "event",
                "status",
                "death",
                "mortality",
                "relapse",
                "progression",
                "readmission",
                "aki",
                "renal",
                "creatinine",
                "ngal",
                "kim",
                "cystatin",
                "結果",
                "事件",
                "死亡",
                "腎",
            )
        )

    time_vars = [
        name
        for name in all_names
        if any(
            token in name.lower()
            for token in (
                "time",
                "day",
                "days",
                "month",
                "months",
                "follow",
                "duration",
                "survival",
                "os_",
                "dfs",
                "pfs",
            )
        )
    ]
    time_vars = list(dict.fromkeys(role_times + time_vars))
    event_vars = [
        name
        for name in all_names
        if any(
            token in name.lower()
            for token in (
                "death",
                "mortality",
                "event",
                "status",
                "relapse",
                "readmission",
                "censor",
                "progression",
            )
        )
        and is_binary_schema_var(name, allow_unknown_categorical=True)
    ]
    event_vars = list(dict.fromkeys(role_events + event_vars))
    treatment_vars = [
        name
        for name in categorical
        if any(token in name.lower() for token in ("treat", "group", "arm", "exposure"))
    ]
    treatment_vars = list(dict.fromkeys(role_groups + treatment_vars))
    repeated_sets = _repeated_measure_sets(numeric)

    suggestions: list[dict[str, Any]] = []

    def add(entry: dict[str, Any]) -> None:
        key = (
            entry.get("experiment_type"),
            tuple(entry.get("variables") or []),
            str(entry.get("hypothesis") or ""),
        )
        existing = {
            (
                item.get("experiment_type"),
                tuple(item.get("variables") or []),
                str(item.get("hypothesis") or ""),
            )
            for item in suggestions
        }
        if key not in existing:
            entry.setdefault("suggestion_pack", "common_medical_eda")
            suggestions.append(entry)

    if missing:
        add(
            {
                "branch_type": BranchType.MISSING_STRATEGY.value,
                "experiment_type": "missing_strategy",
                "hypothesis": "Missing-data handling does not change the substantive conclusion.",
                "reason": "schema.json reports variables with missing_rate > 0.",
                "variables": missing[:5],
            }
        )

    planned_entries = [entry for entry in analyses if isinstance(entry, dict)] or [{}]
    for analysis in planned_entries:
        analysis_outcomes = _analysis_outcomes(analysis)
        outcome_vars = role_outcomes or analysis_outcomes or numeric[:1] or categorical[:1]
        group_var = analysis.get("group_variable") or analysis.get("group_var")
        if not group_var and role_groups:
            group_var = role_groups[0]
        if not group_var and treatment_vars:
            group_var = treatment_vars[0]
        group_var = str(group_var) if group_var else None
        plan_vars = list(dict.fromkeys(outcome_vars + ([group_var] if group_var else [])))
        excluded = set(plan_vars)
        covariates = [
            var
            for var in list(dict.fromkeys(role_covariates + numeric + categorical))
            if var not in excluded
        ][:5]

        if plan_vars:
            add(
                {
                    "branch_type": BranchType.SENSITIVITY.value,
                    "experiment_type": "sensitivity",
                    "hypothesis": "Primary planned result is stable under a sensitivity check.",
                    "reason": "Locked analysis_plan.yaml contains a primary analysis that can be stress-tested.",
                    "variables": plan_vars,
                }
            )

        continuous_outcomes = [
            outcome
            for outcome in outcome_vars
            if schema_type(outcome) in {"continuous", "numeric", "integer"}
        ]
        if continuous_outcomes and covariates:
            for index, outcome in enumerate(continuous_outcomes[:4]):
                add(
                    {
                        "branch_type": BranchType.ADJUSTED_MODEL.value,
                        "experiment_type": "adjusted_model",
                        "hypothesis": (
                            "Adjustment for plausible covariates preserves the planned signal "
                            f"for {outcome}."
                        )
                        if index == 0
                        else (
                            "Autoresearch covariate-adjusted model checks a secondary "
                            f"clinical outcome: {outcome}."
                        ),
                        "reason": (
                            "schema.json contains covariates not already in the primary plan."
                            if index == 0
                            else "schema.json contains multiple clinical outcomes; autonomous RDE should not stop after one adjusted model."
                        ),
                        "variables": list(dict.fromkeys([outcome] + covariates)),
                        "analysis_contract": {
                            "tool": "run_advanced_analysis",
                            "analysis_type": "multiple_regression",
                            "target_variable": outcome,
                            "covariates": covariates,
                            "create_figures": True,
                        },
                    }
                )

        binary_outcomes = [
            var
            for var in outcome_vars
            if (is_binary_schema_var(var, allow_unknown_categorical=False) or var in event_vars)
            and is_outcome_like_var(var)
        ]
        if binary_outcomes and covariates:
            add(
                {
                    "branch_type": BranchType.ADJUSTED_MODEL.value,
                    "experiment_type": "adjusted_model",
                    "hypothesis": "Adjusted model is required for the binary clinical endpoint.",
                    "reason": (
                        "Medical EDA should surface a generic adjusted-model branch even "
                        "when the executable model is logistic regression."
                    ),
                    "variables": list(dict.fromkeys(binary_outcomes[:1] + covariates)),
                    "analysis_contract": {
                        "tool": "run_advanced_analysis",
                        "analysis_type": "logistic_regression",
                        "target_variable": binary_outcomes[0],
                        "covariates": covariates,
                        "create_figures": True,
                    },
                }
            )
            add(
                {
                    "branch_type": BranchType.ADJUSTED_MODEL.value,
                    "experiment_type": "logistic_regression",
                    "hypothesis": "Binary clinical outcome remains associated after adjustment.",
                    "reason": "Medical datasets often require adjusted odds ratios for binary endpoints.",
                    "variables": list(dict.fromkeys(binary_outcomes[:1] + covariates)),
                    "analysis_contract": {
                        "tool": "run_advanced_analysis",
                        "analysis_type": "logistic_regression",
                        "target_variable": binary_outcomes[0],
                        "covariates": covariates,
                        "create_figures": True,
                    },
                }
            )

        if (
            group_var
            and is_binary_schema_var(group_var, allow_unknown_categorical=True)
            and covariates
        ):
            add(
                {
                    "branch_type": BranchType.PROPENSITY.value,
                    "experiment_type": "propensity_score",
                    "hypothesis": "Treatment/exposure groups remain comparable after propensity scoring.",
                    "reason": "Group imbalance is common in observational medical data.",
                    "variables": list(dict.fromkeys([group_var] + covariates)),
                    "analysis_contract": {
                        "tool": "run_advanced_analysis",
                        "analysis_type": "propensity_score",
                        "group_variable": group_var,
                        "covariates": covariates,
                        "create_figures": True,
                    },
                }
            )
        elif group_var and is_multilevel_treatment_var(group_var) and covariates:
            safe_group = _normalize_token(group_var) or "group"
            derived_group = f"{safe_group}_dominant_vs_other"
            add(
                {
                    "branch_type": BranchType.PROPENSITY.value,
                    "experiment_type": "propensity_score",
                    "hypothesis": (
                        "Dominant treatment/exposure level remains comparable with other "
                        "levels after propensity scoring."
                    ),
                    "reason": (
                        "The main exposure is multi-level, so autonomous RDE creates a "
                        "branch-local binary contrast before propensity scoring."
                    ),
                    "variables": list(dict.fromkeys([derived_group, group_var] + covariates)),
                    "analysis_contract": {
                        "tool": "run_advanced_analysis",
                        "analysis_type": "propensity_score",
                        "group_variable": derived_group,
                        "covariates": covariates,
                        "derived_variables": [
                            {
                                "name": derived_group,
                                "source": group_var,
                                "operation": "dominant_vs_other",
                            }
                        ],
                        "create_figures": True,
                    },
                }
            )

        if outcome_vars:
            add(
                {
                    "branch_type": BranchType.VISUALIZATION.value,
                    "experiment_type": "univariate_scan",
                    "hypothesis": "Outcome and baseline variables have interpretable marginal distributions.",
                    "reason": "Common medical EDA requires a univariate scan before modeling.",
                    "variables": list(dict.fromkeys(outcome_vars[:4] + covariates[:3])),
                }
            )
        if outcome_vars and group_var:
            add(
                {
                    "branch_type": BranchType.VISUALIZATION.value,
                    "experiment_type": "bivariate_scan",
                    "hypothesis": "Outcome distributions differ by clinically meaningful group or exposure.",
                    "reason": "Common medical EDA requires crude outcome-by-group exploration.",
                    "variables": list(dict.fromkeys(outcome_vars[:4] + [group_var])),
                }
            )

        if group_var and outcome_vars and covariates:
            add(
                {
                    "branch_type": BranchType.SUBGROUP.value,
                    "experiment_type": "subgroup_interaction",
                    "hypothesis": "Primary association is not driven by a clinically plausible subgroup.",
                    "reason": "Subgroup and interaction checks help detect heterogeneous effects.",
                    "variables": list(dict.fromkeys(outcome_vars + [group_var] + covariates[:2])),
                }
            )

        if plan_vars:
            add(
                {
                    "branch_type": BranchType.VISUALIZATION.value,
                    "experiment_type": "visualization",
                    "hypothesis": "A visualization reveals whether the planned result is pattern-stable.",
                    "reason": "Visual inspection can detect outliers, imbalance, or non-linear structure.",
                    "variables": plan_vars,
                }
            )

    if time_vars and event_vars:
        add(
            {
                "branch_type": BranchType.SURVIVAL.value,
                "experiment_type": "survival_analysis",
                "hypothesis": "Time-to-event patterns are consistent across clinically relevant strata.",
                "reason": "schema.json contains candidate time and event variables.",
                "variables": list(
                    dict.fromkeys(time_vars[:1] + event_vars[:1] + treatment_vars[:1])
                ),
                "analysis_contract": {
                    "tool": "run_advanced_analysis",
                    "analysis_type": "survival_analysis",
                    "time_variable": time_vars[0],
                    "target_variable": event_vars[0],
                    "group_variable": treatment_vars[0] if treatment_vars else None,
                    "create_figures": True,
                },
            }
        )

    score_vars = [
        name
        for name in numeric
        if any(token in name.lower() for token in ("score", "risk", "prob"))
    ]
    if score_vars and event_vars:
        add(
            {
                "branch_type": BranchType.ROC.value,
                "experiment_type": "roc_auc",
                "hypothesis": "Risk score discrimination is adequate for the binary clinical endpoint.",
                "reason": "schema.json contains score-like predictors and event-like outcomes.",
                "variables": list(dict.fromkeys(score_vars[:1] + event_vars[:1])),
                "analysis_contract": {
                    "tool": "run_advanced_analysis",
                    "analysis_type": "roc_auc",
                    "score_variable": score_vars[0],
                    "target_variable": event_vars[0],
                    "create_figures": True,
                },
            }
        )

    for repeated in repeated_sets[:2]:
        add(
            {
                "branch_type": BranchType.REPEATED_MEASURES.value,
                "experiment_type": "repeated_measures",
                "hypothesis": "Repeated clinical measurements change consistently over time.",
                "reason": "schema.json contains repeated-measure naming patterns.",
                "variables": repeated,
            }
        )

    # Readiness-aware prioritization (closes the Readiness->Queue loop). Branches that
    # register derived variables are the only ones that satisfy the scarce
    # `derived_variable_provenance` depth requirement, yet they are emitted late in the
    # per-analysis loop. When an autoresearch run truncates the queue to a task budget,
    # a late derived-variable branch is silently dropped, leaving the report stuck below
    # production-ready even though the analysis is otherwise complete. Stable-sort those
    # provenance-closing branches to the front so budget truncation can never starve them,
    # while preserving the original relative order of every other suggestion.
    suggestions.sort(
        key=lambda entry: 0
        if (entry.get("analysis_contract") or {}).get("derived_variables")
        else 1
    )
    return suggestions


def _analysis_outcomes(analysis: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("variables", "outcome_variables", "targets"):
        raw = analysis.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
        elif raw:
            values.append(str(raw))
    for key in ("target_variable", "outcome", "dependent_variable"):
        if analysis.get(key):
            values.append(str(analysis[key]))
    return list(dict.fromkeys(values))


def _role_values(roles: dict[str, Any], role_names: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key, raw in roles.items():
        normalized_key = str(key).lower()
        key_matches = any(role_name in normalized_key for role_name in role_names)
        if key_matches:
            if isinstance(raw, list):
                values.extend(str(item) for item in raw)
            elif isinstance(raw, dict):
                values.extend(str(item) for item in raw.values() if item)
            elif raw:
                values.append(str(raw))
        if isinstance(raw, dict):
            for variable_name, role_value in raw.items():
                role_text = str(role_value).strip().lower()
                if any(role_name in role_text for role_name in role_names):
                    values.append(str(variable_name))
        if (
            isinstance(raw, str)
            and not key_matches
            and len(raw) <= 40
            and any(role_name in raw.lower() for role_name in role_names)
        ):
            values.append(str(key))
    return list(dict.fromkeys(values))


def _repeated_measure_sets(numeric: list[str]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    suffixes = (
        "_0h",
        "_1h",
        "_4h",
        "_6h",
        "_12h",
        "_24h",
        "_48h",
        "_baseline",
        "_followup",
        "_pre",
        "_post",
        "_visit1",
        "_visit2",
        "_visit_1",
        "_visit_2",
        "_month1",
        "_month3",
        "_month6",
        "_month12",
    )
    prefixes = ("pre_", "post_", "baseline_", "followup_")
    for name in numeric:
        lower = name.lower()
        matched_suffix = next((suffix for suffix in suffixes if lower.endswith(suffix)), None)
        if matched_suffix:
            base = name[: -len(matched_suffix)]
            groups.setdefault(base, []).append(name)
            continue
        matched_prefix = next((prefix for prefix in prefixes if lower.startswith(prefix)), None)
        if not matched_prefix:
            continue
        base = name[len(matched_prefix) :]
        groups.setdefault(base, []).append(name)
    return [items for items in groups.values() if len(items) >= 2]


def _normalize_token(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
