"""Actual MCP regressions: callers cannot replace a typed clinical estimand.

These check authorization before work, not post-hoc deviation logging. Generic
EDA remains available; a clinical observed-data figure is explicitly descriptive.
"""

import asyncio
import json

import numpy as np
import pandas as pd
import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools.clinical_tools import clinical_records
from test_clinical_imputation import fixture as mi_fixture
from test_clinical_noninferiority import means_fixture
from test_clinical_stratified import fixture as cmh_fixture
from test_clinical_survival import clinical_project


def call(name, arguments, *, denied=False):
    response = asyncio.run(create_server().call_tool(name, arguments))
    assert response.is_error is denied, response.content
    return response.content[0].text


def setup(tmp_path, family):
    if family == "survival":
        project, store, dataset, spec = clinical_project(tmp_path)
        outcome, group, subject = "time", "group", None
    else:
        frame, spec = {
            "imputation": mi_fixture,
            "noninferiority": lambda: means_fixture()[:2],
            "stratified": cmh_fixture,
        }[family]()
        frame["secondary"] = np.arange(len(frame), dtype=float) ** 2
        project, store, dataset, spec = clinical_project(tmp_path, frame=frame, options=spec)
        outcome = spec.outcome
        group = "b" if family == "imputation" else spec.treatment
        subject = spec.subject
    entry = get_session().get_dataset_entry(dataset.id)
    loaded = PandasLoader().load(dataset.metadata)
    entry.dataframe, dataset.variables = loaded[:2]
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    plan.update(
        alpha=0.025 if family == "noninferiority" else 0.05,
        missing_strategy="multiple_imputation" if family == "imputation" else "listwise",
        multiple_comparison_method="none",
        scope_policy="approved-only",
    )
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    return project, store, dataset, spec, entry, outcome, group, subject


TOOLS = [
    "apply_cleaning",
    "analyze_variable",
    "compare_groups",
    "correlation_matrix",
    "generate_table_one",
    "run_advanced_analysis",
    "run_repeated_measures",
]


@pytest.mark.parametrize("family", ["imputation", "noninferiority", "stratified", "survival"])
@pytest.mark.parametrize("tool", TOOLS)
def test_locked_clinical_blocks_legacy_entry_before_computation(
    tmp_path, monkeypatch, family, tool
):
    project, store, dataset, spec, entry, outcome, group, subject = setup(tmp_path, family)
    from rde.infrastructure import adapters
    from rde.infrastructure.adapters import dataframe_lineage
    from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine

    def forbidden(*args, **kwargs):
        pytest.fail("A denied tool must not compute, delegate, or clean")

    monkeypatch.setattr(ScipyStatisticalEngine, "run_test", forbidden)
    monkeypatch.setattr(adapters, "get_analysis_delegator", forbidden)
    monkeypatch.setattr(dataframe_lineage, "apply_recorded_cleaning", forbidden)
    numeric = "x" if family == "survival" else "secondary"
    args = {
        "apply_cleaning": {"approved_indices": [0]},
        "analyze_variable": {"variable_name": outcome},
        "compare_groups": {
            "outcome_variables": [outcome],
            "group_variable": group,
            "alpha": 0.05,
            "missing_strategy": "listwise",
            "multiple_comparison_method": "holm",
        },
        "correlation_matrix": {"variables": [outcome, numeric], "missing_strategy": "listwise"},
        "generate_table_one": {
            "variables": [outcome],
            "group_variable": group,
            "include_p_values": True,
        },
        "run_advanced_analysis": {
            "analysis_type": "multiple_regression",
            "target_variable": outcome,
            "covariates": [numeric],
            "confidence_level": 0.95,
            "missing_strategy": "listwise",
        },
        "run_repeated_measures": {
            "variables": f"{outcome},{numeric}",
            "subject_variable": subject,
            "alpha": 0.05,
            "posthoc_case_strategy": "pairwise",
        },
    }[tool]
    before = entry.dataframe.copy(deep=True)
    source = dataset.metadata.file_path.read_bytes()
    plan_path = store.get_path(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    plan_bytes = plan_path.read_bytes()
    artifacts = store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION)
    text = call(tool, {"dataset_id": dataset.id, **args}, denied=True)
    assert "[CLINICAL_PLAN_SCOPE]" in text and tool in text
    assert "run_clinical_study" in text
    assert not entry.analysis_results and not clinical_records(store)
    pd.testing.assert_frame_equal(entry.dataframe, before)
    assert dataset.metadata.file_path.read_bytes() == source
    assert plan_path.read_bytes() == plan_bytes
    assert store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION) == artifacts


def test_mi_cleaning_proposal_cannot_change_missing_mask_before_formal_execution(tmp_path):
    project, store, dataset, spec, entry, *_ = setup(tmp_path, "imputation")
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    original = json.loads(call("inspect_clinical_study", args))
    before = entry.dataframe.copy(deep=True)
    call("profile_dataset", {"dataset_id": dataset.id})
    call("assess_quality", {"dataset_id": dataset.id})
    proposal = call("suggest_cleaning", {"dataset_id": dataset.id})
    assert "不能在此計畫先單次補值或改動來源" in proposal
    indices = [
        i for i, action in enumerate(entry.cleaning_plan.actions) if action.target_variable == "y"
    ]
    assert indices  # A real median proposal exists, so this is not a missing-plan denial.
    denied = call(
        "apply_cleaning", {"dataset_id": dataset.id, "approved_indices": indices}, denied=True
    )
    assert "[CLINICAL_PLAN_SCOPE]" in denied
    pd.testing.assert_frame_equal(entry.dataframe, before)
    after = json.loads(call("inspect_clinical_study", args))
    for key in ["source_sha256", "dataframe_sha256", "case_ledger", "imputed_cells"]:
        assert after[key] == original[key]
    assert after["imputed_cells"] == 20
    call("run_clinical_study", args)
    result = clinical_records(store)[0]["result"]
    assert result["case_ledger"] == original["case_ledger"]
    assert result["dataframe_sha256"] == original["dataframe_sha256"]
    assert len(entry.dataframe) == result["n"] == 100


@pytest.mark.parametrize("family", ["imputation", "noninferiority"])
def test_clinical_observed_scatter_has_no_tests_trend_cleaning_or_formal_credit(
    tmp_path, monkeypatch, family
):
    project, store, dataset, spec, entry, outcome, *_ = setup(tmp_path, family)
    from rde.infrastructure.visualization import matplotlib_viz

    def forbidden(*args, **kwargs):
        pytest.fail("A descriptive clinical figure must not fit, test, or filter observed values")

    monkeypatch.setattr(np, "polyfit", forbidden)
    monkeypatch.setattr(matplotlib_viz, "apply_numeric_plausibility_filters", forbidden)
    monkeypatch.setattr(matplotlib_viz.MatplotlibVisualizer, "_spearman_lite", forbidden)
    before = entry.dataframe.copy(deep=True)
    plan_path = store.get_path(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    plan_bytes = plan_path.read_bytes()
    text = call(
        "create_visualization",
        {
            "dataset_id": dataset.id,
            "plot_type": "scatter",
            "variables": [outcome, "secondary"],
            "include_tests": False,
            "output_filename": "observed-only.png",
        },
    )
    assert "Descriptive only" in text and "Does not replace the locked clinical result" in text
    record = store.load(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json")[0]
    arguments = record["execution_arguments"]
    assert arguments["descriptive_only"] and not arguments["replaces_clinical_result"]
    assert arguments["source_view"] == "original_observed_data_not_imputed_or_filtered"
    assert arguments["input_rows"] == len(before)
    assert arguments["missing_by_variable"][outcome] == int(before[outcome].isna().sum())
    assert arguments["show_trend"] is arguments["apply_plausibility"] is False
    assert "no imputation" in record["stats_summary"]
    assert not entry.analysis_results and not clinical_records(store)
    pd.testing.assert_frame_equal(entry.dataframe, before)
    assert plan_path.read_bytes() == plan_bytes
    figure = project.output_dir / "figures" / "observed-only.png"
    original_bytes = figure.read_bytes()
    # A descriptive artifact may not overwrite either formal evidence or an earlier figure.
    text = call(
        "create_visualization",
        {
            "dataset_id": dataset.id,
            "plot_type": "scatter",
            "variables": [outcome, "secondary"],
            "include_tests": False,
            "output_filename": "observed-only.png",
        },
        denied=True,
    )
    assert "cannot replace existing clinical evidence" in text
    assert figure.read_bytes() == original_bytes


@pytest.mark.parametrize("plot_type", ["scatter", "boxplot", "line"])
def test_clinical_figure_test_request_denied_before_writing_or_plotting(
    tmp_path, monkeypatch, plot_type
):
    project, store, dataset, spec, entry, outcome, *_ = setup(tmp_path, "noninferiority")
    from rde.infrastructure.visualization.matplotlib_viz import MatplotlibVisualizer

    monkeypatch.setattr(
        MatplotlibVisualizer, "create_plot", lambda *a, **k: pytest.fail("Denied plot rendered")
    )
    output = project.output_dir / "figures"
    before = sorted(output.rglob("*")) if output.exists() else []
    artifacts = store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION)
    text = call(
        "create_visualization",
        {
            "dataset_id": dataset.id,
            "plot_type": plot_type,
            "variables": [outcome, "secondary"],
            "include_tests": True,
            "output_filename": "not-authorized.png",
        },
        denied=True,
    )
    assert "[CLINICAL_PLAN_SCOPE]" in text
    assert (sorted(output.rglob("*")) if output.exists() else []) == before
    assert not (output / "not-authorized.png").exists()
    assert store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION) == artifacts
    assert not entry.analysis_results and not clinical_records(store)


def test_generic_eda_keeps_explicit_policy_workflow(tmp_path):
    from test_analysis_policy import fixture
    from test_exploration_branch_loop import _make_phase8_ready_project

    project, store = _make_phase8_ready_project(tmp_path)
    dataset, frame = fixture()
    get_session().register_dataset(dataset, frame)
    project.dataset_ids = [dataset.id]
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        {
            "alpha": 0.01,
            "missing_strategy": "pairwise",
            "multiple_comparison_method": "bonferroni",
            "analyses": [
                {"type": "compare_groups", "variables": ["a", "b"], "group_variable": "group"}
            ],
        },
    )
    text = call(
        "compare_groups",
        {
            "dataset_id": dataset.id,
            "outcome_variables": ["a", "b"],
            "group_variable": "group",
            "alpha": 0.05,
            "missing_strategy": "listwise",
            "multiple_comparison_method": "holm",
        },
    )
    assert "α=0.05" in text and "校正 p 值 (holm)" in text
    assert len(get_session().get_dataset_entry(dataset.id).analysis_results) == 1


def test_clinical_scope_guard_cannot_be_downgraded_by_extra_legacy_entry_or_stale_lock(tmp_path):
    from rde.interface.mcp.tools._shared.clinical_scope import ensure_legacy_analysis_allowed

    project, store, *_ = setup(tmp_path, "noninferiority")
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    plan["locked"] = False
    plan["analyses"].append({"type": "compare_groups", "variables": ["response"]})
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    allowed, reason = ensure_legacy_analysis_allowed(project, "compare_groups")
    assert not allowed and "[CLINICAL_PLAN_SCOPE]" in reason
    plan["analyses"] = {"malformed": "plan"}
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    assert not ensure_legacy_analysis_allowed(project, "compare_groups")[0]
