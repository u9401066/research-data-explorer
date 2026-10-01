"""Explicit longitudinal roles, source identity and one observation per subject/time.

No model fitting, imputation, category inference or visit aggregation occurs here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

import numpy as np
import pandas as pd

from .measurement import _labels, _number, _text
from .survival import digest, level, numeric


@dataclass(frozen=True)
class LongitudinalSpec:
    outcome: str
    subject: str
    time: str
    time_unit: str
    time_origin: str
    outcome_unit: str
    context: str
    independent_subjects: bool
    method: str
    distribution: str
    family: str = "longitudinal"
    group: str | None = None
    group_reference: str | None = None
    time_mode: str = "linear"
    time_reference: float = 0.0
    time_levels: list[float] = field(default_factory=list)
    time_by_group: bool = False
    covariates: list[str] = field(default_factory=list)
    categorical_covariates: list[str] = field(default_factory=list)
    references: dict[str, str] = field(default_factory=dict)
    time_varying_covariates: list[str] = field(default_factory=list)
    correlation: str | None = "exchangeable"
    random_slope: bool = False
    positive: str | None = None
    negative: str | None = None
    exposure: str | None = None
    exposure_unit: str | None = None
    confidence_level: float = 0.95
    cohort_filter: dict | None = None

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown longitudinal options; use the exact study contract.")
        try:
            spec = cls(**options)
        except TypeError as error:
            raise ValueError(f"Missing longitudinal settings: {error}") from error
        spec.validate()
        return spec

    def to_dict(self):
        return asdict(self)

    def variables(self):
        return list(
            dict.fromkeys(
                [
                    self.outcome,
                    self.subject,
                    self.time,
                    *self.covariates,
                    *[
                        v
                        for v in [
                            self.group,
                            self.exposure,
                            self.cohort_filter["column"] if self.cohort_filter else None,
                        ]
                        if v
                    ],
                ]
            )
        )

    def validate(self):
        if self.family != "longitudinal" or self.independent_subjects is not True:
            raise ValueError(
                "Longitudinal models require explicitly independent subjects, not independent rows."
            )
        for key in [
            "outcome",
            "subject",
            "time",
            "time_unit",
            "time_origin",
            "outcome_unit",
            "context",
        ]:
            _text(getattr(self, key), key, 5 if key in {"context", "time_origin"} else 1)
        for key in [
            "group",
            "group_reference",
            "positive",
            "negative",
            "exposure",
            "exposure_unit",
        ]:
            if getattr(self, key) is not None:
                _text(getattr(self, key), key)
        for key in ["covariates", "categorical_covariates", "time_varying_covariates"]:
            _labels(getattr(self, key), key)
        roles = [self.outcome, self.subject, self.time, self.group, self.exposure, *self.covariates]
        roles = [r for r in roles if r is not None]
        if len(set(roles)) != len(roles):
            raise ValueError(
                "Outcome, subject, time, group, exposure and additional covariates must have distinct roles."
            )
        if bool(self.group) != bool(self.group_reference):
            raise ValueError("A longitudinal group requires an explicit reference label.")
        if not isinstance(self.references, dict) or set(self.references) != set(
            self.categorical_covariates
        ):
            raise ValueError("References must match every categorical covariate exactly.")
        for value in self.references.values():
            _text(value, "reference")
        if not set(self.categorical_covariates + self.time_varying_covariates) <= set(
            self.covariates
        ):
            raise ValueError(
                "Categorical and time-varying roles must be declared additional covariates."
            )
        if self.method not in {"gee", "mixed"} or self.distribution not in {
            "gaussian",
            "binomial",
            "poisson",
        }:
            raise ValueError("Use GEE (Gaussian, binomial or Poisson) or Gaussian mixed models.")
        if type(self.random_slope) is not bool or type(self.time_by_group) is not bool:
            raise ValueError("Random slope and time-by-group options must be booleans.")
        if self.method == "gee":
            if self.correlation not in {"independence", "exchangeable"} or self.random_slope:
                raise ValueError(
                    "GEE requires independence/exchangeable working correlation and no random slope."
                )
        elif self.distribution != "gaussian" or self.correlation is not None:
            raise ValueError(
                "Mixed models require Gaussian outcomes and correlation=null; random effects define dependence."
            )
        _number(self.time_reference, "time_reference")
        if self.time_mode not in {"linear", "categorical"}:
            raise ValueError("Time must be explicitly linear or categorical.")
        if not isinstance(self.time_levels, list):
            raise ValueError("Time levels must be an ordered numeric list.")
        for t in self.time_levels:
            _number(t, "time level")
        if self.time_mode == "linear":
            if self.time_levels:
                raise ValueError("Linear time does not accept categorical time levels.")
        elif (
            not 2 <= len(self.time_levels) <= 12
            or any(a >= b for a, b in zip(self.time_levels, self.time_levels[1:]))
            or self.time_reference not in self.time_levels
            or self.random_slope
        ):
            raise ValueError(
                "Categorical time requires 2..12 increasing values, an explicit reference and no numeric random slope."
            )
        if self.time_by_group and not self.group:
            raise ValueError("A prespecified time-by-group interaction requires a group.")
        if self.distribution == "binomial":
            if self.positive is None or self.negative is None or self.positive == self.negative:
                raise ValueError(
                    "Binary responses require distinct explicit positive and negative source labels."
                )
        elif self.positive is not None or self.negative is not None:
            raise ValueError("Only binomial outcomes accept positive/negative codes.")
        if self.exposure:
            if self.distribution != "poisson" or not self.exposure_unit:
                raise ValueError(
                    "An observation-duration offset requires a Poisson model and exposure unit."
                )
        elif self.exposure_unit is not None:
            raise ValueError("Exposure unit requires an actual exposure column.")
        _number(self.confidence_level, "confidence_level")
        if not 0.8 <= self.confidence_level <= 0.999:
            raise ValueError("Confidence level must lie between 0.8 and 0.999.")
        if self.cohort_filter is not None:
            if not isinstance(self.cohort_filter, dict) or set(self.cohort_filter) != {
                "column",
                "values",
            }:
                raise ValueError("Cohort restriction requires an exact column and list of labels.")
            _text(self.cohort_filter["column"], "cohort column")
            _labels(self.cohort_filter["values"], "cohort values")
            if not self.cohort_filter["values"]:
                raise ValueError("Cohort restriction must contain an included label.")


def prepare_longitudinal(df: pd.DataFrame, spec: LongitudinalSpec):
    spec.validate()
    if not df.columns.is_unique or any(v not in df.columns for v in spec.variables()):
        raise ValueError("Source must have unique columns and every specified longitudinal role.")
    if not 10 <= len(df) <= 100_000:
        raise ValueError("Longitudinal studies require 10..100,000 source observations.")
    selected = df[spec.variables()].reset_index(drop=True).copy()
    source = [
        [None if pd.isna(v) else v.item() if isinstance(v, np.generic) else v for v in row]
        for row in selected.itertuples(index=False, name=None)
    ]
    try:
        frame_hash = digest({"columns": spec.variables(), "rows": source})
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Unsupported or nonfinite source value; explicitly correct the source."
        ) from error
    cohort = pd.Series(True, index=selected.index)
    if spec.cohort_filter:
        cohort = (
            selected[spec.cohort_filter["column"]].map(level).isin(spec.cohort_filter["values"])
        )
    working = selected.loc[cohort]
    if working.empty:
        raise ValueError("No observations satisfy the prespecified inclusion restriction.")
    frame = pd.DataFrame(index=working.index)
    frame["subject"] = working[spec.subject].map(level)
    frame["time"] = numeric(working[spec.time], spec.time)
    if frame[["subject", "time"]].isna().any().any():
        raise ValueError(
            "Subject and time must be present on every included source row, before outcome exclusions."
        )
    if frame.duplicated(["subject", "time"]).any():
        raise ValueError(
            "Duplicate subject/time observations require explicit reconciliation; rows are never averaged."
        )
    if spec.time_mode == "categorical" and not frame.time.isin(spec.time_levels).all():
        raise ValueError("A source time is outside the prespecified categorical time levels.")
    frame["group"] = working[spec.group].map(level) if spec.group else "All participants"
    if spec.distribution == "binomial":
        codes = working[spec.outcome].map(level)
        if set(codes.dropna()) - {spec.negative, spec.positive}:
            raise ValueError("Unmapped binary outcome labels; do not infer clinical meaning.")
        frame["outcome"] = codes.map({spec.negative: 0, spec.positive: 1})
    else:
        frame["outcome"] = numeric(working[spec.outcome], spec.outcome)
        if spec.distribution == "poisson":
            y = frame.outcome.dropna()
            if ((y < 0) | (y % 1 != 0)).any():
                raise ValueError("Poisson responses must be nonnegative integer counts.")
    if spec.exposure:
        frame["exposure"] = numeric(working[spec.exposure], spec.exposure)
        if (frame.exposure.dropna() <= 0).any():
            raise ValueError(
                "Every observed exposure must be strictly positive, including rows with missing outcomes."
            )
    for i, name in enumerate(spec.covariates):
        frame[f"c{i}"] = (
            working[name].map(level)
            if name in spec.categorical_covariates
            else numeric(working[name], name)
        )
    baseline = [
        "group",
        *[
            f"c{i}"
            for i, name in enumerate(spec.covariates)
            if name not in spec.time_varying_covariates
        ],
    ]
    for column in baseline:
        if (frame.groupby("subject")[column].nunique(dropna=True) > 1).any():
            raise ValueError(
                f"Baseline role {column} changes within a subject, before missing-observation exclusion."
            )
    complete = frame.notna().all(axis=1)
    retained = frame.loc[complete].copy()
    counts = retained.groupby("subject").size()
    if len(counts) < 10 or (counts > 1).sum() < 3:
        raise ValueError(
            "At least ten independent subjects and three with repeated complete observations are required; this is not a power guarantee."
        )
    if retained.time.nunique() < 2:
        raise ValueError("At least two distinct observed times must remain.")
    if not retained.time.min() <= spec.time_reference <= retained.time.max():
        raise ValueError("The reference time must be inside the observed complete-case time range.")
    if spec.time_mode == "categorical" and set(retained.time) != set(spec.time_levels):
        raise ValueError("Every declared categorical time must retain complete observations.")
    if spec.group and (
        not 2 <= retained.group.nunique() <= 6 or spec.group_reference not in set(retained.group)
    ):
        raise ValueError("Two to six groups including the declared reference must remain.")
    if spec.distribution == "binomial" and retained.outcome.nunique() != 2:
        raise ValueError("Both binary outcomes must remain for model estimation.")
    if spec.distribution == "poisson" and retained.outcome.sum() == 0:
        raise ValueError("No observed counts remain; a finite Poisson model is not estimable.")
    ledger = {
        "input_rows": len(df),
        "cohort_rows": int(cohort.sum()),
        "cohort_subjects": int(frame.subject.nunique()),
        "n_subjects": len(counts),
        "filter_excluded_data_rows": (selected.index[~cohort] + 1).tolist(),
        "missing_excluded_data_rows": (frame.index[~complete] + 1).tolist(),
        "complete_data_rows": (retained.index + 1).tolist(),
        "subjects_with_no_complete_observations": int(frame.subject.nunique() - len(counts)),
        "subjects_with_one_complete_observation": int((counts == 1).sum()),
        "subjects_with_repeated_observations": int((counts > 1).sum()),
        "observations_per_subject": {"min": int(counts.min()), "max": int(counts.max())},
        "missing_by_role": {name: int(frame[name].isna().sum()) for name in frame},
        "policy": "Observation-wise complete cases for all model roles; do not remove every visit of a partially observed subject or impute absent visits.",
        "data_row_numbering": "one-based observations, excluding header",
    }
    return retained, ledger, frame_hash


def longitudinal_design(frame: pd.DataFrame, spec: LongitudinalSpec):
    """Construct a finite explicit design matrix, without formulas or arbitrary code."""
    matrix = pd.DataFrame({"intercept": 1.0}, index=frame.index)
    terms = [
        {
            "term": "intercept",
            "role": "intercept",
            "description": "Intercept at the declared reference time and reference categories; numeric covariates at zero.",
        }
    ]
    time_terms, group_terms = [], []
    if spec.time_mode == "linear":
        matrix["time"] = frame.time - spec.time_reference
        time_terms.append("time")
        terms.append(
            {
                "term": "time",
                "role": "time",
                "variable": spec.time,
                "unit": spec.time_unit,
                "center": spec.time_reference,
            }
        )
    else:
        for i, value in enumerate(t for t in spec.time_levels if t != spec.time_reference):
            term = f"time_L{i + 1}"
            matrix[term] = (frame.time == value).astype(float)
            time_terms.append(term)
            terms.append(
                {
                    "term": term,
                    "role": "time",
                    "variable": spec.time,
                    "level": value,
                    "reference": spec.time_reference,
                    "unit": spec.time_unit,
                }
            )

    def categorical(column, name, reference, prefix, role, maximum=12):
        labels = sorted(frame[column].unique())
        if not 2 <= len(labels) <= maximum or reference not in labels:
            raise ValueError(
                f"{name}: every categorical predictor requires 2..{maximum} levels and its declared reference."
            )
        added = []
        for i, label in enumerate(v for v in labels if v != reference):
            term = f"{prefix}_L{i + 1}"
            matrix[term] = (frame[column] == label).astype(float)
            added.append(term)
            terms.append(
                {
                    "term": term,
                    "role": role,
                    "variable": name,
                    "level": label,
                    "reference": reference,
                }
            )
        return added

    if spec.group:
        group_terms = categorical("group", spec.group, spec.group_reference, "group", "group", 6)
    for i, name in enumerate(spec.covariates):
        key = f"c{i}"
        if name in spec.categorical_covariates:
            categorical(key, name, spec.references[name], key, "covariate")
        else:
            matrix[key] = frame[key].astype(float)
            terms.append(
                {
                    "term": key,
                    "role": "covariate",
                    "variable": name,
                    "unit": "one original source unit",
                }
            )
    if spec.time_by_group:
        for time in time_terms:
            for group in group_terms:
                term = f"{time}:{group}"
                matrix[term] = matrix[time] * matrix[group]
                terms.append({"term": term, "role": "interaction", "components": [time, group]})
    if (
        matrix.shape[1] > 60
        or matrix.shape[1] >= len(matrix)
        or np.linalg.matrix_rank(matrix.to_numpy()) < matrix.shape[1]
    ):
        raise ValueError(
            "The explicit longitudinal design is rank-deficient or exceeds 60 parameters/available observations."
        )
    if spec.method == "gee" and frame.subject.nunique() <= matrix.shape[1]:
        raise ValueError(
            "Robust GEE inference requires more independent subjects than mean-model parameters."
        )
    return matrix, terms


def longitudinal_preflight(df, spec):
    frame, ledger, frame_hash = prepare_longitudinal(df, spec)
    matrix, terms = longitudinal_design(frame, spec)
    return {
        "schema": "longitudinal-preflight-v1",
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": frame_hash,
        "input_rows": len(df),
        "n": len(frame),
        "n_subjects": ledger["n_subjects"],
        "case_ledger": ledger,
        "parameters": len(matrix.columns),
        "terms": terms,
        "observed_time_range": [float(frame.time.min()), float(frame.time.max())],
        "groups": [
            {"label": label, "observations": len(g), "subjects": int(g.subject.nunique())}
            for label, g in frame.groupby("group", sort=True)
        ],
        "scope": "Source roles, visit identity, case counts and design rank only; no fitted model, p-value or verified clinical assumptions.",
    }
