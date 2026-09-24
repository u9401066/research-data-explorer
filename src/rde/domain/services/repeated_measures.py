"""Explicit wide-table contract shared by repeated tests and their figures."""

from __future__ import annotations

import hashlib
import json
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

from rde.domain.services.numeric_plausibility import (
    apply_numeric_plausibility_filters,
    format_plausibility_markdown,
)


def prepare_repeated_frame(
    df: pd.DataFrame,
    variables: list[str],
    subject_variable: str | None = None,
    *,
    apply_plausibility: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    """Validate every row before masking, preserving positional subject identity.

    Row numbers count data records from one, excluding the header. The source file
    and worksheet must be retained to resolve them. No column-wise re-pairing,
    imputation or averaging of duplicate subjects is permitted.
    """
    if len(variables) < 2 or len(variables) != len(set(variables)):
        raise ValueError("至少需要兩個不重複的量測欄位。")
    if not df.columns.is_unique:
        raise ValueError("重複量測不接受重複欄名。")
    if any(column not in df for column in variables):
        raise ValueError("指定的量測欄位不存在。")
    subject_hash = None
    if subject_variable is not None:
        if subject_variable not in df or subject_variable in variables:
            raise ValueError("受試者欄位必須存在且不能同時作為量測欄位。")
        subjects = df[subject_variable].astype("string").str.strip()
        if subjects.isna().any() or subjects.eq("").any() or subjects.duplicated().any():
            raise ValueError("受試者識別必須逐列非空且唯一；長格式或重複受試者不可直接分析。")
        subject_hash = hashlib.sha256(
            json.dumps(subjects.tolist(), ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    numeric = df.copy()
    for column in variables:
        source = df[column]
        values = pd.to_numeric(source, errors="coerce")
        # Only native missing values or truly empty cells count as missing.
        present = source.notna() & source.astype("string").str.strip().ne("")
        if (present & values.isna()).any() or np.isinf(values.to_numpy(dtype=float)).any():
            raise ValueError(f"{column} 含非數值或無限值；請修正來源，不能默默當作缺失。")
        numeric[column] = values
    cleaned, findings = (
        apply_numeric_plausibility_filters(numeric, variables)
        if apply_plausibility
        else (numeric, [])
    )
    complete = cleaned[variables].notna().all(axis=1)
    positions = np.arange(1, len(df) + 1)
    observed_masks = sum(
        cleaned[c].notna().astype("int64") * (1 << i) for i, c in enumerate(variables)
    )
    ledger: dict[str, Any] = {
        "row_numbering": "one_based_data_records_excluding_header",
        "subject_variable": subject_variable,
        "subject_order_sha256": subject_hash,
        "input_rows": len(df),
        "variables": variables,
        "raw_observed_by_variable": {c: int(numeric[c].notna().sum()) for c in variables},
        "observed_by_variable": {c: int(cleaned[c].notna().sum()) for c in variables},
        "complete_data_rows": positions[complete].tolist(),
        "excluded_data_rows": positions[~complete].tolist(),
        "observed_bitmask_by_data_row": observed_masks.tolist(),
        "bitmask_order": "bit 0 = first variable; 1 means observed after plausibility filtering",
        "pairwise": [
            {
                "variables": [a, b],
                "complete_cases": int(cleaned[[a, b]].notna().all(axis=1).sum()),
            }
            for a, b in combinations(variables, 2)
        ],
        "plausibility_exclusions": [
            {
                "variable": c,
                "data_rows": positions[numeric[c].notna() & cleaned[c].isna()].tolist(),
            }
            for c in variables
            if (numeric[c].notna() & cleaned[c].isna()).any()
        ],
    }
    return cleaned, ledger, format_plausibility_markdown(findings)
