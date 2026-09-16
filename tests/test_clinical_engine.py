from __future__ import annotations

import asyncio
import json

import numpy as np
import pandas as pd
import pytest
from scipy.stats import binomtest

from rde.infrastructure.adapters.clinical_engine import (
    run_clinical_analysis,
    render_clinical_result,
)


def test_risk_estimates_known_table_and_direction():
    frame = pd.DataFrame(
        {"event": [1] * 20 + [0] * 80 + [1] * 10 + [0] * 90, "exposed": [1] * 100 + [0] * 100}
    )
    result = run_clinical_analysis(
        frame, "risk_estimates", {"target": "event", "group_var": "exposed"}
    )
    estimates = result["estimates"]
    assert estimates["risk_ratio"]["estimate"] == pytest.approx(2)
    assert estimates["odds_ratio"]["estimate"] == pytest.approx(2.25)
    assert estimates["risk_difference"]["estimate"] == pytest.approx(0.1)
    assert estimates["risk_ratio"]["ci_lower"] < 2 < estimates["risk_ratio"]["ci_upper"]
    json.dumps(result, allow_nan=False)


def test_risk_zero_cells_never_silently_add_half_an_event():
    frame = pd.DataFrame({"event": [1, 1, 0, 0, 0, 0], "exposed": [1, 1, 1, 0, 0, 0]})
    result = run_clinical_analysis(
        frame, "risk_estimates", {"target": "event", "group_var": "exposed"}
    )
    assert result["table"][1][0] == 0
    assert result["estimates"]["risk_ratio"]["estimate"] is None
    assert "no continuity correction" in " ".join(result["warnings"])
    json.dumps(result, allow_nan=False)


def test_diagnostic_denominators_and_prespecified_threshold():
    frame = pd.DataFrame(
        {"gold": [1, 1, 1, 0, 0, 0, None], "score": [0.9, 0.7, 0.2, 0.8, 0.1, 0.2, 0.9]}
    )
    result = run_clinical_analysis(
        frame,
        "diagnostic_accuracy",
        {"target": "gold", "score_variable": "score", "threshold": 0.5},
    )
    assert result["confusion_counts"] == {"TP": 2, "TN": 2, "FP": 1, "FN": 1}
    assert result["estimates"]["sensitivity"]["denominator"] == 3
    assert result["estimates"]["positive_predictive_value"]["estimate"] == pytest.approx(2 / 3)
    assert result["case_set"]["n_excluded"] == 1
    assert result["threshold"] == 0.5


def test_diagnostic_zero_denominator_is_not_perfect_specificity():
    frame = pd.DataFrame({"gold": [1] * 5, "test": [0, 1, 1, 0, 1]})
    result = run_clinical_analysis(
        frame, "diagnostic_accuracy", {"target": "gold", "score_variable": "test"}
    )
    assert result["estimates"]["specificity"]["estimate"] is None
    assert result["estimates"]["specificity"]["denominator"] == 0


def test_mcnemar_preserves_row_pairs_with_asymmetric_missingness():
    frame = pd.DataFrame(
        {"before": [0, 0, 0, 1, 1, 1, None, 0], "after": [1, 1, 1, 0, 1, 1, 0, None]}
    )
    result = run_clinical_analysis(
        frame, "mcnemar", {"target": "before", "score_variable": "after"}
    )
    assert result["table"] == [[0, 3], [1, 2]]
    assert result["p_value"] == pytest.approx(binomtest(3, 4).pvalue)
    assert result["case_set"]["included_row_positions"] == list(range(6))
    assert result["estimates"]["matched_odds_ratio_after_vs_before"]["estimate"] == 3


def test_mcnemar_no_discordant_pairs():
    frame = pd.DataFrame({"a": [0, 0, 1, 1], "b": [0, 0, 1, 1]})
    result = run_clinical_analysis(frame, "mcnemar", {"target": "a", "score_variable": "b"})
    assert result["p_value"] == 1
    assert result["discordant_pairs"] == 0
    json.dumps(result, allow_nan=False)


def test_bland_altman_constant_bias_and_finite_case_accounting():
    frame = pd.DataFrame({"a": [3, 4, 5, 6, np.inf, "bad"], "b": [1, 2, 3, 4, 5, 6]})
    result = run_clinical_analysis(frame, "bland_altman", {"target": "a", "score_variable": "b"})
    assert result["estimates"]["bias_first_minus_second"]["estimate"] == 2
    assert result["estimates"]["lower_limit_of_agreement"]["estimate"] == 2
    assert result["case_set"]["n_invalid_numeric"] == 2
    assert "included_row_positions" not in render_clinical_result(result)


def test_kappa_perfect_agreement_and_degenerate_rejection():
    frame = pd.DataFrame({"a": ["low", "high", "low", "high"], "b": ["low", "high", "low", "high"]})
    result = run_clinical_analysis(frame, "cohens_kappa", {"target": "a", "score_variable": "b"})
    assert result["estimates"]["cohens_kappa"]["estimate"] == 1
    with pytest.raises(ValueError, match="one category"):
        run_clinical_analysis(
            frame.replace("high", "low"), "cohens_kappa", {"target": "a", "score_variable": "b"}
        )


@pytest.mark.parametrize("method", ["gee", "mixed_effects"])
def test_clustered_continuous_model_recovers_slope(method):
    rng = np.random.default_rng(17)
    subject = np.repeat(np.arange(60), 4)
    x = rng.normal(size=len(subject))
    y = 2 + 0.7 * x + np.repeat(rng.normal(size=60), 4) + rng.normal(scale=0.2, size=len(subject))
    frame = pd.DataFrame({"subject": subject, "x": x, "y": y})
    frame.loc[0, "y"] = np.nan
    result = run_clinical_analysis(
        frame, method, {"target": "y", "subject_variable": "subject", "covariates": ["x"]}
    )
    slope = next(item for item in result["coefficients"] if item["term"] == "x")
    assert slope["estimate"] == pytest.approx(0.7, abs=0.08)
    assert result["case_set"]["n_subjects"] == 60
    assert result["case_set"]["n_analyzed"] == 239
    assert result["converged"]
    json.dumps(result, allow_nan=False)


def test_clustered_model_does_not_treat_rows_as_independent_subjects():
    frame = pd.DataFrame({"subject": range(12), "x": range(12), "y": range(12)})
    with pytest.raises(ValueError, match="repeated observations"):
        run_clinical_analysis(
            frame, "gee", {"target": "y", "subject_variable": "subject", "covariates": ["x"]}
        )


@pytest.mark.parametrize("confidence", [0, 1, -1, float("nan")])
def test_confidence_validation(confidence):
    with pytest.raises(ValueError, match="confidence_level"):
        run_clinical_analysis(pd.DataFrame(), "risk_estimates", {"confidence_level": confidence})


def test_clinical_delegation_is_local_and_returns_errors(monkeypatch):
    from rde.infrastructure.adapters.analysis_delegator import AnalysisDelegator

    delegator = AnalysisDelegator()
    monkeypatch.setattr(
        delegator,
        "_check_automl",
        lambda: pytest.fail("clinical methods must not send data to vendor"),
    )
    result = delegator.run_analysis(
        pd.DataFrame({"a": [1, 2, 3], "b": [0, 1, 0]}),
        "mcnemar",
        {"target": "a", "score_variable": "b"},
    )
    assert "explicitly coded 0/1" in result["result"]["error"]
    assert result["source"].startswith("local-clinical")


def test_clinical_mcp_persists_evidence_and_failed_fit_does_not_count(tmp_path, monkeypatch):
    from test_exploration_branch_loop import _make_phase8_ready_project
    from rde.application.session import get_session
    from rde.application.pipeline import PipelinePhase
    from rde.domain.models.dataset import Dataset
    from rde.interface.mcp.server import create_server
    from rde.interface.mcp.tools._shared.project_context import compute_phase6_progress

    project, store = _make_phase8_ready_project(tmp_path)
    data = pd.DataFrame({"event": [1, 0, 1, 0] * 6, "group": [1] * 12 + [0] * 12})
    dataset = Dataset(row_count=len(data))
    get_session().register_dataset(dataset, data)
    project.dataset_ids = [dataset.id]
    # Use a plan-free coverage threshold for a precise failed-count assertion.
    store.save(
        PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", {"locked": True, "analyses": []}
    )
    from rde.infrastructure.adapters import get_analysis_delegator

    monkeypatch.setattr(get_analysis_delegator(), "_automl_available", False)

    async def run():
        server = create_server()
        failed = await server.call_tool(
            "run_advanced_analysis",
            {
                "dataset_id": dataset.id,
                "analysis_type": "risk_estimates",
                "target_variable": "missing",
                "group_variable": "group",
            },
        )
        assert failed.is_error
        assert compute_phase6_progress(project)["executed_analyses"] == 0
        success = await server.call_tool(
            "run_advanced_analysis",
            {
                "dataset_id": dataset.id,
                "analysis_type": "risk_estimates",
                "target_variable": "event",
                "group_variable": "group",
            },
        )
        assert not success.is_error
        assert "24 / 24" in success.content[0].text

    asyncio.run(run())
    logs = get_session().get_logger(project.id).read_decisions()
    assert logs[0]["parameters"]["execution_status"] == "failed"
    phase_dir = project.artifacts_dir / PipelinePhase.EXECUTE_EXPLORATION.value
    results = [
        json.loads(path.read_text())
        for path in phase_dir.glob("advanced_analysis_risk_estimates*.json")
    ]
    assert any(item["result"].get("case_set", {}).get("n_analyzed") == 24 for item in results)
    from rde.interface.mcp.tools.report_tools import _interpret_advanced_models

    interpretation = _interpret_advanced_models(store)
    assert "No valid estimate or evidence of absence" in interpretation
    assert "24 / 24" in interpretation
    assert "risk_ratio" in interpretation
    assert "did not identify covariates" not in interpretation


def test_report_missing_pvalues_are_not_null_evidence(tmp_path):
    from test_exploration_branch_loop import _make_phase8_ready_project
    from rde.application.pipeline import PipelinePhase
    from rde.interface.mcp.tools.report_tools import _interpret_advanced_models

    _, store = _make_phase8_ready_project(tmp_path)
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "advanced_analysis_external.json",
        {"analysis_type": "external_model", "result": {"n": 12}},
    )
    text = _interpret_advanced_models(store)
    assert "did not provide covariate p-values" in text
    assert "did not identify covariates" not in text
