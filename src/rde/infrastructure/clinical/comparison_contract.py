"""Explicit outcome, group direction and planned contrasts for independent cases."""

from dataclasses import asdict, dataclass, field, fields

import numpy as np
import pandas as pd

from .measurement import _labels, _number, _text
from .survival import digest, level, numeric


@dataclass(frozen=True)
class ComparisonSpec:
    outcome: str
    group: str
    group_levels: list[str]
    contrasts: list[list[str]]
    method: str
    primary_effect: str
    outcome_unit: str
    outcome_definition: str
    outcome_window: str
    context: str
    study_design: str
    independent_rows: bool
    family: str = "comparison"
    subject: str | None = None
    outcome_levels: list[str] = field(default_factory=list)
    confidence_level: float = 0.95
    multiplicity: str = "holm"
    omnibus: bool = False
    bootstrap: dict | None = None
    cohort_filter: dict | None = None

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown comparison settings; use the explicit study contract.")
        try:
            spec = cls(**options)
        except TypeError as error:
            raise ValueError(f"Missing comparison settings: {error}") from error
        spec.validate()
        return spec

    def to_dict(self):
        return asdict(self)

    def variables(self):
        return list(
            dict.fromkeys(
                [self.outcome, self.group]
                + [
                    v
                    for v in [
                        self.subject,
                        self.cohort_filter["column"] if self.cohort_filter else None,
                    ]
                    if v is not None
                ]
            )
        )

    def validate(self):
        if self.family != "comparison" or self.independent_rows is not True:
            raise ValueError(
                "Comparison requires explicitly independent source cases; use the paired/clustered workflow otherwise."
            )
        for name in [
            "outcome",
            "group",
            "outcome_unit",
            "outcome_definition",
            "outcome_window",
            "context",
        ]:
            _text(getattr(self, name), name, 5 if name in {"context", "outcome_definition"} else 1)
        if self.subject is not None:
            _text(self.subject, "subject")
        roles = [v for v in [self.outcome, self.group, self.subject] if v is not None]
        if len(set(roles)) != len(roles):
            raise ValueError("Outcome, group and subject roles must be distinct.")
        _labels(self.group_levels, "group levels", 8)
        if len(self.group_levels) < 2:
            raise ValueError("Declare 2..8 exact group labels in display order.")
        if not isinstance(self.contrasts, list) or not 1 <= len(self.contrasts) <= 12:
            raise ValueError("Prespecify 1..12 ordered group contrasts; no data-selected pairs.")
        seen = set()
        for pair in self.contrasts:
            _labels(pair, "contrast", 2)
            if len(pair) != 2 or not set(pair) <= set(self.group_levels):
                raise ValueError(
                    "Each contrast needs two distinct declared group labels: first minus second, or first / second."
                )
            identity = frozenset(pair)
            if identity in seen:
                raise ValueError(
                    "Repeated or reversed duplicate contrasts are not distinct hypotheses."
                )
            seen.add(identity)
        if self.study_design not in {
            "randomized_parallel",
            "observational_cohort",
            "cross_sectional",
            "case_control",
            "unspecified",
        }:
            raise ValueError("Declare the actual sampling design, or explicitly unspecified.")
        methods = {
            "welch_mean": {"mean_difference"},
            "rank": {"rank_biserial"},
            "binary": {"proportion_difference", "proportion_ratio", "odds_ratio"},
        }
        if self.method not in methods or self.primary_effect not in methods[self.method]:
            raise ValueError("The primary effect must match the prespecified comparison method.")
        _labels(self.outcome_levels, "outcome levels", 2)
        if self.method == "binary":
            if len(self.outcome_levels) != 2:
                raise ValueError("Binary comparison requires [non-event, event] source labels.")
            if (
                self.study_design in {"case_control", "unspecified"}
                and self.primary_effect != "odds_ratio"
            ):
                raise ValueError(
                    "Case-control or unspecified sampling does not identify event probability differences or ratios; use odds ratio or clarify the sampling design."
                )
        elif self.outcome_levels:
            raise ValueError(
                "Only binary comparisons accept event labels; rank outcomes use an explicitly numeric ordered scale."
            )
        if self.study_design == "case_control" and self.method != "binary":
            raise ValueError(
                "This case-control comparison contract supports binary odds ratios only."
            )
        if self.method == "rank":
            if not isinstance(self.bootstrap, dict) or set(self.bootstrap) != {"resamples", "seed"}:
                raise ValueError("Rank comparisons require prespecified BCa resamples and seed.")
            if (
                type(self.bootstrap["resamples"]) is not int
                or not 999 <= self.bootstrap["resamples"] <= 19999
            ):
                raise ValueError("Specify 999..19999 BCa resamples.")
            if type(self.bootstrap["seed"]) is not int or not 0 <= self.bootstrap["seed"] < 2**32:
                raise ValueError("Specify an unsigned 32-bit bootstrap seed.")
        elif self.bootstrap is not None:
            raise ValueError("Bootstrap settings apply only to the rank comparison method.")
        _number(self.confidence_level, "confidence level")
        if not 0.8 <= self.confidence_level <= 0.999:
            raise ValueError("Confidence level must be between 0.8 and 0.999.")
        if self.multiplicity not in {"holm", "bonferroni", "fdr"}:
            raise ValueError("Prespecify Holm, Bonferroni or Benjamini–Hochberg (fdr).")
        if type(self.omnibus) is not bool or self.omnibus and len(self.group_levels) < 3:
            raise ValueError(
                "An optional omnibus test requires at least three groups; do not duplicate a two-group test."
            )
        if self.cohort_filter is not None:
            if not isinstance(self.cohort_filter, dict) or set(self.cohort_filter) != {
                "column",
                "values",
            }:
                raise ValueError(
                    "A cohort restriction needs its exact source column and included values."
                )
            _text(self.cohort_filter["column"], "cohort column")
            _labels(self.cohort_filter["values"], "included cohort values")
            if not self.cohort_filter["values"] or self.cohort_filter["column"] == self.outcome:
                raise ValueError(
                    "Specify a nonempty cohort restriction independent of the outcome."
                )


def prepare_comparison(df, spec):
    spec.validate()
    columns = spec.variables()
    if not df.columns.is_unique or any(column not in df for column in columns):
        raise ValueError("Every comparison role must exist in uniquely named source columns.")
    if not 10 <= len(df) <= 100_000:
        raise ValueError(
            "Comparison accepts 10..100,000 source cases; this is an execution limit, not a power calculation."
        )
    selected = df[columns].reset_index(drop=True).copy()
    rows = [
        [None if pd.isna(v) else v.item() if isinstance(v, np.generic) else v for v in row]
        for row in selected.itertuples(index=False, name=None)
    ]
    try:
        source_hash = digest({"columns": columns, "rows": rows})
    except (ValueError, TypeError) as error:
        raise ValueError(
            "Unsupported or nonfinite source values require explicit correction."
        ) from error
    cohort = pd.Series(True, index=selected.index)
    if spec.cohort_filter:
        cohort = (
            selected[spec.cohort_filter["column"]].map(level).isin(spec.cohort_filter["values"])
        )
    working = selected.loc[cohort]
    if spec.subject:
        identities = working[spec.subject].map(level)
        if identities.isna().any() or identities.duplicated().any():
            raise ValueError(
                "Missing or duplicate subject identity must be resolved before missing-outcome exclusion."
            )
    group = working[spec.group].map(level)
    if set(group.dropna()) - set(spec.group_levels):
        raise ValueError(
            "Undeclared group label, including rows with missing outcomes; no implicit recoding."
        )
    if spec.method == "binary":
        outcome = working[spec.outcome].map(level)
        if set(outcome.dropna()) - set(spec.outcome_levels):
            raise ValueError(
                "Undeclared outcome label, including rows with missing groups; no implicit event coding."
            )
        outcome = outcome.map({label: i for i, label in enumerate(spec.outcome_levels)})
    else:
        outcome = numeric(working[spec.outcome], spec.outcome)
    frame = pd.DataFrame({"response": outcome, "group": group})
    complete = frame.notna().all(axis=1)
    retained = frame.loc[complete].copy()
    counts = [int((retained.group == label).sum()) for label in spec.group_levels]
    if len(retained) < 10 or min(counts) < 2:
        raise ValueError(
            "Retain at least ten complete independent cases and two in every declared group; not a power criterion."
        )
    if spec.omnibus and spec.method == "binary":
        table = np.array(
            [
                [
                    int(((retained.group == group) & (retained.response == event)).sum())
                    for group in spec.group_levels
                ]
                for event in (0, 1)
            ]
        )
        expected = np.outer(table.sum(axis=1), table.sum(axis=0)) / len(retained)
        if np.any(expected < 5):
            raise ValueError(
                "The requested multi-group Pearson omnibus has sparse expected cells. Review the plan for an exact/permutation omnibus or explicitly retain only planned two-group contrasts."
            )
    ledger = {
        "input_rows": len(df),
        "cohort_rows": int(cohort.sum()),
        "n": len(retained),
        "filter_excluded_data_rows": (selected.index[~cohort] + 1).tolist(),
        "missing_excluded_data_rows": (frame.index[~complete] + 1).tolist(),
        "complete_data_rows": (retained.index + 1).tolist(),
        "missing_by_role": {name: int(frame[name].isna().sum()) for name in frame},
        "policy": "One complete-case cohort for the outcome and group, then explicitly prespecified contrasts; no imputation, case matching, category merging or data-selected contrast.",
        "data_row_numbering": "one-based source rows, excluding header",
    }
    return retained, ledger, source_hash


def comparison_preflight(df, spec):
    frame, ledger, source_hash = prepare_comparison(df, spec)
    return {
        "schema": "comparison-preflight-v1",
        "spec": spec.to_dict(),
        "case_ledger": ledger,
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": source_hash,
        "n": len(frame),
        "input_rows": ledger["input_rows"],
        "outside_cohort": len(ledger["filter_excluded_data_rows"]),
        "missing_required": len(ledger["missing_excluded_data_rows"]),
        "groups": [
            {"label": label, "n": int((frame.group == label).sum())} for label in spec.group_levels
        ],
        "contrasts": spec.contrasts,
        "planned_hypotheses": len(spec.contrasts) + int(spec.omnibus),
        "scope": "Source labels, identities and included cases only; no effect estimates, intervals or p-values, and no verified randomization or causal assumptions.",
    }
