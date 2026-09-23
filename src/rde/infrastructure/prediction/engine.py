"""Prespecified, bounded model comparison with a single untouched outer holdout."""

from __future__ import annotations

import hashlib
import platform
import time
import warnings
from pathlib import Path
from importlib.metadata import version

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

from .contract import PredictionSpec
from .metrics import bootstrap_intervals, calibration_bins, score_metrics
from .splits import digest, outer_split, prepare_population, training_folds


class PredictionFailure(ValueError):
    def __init__(self, message: str, receipt: dict):
        super().__init__(message)
        self.receipt = {**receipt, "status": "failed", "error": message}


def pipeline(spec: PredictionSpec, candidate: str) -> Pipeline:
    categorical = spec.categorical_predictors or []
    numeric = [p for p in spec.predictors if p not in categorical]
    transforms = []
    if numeric:
        transforms.append(
            (
                "numeric",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            )
        )
    if categorical:
        transforms.append(
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=True)),
                    ]
                ),
                categorical,
            )
        )
    if candidate == "linear":
        estimator = (
            LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=spec.seed)
            if spec.task == "binary"
            else Ridge(alpha=1.0, solver="lsqr", tol=1e-6)
        )
    else:
        cls = RandomForestClassifier if spec.task == "binary" else RandomForestRegressor
        estimator = cls(
            n_estimators=64,
            max_depth=8,
            min_samples_leaf=5,
            max_features=1.0,
            random_state=spec.seed,
            n_jobs=1,
        )
    return Pipeline(
        [("preprocess", ColumnTransformer(transforms, sparse_threshold=1.0)), ("model", estimator)]
    )


def fit_model(population: dict, rows: list[int], spec: PredictionSpec, candidate: str):
    x, y = population["x"].iloc[rows], population["y"].iloc[rows]
    empty = x.columns[x.isna().all()].tolist()
    if empty:
        raise ValueError(f"Training-only feature has no observed values: {empty}.")
    cardinalities = {p: int(x[p].nunique()) for p in (spec.categorical_predictors or [])}
    if (
        any(count > 200 for count in cardinalities.values())
        or sum(cardinalities.values()) + 2 * len(spec.predictors) > 5000
    ):
        raise ValueError(
            "Training categories exceed the 200/category-column or 5,000 encoded-feature budget; review identifier features."
        )
    if spec.task == "binary" and y.nunique() != 2:
        raise ValueError("Both outcome classes are required in each training partition.")
    model = pipeline(spec, candidate)
    with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=1):
        warnings.simplefilter("always")
        model.fit(x, y)
    if any(issubclass(w.category, ConvergenceWarning) for w in caught):
        raise ValueError(
            "Model failed its fixed convergence budget; no validation score is accepted."
        )
    return model, [str(w.message) for w in caught]


def predict(model, x, task: str):
    with threadpool_limits(limits=1):
        if task == "binary":
            index = list(model.named_steps["model"].classes_).index(1.0)
            return model.predict_proba(x)[:, index]
        return model.predict(x)


def fit_record(model, rows, spec: PredictionSpec, messages: list[str]) -> dict:
    preprocess, estimator = model.named_steps["preprocess"], model.named_steps["model"]
    encoded = preprocess.get_feature_names_out().tolist()
    transform = {}
    if "numeric" in preprocess.named_transformers_:
        part = preprocess.named_transformers_["numeric"]
        transform["numeric"] = {
            "columns": [p for p in spec.predictors if p not in (spec.categorical_predictors or [])],
            "median": part.named_steps["imputer"].statistics_.tolist(),
            "missing_indicator_indices": part.named_steps["imputer"].indicator_.features_.tolist(),
            "scale_mean": part.named_steps["scale"].mean_.tolist(),
            "scale_sd": part.named_steps["scale"].scale_.tolist(),
        }
    if "categorical" in preprocess.named_transformers_:
        part = preprocess.named_transformers_["categorical"]
        transform["categorical"] = {
            "columns": spec.categorical_predictors,
            "mode": part.named_steps["imputer"].statistics_.tolist(),
            "categories": [values.tolist() for values in part.named_steps["encode"].categories_],
            "unseen_policy": "all-zero encoding; no vocabulary learned from validation",
        }
    parameters = {
        key: value
        for key, value in estimator.get_params().items()
        if isinstance(value, (str, int, float, bool, type(None)))
    }
    record = {
        "train_positions_sha256": digest(rows),
        "n_train": len(rows),
        "preprocessing": transform,
        "encoded_feature_names": encoded,
        "estimator": type(estimator).__name__,
        "parameters": parameters,
        "warnings": messages,
    }
    if hasattr(estimator, "coef_"):
        record.update(
            coefficients=np.asarray(estimator.coef_).tolist(),
            intercept=np.asarray(estimator.intercept_).tolist(),
            coefficient_scale="training-standardized numeric features / one-hot categories; penalized, no inferential p values",
        )
    else:
        trees = hashlib.sha256()
        for tree in estimator.estimators_:
            state = tree.tree_.__getstate__()
            trees.update(state["nodes"].tobytes())
            trees.update(state["values"].tobytes())
        record.update(
            feature_importance=estimator.feature_importances_.tolist(),
            tree_state_sha256=trees.hexdigest(),
            importance_caveat="Training impurity importance; association or causation cannot be inferred.",
        )
    record["fit_sha256"] = digest(record)
    return record


def prediction_rows(rows, y, scores, spec):
    return [
        {
            "source_position": int(row),
            "observed": float(value),
            "prediction": float(score),
            **({"decision": int(score >= spec.threshold)} if spec.task == "binary" else {}),
        }
        for row, value, score in zip(rows, y, scores, strict=True)
    ]


def run_prediction(df, spec: PredictionSpec, *, budget_seconds: float = 300, progress=None) -> dict:
    spec.validate()
    started = time.monotonic()

    def check_budget():
        if time.monotonic() - started > budget_seconds:
            raise TimeoutError("Prediction time budget exceeded; no incomplete study is accepted.")

    receipt = {
        "contract": "prediction-validation-v1",
        "status": "running",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "versions": {name: version(name) for name in ["scikit-learn", "numpy", "pandas", "scipy"]},
        "python": platform.python_version(),
        "executor_source_sha256": digest(
            {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(Path(__file__).parent.glob("*.py"))
            }
        ),
        "candidates": [],
    }

    def checkpoint():
        check_budget()
        if progress:
            progress(receipt)

    try:
        population = prepare_population(df, spec)
        outer = outer_split(population, spec)
        folds = training_folds(population, outer, spec)
        receipt.update(
            dataframe_sha256=population["dataframe_sha256"],
            n_source=len(df),
            n_eligible=len(population["eligible"]),
            exclusions=population["exclusions"],
            target_encoding=population["encoding"],
            invalid_predictor_values=population["invalid_predictor_values"],
            outer_split=outer,
            cv_splits=folds,
            selection={
                "criterion": "auroc" if spec.task == "binary" else "rmse",
                "direction": "maximize" if spec.task == "binary" else "minimize",
                "aggregation": "unweighted mean of prespecified training CV folds",
                "tie_break": "candidate order in locked plan",
                "outer_validation_used": False,
            },
        )
        checkpoint()
        for name in spec.to_dict()["candidates"]:
            candidate = {"name": name, "status": "running", "folds": []}
            receipt["candidates"].append(candidate)
            try:
                for split in folds:
                    check_budget()
                    train, valid = split["train_positions"], split["validation_positions"]
                    model, messages = fit_model(population, train, spec, name)
                    predictions = predict(model, population["x"].iloc[valid], spec.task)
                    scores = score_metrics(population["y"].iloc[valid], predictions, spec)
                    score = scores[receipt["selection"]["criterion"]]
                    if score is None:
                        raise ValueError(f"Selection metric is not estimable in {split['name']}.")
                    candidate["folds"].append(
                        {
                            "split": split["name"],
                            "metrics": scores,
                            "fit": fit_record(model, train, spec, messages),
                            "predictions": prediction_rows(
                                valid, population["y"].iloc[valid], predictions, spec
                            ),
                        }
                    )
                    checkpoint()
                candidate.update(
                    status="completed",
                    cv_score=float(
                        np.mean(
                            [
                                f["metrics"][receipt["selection"]["criterion"]]
                                for f in candidate["folds"]
                            ]
                        )
                    ),
                )
            except TimeoutError:
                candidate.update(status="failed", error="Prediction time budget exceeded.")
                raise
            except (ValueError, ArithmeticError) as error:
                candidate.update(status="failed", error=str(error), cv_score=None)
            checkpoint()
        eligible = [c for c in receipt["candidates"] if c["status"] == "completed"]
        if not eligible:
            raise ValueError(
                "No candidate completed all training folds; the holdout has not been scored."
            )
        choose = max if spec.task == "binary" else min
        selected = choose(eligible, key=lambda c: c["cv_score"])
        receipt["selection"].update(selected=selected["name"], cv_score=selected["cv_score"])
        train, valid = outer["train_positions"], outer["validation_positions"]
        model, messages = fit_model(population, train, spec, selected["name"])
        receipt["final_fit"] = fit_record(model, train, spec, messages)
        checkpoint()
        predictions = predict(model, population["x"].iloc[valid], spec.task)
        y = population["y"].iloc[valid].to_numpy()
        groups = (
            population["groups"].iloc[valid].tolist() if population["groups"] is not None else None
        )
        baseline = np.repeat(float(population["y"].iloc[train].mean()), len(valid))
        receipt["validation"] = {
            "scope": "single internal held-out evaluation of selected model",
            "n": len(valid),
            "threshold": spec.threshold if spec.task == "binary" else None,
            "metrics": score_metrics(y, predictions, spec),
            "baseline": {
                "rule": "constant training outcome prevalence/mean",
                "constant": float(baseline[0]),
                "metrics": score_metrics(y, baseline, spec),
            },
            "predictions": prediction_rows(valid, y, predictions, spec),
            "calibration_bins": calibration_bins(y, predictions) if spec.task == "binary" else [],
            "uncertainty": bootstrap_intervals(y, predictions, groups, spec, check_budget),
        }
        receipt.update(
            status="completed",
            elapsed_seconds=time.monotonic() - started,
            limitations=[
                "Internal held-out validation; no external or clinical deployment validation.",
                "Feature availability is explicitly attested by the researcher; leakage cannot be ruled out from column names alone.",
                "Fixed candidates and hyperparameters, not exhaustive model optimization. No predictor selection uses the holdout.",
                "Imputation, scaling and categorical vocabulary are learned separately in each training partition.",
                "A split cannot remove selection bias, confounding, measurement error or temporal drift.",
            ],
        )
        receipt["receipt_sha256"] = digest(receipt)
        if progress:
            progress(receipt)
        return receipt
    except (ValueError, ArithmeticError, TimeoutError) as error:
        raise PredictionFailure(str(error), receipt) from error
