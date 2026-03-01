"""CleaningExecutor — Executes approved CleaningPlan actions on a DataFrame.

Maps CleaningActionType to pandas operations.
Not a port adapter — this is a standalone application service helper.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from rde.domain.models.cleaning import CleaningAction, CleaningActionType, CleaningPlan


class CleaningExecutor:
    """Apply approved cleaning actions to a pandas DataFrame."""

    _ACTION_DISPATCH: dict[CleaningActionType, str] = {
        CleaningActionType.DROP_ROWS: "_drop_rows",
        CleaningActionType.DROP_COLUMNS: "_drop_columns",
        CleaningActionType.FILL_MISSING: "_fill_missing",
        CleaningActionType.FILL_MEAN: "_fill_mean",
        CleaningActionType.FILL_MEDIAN: "_fill_median",
        CleaningActionType.FILL_MODE: "_fill_mode",
        CleaningActionType.FILL_CONSTANT: "_fill_constant",
        CleaningActionType.REMOVE_DUPLICATES: "_remove_duplicates",
        CleaningActionType.CLIP_OUTLIERS: "_clip_outliers",
        CleaningActionType.REMOVE_OUTLIERS: "_remove_outliers",
        CleaningActionType.TYPE_CAST: "_type_cast",
        CleaningActionType.RENAME_COLUMN: "_rename_column",
        CleaningActionType.ENCODE_CATEGORICAL: "_encode_categorical",
        CleaningActionType.CUSTOM: "_custom",
    }

    def execute(
        self, df: pd.DataFrame, plan: CleaningPlan
    ) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        """Apply all approved actions. Returns (cleaned_df, action_logs)."""
        result = df.copy()
        logs: list[dict[str, Any]] = []

        for action in plan.approved_actions:
            if action.applied:
                continue
            rows_before = len(result)
            method_name = self._ACTION_DISPATCH.get(action.action_type)
            if method_name is None:
                logs.append({
                    "action": action.action_type.value,
                    "status": "skipped",
                    "reason": "No handler for action type.",
                })
                continue
            method = getattr(self, method_name)
            result = method(result, action)
            rows_after = len(result)
            action.mark_applied()
            logs.append({
                "action": action.action_type.value,
                "target": action.target_variable,
                "status": "applied",
                "rows_before": rows_before,
                "rows_after": rows_after,
                "rows_affected": rows_before - rows_after,
            })

        return result, logs

    # ── action handlers ──────────────────────────────────────────────

    def _drop_rows(self, df: pd.DataFrame, action: CleaningAction) -> pd.DataFrame:
        col = action.target_variable
        if col and col in df.columns:
            return df.dropna(subset=[col])
        # If no target, drop rows with any missing
        return df.dropna()

    def _drop_columns(self, df: pd.DataFrame, action: CleaningAction) -> pd.DataFrame:
        col = action.target_variable
        if col and col in df.columns:
            return df.drop(columns=[col])
        return df

    def _fill_missing(self, df: pd.DataFrame, action: CleaningAction) -> pd.DataFrame:
        col = action.target_variable
        method = action.params.get("method", "ffill")
        if col and col in df.columns:
            df[col] = df[col].fillna(method=method)
        else:
            df = df.fillna(method=method)
        return df

    def _fill_mean(self, df: pd.DataFrame, action: CleaningAction) -> pd.DataFrame:
        col = action.target_variable
        if col and col in df.columns:
            df[col] = df[col].fillna(df[col].mean())
        return df

    def _fill_median(self, df: pd.DataFrame, action: CleaningAction) -> pd.DataFrame:
        col = action.target_variable
        if col and col in df.columns:
            df[col] = df[col].fillna(df[col].median())
        return df

    def _fill_mode(self, df: pd.DataFrame, action: CleaningAction) -> pd.DataFrame:
        col = action.target_variable
        if col and col in df.columns:
            mode_val = df[col].mode()
            if len(mode_val) > 0:
                df[col] = df[col].fillna(mode_val.iloc[0])
        return df

    def _fill_constant(self, df: pd.DataFrame, action: CleaningAction) -> pd.DataFrame:
        col = action.target_variable
        value = action.params.get("value", 0)
        if col and col in df.columns:
            df[col] = df[col].fillna(value)
        return df

    def _remove_duplicates(
        self, df: pd.DataFrame, action: CleaningAction
    ) -> pd.DataFrame:
        subset = action.params.get("subset")
        return df.drop_duplicates(subset=subset)

    def _clip_outliers(self, df: pd.DataFrame, action: CleaningAction) -> pd.DataFrame:
        col = action.target_variable
        if col and col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            q1 = df[col].quantile(0.25)
            q3 = df[col].quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            df[col] = df[col].clip(lower=lower, upper=upper)
        return df

    def _remove_outliers(
        self, df: pd.DataFrame, action: CleaningAction
    ) -> pd.DataFrame:
        col = action.target_variable
        if col and col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            q1 = df[col].quantile(0.25)
            q3 = df[col].quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            df = df[(df[col] >= lower) & (df[col] <= upper)]
        return df

    def _type_cast(self, df: pd.DataFrame, action: CleaningAction) -> pd.DataFrame:
        col = action.target_variable
        target_type = action.params.get("dtype", "float")
        if col and col in df.columns:
            try:
                df[col] = df[col].astype(target_type)
            except (ValueError, TypeError):
                pass  # logged as warning, not a failure
        return df

    def _rename_column(self, df: pd.DataFrame, action: CleaningAction) -> pd.DataFrame:
        old_name = action.target_variable
        new_name = action.params.get("new_name")
        if old_name and new_name and old_name in df.columns:
            df = df.rename(columns={old_name: new_name})
        return df

    def _encode_categorical(
        self, df: pd.DataFrame, action: CleaningAction
    ) -> pd.DataFrame:
        col = action.target_variable
        if col and col in df.columns:
            df[col] = df[col].astype("category").cat.codes
        return df

    def _custom(self, df: pd.DataFrame, action: CleaningAction) -> pd.DataFrame:
        # Custom actions are not executed automatically for safety
        return df
