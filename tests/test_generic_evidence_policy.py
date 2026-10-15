"""Real native lifecycle for finite OLS evidence, not arbitrary figure quotas."""

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools._shared.generic_evidence import evaluate, validate_locked
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness


def call(name, args, *, error=False):
    response = asyncio.run(create_server().call_tool(name, args))
    text = response.content[0].text
    assert response.is_error is error, text
    return response


def fixture(tmp_path, *, covariates=1, figure=True, categorical=False):
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    rng = np.random.default_rng(917)
    group = np.tile([0, 1], 40)
    age = rng.normal(50, 8, 80)
    frame = pd.DataFrame(
        {
            "treatment": group,
            "age": age,
            "outcome": 3 + 1.2 * group + 0.08 * age + rng.normal(size=80),
        }
    )
    if categorical:
        frame["age"] = np.resize(["low", "medium", "high"], len(frame))
    frame.to_csv(raw / "source.csv", index=False)
    call(
        "init_project",
        {
            "name": "Exact OLS evidence QA",
            "data_dir": str(raw),
            "research_question": "Prespecified independent-case mean outcome association by treatment, with explicitly chosen adjustment.",
        },
    )
    project = get_session().get_project()
    call("run_intake", {"project_id": project.id, "directory": str(raw)})
    dataset_id = project.dataset_ids[-1]
    for tool in ["build_schema", "profile_dataset", "assess_quality"]:
        call(tool, {"dataset_id": dataset_id})
    roles = (
        {"outcome": ["outcome"], "group": ["treatment"], "covariates": ["age"]}
        if covariates
        else {"outcome": ["outcome"], "group": ["treatment"], "unassigned": ["age"]}
    )
    call(
        "align_concept",
        {
            "project_id": project.id,
            "dataset_id": dataset_id,
            "variable_roles": roles,
            "confirm": True,
        },
    )
    call("propose_analysis_plan", {"project_id": project.id, "dataset_id": dataset_id})
    call(
        "propose_analysis_plan",
        {"project_id": project.id, "dataset_id": dataset_id, "confirm": True},
    )
    factors = ["treatment"] + (["age"] if covariates else [])
    analyses = [
        {
            "type": "compare_groups",
            "variables": ["outcome"],
            "group_variable": "treatment",
            "rationale": "Prespecified rank screen; no rank effect CI is claimed.",
        },
        {
            "type": "run_advanced_analysis",
            "analysis_type": "multiple_regression",
            "variables": ["outcome", *factors],
            "target_variable": "outcome",
            "covariates": factors,
            "rationale": "Separate prespecified mean-model estimand with model-based CI.",
        },
    ]
    if figure:
        analyses.append(
            {
                "type": "visualization",
                "plot_type": "boxplot",
                "variables": ["outcome"],
                "group_variable": "treatment",
                "rationale": "Review observed group distributions.",
            }
        )
    args = {
        "project_id": project.id,
        "analyses": analyses,
        "alpha": 0.05,
        "missing_strategy": "listwise",
        "multiple_comparison_method": "holm",
    }
    return project, ArtifactStore(project.artifacts_dir), dataset_id, args


def review(args):
    return json.loads(call("register_analysis_plan", {**args, "confirm": False}).content[0].text)


def lock(args):
    result = review(args)
    assert result["can_lock"], result
    call(
        "register_analysis_plan",
        {**args, "confirm": True, "expected_review_sha256": result["review_sha256"]},
    )
    call("check_readiness", {"project_id": args["project_id"]})
    return result


def execute(dataset_id, args, *, include_figure=True):
    model = args["analyses"][1]
    call(
        "compare_groups",
        {"dataset_id": dataset_id, "outcome_variables": ["outcome"], "group_variable": "treatment"},
    )
    call(
        "run_advanced_analysis",
        {
            "dataset_id": dataset_id,
            "analysis_type": "multiple_regression",
            "target_variable": "outcome",
            "covariates": model["covariates"],
        },
    )
    if include_figure and len(args["analyses"]) > 2:
        call(
            "create_visualization",
            {
                "dataset_id": dataset_id,
                "plot_type": "boxplot",
                "variables": ["outcome"],
                "group_var": "treatment",
            },
        )


@pytest.mark.parametrize("covariates", [0, 1])
def test_actual_small_study_uses_complete_exact_evidence_not_six_arbitrary_plots(
    tmp_path, covariates
):
    project, store, dataset_id, args = fixture(tmp_path, covariates=covariates, figure=False)
    before = {
        str(p.relative_to(project.output_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in project.output_dir.rglob("*")
        if p.is_file()
    }
    preflight = review(args)
    assert preflight["applicability"] == "applicable" and preflight["can_lock"]
    after = {
        str(p.relative_to(project.output_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in project.output_dir.rglob("*")
        if p.is_file()
    }
    assert before == after, "Readonly review changed project artifacts"
    lock(args)
    execute(dataset_id, args)
    depth = evaluate(store)
    assert depth["ready"], depth
    assert len(depth["figure_files"]) < 6
    call("collect_results", {"project_id": project.id})
    results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    readiness = _evaluate_report_readiness(results, store, require_report_generation=False)
    assert readiness["ready"], readiness
    call("assemble_report", {"project_id": project.id})


def test_six_unrelated_or_duplicate_figures_never_replace_model_diagnostics(tmp_path):
    _, store, dataset_id, args = fixture(tmp_path)
    lock(args)
    for index in range(6):
        call(
            "create_visualization",
            {
                "dataset_id": dataset_id,
                "plot_type": "histogram",
                "variables": ["outcome"],
                "output_filename": f"duplicate-{index}.png",
            },
        )
    depth = evaluate(store)
    assert not depth["ready"]
    assert "ols_1_denominator_estimates_intervals_diagnostics" in depth["missing_requirements"]
    assert "approved_figure_1" in depth["missing_requirements"]


def test_exact_review_moves_only_unchanged_content_and_rejects_semantic_drift(tmp_path):
    first, _, _, args = fixture(tmp_path / "original")
    original = review(args)
    second, store, dataset_id, copied = fixture(tmp_path / "copy")
    moved = review(copied)
    assert first.id != second.id
    assert (
        original["origin"]["source_identity"]["path"] != moved["origin"]["source_identity"]["path"]
    )
    assert original["portable_contract"] == moved["portable_contract"]
    assert original["review_sha256"] == moved["review_sha256"]
    changed = deepcopy(copied)
    changed["analyses"][1]["covariates"] = ["treatment"]
    denied = call(
        "register_analysis_plan",
        {**changed, "confirm": True, "expected_review_sha256": original["review_sha256"]},
        error=True,
    )
    assert "GENERIC_REVIEW_STALE" in denied.content[0].text
    assert not store.exists(PipelinePhase.PLAN_REGISTRATION, "generic_ols_evidence_contract.json")
    call(
        "register_analysis_plan",
        {**copied, "confirm": True, "expected_review_sha256": original["review_sha256"]},
    )
    validate_locked(store)
    entry = get_session().get_dataset_entry(dataset_id)
    entry.dataframe.loc[0, "age"] += 1
    with pytest.raises(ValueError, match="STALE"):
        validate_locked(store)


def test_pure_rank_and_mixed_unknown_cannot_fall_back_as_verified_ols(tmp_path):
    _, _, _, args = fixture(tmp_path)
    pure = {**args, "analyses": args["analyses"][:1]}
    result = review(pure)
    assert result["applicability"] == "applicable" and not result["can_lock"]
    assert "no effect confidence interval" in " ".join(result["errors"])
    mixed = {
        **args,
        "analyses": [
            *args["analyses"],
            {
                "type": "run_advanced_analysis",
                "analysis_type": "mixed_effects",
                "variables": ["outcome", "age"],
            },
        ],
    }
    result = review(mixed)
    assert result["applicability"] == "requires_revision" and not result["can_lock"]
    outside = {
        **args,
        "analyses": [
            {
                "type": "run_advanced_analysis",
                "analysis_type": "logistic_regression",
                "variables": ["treatment", "age"],
            }
        ],
    }
    result = review(outside)
    assert result["applicability"] == "outside_policy" and not result["can_lock"]


def test_missing_diagnostic_approved_figure_and_forged_figure_binding_fail_closed(tmp_path):
    project, store, dataset_id, args = fixture(tmp_path)
    lock(args)
    execute(dataset_id, args, include_figure=False)
    assert evaluate(store)["missing_requirements"] == ["approved_figure_1"]
    call(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "histogram",
            "variables": ["outcome"],
            "output_filename": "unrelated.png",
        },
    )
    phase = PipelinePhase.EXECUTE_EXPLORATION
    manifest = store.load(phase, "visualization_manifest.json")
    original = deepcopy(manifest)
    item = next(item for item in manifest if item["output_path"].endswith("unrelated.png"))
    item.update(plot_type="boxplot", group_var="treatment")
    item["execution_arguments"].update(plot_type="boxplot", group_var="treatment")
    store.save(phase, "visualization_manifest.json", manifest)
    assert (
        "approved_figure_1" in evaluate(store)["missing_requirements"]
    ), "Manifest labels must not change sealed figure meaning"
    store.save(phase, "visualization_manifest.json", original)
    figure_args = {
        "dataset_id": dataset_id,
        "plot_type": "boxplot",
        "variables": ["outcome"],
        "group_var": "treatment",
    }
    call("create_visualization", figure_args)
    assert evaluate(store)["ready"]
    path = project.output_dir / "figures/boxplot_outcome.png"
    frozen = path.read_bytes()
    response = call("create_visualization", figure_args, error=True)
    assert "cannot replace existing approved generic evidence" in response.content[0].text
    assert path.read_bytes() == frozen and evaluate(store)["ready"]
    model = next(
        store.load(phase, name)
        for name in store.list_phase_artifacts(phase)
        if name.startswith("advanced_study_") and name.endswith(".json")
    )
    diagnostic = project.output_dir / next(
        f["path"] for f in model["figures"] if f["plot_type"] == "advanced_residuals"
    )
    contents = diagnostic.read_bytes()
    diagnostic.unlink()
    assert (
        "ols_1_denominator_estimates_intervals_diagnostics"
        in evaluate(store)["missing_requirements"]
    )
    diagnostic.write_bytes(contents)
    assert evaluate(store)["ready"]
    path.write_bytes(frozen + b"changed")
    assert "approved_figure_1" in evaluate(store)["missing_requirements"]
    path.write_bytes(frozen)
    assert evaluate(store)["ready"]


def test_source_roles_policy_and_exact_model_overrides_rejected_before_computation(
    tmp_path, monkeypatch
):
    from rde.interface.mcp.tools._shared import generic_evidence
    from rde.infrastructure.adapters import get_analysis_delegator

    _, store, dataset_id, args = fixture(tmp_path)
    lock(args)
    monkeypatch.setattr(
        get_analysis_delegator().__class__,
        "run_analysis",
        lambda *a, **k: pytest.fail("Rejected model was fitted"),
    )
    model = {
        "dataset_id": dataset_id,
        "analysis_type": "multiple_regression",
        "target_variable": "outcome",
        "covariates": ["treatment", "age"],
    }
    for update in (
        {"covariates": ["treatment"]},
        {"vendor_options": {"backend": "numpy"}},
        {"confidence_level": 0.99},
        {"missing_strategy": "pairwise"},
    ):
        response = call("run_advanced_analysis", {**model, **update}, error=True)
        assert "GENERIC_" in response.content[0].text
    role_path = store.get_path(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json")
    original = role_path.read_bytes()
    roles = json.loads(original)
    roles["variable_roles"]["age"] = "unassigned"
    role_path.write_text(json.dumps(roles))
    call("run_advanced_analysis", model, error=True)
    assert not evaluate(store)["ready"]
    role_path.write_bytes(original)
    validate_locked(store)
    with monkeypatch.context() as context:
        context.setattr(generic_evidence, "policy_sha256", lambda: "0" * 64)
        assert not evaluate(store)["ready"]
        call("run_advanced_analysis", model, error=True)
    source = get_session().get_dataset_entry(dataset_id).dataset.metadata.file_path
    original = source.read_bytes()
    source.write_bytes(original + b"\n")
    call("run_advanced_analysis", model, error=True)
    source.write_bytes(original)
    validate_locked(store)


def test_unknown_group_cardinality_and_unsupported_overrides_are_not_approved(tmp_path):
    _, _, dataset_id, args = fixture(tmp_path)
    for update in ({"vendor_options": {"backend": "numpy"}}, {"confidence_level": 0.99}):
        changed = deepcopy(args)
        changed["analyses"][1].update(update)
        assert not review(changed)["can_lock"]
    entry = get_session().get_dataset_entry(dataset_id)
    group = next(v for v in entry.dataset.variables if v.name == "treatment")
    group.n_unique = None
    result = review(args)
    assert result["applicability"] == "requires_revision" and not result["can_lock"]


def test_ols_records_three_level_predictor_coding_without_claiming_multigroup_rank_test(tmp_path):
    _, store, dataset_id, args = fixture(tmp_path, categorical=True, figure=False)
    lock(args)
    execute(dataset_id, args)
    assert evaluate(store)["ready"]
    phase = PipelinePhase.EXECUTE_EXPLORATION
    model = next(
        store.load(phase, name)
        for name in store.list_phase_artifacts(phase)
        if name.startswith("advanced_study_") and name.endswith(".json")
    )
    coding = model["analysis_result"]["model_evidence"]["predictor_coding"]
    age = next(item for item in coding if item["source_column"] == "age")
    assert age["kind"] == "treatment_dummy" and len(age["levels"]) == 3


@pytest.mark.parametrize("confirm", [False, True])
def test_same_execution_key_revalidates_readonly_and_locked_generic_source(tmp_path, confirm):
    project, _, dataset_id, args = fixture(tmp_path)
    preflight = review(args)
    request = {**args, "confirm": confirm, "execution_key": "e" * 64}
    if confirm:
        request["expected_review_sha256"] = preflight["review_sha256"]
    first = call("register_analysis_plan", request)
    assert call("register_analysis_plan", request).content[0].text == first.content[0].text
    original = {str(p): p.read_bytes() for p in project.artifacts_dir.rglob("*") if p.is_file()}
    entry = get_session().get_dataset_entry(dataset_id)
    entry.dataframe.loc[0, "age"] += 1
    response = call("register_analysis_plan", request, error=True)
    assert "GENERIC_" in response.content[0].text
    for name, contents in original.items():
        assert Path(name).read_bytes() == contents
