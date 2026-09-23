from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from .contract import PredictionSpec


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def label(value) -> str:
    if (
        isinstance(value, (int, float, np.integer, np.floating))
        and not isinstance(value, (bool, np.bool_))
        and np.isfinite(value)
        and float(value).is_integer()
    ):
        return str(int(value))
    return str(value)


def iso_dates(values: pd.Series) -> pd.Series:
    text = values.astype("string")
    valid = text.str.match(r"^\d{4}-\d{2}-\d{2}([T ].*)?$").fillna(False)
    return pd.to_datetime(text.where(valid), errors="coerce", format="ISO8601", utc=True)


def prepare_population(df: pd.DataFrame, spec: PredictionSpec) -> dict:
    if not df.columns.is_unique:
        raise ValueError("Duplicate column names are ambiguous.")
    columns = list(
        dict.fromkeys(
            [
                spec.target,
                *spec.predictors,
                *[v for v in [spec.subject_variable, spec.time_variable] if v],
            ]
        )
    )
    if any(c not in df.columns for c in columns):
        raise ValueError("Every prediction column must exist in the dataset.")
    if len(df) > 200_000:
        raise ValueError("This executor supports up to 200,000 observations per study.")
    frame = df[columns].copy().reset_index(drop=True)
    raw_y = frame[spec.target].replace([np.inf, -np.inf], np.nan)
    if spec.task == "binary":
        observed = raw_y.dropna().map(label)
        classes = sorted(observed.unique().tolist())
        if len(classes) != 2 or spec.positive_class not in classes:
            raise ValueError(
                f"Binary outcome requires exactly two source labels including positive_class={spec.positive_class!r}; observed={classes[:10]}."
            )
        y = raw_y.map(lambda v: np.nan if pd.isna(v) else float(label(v) == spec.positive_class))
        encoding = {value: int(value == spec.positive_class) for value in classes}
    else:
        y = pd.to_numeric(raw_y, errors="coerce").replace([np.inf, -np.inf], np.nan)
        encoding = {"kind": "numeric; target values are never imputed"}
    reasons = {"missing_or_invalid_target": y.isna()}
    groups = None
    if spec.subject_variable:
        raw_groups = frame[spec.subject_variable]
        groups = raw_groups.map(lambda v: None if pd.isna(v) or not str(v).strip() else label(v))
        reasons["missing_subject_key"] = groups.isna()
    dates = None
    if spec.split == "temporal":
        dates = iso_dates(frame[spec.time_variable])
        reasons["missing_or_invalid_ISO_time"] = dates.isna()
    eligible = ~pd.concat(reasons, axis=1).any(axis=1)
    if eligible.sum() < 40:
        raise ValueError(
            "At least 40 outcome/split-key complete observations are required; this is not a clinical sample-size justification."
        )
    x = frame[spec.predictors].copy()
    invalid_predictors = {}
    for column in spec.predictors:
        if column in (spec.categorical_predictors or []):
            x[column] = x[column].map(lambda v: np.nan if pd.isna(v) else label(v))
        else:
            numeric = pd.to_numeric(x[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
            invalid_predictors[column] = int((numeric.isna() & x[column].notna()).sum())
            x[column] = numeric
    return {
        "x": x,
        "y": y,
        "groups": groups,
        "dates": dates,
        "eligible": np.flatnonzero(eligible.to_numpy()),
        "encoding": encoding,
        "exclusions": {
            reason: np.flatnonzero(mask.to_numpy()).tolist() for reason, mask in reasons.items()
        },
        "invalid_predictor_values": invalid_predictors,
        "dataframe_sha256": hashlib.sha256(
            pd.util.hash_pandas_object(frame, index=True).values.tobytes()
        ).hexdigest(),
    }


def purge_groups(train, valid, groups):
    if groups is None:
        return np.asarray(train), []
    heldout = set(groups.iloc[valid])
    purged = [int(i) for i in train if groups.iloc[i] in heldout]
    return np.asarray([i for i in train if groups.iloc[i] not in heldout], dtype=int), purged


def assert_partition(train, valid, population, *, temporal=False):
    if len(train) < 20 or len(valid) < 10:
        raise ValueError(
            f"Insufficient partition after exclusions: train={len(train)}, validation={len(valid)} (minimum 20/10)."
        )
    if set(train).intersection(valid):
        raise ValueError("Training and validation rows overlap.")
    groups, dates = population["groups"], population["dates"]
    if groups is not None and set(groups.iloc[train]).intersection(groups.iloc[valid]):
        raise ValueError("Training and validation subjects overlap.")
    if temporal and not dates.iloc[train].max() < dates.iloc[valid].min():
        raise ValueError(
            "Training time must be strictly before validation time; ties stay together."
        )


def split_record(train, valid, population, purged, name):
    record = {
        "name": name,
        "train_positions": [int(i) for i in train],
        "validation_positions": [int(i) for i in valid],
        "purged_train_positions": purged,
        "row_position_base": 0,
        "n_train": len(train),
        "n_validation": len(valid),
    }
    record["partition_sha256"] = digest(record)
    if population["groups"] is not None:
        record.update(
            train_subjects=population["groups"].iloc[train].nunique(),
            validation_subjects=population["groups"].iloc[valid].nunique(),
            subject_overlap=0,
        )
    if population["dates"] is not None:
        record.update(
            train_time_max=population["dates"].iloc[train].max().isoformat(),
            validation_time_min=population["dates"].iloc[valid].min().isoformat(),
        )
    return record


def outer_split(population: dict, spec: PredictionSpec) -> dict:
    from sklearn.model_selection import GroupShuffleSplit, train_test_split

    rows = population["eligible"]
    y, groups, dates = [population[key] for key in ["y", "groups", "dates"]]
    purged = []
    if spec.split == "random":
        train, valid = train_test_split(
            rows,
            test_size=spec.test_fraction,
            random_state=spec.seed,
            stratify=y.iloc[rows] if spec.task == "binary" else None,
        )
    elif spec.split == "group":
        a, b = next(
            GroupShuffleSplit(
                n_splits=1, test_size=spec.test_fraction, random_state=spec.seed
            ).split(rows, groups=groups.iloc[rows])
        )
        train, valid = rows[a], rows[b]
    else:
        cutoff = iso_dates(pd.Series([spec.cutoff])).iloc[0]
        if pd.isna(cutoff):
            raise ValueError("cutoff must be an explicit ISO date/time.")
        train, valid = (
            rows[(dates.iloc[rows] < cutoff).to_numpy()],
            rows[(dates.iloc[rows] >= cutoff).to_numpy()],
        )
        train, purged = purge_groups(train, valid, groups)
    train, valid = np.sort(train), np.sort(valid)
    assert_partition(train, valid, population, temporal=spec.split == "temporal")
    return split_record(train, valid, population, purged, "held_out_validation")


def training_folds(population: dict, outer: dict, spec: PredictionSpec) -> list[dict]:
    from sklearn.model_selection import GroupKFold, KFold, StratifiedKFold

    rows = np.asarray(outer["train_positions"])
    y, groups, dates = [population[key] for key in ["y", "groups", "dates"]]
    if spec.split == "temporal":
        times = np.sort(dates.iloc[rows].unique())
        if len(times) < spec.cv_folds + 1:
            raise ValueError("Not enough distinct training dates for temporal CV.")
        chunks = np.array_split(times, spec.cv_folds + 1)
        pairs = [
            (
                rows[dates.iloc[rows].isin(np.concatenate(chunks[:i])).to_numpy()],
                rows[dates.iloc[rows].isin(chunks[i]).to_numpy()],
            )
            for i in range(1, len(chunks))
        ]
    else:
        splitter = (
            GroupKFold(n_splits=spec.cv_folds, shuffle=True, random_state=spec.seed)
            if groups is not None
            else StratifiedKFold(n_splits=spec.cv_folds, shuffle=True, random_state=spec.seed)
            if spec.task == "binary"
            else KFold(n_splits=spec.cv_folds, shuffle=True, random_state=spec.seed)
        )
        pairs = [
            (rows[a], rows[b])
            for a, b in splitter.split(
                rows, y.iloc[rows], groups.iloc[rows] if groups is not None else None
            )
        ]
    records = []
    for index, (train, valid) in enumerate(pairs):
        train, purged = purge_groups(train, valid, groups)
        assert_partition(train, valid, population, temporal=spec.split == "temporal")
        records.append(split_record(train, valid, population, purged, f"training_cv_{index + 1}"))
    return records
