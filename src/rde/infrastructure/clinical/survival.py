"""Prespecified right-censored survival and competing-event studies.

Uses lifelines for KM/Cox/PH diagnostics and statsmodels' non-jittered
Aalen-Johansen estimator for tied competing events. No automatic event recoding,
covariate selection, imputation, or inference of random assignment is performed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import hashlib
import importlib.metadata
import json
import math
import warnings

import numpy as np
import pandas as pd


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def level(value):
    """Canonical numeric source labels, without guessing meaning or trimming labels."""
    if pd.isna(value) or isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, (bool, np.bool_)):
        return str(bool(value)).lower()
    if isinstance(value, (int, float, np.integer, np.floating)):
        if not math.isfinite(float(value)):
            raise ValueError("Infinite category values are not valid source labels.")
        return str(int(value)) if float(value).is_integer() else str(float(value))
    return str(value)


def numeric(series: pd.Series, name: str) -> pd.Series:
    absent = series.isna() | series.map(lambda v: isinstance(v, str) and not v.strip())
    converted = pd.to_numeric(series.mask(absent), errors="coerce")
    if ((~absent & converted.isna()) | (converted.notna() & ~np.isfinite(converted))).any():
        raise ValueError(f"{name}: non-numeric/infinite observations require explicit correction.")
    return converted.astype(float)


@dataclass(frozen=True)
class SurvivalSpec:
    time: str
    event: str
    event_value: str
    censor_value: str
    time_origin: str
    time_unit: str
    independent_rows: bool
    family: str = "survival"
    group: str | None = None
    subject: str | None = None
    covariates: list[str] = field(default_factory=list)
    categorical_covariates: list[str] = field(default_factory=list)
    references: dict[str, str] = field(default_factory=dict)
    competing_values: list[str] = field(default_factory=list)
    risk_times: list[float] = field(default_factory=list)
    confidence_level: float = 0.95
    cohort_filter: dict | None = None

    @classmethod
    def parse(cls, options: dict) -> SurvivalSpec:
        if not isinstance(options, dict):
            raise ValueError("Clinical options must be an object.")
        unknown = set(options) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown survival options: {sorted(unknown)}")
        try:
            result = cls(**options)
        except TypeError as error:
            raise ValueError(f"Missing required survival options: {error}") from error
        result.validate()
        return result

    def validate(self):
        for key in ["time", "event", "event_value", "censor_value", "time_origin", "time_unit"]:
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                raise ValueError(f"{key} must be explicit nonempty text.")
        if self.family != "survival" or self.independent_rows is not True:
            raise ValueError("This survival study requires one independent row per participant.")
        if len(self.time_origin.strip()) < 5:
            raise ValueError("Define the clinical origin of survival time.")
        for key in ["group", "subject"]:
            value = getattr(self, key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{key} must be a column name or null.")
        for key, limit in [
            ("covariates", 20),
            ("categorical_covariates", 20),
            ("competing_values", 5),
        ]:
            value = getattr(self, key)
            if (
                not isinstance(value, list)
                or len(value) > limit
                or any(not isinstance(v, str) or not v.strip() for v in value)
                or len(set(value)) != len(value)
            ):
                raise ValueError(f"{key} requires distinct explicit labels (maximum {limit}).")
        categories = set(self.categorical_covariates)
        if (
            not categories.issubset(self.covariates)
            or not isinstance(self.references, dict)
            or set(self.references) != categories
            or any(not isinstance(v, str) or not v.strip() for v in self.references.values())
        ):
            raise ValueError("Every categorical covariate requires its exact reference label.")
        roles = [v for v in [self.time, self.event, self.subject] if v]
        if (
            len(set(roles)) != len(roles)
            or set(roles).intersection(self.covariates)
            or self.group in roles
        ):
            raise ValueError(
                "Time, event, subject and predictor roles must not leak into each other."
            )
        codes = [self.censor_value, self.event_value, *self.competing_values]
        if len(set(codes)) != len(codes):
            raise ValueError("Event, censor and competing-event codes must be disjoint.")
        if (
            type(self.confidence_level) not in {int, float}
            or not 0.8 <= self.confidence_level <= 0.999
        ):
            raise ValueError("confidence_level must lie between 0.8 and 0.999.")
        if (
            not isinstance(self.risk_times, list)
            or len(self.risk_times) > 12
            or any(
                type(t) not in {int, float} or not math.isfinite(t) or t < 0
                for t in self.risk_times
            )
            or self.risk_times != sorted(set(self.risk_times))
        ):
            raise ValueError(
                "risk_times must contain up to 12 distinct increasing nonnegative times."
            )
        if self.cohort_filter is not None:
            f = self.cohort_filter
            if (
                not isinstance(f, dict)
                or set(f) != {"column", "values"}
                or not isinstance(f["column"], str)
                or not f["column"].strip()
                or not isinstance(f["values"], list)
                or not 1 <= len(f["values"]) <= 20
                or any(not isinstance(v, str) or not v.strip() for v in f["values"])
                or len(set(f["values"])) != len(f["values"])
            ):
                raise ValueError(
                    "cohort_filter requires a column and explicit included source labels."
                )

    def to_dict(self):
        return asdict(self)

    def variables(self):
        return list(
            dict.fromkeys(
                [
                    self.time,
                    self.event,
                    *self.covariates,
                    *[
                        v
                        for v in [
                            self.group,
                            self.subject,
                            self.cohort_filter["column"] if self.cohort_filter else None,
                        ]
                        if v
                    ],
                ]
            )
        )


def prepare_population(df: pd.DataFrame, spec: SurvivalSpec):
    spec.validate()
    if not df.columns.is_unique or any(v not in df.columns for v in spec.variables()):
        raise ValueError("Source must have unique columns and contain every specified variable.")
    if not 2 <= len(df) <= 100_000:
        raise ValueError("Survival studies require 2..100,000 input rows.")
    selected = df[spec.variables()].reset_index(drop=True).copy()
    source = [
        [None if pd.isna(v) else (v.item() if isinstance(v, np.generic) else v) for v in row]
        for row in selected.itertuples(index=False, name=None)
    ]
    # The raw file SHA is pinned separately by the MCP envelope.
    try:
        frame_hash = digest({"columns": spec.variables(), "rows": source})
    except (TypeError, ValueError) as e:
        raise ValueError("Source contains unsupported or non-finite values.") from e
    cohort = pd.Series(True, index=selected.index)
    if spec.cohort_filter:
        cohort = (
            selected[spec.cohort_filter["column"]].map(level).isin(spec.cohort_filter["values"])
        )
    working = selected.loc[cohort].copy()
    if working.empty:
        raise ValueError("The prespecified cohort filter includes no participants.")
    if spec.subject:
        subjects = working[spec.subject].map(level)
        if subjects.isna().any() or subjects.duplicated().any():
            raise ValueError(
                "Subject identifiers must be present and unique within the included cohort."
            )
    transformed = pd.DataFrame(index=working.index)
    transformed["duration"] = numeric(working[spec.time], spec.time)
    if (transformed.duration.dropna() < 0).any():
        raise ValueError("Survival durations must be nonnegative.")
    codes = {
        value: index
        for index, value in enumerate([spec.censor_value, spec.event_value, *spec.competing_values])
    }
    values = working[spec.event].map(level)
    unknown = set(values.dropna()) - set(codes)
    if unknown:
        raise ValueError(
            f"Unmapped event labels: {sorted(unknown)}. Specify every competing event explicitly."
        )
    transformed["event_code"] = values.map(codes)
    if spec.group:
        transformed["group"] = working[spec.group].map(level)
    else:
        transformed["group"] = "All participants"
    for i, name in enumerate(spec.covariates):
        transformed[f"x{i}"] = (
            working[name].map(level)
            if name in spec.categorical_covariates
            else numeric(working[name], name)
        )
    complete = transformed.notna().all(axis=1)
    ledger = {
        "input_rows": len(df),
        "cohort_rows": int(cohort.sum()),
        "filter_excluded_data_rows": (selected.index[~cohort] + 1).tolist(),
        "missing_excluded_data_rows": (transformed.index[~complete] + 1).tolist(),
        "complete_data_rows": (transformed.index[complete] + 1).tolist(),
        "missing_by_role": {name: int(transformed[name].isna().sum()) for name in transformed},
        "policy": "Complete cases for all prespecified roles; every method and figure uses these same participants.",
        "data_row_numbering": "one-based observations, excluding header",
    }
    frame = transformed.loc[complete].copy()
    if len(frame) < 2:
        raise ValueError("Fewer than two complete independent participants remain.")
    frame.event_code = frame.event_code.astype(int)
    if spec.group and not 2 <= frame.group.nunique() <= 6:
        raise ValueError(
            "A group comparison requires 2..6 nonempty groups after complete-case selection."
        )
    if spec.risk_times and max(spec.risk_times) > frame.duration.max():
        raise ValueError("Risk table times must not extend beyond observed follow-up.")
    return frame, ledger, frame_hash, codes


def _risk_table(frame: pd.DataFrame, times: list[float]):
    return [
        dict(
            time=float(t),
            at_risk=int((frame.duration >= t).sum()),
            prior_events=int(((frame.duration < t) & (frame.event_code == 1)).sum()),
            prior_competing=int(((frame.duration < t) & (frame.event_code > 1)).sum()),
            prior_censored=int(((frame.duration < t) & (frame.event_code == 0)).sum()),
        )
        for t in times
    ]


def _km(frame: pd.DataFrame, alpha: float):
    from lifelines import KaplanMeierFitter

    fit = KaplanMeierFitter(alpha=alpha).fit(frame.duration, frame.event_code == 1)
    timeline = fit.survival_function_.index.to_numpy()
    ci = fit.confidence_interval_.to_numpy()
    table = fit.event_table
    return {
        "method": "Kaplan-Meier",
        "ci_method": "pointwise Greenwood log-log",
        "median": float(fit.median_survival_time_)
        if math.isfinite(fit.median_survival_time_)
        else None,
        "median_status": "estimable" if math.isfinite(fit.median_survival_time_) else "not_reached",
        "curve": [
            dict(
                time=float(t),
                estimate=float(s),
                lower=float(bounds[0]),
                upper=float(bounds[1]),
                at_risk=int(table.loc[t, "at_risk"]),
                events=int(table.loc[t, "observed"]),
                censored=int(table.loc[t, "censored"]),
            )
            for t, s, bounds in zip(timeline, fit.survival_function_.iloc[:, 0], ci, strict=True)
        ],
    }


def _cumulative_incidence(frame: pd.DataFrame, alpha: float, codes: dict):
    from statsmodels.duration.survfunc import CumIncidenceRight
    from scipy.stats import norm

    if not (frame.event_code > 0).any():
        return {
            "method": "Aalen-Johansen",
            "ci_method": "pointwise normal approximation, bounded to [0, 1]",
            "curves": {value: [] for value, code in codes.items() if code > 0},
            "no_observed_events": True,
        }
    # statsmodels' expanded variance is singular if the last risk set consists
    # entirely of events. Preserve its non-jittered estimates and evaluate the
    # same Dinse-Larson variance in difference form at such numerical boundaries.
    with np.errstate(divide="ignore", invalid="ignore"):
        fitted = CumIncidenceRight(frame.duration.to_numpy(), frame.event_code.to_numpy())
    times, positions = np.unique(frame.duration.to_numpy(), return_inverse=True)
    removed = np.bincount(positions, minlength=len(times))
    risk = len(frame) - np.r_[0, np.cumsum(removed)[:-1]]
    all_events = np.bincount(positions, weights=frame.event_code > 0, minlength=len(times))
    before_survival = np.r_[1.0, np.cumprod(1 - all_events / risk)[:-1]]
    variance_adjustments = 0
    curves = {}
    for value, code in codes.items():
        if code == 0:
            continue
        if code > len(fitted.cinc):
            estimate, se = np.zeros_like(fitted.times), np.zeros_like(fitted.times)
        else:
            estimate, se = fitted.cinc[code - 1], fitted.cinc_se[code - 1].copy()
            events = np.bincount(positions, weights=frame.event_code == code, minlength=len(times))
            for index in np.flatnonzero(~np.isfinite(se)):
                take = slice(0, index + 1)
                difference = estimate[index] - estimate[take]
                n, d, dk, s = risk[take], all_events[take], events[take], before_survival[take]
                denominator = n * (n - d)
                if np.any((denominator == 0) & (np.abs(difference) > 1e-12)):
                    raise ValueError(
                        "Cumulative incidence variance has an unresolved risk-set singularity."
                    )
                first = np.divide(
                    difference**2 * d,
                    denominator,
                    out=np.zeros_like(difference),
                    where=denominator > 0,
                )
                variance = np.sum(
                    first + s**2 * (n - dk) * dk / n**3 - 2 * difference * s * dk / n**2
                )
                if not math.isfinite(variance) or variance < -1e-12:
                    raise ValueError("Cumulative incidence uncertainty is not estimable.")
                se[index] = math.sqrt(max(0, variance))
                variance_adjustments += 1
        curves[value] = [
            dict(
                time=float(t),
                estimate=float(p),
                standard_error=float(s),
                lower=float(max(0, p - norm.ppf(1 - alpha / 2) * s)),
                upper=float(min(1, p + norm.ppf(1 - alpha / 2) * s)),
            )
            for t, p, s in zip(fitted.times, estimate, se, strict=True)
        ]
    return {
        "method": "Aalen-Johansen",
        "ci_method": "pointwise normal approximation, bounded to [0, 1]",
        "curves": curves,
        "ties": "original event times retained; no random jitter",
        "variance_boundary_adjustments": variance_adjustments,
    }


def _cox(frame: pd.DataFrame, spec: SurvivalSpec):
    from lifelines import CoxPHFitter
    from lifelines.statistics import proportional_hazard_test
    from lifelines.exceptions import ConvergenceWarning
    from statsmodels.stats.multitest import multipletests

    design = pd.DataFrame(index=frame.index)
    encoding = []
    for i, name in enumerate(spec.covariates):
        if name in spec.categorical_covariates:
            levels = sorted(frame[f"x{i}"].unique())
            reference = spec.references[name]
            if reference not in levels or len(levels) < 2 or len(levels) > 20:
                raise ValueError(
                    f"{name}: missing reference, constant, or more than 20 categories."
                )
            for j, label in enumerate(v for v in levels if v != reference):
                term = f"c{i}_{j}"
                design[term] = (frame[f"x{i}"] == label).astype(float)
                encoding.append(dict(term=term, variable=name, level=label, reference=reference))
        else:
            term = f"c{i}"
            design[term] = frame[f"x{i}"].astype(float)
            encoding.append(dict(term=term, variable=name, unit_change=1))
    if (
        design.shape[1] > 30
        or (design.nunique() < 2).any()
        or np.linalg.matrix_rank(design.to_numpy() - design.mean().to_numpy()) < design.shape[1]
    ):
        raise ValueError(
            "Cox predictors are constant, collinear, or have more than 30 encoded parameters."
        )
    events = int((frame.event_code == 1).sum())
    if events <= max(4, design.shape[1]):
        raise ValueError(
            "Cox estimation requires more target events than encoded parameters and at least five events."
        )
    design["_duration"] = frame.duration
    design["_event"] = frame.event_code == 1
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fitted = CoxPHFitter(alpha=1 - spec.confidence_level, penalizer=0).fit(
            design, duration_col="_duration", event_col="_event", show_progress=False
        )
    if any(issubclass(w.category, ConvergenceWarning) for w in caught):
        raise ValueError(
            "Cox model issued a convergence warning; simplify the prespecified model or review the data before refitting."
        )
    values = np.column_stack(
        [
            fitted.params_,
            fitted.standard_errors_,
            fitted.confidence_intervals_,
            fitted.hazard_ratios_,
        ]
    )
    if not np.isfinite(values).all():
        raise ValueError("Cox estimates or uncertainty are non-finite.")
    coefficients = []
    for encoded in encoding:
        term = encoded["term"]
        interval = fitted.confidence_intervals_.loc[term].to_numpy()
        with np.errstate(over="ignore"):
            bounds = np.exp(interval)
        if not np.isfinite(bounds).all():
            raise ValueError("Cox hazard-ratio confidence bounds overflow; estimates are unstable.")
        coefficients.append(
            {
                **encoded,
                "coefficient": float(fitted.params_.loc[term]),
                "standard_error": float(fitted.standard_errors_.loc[term]),
                "hazard_ratio": float(fitted.hazard_ratios_.loc[term]),
                "lower": float(bounds[0]),
                "upper": float(bounds[1]),
                "p_value": float(fitted.summary.loc[term, "p"]),
            }
        )
    checks = []
    for transform in ["rank", "km"]:
        result = proportional_hazard_test(fitted, design, time_transform=transform).summary
        for term, row in result.iterrows():
            checks.append(
                dict(
                    term=term,
                    transform=transform,
                    statistic=float(row["test_statistic"]),
                    p_value=float(row["p"]),
                )
            )
    finite = all(math.isfinite(c["p_value"]) and math.isfinite(c["statistic"]) for c in checks)
    if not finite:
        raise ValueError(
            "Proportional-hazards diagnostics are not estimable; do not report an unchecked Cox result."
        )
    adjusted = multipletests([c["p_value"] for c in checks], method="holm")[1]
    for check, p_value in zip(checks, adjusted, strict=True):
        check["p_adjusted"] = float(p_value)
    residuals = fitted.compute_residuals(design, kind="scaled_schoenfeld")
    residual_rows = [
        {
            "data_row": int(index) + 1,
            "time": float(frame.loc[index, "duration"]),
            **{str(term): float(value) for term, value in row.items()},
        }
        for index, row in residuals.iterrows()
    ]
    return dict(
        method="cause-specific Cox" if spec.competing_values else "Cox proportional hazards",
        ties="Efron",
        baseline_method="Breslow",
        penalizer=0,
        n=len(frame),
        events=events,
        coefficients=coefficients,
        ph_checks=checks,
        ph_correction="Holm across both transforms and all encoded terms",
        scaled_schoenfeld=residual_rows,
        events_per_parameter=events / len(encoding),
        warnings=[str(w.message) for w in caught],
    )


def run_survival(df: pd.DataFrame, spec: SurvivalSpec):
    frame, ledger, frame_hash, codes = prepare_population(df, spec)
    return _run_prepared_survival(frame, ledger, frame_hash, codes, spec)


def run_survival_sensitivity(df: pd.DataFrame, baseline: SurvivalSpec, covariates: list[str]):
    """Adjust a Cox model without changing the primary study's complete-case population."""
    if (
        not covariates
        or len(set(covariates)) != len(covariates)
        or not set(covariates) < set(baseline.covariates)
    ):
        raise ValueError(
            "A sensitivity model requires a nonempty proper subset of primary covariates."
        )
    selected = [name for name in baseline.covariates if name in covariates]
    spec = SurvivalSpec.parse(
        {
            **baseline.to_dict(),
            "covariates": selected,
            "categorical_covariates": [n for n in baseline.categorical_covariates if n in selected],
            "references": {k: v for k, v in baseline.references.items() if k in selected},
        }
    )
    frame, ledger, frame_hash, codes = prepare_population(df, baseline)
    # Build a new column mapping: renaming x1->x0 in place could overwrite a retained column.
    model_frame = frame[["duration", "event_code", "group"]].copy()
    for index, name in enumerate(selected):
        model_frame[f"x{index}"] = frame[f"x{baseline.covariates.index(name)}"]
    result = _run_prepared_survival(model_frame, ledger, frame_hash, codes, spec)
    # The frame hash and exclusions describe ALL baseline roles, including omitted predictors.
    result["population_spec"] = baseline.to_dict()
    result["population_spec_sha256"] = digest(baseline.to_dict())
    result["case_set_sha256"] = digest(ledger["complete_data_rows"])
    result["limitations"].append(
        "Exploratory adjustment sensitivity on the primary complete-case population. "
        "Omitting predictors does not restore excluded participants. "
        "Intervals are pointwise; no multiplicity correction across exploratory models. "
        "Changes in hazard ratios are not a formal test between models or evidence of causality."
    )
    result["receipt_sha256"] = digest({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def _run_prepared_survival(frame, ledger, frame_hash, codes, spec):
    from lifelines.statistics import multivariate_logrank_test

    alpha = 1 - spec.confidence_level
    times = spec.risk_times or np.unique(np.linspace(0, float(frame.duration.max()), 5)).tolist()
    strata = []
    for name, subframe in frame.groupby("group", sort=True):
        strata.append(
            dict(
                label=str(name),
                n=len(subframe),
                followup_min=float(subframe.duration.min()),
                followup_max=float(subframe.duration.max()),
                events=int((subframe.event_code == 1).sum()),
                censored=int((subframe.event_code == 0).sum()),
                competing=int((subframe.event_code > 1).sum()),
                risk_table=_risk_table(subframe, times),
                estimate=_cumulative_incidence(subframe, alpha, codes)
                if spec.competing_values
                else _km(subframe, alpha),
            )
        )
    logrank = None
    if spec.group and not spec.competing_values:
        if (frame.event_code == 1).any():
            tested = multivariate_logrank_test(frame.duration, frame.group, frame.event_code == 1)
            if math.isfinite(tested.test_statistic) and math.isfinite(tested.p_value):
                logrank = dict(
                    statistic=float(tested.test_statistic),
                    p_value=float(tested.p_value),
                    df=int(frame.group.nunique() - 1),
                )
            else:
                logrank = dict(
                    status="not_estimable", reason="No informative between-group risk sets."
                )
        else:
            logrank = dict(status="not_estimable", reason="No observed target events.")
    result = dict(
        schema="clinical-survival-v1",
        status="completed",
        spec=spec.to_dict(),
        spec_sha256=digest(spec.to_dict()),
        dataframe_sha256=frame_hash,
        case_ledger=ledger,
        event_codes=codes,
        n=len(frame),
        events=int((frame.event_code == 1).sum()),
        censored=int((frame.event_code == 0).sum()),
        competing=int((frame.event_code > 1).sum()),
        strata=strata,
        logrank=logrank,
        cox=_cox(frame, spec) if spec.covariates else None,
        versions={
            p: importlib.metadata.version(p)
            for p in ["lifelines", "statsmodels", "numpy", "pandas", "scipy"]
        },
        limitations=[
            "Independent participants and right censoring only; no delayed entry, recurrent events, or time-varying predictors.",
            "Complete-case estimates require review of missingness and censoring mechanisms.",
            "Observational associations do not establish treatment effects; proportional-hazards tests cannot prove the assumption.",
            "Pointwise intervals are not simultaneous bands. No observed events, or a boundary interval, do not establish absence of risk.",
        ],
    )
    if spec.competing_values:
        result["limitations"].append(
            "Target risk uses Aalen-Johansen with competing events. Cox estimates a cause-specific hazard ratio, not a subdistribution hazard or risk ratio. No log-rank/Gray test of cumulative incidence is reported."
        )
    if result["cox"] and result["cox"]["events_per_parameter"] < 10:
        result["limitations"].append(
            "Fewer than 10 target events per encoded parameter; estimates may be unstable. No automatic variable selection was applied."
        )
    result["receipt_sha256"] = digest(result)
    return result
