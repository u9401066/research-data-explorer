"""Prespecified within-person contrasts with explicit complete-case populations."""

from dataclasses import asdict, dataclass, fields

import numpy as np
import pandas as pd

from .measurement import _labels, _number, _text
from .survival import digest, level, numeric


@dataclass(frozen=True)
class RepeatedSpec:
    subject: str
    measurements: list[dict]
    contrasts: list[list[str]]
    outcome_name: str
    outcome_unit: str
    outcome_definition: str
    context: str
    method: str
    primary_effect: str
    case_strategy: str
    independent_subjects: bool
    same_outcome: bool
    family: str = "repeated"
    confidence_level: float = 0.95
    multiplicity: str = "bonferroni"
    omnibus: bool = False
    bootstrap: dict | None = None
    cohort_filter: dict | None = None

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown repeated-study settings; use the explicit contract.")
        try:
            spec = cls(**options)
        except TypeError as error:
            raise ValueError(f"Missing repeated-study settings: {error}") from error
        spec.validate()
        return spec

    def to_dict(self):
        return asdict(self)

    def columns(self):
        return [item["column"] for item in self.measurements]

    def variables(self):
        return list(
            dict.fromkeys(
                [self.subject, *self.columns()]
                + ([self.cohort_filter["column"]] if self.cohort_filter else [])
            )
        )

    def validate(self):
        if (
            self.family != "repeated"
            or self.independent_subjects is not True
            or self.same_outcome is not True
        ):
            raise ValueError(
                "Confirm independent subjects and the same measured outcome/units at every occasion."
            )
        for name in ["subject", "outcome_name", "outcome_unit", "outcome_definition", "context"]:
            _text(getattr(self, name), name, 5 if name in {"outcome_definition", "context"} else 1)
        if not isinstance(self.measurements, list) or not 2 <= len(self.measurements) <= 8:
            raise ValueError("Prespecify 2..8 ordered measurement columns and occasion labels.")
        for item in self.measurements:
            if not isinstance(item, dict) or set(item) != {"column", "label"}:
                raise ValueError("Every occasion requires exactly column and label.")
            _text(item["column"], "measurement column")
            _text(item["label"], "occasion label")
        columns = self.columns()
        if len(set([self.subject, *columns])) != len(columns) + 1 or len(
            {m["label"] for m in self.measurements}
        ) != len(columns):
            raise ValueError("Subject, measurement columns and occasion labels must be distinct.")
        if not isinstance(self.contrasts, list) or not 1 <= len(self.contrasts) <= 28:
            raise ValueError("Prespecify 1..28 directional within-person contrasts.")
        seen = set()
        for pair in self.contrasts:
            _labels(pair, "contrast columns", 2)
            if len(pair) != 2 or not set(pair) <= set(columns):
                raise ValueError(
                    "A contrast requires two distinct measurement columns: first minus second."
                )
            if frozenset(pair) in seen:
                raise ValueError(
                    "Duplicate or reversed duplicate contrasts are not new hypotheses."
                )
            seen.add(frozenset(pair))
        methods = {"paired_mean": "mean_difference", "signed_rank": "rank_biserial"}
        if self.method not in methods or self.primary_effect != methods[self.method]:
            raise ValueError("The primary effect must match the prespecified paired method.")
        if (
            self.case_strategy not in {"complete", "pairwise"}
            or len(columns) == 2
            and self.case_strategy != "complete"
        ):
            raise ValueError(
                "Choose common complete or pairwise complete subjects; two occasions require complete."
            )
        if (
            type(self.omnibus) is not bool
            or self.omnibus
            and (len(columns) < 3 or self.method != "signed_rank")
        ):
            raise ValueError(
                "Optional Friedman inference requires at least three occasions and the signed-rank workflow."
            )
        _number(self.confidence_level, "confidence level")
        if not 0.8 <= self.confidence_level <= 0.999:
            raise ValueError("Confidence level must be between 0.8 and 0.999.")
        if self.multiplicity not in {"holm", "bonferroni", "fdr"}:
            raise ValueError("Prespecify Holm, Bonferroni or Benjamini-Hochberg correction.")
        if self.method == "signed_rank":
            if not isinstance(self.bootstrap, dict) or set(self.bootstrap) != {"resamples", "seed"}:
                raise ValueError("Signed-rank effects require fixed BCa resamples and seed.")
            if (
                type(self.bootstrap["resamples"]) is not int
                or not 999 <= self.bootstrap["resamples"] <= 19999
            ):
                raise ValueError("Specify 999..19999 BCa resamples.")
            if type(self.bootstrap["seed"]) is not int or not 0 <= self.bootstrap["seed"] < 2**32:
                raise ValueError("Specify an unsigned 32-bit seed.")
        elif self.bootstrap is not None:
            raise ValueError("Bootstrap settings belong to the signed-rank workflow.")
        if self.cohort_filter is not None:
            if not isinstance(self.cohort_filter, dict) or set(self.cohort_filter) != {
                "column",
                "values",
            }:
                raise ValueError(
                    "A cohort restriction needs its source column and included values."
                )
            _text(self.cohort_filter["column"], "cohort column")
            _labels(self.cohort_filter["values"], "cohort labels")
            if not self.cohort_filter["values"] or self.cohort_filter["column"] in columns:
                raise ValueError(
                    "Cohort restriction must be nonempty and independent of measured outcomes."
                )


def prepare_repeated(df, spec):
    spec.validate()
    if not df.columns.is_unique or any(c not in df for c in spec.variables()):
        raise ValueError("All repeated-study roles require uniquely named source columns.")
    if not 10 <= len(df) <= 100_000:
        raise ValueError(
            "Repeated studies accept 10..100,000 source rows; this is not a power criterion."
        )
    source = df[spec.variables()].reset_index(drop=True).copy()
    rows = [
        [None if pd.isna(v) else v.item() if isinstance(v, np.generic) else v for v in row]
        for row in source.itertuples(index=False, name=None)
    ]
    try:
        frame_hash = digest({"columns": spec.variables(), "rows": rows})
    except (ValueError, TypeError) as error:
        raise ValueError("Nonfinite or unsupported source values require correction.") from error
    cohort = pd.Series(True, index=source.index)
    if spec.cohort_filter:
        cohort = source[spec.cohort_filter["column"]].map(level).isin(spec.cohort_filter["values"])
    selected = source.loc[cohort]
    subjects = selected[spec.subject].map(level)
    if subjects.isna().any() or subjects.duplicated().any():
        raise ValueError(
            "Resolve missing or duplicate subject identities before excluding incomplete measurements."
        )
    frame = pd.DataFrame({c: numeric(selected[c], c) for c in spec.columns()})
    complete = frame.notna().all(axis=1)
    if int(complete.sum()) < 5:
        raise ValueError(
            "At least five common complete subjects are required for this wide study; not a power criterion."
        )
    pairs = []
    for i, pair in enumerate(spec.contrasts):
        included = complete if spec.case_strategy == "complete" else frame[pair].notna().all(axis=1)
        pairs.append(
            {
                "id": f"contrast_{i+1}",
                "columns": pair,
                "n": int(included.sum()),
                "complete_data_rows": (frame.index[included] + 1).tolist(),
                "missing_excluded_data_rows": (frame.index[~included] + 1).tolist(),
            }
        )
    ledger = {
        "input_rows": len(df),
        "cohort_rows": int(cohort.sum()),
        "n": int(complete.sum()),
        "filter_excluded_data_rows": (source.index[~cohort] + 1).tolist(),
        "missing_excluded_data_rows": (frame.index[~complete] + 1).tolist(),
        "complete_data_rows": (frame.index[complete] + 1).tolist(),
        "missing_by_role": {c: int(frame[c].isna().sum()) for c in frame},
        "observed_by_occasion": {c: int(frame[c].notna().sum()) for c in frame},
        "observed_bitmask_by_cohort_row": sum(
            frame[c].notna().astype("int64") * (1 << i) for i, c in enumerate(frame)
        ).tolist(),
        "cohort_data_rows": (frame.index + 1).tolist(),
        "subject_order_sha256": digest(subjects.tolist()),
        "contrasts": pairs,
        "policy": "Common complete subjects for occasion summaries and Friedman; each fixed contrast follows the declared complete/pairwise strategy. No imputation or column-name-based plausibility masking.",
        "data_row_numbering": "one-based source rows, excluding header",
    }
    return frame, ledger, frame_hash


def repeated_preflight(df, spec):
    _frame, ledger, frame_hash = prepare_repeated(df, spec)
    return {
        "schema": "repeated-preflight-v2",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": frame_hash,
        "n": ledger["n"],
        "input_rows": ledger["input_rows"],
        "case_ledger": ledger,
        "planned_hypotheses": len(spec.contrasts) + int(spec.omnibus),
        "scope": "Source, pairing and declared denominators only; no effect estimates or p-values; does not verify clinical assumptions.",
    }
