"""Explicit, auditable case sets and within-call inference policies."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def validate_policy(alpha: float, missing_strategy: str, multiplicity: str) -> None:
    if not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("alpha must be finite and strictly between 0 and 1.")
    if missing_strategy not in {"listwise", "pairwise"}:
        raise ValueError("missing_strategy must be listwise or pairwise; no implicit imputation.")
    if multiplicity not in {"bonferroni", "holm", "fdr"}:
        raise ValueError("multiple_comparison_method must be bonferroni, holm or fdr (BH).")


def finite_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Keep positional identity, map non-finite numeric observations to missing."""
    if not df.columns.is_unique or any(c not in df.columns for c in columns):
        raise ValueError("Analysis columns must exist and column names must be unique.")
    frame = df.copy()
    for column in columns:
        if pd.api.types.is_numeric_dtype(frame[column]):
            frame[column] = frame[column].replace([np.inf, -np.inf], np.nan)
    return frame


def case_record(df: pd.DataFrame, columns: list[str], mask: pd.Series, strategy: str) -> dict:
    return {
        "strategy": strategy,
        "variables": columns,
        "n_input": len(df),
        "n_analyzed": int(mask.sum()),
        "n_excluded": int((~mask).sum()),
        "missing_by_variable": {c: int(df[c].isna().sum()) for c in columns},
        "included_row_positions": np.flatnonzero(mask.to_numpy()).tolist(),
        "row_position_base": 0,
    }


def correlation_with_cases(df: pd.DataFrame, columns: list[str], strategy: str) -> dict:
    validate_policy(0.05, strategy, "holm")
    frame = finite_frame(df, columns)
    complete = frame[columns].notna().all(axis=1)
    source = frame.loc[complete, columns] if strategy == "listwise" else frame[columns]
    cases = {}
    for i, a in enumerate(columns):
        for b in columns[i:]:
            mask = complete if strategy == "listwise" else frame[[a, b]].notna().all(axis=1)
            cases[f"{a} / {b}"] = case_record(frame, list(dict.fromkeys([a, b])), mask, strategy)
    return {"matrix": source.corr(), "case_sets": cases, "missing_strategy": strategy}
