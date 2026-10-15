"""PMM preserves observed cells/populations; pooling has an independent oracle."""

from dataclasses import replace
import hashlib
import json
import math

import numpy as np
import pandas as pd
import pytest

from rde.infrastructure.clinical.imputation import run_imputation
from rde.infrastructure.clinical.imputation_contract import (
    ImputationSpec,
    imputation_preflight,
    prepare_imputation,
)


def fixture(distribution="gaussian"):
    rng = np.random.default_rng(1017)
    n = 100
    x = rng.normal(size=n)
    z = rng.normal(size=n)
    b = rng.binomial(1, 0.5, n)
    y = 0.8 + 0.6 * x + 0.3 * b + rng.normal(size=n)
    if distribution == "binomial":
        y = rng.binomial(1, 1 / (1 + np.exp(-0.3 - 0.3 * x - 0.2 * b)))
        y = np.where(y, "event", "absent").astype(object)
    frame = pd.DataFrame(
        {
            "case": [f"P{i:03d}" for i in range(n)],
            "y": y,
            "x": x,
            "b": np.where(b, "yes", "no").astype(object),
            "z": z,
            "eligible": ["yes"] * n,
        }
    )
    for name, rows in [
        ("y", [0, 7, 23, 31, 45, 52, 64, 73]),
        ("x", [3, 8, 27, 38, 49, 62]),
        ("b", [4, 15, 24, 35, 56, 69]),
    ]:
        frame.loc[rows, name] = None
    roles = []
    for name in ["y", "x", "b", "z"]:
        binary = name == "b" or name == "y" and distribution == "binomial"
        roles.append(
            {
                "column": name,
                "kind": "binary" if binary else "continuous",
                "levels": ["no", "yes"] if name == "b" else ["absent", "event"] if binary else [],
                "unit": "source indicator" if binary else "synthetic units",
                "impute": name != "z",
                "predictors": [v for v in ["y", "x", "b", "z"] if v != name] if name != "z" else [],
            }
        )
    spec = ImputationSpec(
        subject="case",
        outcome="y",
        outcome_unit="synthetic units",
        distribution=distribution,
        predictors=["x", "b"],
        columns=roles,
        study_design="observational_cohort",
        context="Synthetic engineering fixture only",
        population_definition="All generated independent cases",
        missingness_basis="Synthetic missingness independent of generated outcomes; MAR working assumption",
        imputation_scope="Only generated item nonresponse, excluding structural missingness",
        independent_rows=True,
        structural_missingness_absent=True,
        nonimputable_missing="exclude",
        m=5,
        burn_in=5,
        between=1,
        k_pmm=5,
        seed=20261015,
    )
    return frame, spec


def test_legacy_runtime_without_local_rng_fails_explicitly_and_preserves_receipt(
    tmp_path, monkeypatch
):
    from rde.infrastructure.clinical import imputation

    class LegacyMICEData:
        def __init__(self, data, perturbation_method="gaussian", k_pmm=20):
            pytest.fail("Unsupported MICE runtime must not execute")

    monkeypatch.setattr(imputation, "MICEData", LegacyMICEData)
    frame, spec = fixture()
    output = tmp_path / "legacy-runtime"
    state = np.random.get_state()
    with pytest.raises(ValueError, match="explicit local rng"):
        run_imputation(frame, spec, output)
    assert not (output / "result.json").exists()
    failure = json.loads((output / "failure.json").read_text())
    assert "global-RNG fallback is forbidden" in failure["reason"]
    after = np.random.get_state()
    assert np.array_equal(state[1], after[1]) and state[2:] == after[2:]


def test_preflight_keeps_incomplete_cases_and_records_explicit_exclusions():
    frame, spec = fixture()
    frame.loc[8, "z"] = np.nan
    frame.loc[9, "eligible"] = "no"
    spec = replace(spec, cohort_filter={"column": "eligible", "values": ["yes"]})
    before = frame.copy(deep=True)
    prepared, ledger, fingerprint = prepare_imputation(frame, spec)
    preflight = imputation_preflight(frame, spec)
    assert len(prepared) == preflight["n"] == 98
    assert ledger["missing_excluded_data_rows"] == [9]
    assert ledger["filter_excluded_data_rows"] == [10]
    assert 1 in ledger["included_data_rows"] and 1 in ledger["imputed_data_rows"]
    assert preflight["dataframe_sha256"] == fingerprint
    pd.testing.assert_frame_equal(frame, before)
    changed = frame.copy()
    changed.loc[20, "x"] += 0.1
    assert prepare_imputation(changed, spec)[2] != fingerprint


@pytest.mark.parametrize(
    "which",
    [
        "missing_id",
        "duplicate_id",
        "unknown_binary",
        "invalid_numeric",
        "all_missing",
        "empty_column",
    ],
)
def test_invalid_source_cannot_hide_behind_another_missing_role(which):
    frame, spec = fixture()
    frame.loc[0, "z"] = np.nan
    match = ""
    if which == "missing_id":
        frame.loc[0, "case"] = None
        match = "identity"
    elif which == "duplicate_id":
        frame.loc[0, "case"] = frame.loc[1, "case"]
        match = "identity"
    elif which == "unknown_binary":
        frame.loc[0, "b"] = "unknown"
        match = "undeclared binary"
    elif which == "invalid_numeric":
        frame["x"] = frame.x.astype(object)
        frame.loc[0, "x"] = "bad value"
        match = "non-numeric"
    elif which == "all_missing":
        frame.loc[0, ["y", "x", "b", "z"]] = None
        match = "entirely missing"
    else:
        frame["x"] = np.nan
        match = "observed donors"
    with pytest.raises(ValueError, match=match):
        prepare_imputation(frame, spec)


@pytest.mark.parametrize(
    "mutation",
    [
        {"m": True},
        {"between": 0},
        {"k_pmm": 99},
        {"structural_missingness_absent": False},
        {"distribution": "ordinal"},
        {"sensitivity": []},
        {"method": "NARFCS"},
    ],
)
def test_unsupported_settings_rejected(mutation):
    _, spec = fixture()
    with pytest.raises(ValueError):
        ImputationSpec.parse({**spec.to_dict(), **mutation})


def test_complete_data_does_not_create_artificial_imputation_study(tmp_path):
    frame, spec = fixture()
    frame = frame.dropna().copy()
    with pytest.raises(ValueError, match="No eligible missing cells"):
        run_imputation(frame, spec, tmp_path / "unused")
    assert not (tmp_path / "unused").exists()


def pooling_oracle(models):
    """Scalar loops, no statsmodels, production helper or NumPy covariance."""
    m = len(models)
    p = len(models[0]["coefficients"])
    q = [math.fsum(r["coefficients"][j] for r in models) / m for j in range(p)]
    within, between, total = [], [], []
    for j in range(p):
        urow, brow, trow = [], [], []
        for k in range(p):
            u = math.fsum(r["covariance"][j][k] for r in models) / m
            b = math.fsum(
                (r["coefficients"][j] - q[j]) * (r["coefficients"][k] - q[k]) for r in models
            ) / (m - 1)
            urow.append(u)
            brow.append(b)
            trow.append(u + (1 + 1 / m) * b)
        within.append(urow)
        between.append(brow)
        total.append(trow)
    return q, within, between, total


@pytest.mark.parametrize("distribution", ["gaussian", "binomial"])
def test_actual_pmm_models_pooling_and_immutable_artifacts(tmp_path, distribution):
    frame, spec = fixture(distribution)
    before = frame.copy(deep=True)
    root = tmp_path / distribution
    result = run_imputation(frame, spec, root)
    assert result["status"] == "completed"
    assert result["n"] == 100 and result["m"] == 5
    assert result["observed_cells_unchanged"] is True
    assert result["complete_case_comparison"]["status"] == "completed"
    assert result["complete_case_comparison"]["n"] < result["n"]
    assert len(result["completed_datasets"]) == 5
    q, within, between, total = pooling_oracle(result["fit_receipts"])
    np.testing.assert_allclose(
        [c["coefficient"] for c in result["coefficients"]], q, rtol=2e-13, atol=1e-14
    )
    np.testing.assert_allclose(result["within_covariance"], within, rtol=2e-13, atol=1e-14)
    np.testing.assert_allclose(result["between_covariance"], between, rtol=2e-13, atol=1e-14)
    np.testing.assert_allclose(result["covariance"], total, rtol=2e-13, atol=1e-14)
    for j, c in enumerate(result["coefficients"]):
        assert c["standard_error"] == pytest.approx(math.sqrt(total[j][j]), rel=2e-13)
        # Phi(z) via erfc is independent of the production scipy.stats.norm call.
        assert c["p_value"] == pytest.approx(
            math.erfc(abs(q[j]) / math.sqrt(2 * total[j][j])), rel=2e-12, abs=1e-15
        )
    normalized, _, _ = prepare_imputation(frame, spec)
    for item in result["artifact_files"]:
        path = root / item["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    for item in result["completed_datasets"]:
        complete = pd.read_csv(root / item["path"], float_precision="round_trip").set_index(
            "__rde_source_data_row__"
        )
        complete.index -= 1
        for column in spec.columns:
            name = column["column"]
            original = normalized[name]
            observed_rows = original.index[original.notna()]
            assert np.array_equal(complete.loc[observed_rows, name], original.loc[observed_rows])
            missing_rows = original.index[original.isna()]
            assert np.isin(complete.loc[missing_rows, name], original.dropna()).all()
        assert set(complete.b) <= {0, 1}
    pd.testing.assert_frame_equal(frame, before)
    manifest_bytes = (root / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_imputation(frame, spec, root)
    assert (root / "manifest.json").read_bytes() == manifest_bytes
    assert "Barnard-Rubin" in result["model"]["inference"]
    assert "not_certified" in result["diagnostics"]["convergence"]


def test_source_permutation_is_reproducible_by_identity_and_preserves_global_rng(tmp_path):
    frame, spec = fixture()
    state = np.random.get_state()
    first = run_imputation(frame, spec, tmp_path / "first")
    second_frame = frame.sample(frac=1, random_state=82).reset_index(drop=True)
    second = run_imputation(second_frame, spec, tmp_path / "second")
    after = np.random.get_state()
    assert state[0] == after[0] and np.array_equal(state[1], after[1]) and state[2:] == after[2:]
    assert first["dataframe_sha256"] != second["dataframe_sha256"]
    assert first["coefficients"] == second["coefficients"]
    assert first["fit_receipts"] == second["fit_receipts"]
    for number in range(1, spec.m + 1):
        left = pd.read_csv(
            tmp_path / "first" / f"completed-{number:03d}.csv", float_precision="round_trip"
        )
        right = pd.read_csv(
            tmp_path / "second" / f"completed-{number:03d}.csv", float_precision="round_trip"
        )
        left["case"] = frame.iloc[left["__rde_source_data_row__"].to_numpy() - 1].case.to_numpy()
        right["case"] = second_frame.iloc[
            right["__rde_source_data_row__"].to_numpy() - 1
        ].case.to_numpy()
        pd.testing.assert_frame_equal(
            left.drop(columns="__rde_source_data_row__").set_index("case").sort_index(),
            right.drop(columns="__rde_source_data_row__").set_index("case").sort_index(),
        )


def test_rank_failure_preserves_failure_receipt_without_false_result(tmp_path):
    frame, spec = fixture()
    frame["z"] = frame["x"].fillna(0) * 2
    frame["x"] = frame["x"].fillna(0)
    spec = replace(spec, predictors=["x", "z"])
    with pytest.raises(ValueError, match="rank-deficient"):
        run_imputation(frame, spec, tmp_path / "failure")
    failure = json.loads((tmp_path / "failure" / "failure.json").read_text())
    assert failure["status"] == "failed"
    assert not (tmp_path / "failure" / "result.json").exists()


def test_literal_source_names_cannot_become_formula_code(tmp_path):
    frame, spec = fixture()
    dangerous = "x + __import__('os').system('do not execute')"
    frame = frame.rename(columns={"x": dangerous})
    source = spec.to_dict()
    source["predictors"] = [dangerous, "b"]
    for column in source["columns"]:
        if column["column"] == "x":
            column["column"] = dangerous
        column["predictors"] = [dangerous if p == "x" else p for p in column["predictors"]]
    result = run_imputation(frame, ImputationSpec.parse(source), tmp_path / "literal")
    assert result["coefficients"][1]["column"] == dangerous


def test_separation_in_binary_conditional_model_is_not_repaired_silently(tmp_path):
    frame, spec = fixture()
    frame["x"] = np.linspace(-2, 2, len(frame))
    frame["b"] = np.where(frame.x > 0, "yes", "no").astype(object)
    frame.loc[[4, 14, 63, 74], "b"] = None
    with pytest.raises(ValueError, match="separation"):
        run_imputation(frame, spec, tmp_path / "separation")
    assert (tmp_path / "separation" / "failure.json").is_file()
    assert not (tmp_path / "separation" / "result.json").exists()


def test_one_failed_analysis_cannot_silently_reduce_m(tmp_path, monkeypatch):
    from rde.infrastructure.clinical import imputation

    frame, spec = fixture()
    real_fit = imputation._fit
    calls = 0

    def fail_third(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("Synthetic third-model failure")
        return real_fit(*args, **kwargs)

    monkeypatch.setattr(imputation, "_fit", fail_third)
    with pytest.raises(ValueError, match="third-model failure"):
        run_imputation(frame, spec, tmp_path / "partial")
    assert len(list((tmp_path / "partial").glob("completed-*.csv"))) == 2
    assert (tmp_path / "partial" / "failure.json").is_file()
    assert not (tmp_path / "partial" / "result.json").exists()
    assert not (tmp_path / "partial" / "manifest.json").exists()
