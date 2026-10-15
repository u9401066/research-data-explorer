"""Explicit independent-case noninferiority margins, direction and populations."""

from dataclasses import asdict, dataclass, fields
import math

import numpy as np
import pandas as pd

from .measurement import _labels, _number, _text
from .survival import digest, level, numeric


@dataclass(frozen=True)
class NoninferioritySpec:
    subject: str
    treatment: str
    treatment_levels: list[str]
    treatment_definition: str
    outcome: str
    outcome_definition: str
    outcome_window: str
    outcome_unit: str
    method: str
    direction: str
    margin: float
    margin_scale: str
    margin_basis: str
    population_definition: str
    context: str
    study_design: str
    independent_rows: bool
    missing_strategy: str
    one_sided_alpha: float
    family: str = "noninferiority"
    confidence_level: float = 0.975

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) - {f.name for f in fields(cls)}:
            raise ValueError(
                "Unknown noninferiority settings; use the exact independent-case contract."
            )
        try:
            spec = cls(**options)
        except TypeError as error:
            raise ValueError(f"Missing noninferiority settings: {error}") from error
        spec.validate()
        return spec

    def to_dict(self):
        return asdict(self)

    def variables(self):
        return [self.subject, self.treatment, self.outcome]

    def validate(self):
        if self.family != "noninferiority" or self.independent_rows is not True:
            raise ValueError(
                "Noninferiority requires explicitly independent subjects, not paired or clustered rows."
            )
        for name in [
            "subject",
            "treatment",
            "outcome",
            "treatment_definition",
            "outcome_definition",
            "outcome_window",
            "outcome_unit",
            "margin_basis",
            "population_definition",
            "context",
        ]:
            _text(
                getattr(self, name),
                name,
                10
                if name in {"margin_basis", "population_definition"}
                else 5
                if name
                in {"treatment_definition", "outcome_definition", "outcome_window", "context"}
                else 1,
            )
        if len(set(self.variables())) != 3:
            raise ValueError("Subject, treatment and outcome must have distinct source roles.")
        _labels(self.treatment_levels, "treatment levels", 2)
        if len(self.treatment_levels) != 2:
            raise ValueError("Declare exactly [control, treatment] original source labels.")
        if self.method == "binary_risk_difference":
            raise ValueError(
                "Binary risk-difference noninferiority is unsupported in this release; no Wald, Welch or pseudo-count fallback."
            )
        if self.method != "welch_mean":
            raise ValueError(
                "Only welch_mean noninferiority is supported; no implicit method substitution."
            )
        if self.direction not in {"higher_is_better", "lower_is_better"}:
            raise ValueError(
                "Prespecify higher_is_better or lower_is_better from the research question."
            )
        for name in ["margin", "one_sided_alpha", "confidence_level"]:
            _number(getattr(self, name), name)
        if self.margin <= 0:
            raise ValueError("The prespecified noninferiority margin must be strictly positive.")
        if not 0 < self.one_sided_alpha < 0.5 or not 0.5 < self.confidence_level < 1:
            raise ValueError(
                "Specify 0 < one_sided_alpha < .5 and .5 < one-sided confidence_level < 1."
            )
        if not math.isclose(
            self.confidence_level, 1 - self.one_sided_alpha, rel_tol=0, abs_tol=1e-12
        ):
            raise ValueError("confidence_level is ONE-SIDED and must equal 1 - one_sided_alpha.")
        if self.margin_scale != "outcome_unit":
            raise ValueError(
                "Welch NI requires margin_scale='outcome_unit', on the original continuous outcome scale."
            )
        if self.study_design not in {
            "randomized_parallel",
            "observational_cohort",
            "cross_sectional",
        }:
            raise ValueError(
                "Declare independent parallel/cohort/cross-sectional sampling; case-control risks are not identified."
            )
        if self.missing_strategy != "complete_case":
            raise ValueError(
                "This contract requires explicit complete_case; no outcome imputation or implicit ITT/PP population."
            )


def prepare_noninferiority(df, spec: NoninferioritySpec):
    spec.validate()
    columns = spec.variables()
    if not df.columns.is_unique or any(column not in df for column in columns):
        raise ValueError("Every NI role must exist in uniquely named source columns.")
    if not 10 <= len(df) <= 100_000:
        raise ValueError(
            "Noninferiority accepts 10..100,000 source cases; this is not a sample-size justification."
        )
    selected = df[columns].reset_index(drop=True).copy()
    rows = []
    for row in selected.itertuples(index=False, name=None):
        values = []
        for value in row:
            if not pd.api.types.is_scalar(value):
                raise ValueError("NI source cells must be scalar original values.")
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
    identities = selected[spec.subject].map(level)
    if identities.isna().any() or identities.duplicated().any():
        raise ValueError(
            "Missing or duplicate subject identity must be resolved before missing-outcome exclusion."
        )
    treatment = selected[spec.treatment].map(level)
    if set(treatment.dropna()) - set(spec.treatment_levels):
        raise ValueError("Undeclared treatment label, including rows with missing outcomes.")
    outcome = numeric(selected[spec.outcome], spec.outcome)
    frame = pd.DataFrame({"treatment": treatment, "response": outcome})
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
        },
        "identity_checked_rows": len(df),
        "population_definition": spec.population_definition,
        "population_membership_verification": "not_performed",
        "policy": "Shared complete-case population after source identity and coding checks; no imputation, matching or automatic ITT/PP classification.",
        "data_row_numbering": "one-based source rows, excluding header",
    }
    return retained, ledger, source_hash


def noninferiority_groups(frame, spec):
    groups, blockers = [], []
    for index, label in enumerate(spec.treatment_levels):
        sample = frame.loc[frame.treatment == label, "response"]
        summary = {
            "label": label,
            "role": "control" if index == 0 else "treatment",
            "n": len(sample),
            "data_rows": (sample.index + 1).tolist(),
        }
        if len(sample) < 2:
            blockers.append({"group": label, "reason": "fewer_than_two_complete_subjects"})
        with np.errstate(all="ignore"):
            variance = float(sample.var(ddof=1)) if len(sample) > 1 else None
        summary["sample_variance"] = (
            variance if variance is not None and math.isfinite(variance) else None
        )
        if variance is None or not math.isfinite(variance) or variance <= 0:
            blockers.append({"group": label, "reason": "nonpositive_or_nonfinite_sample_variance"})
        groups.append(summary)
    if frame.response.nunique() <= 2:
        blockers.append(
            {
                "group": None,
                "reason": "fewer_than_three_distinct_values_not_a_supported_continuous_outcome",
            }
        )
    return groups, blockers


def noninferiority_preflight(df, spec):
    frame, ledger, source_hash = prepare_noninferiority(df, spec)
    groups, blockers = noninferiority_groups(frame, spec)
    return {
        "schema": "noninferiority-preflight-v1",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": source_hash,
        "case_ledger": ledger,
        "n": len(frame),
        "input_rows": ledger["input_rows"],
        "outside_cohort": 0,
        "missing_required": len(ledger["missing_excluded_data_rows"]),
        "groups": groups,
        "blocking_groups": blockers,
        "minimum_complete_cases_met": len(frame) >= 10,
        "can_execute": len(frame) >= 10 and not blockers,
        "scope": "Coding, identities, complete-case counts and estimator boundary checks only. No test, CI, margin justification or ITT/PP verification is performed.",
    }
