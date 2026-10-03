"""Edges that used to lose rows, conceal wide intervals, or obscure actual coding."""

import json

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from rde.infrastructure.adapters.analysis_delegator import AnalysisDelegator
from rde.infrastructure.adapters.advanced_evidence import exp_with_status, finite_evidence
from rde.infrastructure.prediction.splits import digest


def analyze(frame, method, config):
    engine = AnalysisDelegator()
    engine._automl_available = False
    result = engine.run_analysis(frame, method, config)["result"]
    assert "error" not in result, result
    return result


def verify(evidence):
    assert evidence["sha256"] == digest({k: v for k, v in evidence.items() if k != "sha256"})
    assert json.loads(json.dumps(evidence, allow_nan=False)) == evidence


def test_full_propensity_population_and_over_500_pairs_retain_positions_and_weights():
    rng = np.random.default_rng(3701)
    frame = pd.DataFrame(
        {"treatment": [0, 1] * 602, "x": rng.normal(size=1204), "site": ["a", "b", "c", "d"] * 301},
        index=["duplicate_source_index"] * 1204,
    )
    frame.iloc[[2, 5], frame.columns.get_loc("x")] = np.nan
    # Do not condition treatment on a perfectly separating site encoding.
    frame["site"] = rng.choice(["a", "b", "c", "d"], len(frame))
    result = analyze(
        frame, "propensity_score", {"group_var": "treatment", "covariates": ["x", "site"]}
    )
    assert result["case_set"]["n_input"] == 1204
    assert result["case_set"]["n_analyzed"] == 1202
    assert result["case_set"]["n_excluded"] == 2
    rows = result["propensity_scores"]
    assert len(rows) == 1202
    assert len(result["matched_pairs"]) == 601
    assert result["propensity_scores_truncated"] is False
    assert result["matched_pairs_truncated"] is False
    assert {r["row_position"] for r in rows} == set(range(1204)) - {2, 5}
    pairs = result["matched_pairs"]
    assert len({p["control_row_position"] for p in pairs}) == 601
    assert len({p["treated_row_position"] for p in pairs}) == 601
    by_position = {r["row_position"]: r for r in rows}
    for pair in pairs:
        treated = by_position[pair["treated_row_position"]]
        control = by_position[pair["control_row_position"]]
        assert treated["treatment"] == 1 and control["treatment"] == 0
        assert pair["score_distance"] == abs(
            treated["propensity_score"] - control["propensity_score"]
        )
        assert treated["matching_weight"] == control["matching_weight"] == 1
    evidence = result["propensity_model"]["model_evidence"]
    verify(evidence)
    assert [r["row_position"] for r in evidence["rows"]] == [r["row_position"] for r in rows]
    for row in rows:
        score = np.clip(row["propensity_score"], 1e-6, 1 - 1e-6)
        expected = 0.5 / (score if row["treatment"] else 1 - score)
        assert row["iptw_weight"] == pytest.approx(expected)
    assert result["diagnostic_policy"]["outcome_effect_estimated"] is False
    assert result["diagnostic_policy"]["caliper"] is None


def test_logistic_wide_intervals_are_not_silently_clipped_and_coding_is_exact():
    rng = np.random.default_rng(74)
    z = rng.normal(size=500)
    y = rng.binomial(1, 1 / (1 + np.exp(-0.7 * z)))
    frame = pd.DataFrame({"y": np.where(y, " yes ", "no"), "x": z / 100})
    result = analyze(
        frame, "logistic_regression", {"target": "y", "covariates": ["x"], "confidence_level": 0.9}
    )
    reference = sm.Logit(y, sm.add_constant(frame[["x"]])).fit(disp=False)
    expected = np.exp(reference.conf_int(alpha=0.1).loc["x"].to_numpy())
    assert min(expected) > np.exp(30)
    np.testing.assert_allclose(result["odds_ratio_ci"]["x"], expected)
    evidence = result["model_evidence"]
    verify(evidence)
    assert evidence["converged"] is True
    assert evidence["confidence_level"] == 0.9
    assert {r["source_value"]: r["model_value"] for r in evidence["outcome_coding"]["mapping"]} == {
        " yes ": 1,
        "no": 0,
    }
    np.testing.assert_allclose(evidence["covariance"], reference.cov_params())
    np.testing.assert_allclose([r["fitted"] for r in evidence["rows"]], reference.predict())
    assert exp_with_status(1000) == (None, "overflow")
    assert exp_with_status(-1000) == (0, "underflow")


def test_linear_full_design_and_diagnostics_use_original_row_positions():
    rng = np.random.default_rng(81)
    x = rng.normal(size=700)
    frame = pd.DataFrame(
        {
            "y": 3 + 0.8 * x + rng.normal(size=700),
            "x": x,
            "category": pd.Categorical(
                ["mid", "low", "high", "mid"] * 175, categories=["mid", "low", "high"], ordered=True
            ),
        }
    )
    frame.loc[699, "x"] = np.nan
    result = analyze(
        frame,
        "multiple_regression",
        {"target": "y", "covariates": ["x", "category"], "confidence_level": 0.9},
    )
    evidence = result["model_evidence"]
    verify(evidence)
    assert len(evidence["rows"]) == 699
    coding = evidence["predictor_coding"][1]
    assert coding["reference"] == "mid"
    assert coding["levels"] == ["mid", "low", "high"]
    assert coding["encoded_columns"] == [
        {"name": "category_low", "level": "low"},
        {"name": "category_high", "level": "high"},
    ]
    design = np.array([r["design"] for r in evidence["rows"]])
    outcomes = np.array([r["outcome"] for r in evidence["rows"]])
    reference = sm.OLS(outcomes, design).fit()
    np.testing.assert_allclose(evidence["parameters"], reference.params)
    np.testing.assert_allclose(evidence["covariance"], reference.cov_params())
    np.testing.assert_allclose(evidence["coefficient_intervals"], reference.conf_int(alpha=0.1))
    np.testing.assert_allclose([r["fitted"] for r in evidence["rows"]], reference.fittedvalues)
    np.testing.assert_allclose([r["response_residual"] for r in evidence["rows"]], reference.resid)
    assert evidence["df_resid"] == 695


@pytest.mark.parametrize(
    "method", ["multiple_regression", "logistic_regression", "propensity_score"]
)
def test_fast_ridge_retains_its_actual_scale_engine_and_no_inference(method):
    rng = np.random.default_rng(42)
    frame = pd.DataFrame({"x": rng.normal(30, 10, 200), "y": rng.binomial(1, 0.5, 200)})
    result = analyze(
        frame, method, {"target": "y", "group_var": "y", "covariates": ["x"], "backend": "fast"}
    )
    model = result["propensity_model"] if method == "propensity_score" else result
    evidence = model["model_evidence"]
    verify(evidence)
    assert result["engine"] == model["engine"]
    assert evidence["regularized"] is True
    assert evidence["covariance"] is None
    assert evidence["coefficient_intervals"] is None
    assert evidence["converged"] is None
    assert evidence["scaling"]["means"] == pytest.approx([frame.x.mean()])
    design = np.array([r["design"] for r in evidence["rows"]])
    expected = design @ np.array(evidence["parameters"])
    if method != "multiple_regression":
        expected = 1 / (1 + np.exp(-np.clip(expected, -30, 30)))
    np.testing.assert_allclose([r["fitted"] for r in evidence["rows"]], expected)


def test_zero_cell_risk_preserves_all_cases_without_inventing_ratio_intervals():
    frame = pd.DataFrame(
        {"event": [0] * 600 + [0, 1] * 300, "group": [0] * 600 + [1] * 600}, index=["same"] * 1200
    )
    frame.iloc[4, 0] = np.nan
    result = analyze(frame, "risk_estimates", {"target": "event", "group_var": "group"})
    evidence = result["risk_evidence"]
    verify(evidence)
    assert len(evidence["rows"]) == 1199
    assert evidence["table"] == [[300, 300], [0, 599]]
    assert 4 not in {r["row_position"] for r in evidence["rows"]}
    assert result["estimates"]["risk_ratio"]["ci_upper"] is None
    assert result["estimates"]["odds_ratio"]["estimate"] is None


def test_nonfinite_receipt_positions_and_invalid_fast_outcomes_are_explicit():
    receipt = finite_evidence({"data": [np.nan, np.inf, -np.inf, 0.0]})
    verify(receipt)
    assert receipt["data"] == [None, None, None, 0]
    assert [item["path"] for item in receipt["nonfinite_values"]] == [
        ["data", 0],
        ["data", 1],
        ["data", 2],
    ]
    engine = AnalysisDelegator()
    engine._automl_available = False
    frame = pd.DataFrame({"y": [1, 2, "invalid", 3], "x": [4, 3, 1, 2]})
    result = engine.run_analysis(
        frame, "multiple_regression", {"target": "y", "covariates": ["x"], "backend": "fast"}
    )
    assert "not imputed" in result["result"]["error"]


def test_dummy_name_collision_is_rejected_before_fitting():
    engine = AnalysisDelegator()
    engine._automl_available = False
    frame = pd.DataFrame({"y": [0, 1] * 20, "site": ["a", "b", "b", "a"] * 10, "site_b": range(40)})
    result = engine.run_analysis(
        frame, "logistic_regression", {"target": "y", "covariates": ["site", "site_b"]}
    )
    assert "collide" in result["result"]["error"]


def test_report_retains_model_results_without_expanding_full_individual_evidence():
    from rde.interface.mcp.tools.analysis_tools import _format_advanced_analysis_output

    rows = [{"row_position": i, "individual": "source-row-marker"} for i in range(1200)]
    result = {
        "analysis_type": "propensity_score",
        "propensity_scores": rows,
        "propensity_model": {"coefficients": {"x": 0.7}, "model_evidence": {"rows": rows}},
        "case_set": {"included_row_positions": list(range(1200)), "n_analyzed": 1200},
        "matching_summary": {"matched_pairs": 600},
    }
    report = _format_advanced_analysis_output(
        analysis_type="propensity_score",
        source="local-lite",
        analysis_result=result,
        artifact_path=None,
        automl_available=False,
    )
    assert "source-row-marker" not in report
    assert "1200" in report and "0.7" in report and "600" in report
    assert len(report) < 3000
    assert result["propensity_scores"] == rows
