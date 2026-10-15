"""Auditable PMM through statsmodels; source datasets are never overwritten.

All stochastic imputation and Rubin covariance pooling use the installed mature
statsmodels implementation. This finite v1 deliberately reports asymptotic
normal Wald inference, not Barnard--Rubin degrees of freedom or MNAR sensitivity.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from scipy.stats import norm
import statsmodels.api as sm
from statsmodels.imputation.mice import MICE, MICEData

from .imputation_contract import ImputationSpec, prepare_imputation
from .regression import _positive_covariance, _reject_binary_separation
from .survival import digest


def _check_design(model):
    x = np.asarray(model.exog, dtype=float)
    if (
        not np.isfinite(x).all()
        or np.linalg.matrix_rank(x) != x.shape[1]
        or len(x) <= x.shape[1] + 2
    ):
        raise ValueError(
            "A conditional/analysis design is rank-deficient or has insufficient residual cases."
        )


def _check_fit(fitted):
    if not np.isfinite(np.asarray(fitted.params)).all() or not bool(
        getattr(fitted, "converged", True)
    ):
        raise ValueError("A conditional/analysis model did not converge to finite estimates.")
    _positive_covariance(np.asarray(fitted.cov_params()), "Conditional/analysis covariance")
    return fitted


class _CheckedOLS(sm.OLS):
    def fit(self, *args, **kwargs):
        _check_design(self)
        return _check_fit(super().fit(*args, **kwargs))


class _CheckedBinomial(sm.GLM):
    def fit(self, *args, **kwargs):
        _check_design(self)
        _reject_binary_separation(self.exog, self.endog)
        return _check_fit(super().fit(*args, **kwargs))


def _write_json(path: Path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, allow_nan=False, indent=2)
        output.write("\n")


def _file(path, root):
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def _design(frame, outcome, predictors):
    return frame[outcome].astype(float), sm.add_constant(
        frame[predictors].astype(float), has_constant="add"
    )


def _fit(frame, outcome, predictors, distribution):
    y, x = _design(frame, outcome, predictors)
    if distribution == "gaussian":
        return _CheckedOLS(y, x).fit()
    return _CheckedBinomial(y, x, family=sm.families.Binomial()).fit(maxiter=100)


def _coefficients(beta, covariance, terms, distribution, confidence):
    beta = np.asarray(beta, dtype=float)
    covariance = np.asarray(covariance, dtype=float)
    _positive_covariance(covariance, "Pooled/complete-case covariance")
    se = np.sqrt(np.diag(covariance))
    critical = norm.ppf((1 + confidence) / 2)
    output = []
    for i, term in enumerate(terms):
        lower, upper = beta[i] - critical * se[i], beta[i] + critical * se[i]
        values = np.array([beta[i], lower, upper])
        if distribution == "binomial":
            with np.errstate(over="ignore", under="ignore"):
                values = np.exp(values)
            if not np.isfinite(values).all() or (values <= 0).any():
                raise ValueError(
                    "Exponentiated pooled/complete-case odds are not finite and positive."
                )
        output.append(
            {
                **term,
                "coefficient": float(beta[i]),
                "standard_error": float(se[i]),
                "coefficient_lower": float(lower),
                "coefficient_upper": float(upper),
                "estimate": float(values[0]),
                "lower": float(values[1]),
                "upper": float(values[2]),
                "effect_scale": ("reference odds" if i == 0 else "conditional odds ratio")
                if distribution == "binomial"
                else (
                    "reference mean"
                    if i == 0
                    else "mean difference per one source unit / binary 1 versus 0"
                ),
                "p_value": float(2 * norm.sf(abs(beta[i] / se[i]))),
                "interval_scope": "pointwise asymptotic normal Wald; no multiplicity adjustment",
            }
        )
    return output


def _diagnostic(frame, original, column, iteration, phase):
    missing = original[column].isna()
    values = frame.loc[missing, column].to_numpy(dtype=float)
    return {
        "cycle": iteration,
        "phase": phase,
        "column": column,
        "n_imputed": len(values),
        "imputed_mean": float(values.mean()),
        "imputed_sd": float(values.std(ddof=1)) if len(values) > 1 else None,
        "imputed_min": float(values.min()),
        "imputed_max": float(values.max()),
    }


def _validate_completed(completed, original, spec, names):
    if completed.shape != original.shape or completed.columns.tolist() != original.columns.tolist():
        raise ValueError("The imputation engine changed the source population or column order.")
    values = completed.to_numpy(dtype=float)
    observed = original.to_numpy(dtype=float)
    mask = np.isfinite(observed)
    if not np.isfinite(values).all() or not np.array_equal(values[mask], observed[mask]):
        raise ValueError(
            "Completed data changed an observed source cell or retained invalid missing values."
        )
    for column in spec.columns:
        name = names[column["column"]]
        miss = original[name].isna()
        donors = original.loc[~miss, name].to_numpy(dtype=float)
        if (
            miss.any()
            and not np.isin(values[miss.to_numpy(), completed.columns.get_loc(name)], donors).all()
        ):
            raise ValueError("A PMM imputed value is not an observed donor value.")
        if column["kind"] == "binary" and not completed[name].isin([0.0, 1.0]).all():
            raise ValueError("Binary PMM introduced an invalid outcome/category code.")


def run_imputation(df, spec: ImputationSpec, output_dir: Path):
    """Run the approved spec into a NEW directory; preserve failures for audit.

    The orchestrator pins original file bytes/sheet and approval. This numerical
    kernel separately pins typed source rows, spec, versions and derived files.
    It neither approves a plan nor registers completed data as new raw sources.
    """
    frame, ledger, frame_hash = prepare_imputation(df, spec)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _run(frame, ledger, frame_hash, spec, root)
        if caught:
            notes = [str(item.message) for item in caught]
            _write_json(root / "warnings.json", notes)
            raise ValueError(
                "The PMM/analysis engine emitted warnings; no completed study is accepted. Review the preserved warnings."
            )
        inventory = [_file(path, root) for path in sorted(root.rglob("*")) if path.is_file()]
        manifest = {
            "schema": "rde-imputation-artifact-manifest-v1",
            "spec_sha256": digest(spec.to_dict()),
            "dataframe_sha256": frame_hash,
            "files": inventory,
            "observed_cells_unchanged": True,
            "source_files_modified": False,
        }
        _write_json(root / "manifest.json", manifest)
        result["artifact_manifest"] = _file(root / "manifest.json", root)
        result["artifact_files"] = [*inventory, result["artifact_manifest"]]
        result["receipt_sha256"] = digest(result)
        _write_json(root / "result.json", result)
        return result
    except BaseException as error:
        _write_json(
            root / "failure.json",
            {
                "status": "failed",
                "spec_sha256": digest(spec.to_dict()),
                "dataframe_sha256": frame_hash,
                "error_type": type(error).__name__,
                "reason": str(error),
                "partial_files_are_completed_study": False,
            },
        )
        raise


def _run(frame, ledger, frame_hash, spec, root):
    if "rng" not in inspect.signature(MICEData).parameters:
        raise ValueError(
            "Imputation requires statsmodels MICEData with an explicit local rng (validated with statsmodels 0.15.0). Upgrade the supported Python runtime; global-RNG fallback is forbidden."
        )
    names = {column["column"]: f"v{i:03d}" for i, column in enumerate(spec.columns)}
    reverse = {safe: source for source, safe in names.items()}
    original = frame.rename(columns=names).reset_index(drop=True)
    versions = {
        name: importlib.metadata.version(name)
        for name in ["numpy", "pandas", "scipy", "statsmodels"]
    }
    terms = [dict(term="intercept", column=None, role="intercept")]
    for column in spec.predictors:
        role = next(c for c in spec.columns if c["column"] == column)
        terms.append(
            {
                "term": names[column],
                "column": column,
                "role": "predictor",
                "unit": role["unit"],
                "levels": role["levels"],
                "increment": 1,
            }
        )
    recipe = {
        "schema": "rde-imputation-recipe-v1",
        "spec": spec.to_dict(),
        "versions": versions,
        "dataframe_sha256": frame_hash,
        "case_ledger": ledger,
        "safe_columns": names,
        "terms": terms,
        "conditional_models": {
            c["column"]: "OLS" if c["kind"] == "continuous" else "GLM Binomial (logit)"
            for c in spec.columns
            if c["impute"]
        },
        "imputation": "Predictive mean matching from observed donors for ALL imputed roles, including binary; not Bernoulli draws or NARFCS",
        "parameter_perturbation": "Gaussian sampling distribution approximation from conditional model covariance",
        "k_pmm_scope": "one global value shared by all columns",
    }
    _write_json(root / "recipe.json", recipe)
    engine = MICEData(
        original,
        perturbation_method="gaussian",
        k_pmm=spec.k_pmm,
        rng=np.random.default_rng(spec.seed),
    )
    if len(engine.data) != len(original):
        raise ValueError(
            "MICEData changed the eligible population; no silent row exclusion is permitted."
        )
    order = sorted(
        [
            names[c["column"]]
            for c in spec.columns
            if c["impute"] and original[names[c["column"]]].isna().any()
        ],
        key=lambda safe: (int(original[safe].isna().sum()), list(names.values()).index(safe)),
    )
    for column in spec.columns:
        safe = names[column["column"]]
        if safe not in order:
            continue
        kwargs = {} if column["kind"] == "continuous" else {"family": sm.families.Binomial()}
        engine.set_imputer(
            safe,
            formula=" + ".join(names[c] for c in column["predictors"]),
            model_class=_CheckedOLS if column["kind"] == "continuous" else _CheckedBinomial,
            init_kwds=kwargs,
            fit_kwds={} if column["kind"] == "continuous" else {"maxiter": 100},
            k_pmm=spec.k_pmm,
            perturbation_method="gaussian",
            regularized=False,
        )
    traces = []
    fits = []
    fit_receipts = []
    completed_files = []
    completed_masks = original.isna()
    observed_sha = digest(
        {
            "rows": ledger["sampling_data_rows"],
            "columns": list(names),
            "values": [
                [None if pd.isna(v) else float(v) for v in row] for row in original.to_numpy()
            ],
        }
    )
    for cycle in range(1, spec.burn_in + spec.m * spec.between + 1):
        for safe in order:
            engine.update(safe)
        completed = engine.data.copy(deep=True)
        _validate_completed(completed, original, spec, names)
        phase = "burn_in" if cycle <= spec.burn_in else "sampling"
        for safe in order:
            trace = _diagnostic(completed, original, safe, cycle, phase)
            trace["column"] = reverse[safe]
            traces.append(trace)
        if cycle <= spec.burn_in or (cycle - spec.burn_in) % spec.between:
            continue
        fitted = _fit(
            completed, names[spec.outcome], [names[p] for p in spec.predictors], spec.distribution
        )
        if len(fitted.params) != len(terms):
            raise ValueError("Complete-data analysis changed the prespecified parameter set.")
        fits.append(fitted)
        index = len(fits)
        saved = completed.rename(columns=reverse).copy()
        saved.insert(0, "__rde_source_data_row__", ledger["sampling_data_rows"])
        saved = saved.sort_values("__rde_source_data_row__", kind="stable")
        path = root / f"completed-{index:03d}.csv"
        # 17 significant digits preserve binary64 observed values on round-trip.
        with path.open("x", encoding="utf-8", newline="") as output:
            saved.to_csv(output, index=False, float_format="%.17g", lineterminator="\n")
        completed_files.append(_file(path, root))
        fit_receipts.append(
            {
                "imputation": index,
                "cycle": cycle,
                "n": int(fitted.nobs),
                "terms": terms,
                "coefficients": np.asarray(fitted.params).tolist(),
                "covariance": np.asarray(fitted.cov_params()).tolist(),
                "df_residual": float(fitted.df_resid),
                "converged": bool(getattr(fitted, "converged", True)),
                "observed_cells_unchanged": True,
            }
        )
    if len(fits) != spec.m:
        raise ValueError(
            "Every prespecified imputation must yield one valid model; m cannot shrink."
        )
    combiner = MICE(
        f"{names[spec.outcome]} ~ " + " + ".join(names[p] for p in spec.predictors),
        sm.OLS if spec.distribution == "gaussian" else sm.GLM,
        engine,
    )
    combiner.results_list = fits
    combiner.endog_names = names[spec.outcome]
    combiner.exog_names = fits[-1].model.exog_names
    pooled = combiner.combine()
    beta = np.asarray(pooled.params)
    covariance = np.asarray(pooled.cov_params())
    within = np.mean([np.asarray(f.cov_params()) for f in fits], axis=0)
    between = np.cov(np.asarray([np.asarray(f.params) for f in fits]), rowvar=False, ddof=1)
    coefficients = _coefficients(beta, covariance, terms, spec.distribution, spec.confidence_level)
    for i, coefficient in enumerate(coefficients):
        coefficient.update(
            {
                "within_variance": float(within[i, i]),
                "between_variance": float(between[i, i]),
                "total_variance": float(covariance[i, i]),
                "missing_information_ratio": float(pooled.frac_miss_info[i]),
                "missing_information_scope": "(1 + 1/m) B / T; no finite-df FMI adjustment",
            }
        )
    complete = original.dropna(subset=[names[spec.outcome], *[names[p] for p in spec.predictors]])
    complete_case = {
        "status": "not_estimated",
        "n": len(complete),
        "data_rows": ledger["analysis_complete_data_rows"],
    }
    try:
        with warnings.catch_warnings(record=True) as cc_warnings:
            warnings.simplefilter("always")
            comparison = _fit(
                complete,
                names[spec.outcome],
                [names[p] for p in spec.predictors],
                spec.distribution,
            )
        if cc_warnings:
            raise ValueError(
                "Complete-case model produced warnings: "
                + "; ".join(str(w.message) for w in cc_warnings)
            )
        complete_case.update(
            {
                "status": "completed",
                "coefficients": _coefficients(
                    comparison.params,
                    comparison.cov_params(),
                    terms,
                    spec.distribution,
                    spec.confidence_level,
                ),
                "covariance": np.asarray(comparison.cov_params()).tolist(),
                "interpretation": "Descriptive comparison of missing-data handling and changed population; not proof of MAR or MNAR sensitivity.",
            }
        )
    except (ValueError, np.linalg.LinAlgError) as error:
        complete_case["reason"] = str(error)
    distributions = []
    for source, safe in names.items():
        observed = original.loc[~completed_masks[safe], safe]
        distributions.append(
            {
                "column": source,
                "n_observed": len(observed),
                "n_imputed_per_dataset": int(completed_masks[safe].sum()),
                "observed_mean": float(observed.mean()),
                "observed_sd": float(observed.std(ddof=1)),
                "observed_min": float(observed.min()),
                "observed_max": float(observed.max()),
            }
        )
    _write_json(root / "models.json", fit_receipts)
    _write_json(root / "chain-diagnostics.json", traces)
    _write_json(root / "complete-case-comparison.json", complete_case)
    return {
        "schema": "rde-imputation-study-v1",
        "status": "completed",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": frame_hash,
        "n": len(frame),
        "m": spec.m,
        "case_ledger": ledger,
        "terms": terms,
        "model": {
            "imputation": "statsmodels MICEData predictive mean matching",
            "conditional_continuous": "OLS with Gaussian parameter perturbation, then observed-donor PMM",
            "conditional_binary": "GLM Binomial(logit) with Gaussian parameter perturbation, then observed 0/1 donor PMM",
            "analysis": "Gaussian OLS"
            if spec.distribution == "gaussian"
            else "binary logistic GLM",
            "complete_data_covariance": "model-based; not HC3/robust",
            "pooling": "statsmodels MICE.combine Rubin covariance: U_bar + (1 + 1/m) B",
            "inference": "pointwise asymptotic normal Wald; no Barnard-Rubin degrees of freedom",
            "multiplicity": "none; fixed coefficients, no outcome-driven selection",
        },
        "coefficients": coefficients,
        "covariance": covariance.tolist(),
        "within_covariance": within.tolist(),
        "between_covariance": between.tolist(),
        "fit_receipts": fit_receipts,
        "completed_datasets": completed_files,
        "observed_cells_sha256": observed_sha,
        "observed_cells_unchanged": True,
        "complete_case_comparison": complete_case,
        "diagnostics": {
            "chain_traces": traces,
            "cycle_order": [reverse[safe] for safe in order],
            "cycles": spec.burn_in + spec.m * spec.between,
            "trace_file": "chain-diagnostics.json",
            "observed_distributions": distributions,
            "convergence": "not_certified; chain traces and distribution review are required",
        },
        "versions": versions,
        "limitations": [
            "Single-level independent subjects; continuous/binary additive models only. No survival, multilevel, ordinal, nominal, interactions or splines.",
            "MAR is a research assumption, not established by this computation. No NARFCS, MNAR delta, reference-based or structural-missingness imputation.",
            "Binary imputation uses observed-donor PMM, not independent Bernoulli draws or R mice::logreg.",
            "Gaussian parameter perturbation and normal Wald pooling are asymptotic approximations; no small-sample coverage guarantee or Barnard-Rubin correction.",
            "The complete-case comparison changes the analyzed population; differences do not diagnose MAR/MNAR or verify causal assumptions.",
            "m completed datasets contain the same subjects, not m times as many independent patients. Numerical completion does not certify chain convergence.",
        ],
    }
