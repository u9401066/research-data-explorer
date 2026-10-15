"""Source-bound single-level predictive mean matching, without fitting models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math

import numpy as np
import pandas as pd

from .measurement import _labels, _text
from .survival import digest, level, numeric


@dataclass(frozen=True)
class ImputationSpec:
    subject: str
    outcome: str
    outcome_unit: str
    distribution: str
    predictors: list[str]
    columns: list[dict]
    study_design: str
    context: str
    population_definition: str
    missingness_basis: str
    imputation_scope: str
    independent_rows: bool
    structural_missingness_absent: bool
    nonimputable_missing: str
    m: int
    burn_in: int
    between: int
    k_pmm: int
    seed: int
    family: str = "imputation"
    confidence_level: float = 0.95
    cohort_filter: dict | None = None

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown imputation settings; use the complete typed contract.")
        try:
            spec = cls(**options)
        except TypeError as error:
            raise ValueError(f"Missing imputation settings: {error}") from error
        spec.validate()
        return spec

    def to_dict(self):
        return asdict(self)

    def variables(self):
        return list(
            dict.fromkeys(
                [
                    self.subject,
                    *[c["column"] for c in self.columns],
                    *([self.cohort_filter["column"]] if self.cohort_filter else []),
                ]
            )
        )

    def validate(self):
        if self.family != "imputation" or self.independent_rows is not True:
            raise ValueError("Imputation v1 requires declared independent single-level subjects.")
        if self.structural_missingness_absent is not True:
            raise ValueError(
                "Structural missingness needs a separate reviewed strategy; do not impute it."
            )
        if self.nonimputable_missing != "exclude":
            raise ValueError("Explicitly declare exclude for missing nonimputable roles.")
        descriptions = {"context", "population_definition", "missingness_basis", "imputation_scope"}
        for name in ["subject", "outcome", "outcome_unit", *sorted(descriptions)]:
            _text(getattr(self, name), name, 5 if name in descriptions else 1)
        if self.study_design not in {
            "randomized_parallel",
            "observational_cohort",
            "cross_sectional",
            "case_control",
        }:
            raise ValueError(
                "Prespecify the actual study design; imputation does not establish it."
            )
        if self.distribution not in {"gaussian", "binomial"} or (
            self.study_design == "case_control" and self.distribution != "binomial"
        ):
            raise ValueError("Use Gaussian/binary logistic analysis; case-control only logistic.")
        for name, lower, upper in [
            ("m", 5, 100),
            ("burn_in", 5, 200),
            ("between", 1, 50),
            ("k_pmm", 3, 20),
            ("seed", 1, 2147483647),
        ]:
            value = getattr(self, name)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{name} must be an integer in {lower}..{upper}.")
        if self.burn_in + self.m * self.between > 2000:
            raise ValueError("The prespecified imputation cycle budget exceeds 2000.")
        if (
            isinstance(self.confidence_level, bool)
            or not isinstance(self.confidence_level, (int, float))
            or not math.isfinite(self.confidence_level)
            or not 0.8 <= self.confidence_level <= 0.999
        ):
            raise ValueError("confidence_level must be finite and in 0.8..0.999.")
        if not isinstance(self.columns, list) or not 2 <= len(self.columns) <= 20:
            raise ValueError("Declare 2..20 continuous/binary imputation-model columns.")
        names = []
        for column in self.columns:
            if not isinstance(column, dict) or set(column) != {
                "column",
                "kind",
                "levels",
                "unit",
                "impute",
                "predictors",
            }:
                raise ValueError(
                    "Each role needs exactly column/kind/levels/unit/impute/predictors."
                )
            _text(column["column"], "column")
            if column["column"] == "__rde_source_data_row__":
                raise ValueError(
                    "The source-row locator name is reserved for derived CSV artifacts."
                )
            _text(column["unit"], "column unit")
            names.append(column["column"])
            _labels(column["levels"], "source levels", 2)
            if column["kind"] == "continuous":
                if column["levels"]:
                    raise ValueError("Continuous roles have no source levels.")
            elif column["kind"] != "binary" or len(column["levels"]) != 2:
                raise ValueError(
                    "Only continuous/binary roles; binary needs [reference,event] labels."
                )
            if type(column["impute"]) is not bool:
                raise ValueError("Each role must explicitly permit or prohibit imputation.")
        if len(set(names)) != len(names) or self.subject in names or self.outcome not in names:
            raise ValueError("Column roles must be unique, include outcome, and exclude identity.")
        _labels(self.predictors, "analysis predictors", 12)
        if not self.predictors or not set(self.predictors) <= set(names) - {self.outcome}:
            raise ValueError("Declare 1..12 distinct non-outcome analysis predictors.")
        outcome = next(c for c in self.columns if c["column"] == self.outcome)
        if outcome["kind"] != {"gaussian": "continuous", "binomial": "binary"}[self.distribution]:
            raise ValueError("Outcome role must agree with the analysis distribution.")
        for column in self.columns:
            _labels(column["predictors"], "imputation predictors", 19)
            if not set(column["predictors"]) <= set(names) - {column["column"]}:
                raise ValueError("Imputation predictors must name other declared roles, never IDs.")
            if bool(column["predictors"]) != column["impute"]:
                raise ValueError(
                    "Imputed roles need predictors; nonimputed roles need an empty list."
                )
        if not any(c["impute"] for c in self.columns):
            raise ValueError("At least one role must be designated for imputation.")
        if self.cohort_filter is not None:
            if not isinstance(self.cohort_filter, dict) or set(self.cohort_filter) != {
                "column",
                "values",
            }:
                raise ValueError("Cohort filter requires exactly column/values.")
            _text(self.cohort_filter["column"], "cohort column")
            _labels(self.cohort_filter["values"], "cohort values")
            if not self.cohort_filter["values"] or self.cohort_filter["column"] in names:
                raise ValueError(
                    "Eligibility cannot depend on an analysis/imputed role in this v1 contract."
                )


def prepare_imputation(df: pd.DataFrame, spec: ImputationSpec):
    spec.validate()
    columns = spec.variables()
    if not df.columns.is_unique or any(c not in df.columns for c in columns):
        raise ValueError("Source columns must be unique and contain all imputation roles.")
    if not 10 <= len(df) <= 100000:
        raise ValueError("Imputation supports 10..100,000 source subjects, not a power criterion.")
    selected = df[columns].reset_index(drop=True).copy()
    rows = [
        [None if pd.isna(v) else v.item() if isinstance(v, np.generic) else v for v in row]
        for row in selected.itertuples(index=False, name=None)
    ]
    try:
        frame_hash = digest({"columns": columns, "rows": rows})
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
    identities = working[spec.subject].map(level)
    if working.empty or identities.isna().any() or identities.duplicated().any():
        raise ValueError("Resolve missing/duplicate identity before missing-role exclusion.")
    frame = pd.DataFrame(index=working.index)
    for column in spec.columns:
        name = column["column"]
        if column["kind"] == "binary":
            labels = working[name].map(level)
            if set(labels.dropna()) - set(column["levels"]):
                raise ValueError(
                    f"{name}: undeclared binary code, even on a row with other missing roles."
                )
            frame[name] = labels.map({v: i for i, v in enumerate(column["levels"])}).astype(float)
        else:
            frame[name] = numeric(working[name], name)
    if frame.isna().all(axis=1).any():
        raise ValueError(
            "An eligible row is entirely missing across imputation roles; MICEData would silently drop it. Review eligibility explicitly."
        )
    nonimputed = [c["column"] for c in spec.columns if not c["impute"]]
    retained_mask = frame[nonimputed].notna().all(axis=1)
    retained = frame.loc[retained_mask].copy()
    if len(retained) < max(10, len(spec.predictors) + 4):
        raise ValueError("Too few eligible subjects after nonimputable-role exclusions.")
    if not retained.isna().any().any():
        raise ValueError(
            "No eligible missing cells remain; use the ordinary regression contract instead of artificial multiple imputation."
        )
    if len(retained) * len(spec.columns) * spec.m > 5_000_000:
        raise ValueError("Completed-data artifact budget exceeds five million cells.")
    for column in spec.columns:
        name = column["column"]
        observed = retained[name].dropna()
        if len(observed) < max(5, spec.k_pmm) or observed.nunique() < 2:
            raise ValueError(f"{name}: insufficient or constant observed donors.")
        if column["kind"] == "binary" and any((observed == code).sum() < 2 for code in [0, 1]):
            raise ValueError(f"{name}: both binary levels need at least two observed subjects.")
        if retained[name].isna().any() and len(observed) <= len(column["predictors"]) + 3:
            raise ValueError(f"{name}: insufficient observed cases for the conditional model.")
    # Stable identity ordering makes the RNG mapping independent of imported row order.
    retained = retained.loc[identities.loc[retained.index].sort_values(kind="stable").index]
    ledger = {
        "input_rows": len(df),
        "cohort_rows": int(cohort.sum()),
        "n": len(retained),
        "filter_excluded_data_rows": (selected.index[~cohort] + 1).tolist(),
        "missing_excluded_data_rows": (frame.index[~retained_mask] + 1).tolist(),
        "included_data_rows": sorted((retained.index + 1).tolist()),
        "sampling_data_rows": (retained.index + 1).tolist(),
        "original_complete_data_rows": sorted(
            (retained.index[retained.notna().all(axis=1)] + 1).tolist()
        ),
        "analysis_complete_data_rows": sorted(
            (
                retained.index[retained[[spec.outcome, *spec.predictors]].notna().all(axis=1)] + 1
            ).tolist()
        ),
        "imputed_data_rows": sorted((retained.index[retained.isna().any(axis=1)] + 1).tolist()),
        "missing_by_role": {c: int(frame[c].isna().sum()) for c in frame},
        "imputed_cells": [
            {"data_row": int(i + 1), "column": c}
            for c in retained
            for i in sorted(retained.index[retained[c].isna()])
        ],
        "policy": "Exclude declared nonimputable-role missingness only; retain all other eligible subjects in every completed dataset. All-missing rows are rejected before MICE. No structural imputation or subject multiplication.",
        "data_row_numbering": "one-based original source rows, excluding header",
        "sampling_order": "lexical order of canonical unique subject labels; IDs are not model predictors or exported values",
    }
    return retained, ledger, frame_hash


def imputation_preflight(df, spec):
    frame, ledger, frame_hash = prepare_imputation(df, spec)
    return {
        "schema": "imputation-preflight-v1",
        "spec": spec.to_dict(),
        "family": spec.family,
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": frame_hash,
        "n": len(frame),
        "input_rows": ledger["input_rows"],
        "outside_cohort": len(ledger["filter_excluded_data_rows"]),
        "missing_required": len(ledger["missing_excluded_data_rows"]),
        "imputed_subjects": len(ledger["imputed_data_rows"]),
        "imputed_cells": len(ledger["imputed_cells"]),
        "case_ledger": ledger,
        "study_design": spec.study_design,
        "m": spec.m,
        "scope": "Roles, source coding, missing-cell mask and eligible population only; no model fit, proof of MAR, convergence, randomization or clinical validation.",
    }
