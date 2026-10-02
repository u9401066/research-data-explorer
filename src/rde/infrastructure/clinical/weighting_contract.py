"""Source-bound roles for binary-treatment, independent-case weighting.

Preflight checks an explicitly declared cohort and one complete-case population.
It does not fit propensity scores or verify causal identification assumptions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

import numpy as np
import pandas as pd

from .measurement import _labels, _text
from .regression_contract import RegressionSpec, regression_design
from .survival import digest, level, numeric


@dataclass(frozen=True)
class WeightingSpec:
    treatment: str
    treatment_levels: list[str]
    treatment_definition: str
    outcome: str
    outcome_type: str
    outcome_unit: str
    outcome_definition: str
    time_origin: str
    outcome_window: str
    study_design: str
    context: str
    estimand: str
    independent_rows: bool
    pretreatment_covariates: bool
    covariates: list[dict]
    family: str = "weighting"
    subject: str | None = None
    outcome_levels: list[str] = field(default_factory=list)
    interactions: list[list[str]] = field(default_factory=list)
    confidence_level: float = 0.95
    cohort_filter: dict | None = None

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown weighting settings; use the explicit study contract.")
        try:
            spec = cls(**options)
        except TypeError as error:
            raise ValueError(f"Missing weighting settings: {error}") from error
        spec.validate()
        return spec

    def to_dict(self):
        return asdict(self)

    def propensity_spec(self):
        """Reuse typed, formula-free covariate bases, not outcome regression."""
        return RegressionSpec(
            outcome=self.treatment,
            outcome_unit=self.treatment_definition,
            context=self.context,
            independent_rows=self.independent_rows,
            study_design=self.study_design,
            distribution="binomial",
            predictors=[
                {key: value for key, value in cov.items() if key != "pre_exposure_basis"}
                for cov in self.covariates
            ],
            outcome_levels=self.treatment_levels,
            subject=self.subject,
            interactions=self.interactions,
            confidence_level=self.confidence_level,
            cohort_filter=self.cohort_filter,
        )

    def variables(self):
        return list(dict.fromkeys([self.outcome, *self.propensity_spec().variables()]))

    def validate(self):
        if self.family != "weighting" or self.study_design != "observational_cohort":
            raise ValueError(
                "Weighting requires a declared observational cohort; case-control, cross-sectional, clustered and longitudinal treatment designs need another contract."
            )
        if self.independent_rows is not True or self.pretreatment_covariates is not True:
            raise ValueError(
                "Confirm independent cases and the pre-exposure timing of all covariates."
            )
        for name in [
            "treatment_definition",
            "outcome_definition",
            "time_origin",
            "outcome_window",
            "context",
        ]:
            _text(getattr(self, name), name, 5)
        _text(self.outcome, "outcome")
        _text(self.outcome_unit, "outcome unit")
        if self.estimand not in {"ATE", "ATT", "ATO"}:
            raise ValueError("Prespecify ATE, ATT or ATO; do not select the target from results.")
        _labels(self.outcome_levels, "outcome levels", 2)
        if self.outcome_type == "binary":
            if len(self.outcome_levels) != 2:
                raise ValueError("Binary outcomes require [negative, positive] source labels.")
        elif self.outcome_type != "continuous" or self.outcome_levels:
            raise ValueError("Use a continuous outcome without levels, or an explicit binary one.")
        if not isinstance(self.covariates, list) or not 1 <= len(self.covariates) <= 12:
            raise ValueError("Prespecify 1..12 typed pre-exposure covariates.")
        for covariate in self.covariates:
            if not isinstance(covariate, dict):
                raise ValueError("Every covariate needs a typed source and timing definition.")
            _text(covariate.get("pre_exposure_basis"), "pre-exposure basis", 5)
        propensity = self.propensity_spec()
        propensity.validate()
        if self.outcome in [self.treatment, self.subject, *[p["column"] for p in self.covariates]]:
            raise ValueError("The outcome cannot be a treatment, identity or propensity covariate.")
        if self.cohort_filter and self.cohort_filter["column"] == self.outcome:
            raise ValueError("Do not define this cohort by its analysis outcome.")


def prepare_weighting(df: pd.DataFrame, spec: WeightingSpec):
    spec.validate()
    columns = spec.variables()
    if not df.columns.is_unique or any(column not in df.columns for column in columns):
        raise ValueError("Source columns must be unique and contain every weighting role.")
    if not 10 <= len(df) <= 100_000:
        raise ValueError("Weighting accepts 10..100,000 source cases; this is not a power rule.")
    selected = df[columns].reset_index(drop=True).copy()
    rows = [
        [None if pd.isna(v) else v.item() if isinstance(v, np.generic) else v for v in row]
        for row in selected.itertuples(index=False, name=None)
    ]
    try:
        source_hash = digest({"columns": columns, "rows": rows})
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Unsupported or nonfinite source values require explicit correction."
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
        identifiers = working[spec.subject].map(level)
        if identifiers.isna().any() or identifiers.duplicated().any():
            raise ValueError(
                "Missing or duplicate identity must be resolved before outcome exclusion."
            )
    frame = pd.DataFrame(index=working.index)
    treatments = working[spec.treatment].map(level)
    if set(treatments.dropna()) - set(spec.treatment_levels):
        raise ValueError(
            "Unmapped treatment label; never infer the reference or positive direction."
        )
    frame["treatment"] = treatments.map({v: i for i, v in enumerate(spec.treatment_levels)})
    if spec.outcome_type == "binary":
        outcomes = working[spec.outcome].map(level)
        if set(outcomes.dropna()) - set(spec.outcome_levels):
            raise ValueError("Unmapped outcome label, including rows with another missing role.")
        frame["response"] = outcomes.map({v: i for i, v in enumerate(spec.outcome_levels)})
    else:
        frame["response"] = numeric(working[spec.outcome], spec.outcome)
    for i, covariate in enumerate(spec.covariates):
        name = covariate["column"]
        if covariate["kind"] == "categorical":
            values = working[name].map(level)
            if set(values.dropna()) - set(covariate["levels"]):
                raise ValueError(
                    f"{name}: an undeclared covariate level requires a new specification."
                )
        else:
            values = numeric(working[name], name)
        frame[f"x{i}"] = values
    complete = frame.notna().all(axis=1)
    retained = frame.loc[complete].copy()
    if len(retained) < 10 or any((retained.treatment == code).sum() < 2 for code in [0, 1]):
        raise ValueError(
            "Retain at least ten complete cases and two in each treatment; not a power criterion."
        )
    if retained.response.nunique() < 2:
        raise ValueError("A constant outcome does not support this weighting inference.")
    for i, covariate in enumerate(spec.covariates):
        values = retained[f"x{i}"]
        if covariate["kind"] == "categorical":
            if set(values) != set(covariate["levels"]):
                raise ValueError(
                    "Every declared covariate level and reference must retain complete cases."
                )
        else:
            lower, upper = float(values.min()), float(values.max())
            if any(
                not lower <= value <= upper
                for value in [covariate["reference"], *covariate["knots"]]
            ):
                raise ValueError(
                    "Covariate references and knots must stay inside the retained source range."
                )
    ledger = {
        "input_rows": len(df),
        "cohort_rows": int(cohort.sum()),
        "n": len(retained),
        "filter_excluded_data_rows": (selected.index[~cohort] + 1).tolist(),
        "missing_excluded_data_rows": (frame.index[~complete] + 1).tolist(),
        "complete_data_rows": (retained.index + 1).tolist(),
        "missing_by_role": {name: int(frame[name].isna().sum()) for name in frame},
        "policy": "Common complete cases across treatment, outcome and all propensity covariates; no imputation, clipping, trimming or duplicate aggregation.",
        "data_row_numbering": "one-based source rows, excluding header",
    }
    return retained, ledger, source_hash


def weighting_preflight(df, spec):
    frame, ledger, source_hash = prepare_weighting(df, spec)
    matrix, terms, groups = regression_design(frame, spec.propensity_spec())
    if len(matrix.columns) + 2 >= len(frame):
        raise ValueError(
            "The joint propensity and outcome-mean parameter count must be below case count."
        )
    return {
        "schema": "weighting-preflight-v1",
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": source_hash,
        "design_sha256": digest(
            {"columns": matrix.columns.tolist(), "values": matrix.to_numpy().tolist()}
        ),
        "study_design": spec.study_design,
        "estimand": spec.estimand,
        "input_rows": len(df),
        "n": len(frame),
        "case_ledger": ledger,
        "propensity_parameters": len(matrix.columns),
        "joint_parameters": len(matrix.columns) + 2,
        "terms": terms,
        "term_groups": groups,
        "treatment_levels": [
            {"label": label, "code": code, "n": int((frame.treatment == code).sum())}
            for code, label in enumerate(spec.treatment_levels)
        ],
        "outcome_levels": [
            {"label": label, "code": code, "n": int((frame.response == code).sum())}
            for code, label in enumerate(spec.outcome_levels)
        ],
        "scope": "Source roles, common cases and propensity design rank only; no fitted scores, weighted results or verified causal assumptions.",
    }
