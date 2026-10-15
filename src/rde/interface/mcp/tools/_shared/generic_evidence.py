"""Exact review and saved-evidence checks for the finite generic OLS policy."""

import hashlib
import math
from pathlib import Path
from types import SimpleNamespace

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.domain.services.generic_evidence_policy import (
    POLICY,
    arguments,
    digest,
    figure_binding,
    plan_requirements,
    policy_sha256,
)
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.research_plans import read_sealed, write_once
from .target_trial_replay import source_identity


CONTRACT_FILE = "generic_ols_evidence_contract.json"


def schema_variables(dataset):
    return [
        {
            "name": v.name,
            "variable_type": v.variable_type.value,
            "dtype": v.dtype,
            "n_unique": v.n_unique,
        }
        for v in dataset.variables
    ]


def role_bindings(roles):
    if not isinstance(roles, dict) or roles.get("confirmed") is not True:
        return None
    mapping = roles.get("variable_roles")
    if isinstance(mapping, dict):
        return {str(name): str(role) for name, role in sorted(mapping.items())}
    result = {}
    for role in ("outcome", "group", "covariate", "predictor", "id", "unassigned"):
        raw = roles.get(role, roles.get(role + "s", []))
        for name in [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []:
            if not isinstance(name, str) or name in result and result[name] != role:
                raise ValueError("Conflicting or malformed confirmed role bindings")
            result[name] = role
    return result


def preflight(project, entry, analyses, *, alpha, missing_strategy, multiple_comparison_method):
    from rde.domain.services.analysis_policy import validate_policy

    validate_policy(alpha, missing_strategy, multiple_comparison_method)
    store = ArtifactStore(project.artifacts_dir)
    schema = schema_variables(entry.dataset)
    requirements = plan_requirements(analyses, schema)
    has_ols_intent = (
        any(
            isinstance(entry, dict)
            and (
                entry.get("type") == "multiple_regression"
                or arguments(entry).get("analysis_type") == "multiple_regression"
            )
            for entry in analyses
        )
        if isinstance(analyses, list)
        else False
    )
    applicability = (
        "applicable"
        if requirements is not None
        else "requires_revision"
        if has_ols_intent
        else "outside_policy"
    )
    roles = store.load(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json") or {}
    identity = source_identity(entry)
    bindings = role_bindings(roles)
    errors = (
        list(requirements["errors"])
        if requirements
        else [
            "Outside generic OLS evidence policy; use the method's typed contract or the existing legacy review. No new-policy readiness is granted."
        ]
    )
    if bindings is None:
        errors.append(
            "A confirmed concept-role artifact is required; unknown roles are not inferred."
        )
    if roles.get("analysis_scope") == "descriptive" and requirements is not None:
        errors.append(
            "Descriptive concept scope cannot approve inferential OLS; revise the confirmed concept first."
        )
    if missing_strategy != "listwise":
        errors.append(
            "The finite OLS evidence policy requires listwise complete cases; other missing strategies require a separate contract."
        )
    if requirements is not None:
        settings = {
            "alpha": alpha,
            "confidence_level": 1 - alpha,
            "missing_strategy": missing_strategy,
            "multiple_comparison_method": multiple_comparison_method,
        }
        for item in analyses:
            supplied = arguments(item)
            for key, expected in settings.items():
                if key in supplied and supplied[key] is not None and supplied[key] != expected:
                    errors.append(f"Exact analysis {key} differs from the registered plan setting.")
    contract = {
        "schema": "generic-plan-approval-v1",
        "policy_sha256": policy_sha256(),
        "source_content": {
            key: identity[key] for key in ("source_sha256", "sheet", "format", "frame")
        },
        "source_schema": schema,
        "confirmed_roles": bindings,
        "analyses": analyses,
        "settings": {
            "alpha": alpha,
            "missing_strategy": missing_strategy,
            "multiple_comparison_method": multiple_comparison_method,
        },
        "requirements": requirements,
    }
    return {
        "schema": "generic-plan-preflight-v1",
        "applicability": applicability,
        "can_lock": not errors,
        "errors": errors,
        "portable_contract": contract,
        "review_sha256": digest(contract),
        "origin": {
            "project_id": project.id,
            "source_identity": identity,
            "roles_artifact_sha256": digest(roles),
        },
        "scope": POLICY["schema"] if requirements else "outside_finite_generic_policy",
        "limitations": POLICY["limitations"] + [POLICY["rank_interval_scope"]],
        "transfer_contract": "The host must retain the original review artifact and record its mapping to the new local receipt. Equal portable review hashes permit unchanged bytes/schema/roles/plan in a new execution workspace; local source identity is pinned separately after locking.",
    }


def freeze_review(project, review):
    path = ArtifactStore(project.artifacts_dir).get_path(
        PipelinePhase.PLAN_REGISTRATION, CONTRACT_FILE
    )
    payload = {"schema": "generic-ols-locked-evidence-v1", "review": review}
    write_once(path, payload)
    return {
        "schema": payload["schema"],
        "path": str(path.relative_to(project.output_dir)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "review_sha256": review["review_sha256"],
        "policy_sha256": policy_sha256(),
    }


def _project(store, dataset_id):
    root = store.get_path(PipelinePhase.PLAN_REGISTRATION, "unused").parents[2]
    return SimpleNamespace(
        output_dir=root, artifacts_dir=root / "artifacts", dataset_ids=[dataset_id]
    )


def validate_locked(store):
    """Read-only: exact local identity plus portable approved research definitions."""
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
    reference = plan.get("generic_evidence_contract")
    if not isinstance(reference, dict):
        raise ValueError("No approved generic evidence contract")
    path = store.get_path(PipelinePhase.PLAN_REGISTRATION, CONTRACT_FILE)
    if (
        plan.get("locked") is not True
        or reference.get("path") != str(path.relative_to(path.parents[2]))
        or reference.get("policy_sha256") != policy_sha256()
        or not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != reference.get("sha256")
    ):
        raise ValueError(
            "GENERIC_EVIDENCE_STALE: locked plan or immutable evidence contract changed"
        )
    payload = read_sealed(path)["payload"]
    review = payload["review"]
    approved = review["portable_contract"]
    if (
        payload.get("schema") != "generic-ols-locked-evidence-v1"
        or not review.get("can_lock")
        or review["review_sha256"] != digest(approved)
        or reference.get("review_sha256") != review["review_sha256"]
        or approved["policy_sha256"] != policy_sha256()
    ):
        raise ValueError("GENERIC_EVIDENCE_STALE: review or policy differs")
    identity = review["origin"]["source_identity"]
    entry = get_session().get_dataset_entry(identity["dataset_id"])
    if entry is None or source_identity(entry) != identity:
        raise ValueError("GENERIC_EVIDENCE_STALE: exact local source identity changed")
    project = _project(store, entry.dataset.id)
    project.id = review["origin"]["project_id"]
    current = preflight(
        project,
        entry,
        plan["analyses"],
        **{key: plan[key] for key in ("alpha", "missing_strategy", "multiple_comparison_method")},
    )
    if (
        not current["can_lock"]
        or current["portable_contract"] != approved
        or current["origin"]["roles_artifact_sha256"] != review["origin"]["roles_artifact_sha256"]
    ):
        raise ValueError(
            "GENERIC_EVIDENCE_STALE: source schema, confirmed roles or exact locked plan changed"
        )
    return project, plan, approved


def ensure_current(project):
    store = ArtifactStore(project.artifacts_dir)
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
    if plan.get("generic_evidence_contract") is not None:
        validate_locked(store)


def ensure_model_call(
    project, *, analysis_type, target_variable, covariates, confidence_level, overrides
):
    """No-op for legacy/typed plans; pinned finite models cannot change at execution."""
    store = ArtifactStore(project.artifacts_dir)
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
    if plan.get("generic_evidence_contract") is None:
        return
    _, _, approved = validate_locked(store)
    model = {
        "analysis_type": analysis_type,
        "target_variable": target_variable,
        "covariates": covariates or [],
    }
    if (
        model not in approved["requirements"]["models"]
        or any(overrides.values())
        or confidence_level != 1 - approved["settings"]["alpha"]
    ):
        raise ValueError(
            "GENERIC_MODEL_SCOPE: use the exact approved OLS target, predictors and confidence level without model overrides; revise the plan for another model."
        )


def _output_receipt_path(store, identity):
    return store.get_path(
        PipelinePhase.EXECUTE_EXPLORATION, f"generic_evidence_outputs/{digest(identity)}.json"
    )


def seal_output(project, paths, *, identity, binding=None):
    store = ArtifactStore(project.artifacts_dir)
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
    if plan.get("generic_evidence_contract") is None:
        return
    _, _, approved = validate_locked(store)
    root = project.output_dir.resolve()
    files = []
    for raw in paths:
        path = Path(raw).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Generic output must be a saved project file")
        files.append(
            {
                "path": str(path.relative_to(root)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
        )
    write_once(
        _output_receipt_path(store, identity),
        {
            "schema": "generic-ols-output-evidence-v1",
            "identity": identity,
            "binding": binding,
            "review_sha256": digest(approved),
            "plan_sha256": hashlib.sha256(
                store.get_path(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml").read_bytes()
            ).hexdigest(),
            "files": files,
        },
    )


def verify_output(store, identity, expected_path, *, binding=None):
    try:
        project, _, approved = validate_locked(store)
        payload = read_sealed(_output_receipt_path(store, identity))["payload"]
        if (
            payload.get("schema") != "generic-ols-output-evidence-v1"
            or payload["identity"] != identity
            or payload.get("binding") != binding
            or payload["review_sha256"] != digest(approved)
            or payload["plan_sha256"]
            != hashlib.sha256(
                store.get_path(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml").read_bytes()
            ).hexdigest()
        ):
            return False
        files = payload["files"]
        if (
            not files
            or len({item["path"] for item in files}) != len(files)
            or expected_path not in {item["path"] for item in files}
        ):
            return False
        for item in files:
            raw = project.output_dir / item["path"]
            path = raw.resolve()
            if (
                raw.is_symlink()
                or not path.is_relative_to(project.output_dir)
                or not path.is_file()
                or path.stat().st_size != item["bytes"]
                or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
            ):
                return False
        return True
    except (ValueError, KeyError, TypeError, OSError):
        return False


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def evaluate(store):
    """Validate original artifacts; never fit, render or repair missing evidence."""
    checks, used_figures = [], []

    def check(name, passed, evidence):
        checks.append({"id": name, "required": True, "passed": bool(passed), "evidence": evidence})

    try:
        project, plan, approved = validate_locked(store)
        check("exact_approved_source_roles_plan_policy", True, [CONTRACT_FILE])
    except (ValueError, KeyError, TypeError, OSError) as exc:
        check("exact_approved_source_roles_plan_policy", False, [str(exc)])
        return {
            "ready": False,
            "assessable": True,
            "checks": checks,
            "missing_requirements": [checks[0]["id"]],
            "summary": str(exc),
            "figure_files": [],
        }
    requirements, settings = approved["requirements"], approved["settings"]
    phase = PipelinePhase.EXECUTE_EXPLORATION
    from .advanced_study import advanced_study_source

    for index, model in enumerate(requirements["models"]):
        candidates = []
        for name in store.list_phase_artifacts(phase):
            if name.startswith("advanced_study_") and name.endswith(".json"):
                record = store.load(phase, name) or {}
                contract = record.get("analysis_contract", {})
                if all(contract.get(key) == value for key, value in model.items()):
                    candidates.append((name, record))
        passed, evidence = len(candidates) == 1, []
        if passed:
            name, record = candidates[0]
            path = store.get_path(phase, name)
            try:
                _, frozen = advanced_study_source(
                    project, name, hashlib.sha256(path.read_bytes()).hexdigest()
                )
                data = frozen["analysis_result"]
                model_evidence = data["model_evidence"]
                p = model_evidence["design_columns_count"]
                rows = model_evidence["rows"]
                intervals = model_evidence["coefficient_intervals"]
                covariance = model_evidence["covariance"]
                passed = (
                    frozen["analysis_contract"]["confidence_level"] == 1 - settings["alpha"]
                    and frozen["analysis_contract"]["missing_strategy"]
                    == settings["missing_strategy"]
                    and (project.output_dir / frozen["plan_snapshot"]["path"]).read_bytes()
                    == store.get_path(
                        PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml"
                    ).read_bytes()
                    and data["nobs"] == len(rows) > p > 1
                    and model_evidence["design_rank"] == p
                    and model_evidence["df_resid"] > 0
                    and model_evidence["regularized"] is False
                    and model_evidence["inference_error"] is None
                    and len(intervals) == p
                    and all(
                        len(pair) == 2 and all(_finite(v) for v in pair) and pair[0] <= pair[1]
                        for pair in intervals
                    )
                    and len(covariance) == p
                    and all(len(row) == p and all(_finite(v) for v in row) for row in covariance)
                    and all(
                        all(_finite(row[key]) for key in ("outcome", "fitted", "response_residual"))
                        for row in rows
                    )
                    and bool(model_evidence["case_set"])
                    and {"advanced_inclusion", "advanced_fitted", "advanced_residuals"}.issubset(
                        {f["plot_type"] for f in frozen["figures"]}
                    )
                    and any(
                        f["plot_type"].startswith("advanced_coefficients_")
                        for f in frozen["figures"]
                    )
                )
                evidence = [name]
                used_figures.extend(f["path"] for f in frozen["figures"])
            except (ValueError, KeyError, TypeError, OSError) as exc:
                passed, evidence = False, [str(exc)]
        check(f"ols_{index + 1}_denominator_estimates_intervals_diagnostics", passed, evidence)
    for index, comparison in enumerate(requirements["comparisons"]):
        found = []
        for name in store.list_phase_artifacts(phase):
            if name.startswith("compare_groups_") and name.endswith(".json"):
                record = store.load(phase, name) or {}
                if (
                    record.get("group_variable") == comparison["group_variable"]
                    and record.get("outcome_variables") == comparison["outcome_variables"]
                ):
                    found.append((name, record))
        passed = len(found) == 1
        if passed:
            _, record = found[0]
            passed = (
                verify_output(
                    store,
                    {"comparison": found[0][0]},
                    str(store.get_path(phase, found[0][0]).relative_to(project.output_dir)),
                )
                and record.get("method_contract") == "comparison-inference-v2"
                and record.get("is_paired") is False
                and record.get("policy") == settings
                and len(record.get("tests", [])) == len(comparison["outcome_variables"])
                and all(
                    len(t.get("sample_sizes", [])) == 2
                    and all(isinstance(n, int) and n > 0 for n in t["sample_sizes"])
                    and _finite(t.get("effect_size"))
                    and _finite(t.get("adjusted_p_value"))
                    for t in record["tests"]
                )
                and all(
                    bool(record.get("case_sets", {}).get(outcome))
                    for outcome in comparison["outcome_variables"]
                )
            )
        check(
            f"rank_screen_{index + 1}_separate_estimand_and_denominators",
            passed,
            [name for name, _ in found],
        )
    manifest = store.load(phase, "visualization_manifest.json") or []
    for index, binding in enumerate(requirements["approved_figures"]):
        matching = [
            item for item in manifest if isinstance(item, dict) and figure_binding(item) == binding
        ]
        valid = []
        for item in matching:
            raw = project.output_dir / str(item.get("output_path", ""))
            path = raw.resolve()
            if (
                path.is_relative_to(project.output_dir / "figures")
                and path.is_file()
                and not raw.is_symlink()
                and hashlib.sha256(path.read_bytes()).hexdigest() == item.get("sha256")
                and verify_output(
                    store,
                    {"figure": str(path.relative_to(project.output_dir))},
                    str(path.relative_to(project.output_dir)),
                    binding=binding,
                )
            ):
                valid.append(str(path.relative_to(project.output_dir)))
        check(f"approved_figure_{index + 1}", bool(valid), valid)
        used_figures.extend(valid)
    missing = [c["id"] for c in checks if not c["passed"]]
    return {
        "ready": not missing,
        "assessable": True,
        "checks": checks,
        "missing_requirements": missing,
        "summary": f"{len(checks) - len(missing)}/{len(checks)} exact evidence checks passed",
        "figure_files": sorted(set(used_figures)),
        "policy_sha256": policy_sha256(),
        "recommendations": requirements["recommendations"],
        "limitations": requirements["limitations"],
    }


def deliverables(store):
    depth = evaluate(store)
    return {
        "scope": POLICY["schema"],
        "publication_bundle_applicable": True,
        "minimum_publication_bundle_met": depth["ready"],
        "table_one_required": False,
        "table_one_present": store.exists(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md"),
        "descriptive_figures": 0,
        "analytical_figures": len(depth["figure_files"]),
        "required_descriptive_figures": 0,
        "required_analytical_figures": 0,
        "total_figures": len(depth["figure_files"]),
        "figure_files": depth["figure_files"],
        "missing_components": depth["missing_requirements"],
        "evidence_policy": depth,
        "applicability": "Figure counts are descriptive only. Readiness requires the exact approved figures and finite OLS numerical/diagnostic evidence; six plots cannot replace missing evidence.",
    }
