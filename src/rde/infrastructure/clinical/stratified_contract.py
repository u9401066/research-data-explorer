"""Prespecified binary strata, independent identities and a shared case ledger.

This contract never estimates treatment effects or infers randomization.  A
composite stratum must already exist as a provenance-bound preparation output.
"""

from dataclasses import asdict, dataclass, fields

import numpy as np
import pandas as pd

from .measurement import _labels, _number, _text
from .survival import digest, level


@dataclass(frozen=True)
class StratifiedSpec:
    subject: str
    treatment: str
    treatment_levels: list[str]
    treatment_definition: str
    outcome: str
    outcome_levels: list[str]
    outcome_definition: str
    outcome_window: str
    strata: str
    strata_levels: list[str]
    context: str
    study_design: str
    independent_rows: bool
    missing_strategy: str
    family: str = "stratified"
    confidence_level: float = 0.95

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown stratified settings; use the exact binary CMH contract.")
        try:
            spec = cls(**options)
        except TypeError as error:
            raise ValueError(f"Missing stratified settings: {error}") from error
        spec.validate()
        return spec

    def to_dict(self):
        return asdict(self)

    def variables(self):
        return [self.subject, self.treatment, self.outcome, self.strata]

    def validate(self):
        if self.family != "stratified" or self.independent_rows is not True:
            raise ValueError(
                "Binary CMH requires independent subjects within and between strata; "
                "matched, repeated and cluster-randomized observations need another contract."
            )
        for name in [
            "subject",
            "treatment",
            "outcome",
            "strata",
            "treatment_definition",
            "outcome_definition",
            "outcome_window",
            "context",
        ]:
            _text(
                getattr(self, name),
                name,
                5 if name.endswith("definition") or name in {"outcome_window", "context"} else 1,
            )
        if len(set(self.variables())) != 4:
            raise ValueError(
                "Subject, treatment, outcome and strata must be distinct source roles."
            )
        for name in ["treatment_levels", "outcome_levels"]:
            _labels(getattr(self, name), name, 2)
            if len(getattr(self, name)) != 2:
                raise ValueError(
                    "Declare two treatment labels [reference, exposed] and two outcome "
                    "labels [non-event, event]; no inferred event or treatment direction."
                )
        _labels(self.strata_levels, "strata levels", 50)
        if not 2 <= len(self.strata_levels) <= 50:
            raise ValueError("Prespecify 2..50 exact strata labels, including any empty strata.")
        if self.study_design not in {
            "randomized_parallel",
            "observational_cohort",
            "cross_sectional",
            "case_control",
            "unspecified",
        }:
            raise ValueError(
                "Declare the actual study design; only independent-case OR is estimated."
            )
        if self.missing_strategy != "complete_case":
            raise ValueError(
                "Prespecify missing_strategy='complete_case'; no imputation is performed."
            )
        _number(self.confidence_level, "confidence level")
        if not 0.8 <= self.confidence_level <= 0.999:
            raise ValueError("Confidence level must be between 0.8 and 0.999.")


def prepare_stratified(df, spec: StratifiedSpec):
    spec.validate()
    columns = spec.variables()
    if not df.columns.is_unique or any(column not in df for column in columns):
        raise ValueError("Every stratified role must exist in uniquely named source columns.")
    if not 10 <= len(df) <= 100_000:
        raise ValueError("CMH accepts 10..100,000 source cases; this is not a power criterion.")
    selected = df[columns].reset_index(drop=True).copy()
    rows = []
    for row in selected.itertuples(index=False, name=None):
        values = []
        for value in row:
            if not pd.api.types.is_scalar(value):
                raise ValueError("Stratified source cells must be scalar original labels.")
            values.append(
                None if pd.isna(value) else value.item() if isinstance(value, np.generic) else value
            )
        rows.append(values)
    try:
        source_hash = digest({"columns": columns, "rows": rows})
    except (ValueError, TypeError) as error:
        raise ValueError(
            "Unsupported or nonfinite source values require explicit correction."
        ) from error

    # Validate identities and all observed codes before removing incomplete rows.
    identities = selected[spec.subject].map(level)
    if identities.isna().any() or identities.duplicated().any():
        raise ValueError(
            "Missing or duplicate subject identity must be resolved before complete-case exclusion."
        )
    treatment = selected[spec.treatment].map(level)
    outcome = selected[spec.outcome].map(level)
    strata = selected[spec.strata].map(level)
    for role, values, declared in [
        ("treatment", treatment, spec.treatment_levels),
        ("outcome", outcome, spec.outcome_levels),
        ("strata", strata, spec.strata_levels),
    ]:
        if set(values.dropna()) - set(declared):
            raise ValueError(
                f"Undeclared {role} label, including incomplete rows; no implicit recoding or merging."
            )
    frame = pd.DataFrame({"treatment": treatment, "outcome": outcome, "stratum": strata})
    complete = frame.notna().all(axis=1)
    retained = frame.loc[complete].copy()
    ledger = {
        "input_rows": len(df),
        "cohort_rows": len(df),
        "n": len(retained),
        "filter_excluded_data_rows": [],
        "missing_excluded_data_rows": (frame.index[~complete] + 1).tolist(),
        "complete_data_rows": (retained.index + 1).tolist(),
        "missing_by_role": {
            spec.treatment: int(treatment.isna().sum()),
            spec.outcome: int(outcome.isna().sum()),
            spec.strata: int(strata.isna().sum()),
        },
        "strata_counts": [
            {
                "label": label,
                "source_rows": int((strata == label).sum()),
                "complete_rows": int((retained.stratum == label).sum()),
            }
            for label in spec.strata_levels
        ],
        "identity_checked_rows": len(df),
        "policy": (
            "One independent unique subject per source row; all observed source codes checked "
            "before shared complete-case exclusion; no matching, imputation, stratum dropping, "
            "category merging or zero-cell correction."
        ),
        "data_row_numbering": "one-based source rows, excluding header",
    }
    return retained, ledger, source_hash


def stratified_tables(frame, spec):
    """Retain every declared stratum; counts/expected counts only, no inference."""
    summaries = []
    for label in spec.strata_levels:
        subset = frame.loc[frame.stratum == label]
        counts = np.array(
            [
                [
                    int(((subset.treatment == arm) & (subset.outcome == outcome)).sum())
                    for outcome in spec.outcome_levels
                ]
                for arm in spec.treatment_levels
            ],
            dtype=int,
        )
        total = int(counts.sum())
        row_totals, column_totals = counts.sum(axis=1), counts.sum(axis=0)
        reasons = []
        if total < 2:
            reasons.append("fewer_than_two_complete_subjects")
        if (row_totals == 0).any():
            reasons.append("zero_treatment_margin")
        if (column_totals == 0).any():
            reasons.append("zero_outcome_margin")
        expected = np.outer(row_totals, column_totals) / total if total else None
        summaries.append(
            {
                "label": label,
                "n": total,
                "table": counts.tolist(),
                "row_levels": spec.treatment_levels,
                "column_levels": spec.outcome_levels,
                "expected_under_independence": expected.tolist() if expected is not None else None,
                "zero_cells": int((counts == 0).sum()),
                "expected_cells_below_five": int((expected < 5).sum())
                if expected is not None
                else 4,
                "blocking_reasons": reasons,
                "data_rows": (subset.index + 1).tolist(),
            }
        )
    return summaries


def stratified_preflight(df, spec):
    frame, ledger, source_hash = prepare_stratified(df, spec)
    summaries = stratified_tables(frame, spec)
    blockers = [
        {"stratum": item["label"], "reasons": item["blocking_reasons"]}
        for item in summaries
        if item["blocking_reasons"]
    ]
    return {
        "schema": "stratified-preflight-v1",
        "spec": spec.to_dict(),
        "case_ledger": ledger,
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": source_hash,
        "n": len(frame),
        "input_rows": ledger["input_rows"],
        "outside_cohort": 0,
        "missing_required": len(ledger["missing_excluded_data_rows"]),
        "strata": summaries,
        "blocking_strata": blockers,
        "minimum_complete_cases_met": len(frame) >= 10,
        "can_execute": len(frame) >= 10 and not blockers,
        "scope": (
            "Labels, identities, shared complete cases and every declared 2x2 table only; "
            "no effects, intervals or p-values. Sparse expected counts remain visible and "
            "require review of asymptotic inference; randomization/causal validity are not verified."
        ),
    }
