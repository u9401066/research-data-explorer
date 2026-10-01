"""Prespecified independent-case regression roles and formula-free design matrices.

Source units, outcome order, contrasts and spline knots are explicit. Preflight
does not fit a model, select variables or infer a clinical sampling design.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

import numpy as np
import pandas as pd

from .measurement import _labels, _number, _text
from .survival import digest, level, numeric


@dataclass(frozen=True)
class RegressionSpec:
    outcome: str
    outcome_unit: str
    context: str
    independent_rows: bool
    study_design: str
    distribution: str
    predictors: list[dict]
    family: str = "regression"
    subject: str | None = None
    outcome_levels: list[str] = field(default_factory=list)
    interactions: list[list[str]] = field(default_factory=list)
    exposure: str | None = None
    exposure_unit: str | None = None
    confidence_level: float = 0.95
    cohort_filter: dict | None = None

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown regression settings; use the explicit study contract.")
        try:
            spec = cls(**options)
        except TypeError as error:
            raise ValueError(f"Missing regression settings: {error}") from error
        spec.validate()
        return spec

    def to_dict(self):
        return asdict(self)

    def variables(self):
        return list(
            dict.fromkeys(
                [self.outcome, *[p["column"] for p in self.predictors]]
                + [
                    name
                    for name in [
                        self.subject,
                        self.exposure,
                        self.cohort_filter["column"] if self.cohort_filter else None,
                    ]
                    if name is not None
                ]
            )
        )

    def validate(self):
        if self.family != "regression" or self.independent_rows is not True:
            raise ValueError("Regression requires explicitly independent source cases.")
        for name in ["outcome", "outcome_unit", "context"]:
            _text(getattr(self, name), name, 5 if name == "context" else 1)
        for name in ["subject", "exposure", "exposure_unit"]:
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)
        if self.study_design not in {
            "randomized_parallel",
            "observational_cohort",
            "cross_sectional",
            "case_control",
            "unspecified",
        }:
            raise ValueError("Declare the actual sampling design, or explicitly unspecified.")
        if self.distribution not in {
            "gaussian",
            "binomial",
            "poisson",
            "negative_binomial",
            "ordinal",
        }:
            raise ValueError("Unsupported prespecified regression distribution.")
        if self.study_design == "case_control" and self.distribution != "binomial":
            raise ValueError(
                "This case-control workflow supports binary logistic associations only."
            )
        _labels(self.outcome_levels, "outcome levels", 8)
        if self.distribution == "binomial":
            if len(self.outcome_levels) != 2:
                raise ValueError("Binary outcomes require [negative, positive] original labels.")
        elif self.distribution == "ordinal":
            if not 3 <= len(self.outcome_levels) <= 8:
                raise ValueError("Ordinal outcomes require 3..8 explicit lowest-to-highest labels.")
        elif self.outcome_levels:
            raise ValueError("Only binary/ordinal outcomes accept outcome labels.")
        if self.exposure:
            if self.distribution not in {"poisson", "negative_binomial"} or not self.exposure_unit:
                raise ValueError("A log-exposure offset needs a count model and declared units.")
        elif self.exposure_unit is not None:
            raise ValueError("An exposure unit requires an actual source column.")
        if not isinstance(self.predictors, list) or not 1 <= len(self.predictors) <= 12:
            raise ValueError("Specify 1..12 predictor roles before fitting.")
        names = []
        for predictor in self.predictors:
            if not isinstance(predictor, dict):
                raise ValueError("Each predictor requires an explicit typed definition.")
            kind = predictor.get("kind")
            keys = {"column", "kind", "label", "reference"}
            if kind == "continuous":
                keys |= {"unit", "increment", "knots"}
            elif kind == "categorical":
                keys |= {"levels"}
            else:
                raise ValueError("Predictors must be explicitly continuous or categorical.")
            if set(predictor) != keys:
                raise ValueError("Predictor definition does not match the exact typed contract.")
            for key in ["column", "label"]:
                _text(predictor[key], key)
            names.append(predictor["column"])
            if kind == "categorical":
                _labels(predictor["levels"], "predictor levels", 8)
                _text(predictor["reference"], "categorical reference")
                if (
                    not 2 <= len(predictor["levels"]) <= 8
                    or predictor["reference"] not in predictor["levels"]
                ):
                    raise ValueError(
                        "Every categorical role needs 2..8 labels and a reference among them."
                    )
            else:
                _text(predictor["unit"], "source unit")
                _number(predictor["reference"], "continuous reference")
                _number(predictor["increment"], "comparison increment")
                if predictor["increment"] <= 0:
                    raise ValueError("The comparison increment must be positive in source units.")
                knots = predictor["knots"]
                if not isinstance(knots, list) or knots and not 3 <= len(knots) <= 5:
                    raise ValueError(
                        "Use no knots for a linear term or 3..5 explicit spline knots."
                    )
                for knot in knots:
                    _number(knot, "spline knot")
                if any(a >= b for a, b in zip(knots, knots[1:])):
                    raise ValueError("Spline knots must be strictly increasing in source units.")
        roles = [v for v in [self.outcome, self.subject, self.exposure, *names] if v is not None]
        if len(set(roles)) != len(roles):
            raise ValueError("Outcome, identity, exposure and predictor roles must be distinct.")
        if not isinstance(self.interactions, list) or len(self.interactions) > 6:
            raise ValueError("Specify at most six two-predictor interactions.")
        seen = set()
        for pair in self.interactions:
            _labels(pair, "interaction pair", 2)
            if len(pair) != 2 or not set(pair) <= set(names):
                raise ValueError("Each interaction needs two distinct, declared main predictors.")
            identity = frozenset(pair)
            if identity in seen:
                raise ValueError("An interaction is repeated, possibly in reverse order.")
            seen.add(identity)
        _number(self.confidence_level, "confidence_level")
        if not 0.8 <= self.confidence_level <= 0.999:
            raise ValueError("Confidence level must lie between 0.8 and 0.999.")
        if self.cohort_filter is not None:
            if not isinstance(self.cohort_filter, dict) or set(self.cohort_filter) != {
                "column",
                "values",
            }:
                raise ValueError("Cohort restriction requires exactly column and included values.")
            _text(self.cohort_filter["column"], "cohort column")
            _labels(self.cohort_filter["values"], "cohort values")
            if not self.cohort_filter["values"]:
                raise ValueError("An inclusion restriction requires at least one source label.")


def prepare_regression(df: pd.DataFrame, spec: RegressionSpec):
    spec.validate()
    if not df.columns.is_unique or any(v not in df.columns for v in spec.variables()):
        raise ValueError("Source columns must be unique and contain every declared role.")
    if not 10 <= len(df) <= 100_000:
        raise ValueError(
            "Regression requires 10..100,000 source cases; this is not a power criterion."
        )
    selected = df[spec.variables()].reset_index(drop=True).copy()
    source = [
        [None if pd.isna(v) else v.item() if isinstance(v, np.generic) else v for v in row]
        for row in selected.itertuples(index=False, name=None)
    ]
    try:
        source_hash = digest({"columns": spec.variables(), "rows": source})
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Unsupported/nonfinite source values require explicit correction."
        ) from error
    cohort = pd.Series(True, index=selected.index)
    if spec.cohort_filter:
        cohort = (
            selected[spec.cohort_filter["column"]].map(level).isin(spec.cohort_filter["values"])
        )
    working = selected.loc[cohort]
    if working.empty:
        raise ValueError("No source cases satisfy the declared inclusion restriction.")
    if spec.subject:
        identities = working[spec.subject].map(level)
        if identities.isna().any() or identities.duplicated().any():
            raise ValueError(
                "Missing or duplicate subject identity precedes outcome exclusion; use a repeated-observation design when appropriate."
            )
    frame = pd.DataFrame(index=working.index)
    if spec.outcome_levels:
        codes = working[spec.outcome].map(level)
        if set(codes.dropna()) - set(spec.outcome_levels):
            raise ValueError(
                "Unmapped outcome label; never infer an ordinal or positive direction."
            )
        frame["outcome"] = codes.map({v: i for i, v in enumerate(spec.outcome_levels)})
    else:
        frame["outcome"] = numeric(working[spec.outcome], spec.outcome)
        if spec.distribution in {"poisson", "negative_binomial"}:
            values = frame.outcome.dropna()
            if ((values < 0) | (values % 1 != 0)).any():
                raise ValueError("Count outcomes require nonnegative integer observations.")
    if spec.exposure:
        frame["exposure"] = numeric(working[spec.exposure], spec.exposure)
        if (frame.exposure.dropna() <= 0).any():
            raise ValueError(
                "Every observed exposure must be positive, even if another role is missing."
            )
    for i, predictor in enumerate(spec.predictors):
        column = predictor["column"]
        if predictor["kind"] == "categorical":
            values = working[column].map(level)
            if set(values.dropna()) - set(predictor["levels"]):
                raise ValueError(
                    f"{column}: unmapped predictor levels require a new explicit definition."
                )
        else:
            values = numeric(working[column], column)
        frame[f"x{i}"] = values
    complete = frame.notna().all(axis=1)
    retained = frame.loc[complete].copy()
    if len(retained) < 10:
        raise ValueError(
            "At least ten complete independent cases are required; this does not prove adequate power."
        )
    if spec.outcome_levels and set(retained.outcome) != set(range(len(spec.outcome_levels))):
        raise ValueError("Every declared outcome level must retain complete cases.")
    if retained.outcome.nunique() < 2:
        raise ValueError("A constant outcome cannot support this regression inference.")
    for i, predictor in enumerate(spec.predictors):
        values = retained[f"x{i}"]
        if predictor["kind"] == "categorical":
            if set(values) != set(predictor["levels"]):
                raise ValueError(
                    "Every declared predictor category and reference must retain complete cases."
                )
        else:
            lower, upper = float(values.min()), float(values.max())
            if not lower <= predictor["reference"] <= upper:
                raise ValueError(
                    "A continuous reference must be inside its observed complete-case range."
                )
            if any(not lower <= knot <= upper for knot in predictor["knots"]):
                raise ValueError(
                    "Spline knots must remain within the observed complete-case range."
                )
    ledger = {
        "input_rows": len(df),
        "cohort_rows": int(cohort.sum()),
        "n": len(retained),
        "filter_excluded_data_rows": (selected.index[~cohort] + 1).tolist(),
        "missing_excluded_data_rows": (frame.index[~complete] + 1).tolist(),
        "complete_data_rows": (retained.index + 1).tolist(),
        "missing_by_role": {name: int(frame[name].isna().sum()) for name in frame},
        "policy": "Common complete cases across this outcome, all predictors and exposure; no imputation or automatic aggregation.",
        "data_row_numbering": "one-based source rows, excluding header",
    }
    return retained, ledger, source_hash


def restricted_cubic_basis(values, knots):
    """Natural cubic truncated-power basis, scaled by outer-knot distance squared.

    Returns the linear column followed by K-2 nonlinear columns; both tails are
    linear. No data-derived knot selection or response information is used.
    """
    values = np.asarray(values, dtype=float)
    if not knots:
        return values[:, None]
    a, b = knots[-2:]
    span = knots[-1] - knots[0]
    basis = [values]
    for knot in knots[:-2]:
        cubic = (
            np.maximum(values - knot, 0) ** 3
            - (b - knot) / (b - a) * np.maximum(values - a, 0) ** 3
            + (a - knot) / (b - a) * np.maximum(values - b, 0) ** 3
        ) / span**2
        basis.append(cubic)
    return np.column_stack(basis)


def regression_design(frame: pd.DataFrame, spec: RegressionSpec, *, check_rank=True):
    """Use internal term IDs; user column names are never evaluated as formulas."""
    matrix = pd.DataFrame(index=frame.index)
    terms, groups = [], []
    if spec.distribution != "ordinal":
        matrix["intercept"] = 1.0
        terms.append({"term": "intercept", "role": "intercept"})
    for i, predictor in enumerate(spec.predictors):
        prefix = f"x{i}"
        added = []
        if predictor["kind"] == "continuous":
            basis = (
                restricted_cubic_basis(frame[prefix], predictor["knots"])
                - restricted_cubic_basis([predictor["reference"]], predictor["knots"])
            ) / predictor["increment"]
            for j in range(basis.shape[1]):
                term = f"{prefix}_b{j}"
                matrix[term] = basis[:, j]
                added.append(term)
                terms.append(
                    {
                        "term": term,
                        "role": "spline_basis" if predictor["knots"] else "linear",
                        "predictor": i,
                        "basis": j,
                    }
                )
        else:
            for j, label in enumerate(
                v for v in predictor["levels"] if v != predictor["reference"]
            ):
                term = f"{prefix}_l{j}"
                matrix[term] = (frame[prefix] == label).astype(float)
                added.append(term)
                terms.append({"term": term, "role": "categorical", "predictor": i, "level": label})
        groups.append({"role": "main", "predictors": [i], "terms": added})
    names = [p["column"] for p in spec.predictors]
    for pair in spec.interactions:
        left, right = [names.index(name) for name in pair]
        added = []
        for a in groups[left]["terms"]:
            for b in groups[right]["terms"]:
                term = f"{a}:{b}"
                matrix[term] = matrix[a] * matrix[b]
                added.append(term)
                terms.append(
                    {
                        "term": term,
                        "role": "interaction",
                        "predictors": [left, right],
                        "components": [a, b],
                    }
                )
        groups.append({"role": "interaction", "predictors": [left, right], "terms": added})
    values = matrix.to_numpy(dtype=float)
    nuisance = (
        len(spec.outcome_levels) - 1
        if spec.distribution == "ordinal"
        else int(spec.distribution == "negative_binomial")
    )
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite regression basis; review numeric scales and knots.")
    if check_rank and (
        len(matrix.columns) + nuisance > 60
        or len(matrix.columns) + nuisance >= len(matrix)
        or np.linalg.matrix_rank(values) != len(matrix.columns)
        or spec.distribution == "ordinal"
        and np.linalg.matrix_rank(np.column_stack([np.ones(len(matrix)), values]))
        != len(matrix.columns) + 1
    ):
        raise ValueError(
            "Regression design is rank-deficient, contains an ordinal intercept, or exceeds the parameter/case limits."
        )
    return matrix, terms, groups


def regression_preflight(df, spec):
    frame, ledger, source_hash = prepare_regression(df, spec)
    matrix, terms, groups = regression_design(frame, spec)
    return {
        "schema": "regression-preflight-v1",
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": source_hash,
        "design_sha256": digest(
            {"columns": matrix.columns.tolist(), "values": matrix.to_numpy().tolist()}
        ),
        "study_design": spec.study_design,
        "input_rows": len(df),
        "n": len(frame),
        "case_ledger": ledger,
        "mean_parameters": len(matrix.columns),
        "terms": terms,
        "term_groups": groups,
        "outcome_levels": [
            {"label": label, "code": i, "n": int((frame.outcome == i).sum())}
            for i, label in enumerate(spec.outcome_levels)
        ],
        "predictors": [
            {
                **p,
                "observed_range": [float(frame[f"x{i}"].min()), float(frame[f"x{i}"].max())]
                if p["kind"] == "continuous"
                else None,
            }
            for i, p in enumerate(spec.predictors)
        ],
        "scope": "Source identities, explicit coding, common-case counts and design rank only; no model fitting, significance test or verified sampling assumption.",
    }
