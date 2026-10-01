"""Locked diagnostic and paired measurement studies with explicit source coding.

No cutoff optimization, label inference, synthetic prevalence or imputation.
The same participant ledger feeds every estimate, table and figure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import importlib.metadata
import math

import numpy as np
import pandas as pd

from rde.infrastructure.adapters.clinical_engine import run_clinical_analysis
from rde.infrastructure.clinical.survival import digest, level, numeric


def _text(value, name, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= 2000:
        raise ValueError(f"{name} requires explicit text ({minimum}..2000 characters).")


def _labels(value, name, maximum=20):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{name} must be a list of up to {maximum} exact labels.")
    for v in value:
        _text(v, name)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} contains duplicate labels.")


def _number(value, name):
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number.")


@dataclass(frozen=True)
class MeasurementSpec:
    family: str
    first: str
    second: str
    context: str
    independent_rows: bool
    subject: str | None = None
    diagnostic: dict | None = None
    agreement: dict | None = None
    categories: list[str] = field(default_factory=list)
    confidence_level: float = 0.95

    @property
    def group(self):
        return None

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown measurement options; use the exact study contract.")
        try:
            spec = cls(**options)
        except TypeError as error:
            raise ValueError(f"Missing measurement settings: {error}") from error
        spec.validate()
        return spec

    def validate(self):
        if self.family not in {"diagnostic_accuracy", "bland_altman", "cohens_kappa"}:
            raise ValueError("Unsupported measurement study family.")
        for key in ["first", "second"]:
            _text(getattr(self, key), key)
        _text(self.context, "context", 5)
        if self.subject is not None:
            _text(self.subject, "subject")
        roles = [v for v in [self.first, self.second, self.subject] if v is not None]
        if len(set(roles)) != len(roles) or self.independent_rows is not True:
            raise ValueError(
                "Distinct roles and one independent paired observation per subject are required."
            )
        _number(self.confidence_level, "confidence_level")
        if not 0.8 <= self.confidence_level <= 0.999:
            raise ValueError("confidence_level must lie between 0.8 and 0.999.")
        _labels(self.categories, "categories")
        if self.family == "diagnostic_accuracy":
            d = self.diagnostic
            keys = {
                "positive",
                "negative",
                "reference_description",
                "reference_independence",
                "sampling",
                "test_kind",
                "threshold",
                "positive_direction",
                "test_positive",
                "test_negative",
                "threshold_basis",
                "threshold_status",
                "reference_indeterminate",
                "test_indeterminate",
            }
            if not isinstance(d, dict) or set(d) != keys or self.agreement or self.categories:
                raise ValueError("Diagnostic study requires the exact diagnostic settings only.")
            for key in ["positive", "negative", "reference_description", "threshold_basis"]:
                _text(d[key], key, 5 if key.endswith(("description", "basis")) else 1)
            if d["reference_independence"] not in {"independent", "not_independent", "unknown"}:
                raise ValueError("Declare reference standard independence, or unknown.")
            if d["sampling"] not in {"single_gate", "two_gate", "unknown"}:
                raise ValueError("sampling must be single_gate, two_gate or unknown.")
            if d["threshold_status"] not in {"prespecified", "exploratory"}:
                raise ValueError("Declare whether the test rule is prespecified or exploratory.")
            _labels(d["reference_indeterminate"], "reference_indeterminate", 5)
            _labels(d["test_indeterminate"], "test_indeterminate", 5)
            _labels(
                [d["positive"], d["negative"], *d["reference_indeterminate"]], "reference codes"
            )
            if d["test_kind"] == "score":
                _number(d["threshold"], "threshold")
                if d["positive_direction"] not in {"greater_equal", "less_equal"}:
                    raise ValueError("A numeric score requires an explicit positive direction.")
                if d["test_positive"] is not None or d["test_negative"] is not None:
                    raise ValueError("A score cannot also specify binary test labels.")
            elif d["test_kind"] == "binary":
                _labels(
                    [d["test_positive"], d["test_negative"], *d["test_indeterminate"]], "test codes"
                )
                if d["threshold"] is not None or d["positive_direction"] is not None:
                    raise ValueError("A binary test uses source labels, not a numeric cutoff.")
            else:
                raise ValueError("test_kind must be score or binary.")
        elif self.family == "bland_altman":
            a = self.agreement
            if (
                not isinstance(a, dict)
                or set(a)
                != {"unit", "coverage", "acceptable_lower", "acceptable_upper", "margin_basis"}
                or self.diagnostic
                or self.categories
            ):
                raise ValueError(
                    "Bland–Altman requires the exact continuous agreement settings only."
                )
            _text(a["unit"], "unit")
            _number(a["coverage"], "coverage")
            if not 0.8 <= a["coverage"] <= 0.99:
                raise ValueError(
                    "Agreement coverage must lie between 0.8 and 0.99, separately from CI confidence."
                )
            if a["acceptable_lower"] is None and a["acceptable_upper"] is None:
                if a["margin_basis"] is not None:
                    raise ValueError("A margin basis requires explicit lower and upper margins.")
            else:
                for key in ["acceptable_lower", "acceptable_upper"]:
                    _number(a[key], key)
                if a["acceptable_lower"] >= a["acceptable_upper"]:
                    raise ValueError("Acceptable difference lower must be smaller than upper.")
                _text(a["margin_basis"], "margin_basis", 5)
        elif self.diagnostic or self.agreement or not 2 <= len(self.categories) <= 20:
            raise ValueError(
                "Unweighted kappa requires 2..20 prespecified categories and no diagnostic/continuous settings."
            )

    def variables(self):
        return [self.first, self.second, *([self.subject] if self.subject else [])]

    def to_dict(self):
        return asdict(self)


def prepare_measurement(df, spec: MeasurementSpec):
    spec.validate()
    if not df.columns.is_unique or any(v not in df for v in spec.variables()):
        raise ValueError("Source must contain unique columns and every measurement role.")
    if not 3 <= len(df) <= 100_000:
        raise ValueError("Measurement studies require 3..100,000 input rows.")
    selected = df[spec.variables()].reset_index(drop=True).copy()
    source = [
        [None if pd.isna(v) else v.item() if isinstance(v, np.generic) else v for v in row]
        for row in selected.itertuples(index=False, name=None)
    ]
    try:
        frame_hash = digest({"columns": spec.variables(), "rows": source})
    except (ValueError, TypeError) as error:
        raise ValueError("Source contains unsupported or non-finite values.") from error
    if spec.subject:
        subjects = selected[spec.subject].map(level)
        if subjects.isna().any() or subjects.duplicated().any():
            raise ValueError(
                "Subject identifiers must be present and unique; repeated observations need a different study."
            )
    raw_first, raw_second = selected[spec.first].map(level), selected[spec.second].map(level)
    missing = raw_first.isna() | raw_second.isna()
    indeterminate = pd.Series(False, index=selected.index)
    frame = pd.DataFrame(index=selected.index)
    if spec.family == "diagnostic_accuracy":
        d = spec.diagnostic
        indeterminate = ~missing & (
            raw_first.isin(d["reference_indeterminate"]) | raw_second.isin(d["test_indeterminate"])
        )
        allowed = [d["positive"], d["negative"], *d["reference_indeterminate"]]
        if (~raw_first.dropna().isin(allowed)).any():
            raise ValueError(
                "Unlisted reference standard codes require explicit correction or declared indeterminate labels."
            )
        frame["first"] = raw_first.map({d["positive"]: 1, d["negative"]: 0})
        if d["test_kind"] == "binary":
            allowed_test = [d["test_positive"], d["test_negative"], *d["test_indeterminate"]]
            if (~raw_second.dropna().isin(allowed_test)).any():
                raise ValueError("Unlisted binary test codes require explicit correction.")
            frame["second"] = raw_second.map({d["test_positive"]: 1, d["test_negative"]: 0})
        else:
            frame["second"] = numeric(
                selected[spec.second].mask(raw_second.isin(d["test_indeterminate"])), spec.second
            )
    elif spec.family == "bland_altman":
        frame["first"], frame["second"] = (
            numeric(selected[spec.first], spec.first),
            numeric(selected[spec.second], spec.second),
        )
    else:
        for raw in [raw_first, raw_second]:
            if (~raw.dropna().isin(spec.categories)).any():
                raise ValueError(
                    "Ratings contain categories outside the prespecified shared category set."
                )
        frame["first"], frame["second"] = raw_first, raw_second
    complete = ~(missing | indeterminate)
    frame = frame.loc[complete].copy()
    if len(frame) < 3:
        raise ValueError(
            "At least three complete independent pairs are required; this is not a sample-size adequacy claim."
        )
    ledger = dict(
        input_rows=len(df),
        row_number_base=1,
        header_excluded=True,
        complete_data_rows=(np.flatnonzero(complete) + 1).tolist(),
        filter_excluded_data_rows=[],
        missing_excluded_data_rows=(np.flatnonzero(missing) + 1).tolist(),
        indeterminate_excluded_data_rows=(np.flatnonzero(indeterminate) + 1).tolist(),
        strategy="One paired row per independent subject; shared complete cases; missing takes precedence over indeterminate in exclusive flow counts.",
        reference_indeterminate_rows=(
            np.flatnonzero(raw_first.isin(spec.diagnostic["reference_indeterminate"])) + 1
        ).tolist()
        if spec.diagnostic
        else [],
        test_indeterminate_rows=(
            np.flatnonzero(raw_second.isin(spec.diagnostic["test_indeterminate"])) + 1
        ).tolist()
        if spec.diagnostic
        else [],
    )
    return frame, ledger, frame_hash


def measurement_preflight(df, spec):
    frame, ledger, frame_hash = prepare_measurement(df, spec)
    return dict(
        schema="measurement-preflight-v1",
        family=spec.family,
        spec_sha256=digest(spec.to_dict()),
        dataframe_sha256=frame_hash,
        n=len(frame),
        input_rows=ledger["input_rows"],
        missing_required=len(ledger["missing_excluded_data_rows"]),
        indeterminate=len(ledger["indeterminate_excluded_data_rows"]),
        reference_positive=int((frame["first"] == 1).sum()) if spec.diagnostic else None,
        reference_negative=int((frame["first"] == 0).sum()) if spec.diagnostic else None,
        scope="Eligibility, coding and pair counts only; no estimates or assumption validation.",
    )


def run_measurement(df, spec: MeasurementSpec):
    from scipy.stats import norm, t
    from sklearn.metrics import roc_auc_score, roc_curve

    frame, ledger, frame_hash = prepare_measurement(df, spec)
    config = dict(target="first", score_variable="second", confidence_level=spec.confidence_level)
    if spec.diagnostic and spec.diagnostic["test_kind"] == "score":
        config.update(
            threshold=spec.diagnostic["threshold"],
            positive_direction=spec.diagnostic["positive_direction"],
        )
    calculated = run_clinical_analysis(frame, spec.family, config)
    calculated.pop("case_set")
    points, roc, margin = [], None, None
    if spec.diagnostic:
        d = spec.diagnostic
        calculated["positive_direction"] = d["positive_direction"]
        if d["sampling"] != "single_gate":
            for name in ["positive_predictive_value", "negative_predictive_value", "accuracy"]:
                calculated["estimates"][name] = dict(
                    status="withheld_by_sampling_design",
                    estimate=None,
                    ci_lower=None,
                    ci_upper=None,
                    reason="依抽樣設計不提供：樣本比例雖可由交叉表計算，但抽樣未確認為共同納入途徑，不可將 PPV、NPV 或正確率推論為臨床母群表現。",
                )
        if d["test_kind"] == "score":
            gold = frame["first"].to_numpy(dtype=int)
            scores = frame["second"].to_numpy() * (
                1 if d["positive_direction"] == "greater_equal" else -1
            )
            if len(set(gold)) == 2:
                fpr, tpr, thresholds = roc_curve(gold, scores, drop_intermediate=False)
                auc = float(roc_auc_score(gold, scores))
                # Stratified subject bootstrap keeps reference class counts fixed.
                # Vectorized rank sums avoid a potentially quadratic pair matrix.
                from scipy.stats import rankdata

                positive, negative = scores[gold == 1], scores[gold == 0]
                rng = np.random.default_rng(20261001)
                n1, n0 = len(positive), len(negative)
                samples = []
                bootstrap_count = 1000 if min(n1, n0) >= 2 else 0
                for _ in range(bootstrap_count):
                    sample = np.concatenate([rng.choice(positive, n1), rng.choice(negative, n0)])
                    samples.append(
                        float((rankdata(sample)[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
                    )
                lower, upper = (
                    np.quantile(
                        samples, [(1 - spec.confidence_level) / 2, (1 + spec.confidence_level) / 2]
                    )
                    if samples
                    else (None, None)
                )
                roc = dict(
                    estimate=auc,
                    ci_lower=float(lower) if lower is not None else None,
                    ci_upper=float(upper) if upper is not None else None,
                    ci_method="stratified subject percentile bootstrap",
                    bootstrap_samples=bootstrap_count,
                    seed=20261001,
                    positive_count=n1,
                    negative_count=n0,
                    curve=[
                        dict(
                            false_positive_rate=float(x),
                            sensitivity=float(y),
                            oriented_threshold=float(z) if np.isfinite(z) else None,
                        )
                        for x, y, z in zip(fpr, tpr, thresholds, strict=True)
                    ],
                )
                if bootstrap_count == 0:
                    roc["reason"] = (
                        "At least two participants in each reference class are needed for bootstrap uncertainty; AUC point estimate only."
                    )
                calculated["warnings"].append(
                    "ROC/AUC describes the supplied sample. Bootstrap conditions on class counts, cannot correct selection/verification bias, and may be degenerate with tiny classes or perfect separation; no threshold is selected."
                )
            else:
                roc = dict(
                    estimate=None,
                    ci_lower=None,
                    ci_upper=None,
                    reason="ROC/AUC requires both reference classes.",
                    curve=[],
                )
    elif spec.agreement:
        a, n = spec.agreement, len(frame)
        first, second = frame["first"].to_numpy(), frame["second"].to_numpy()
        difference, mean = first - second, (first + second) / 2
        sd, bias = float(np.std(difference, ddof=1)), float(np.mean(difference))
        z = float(norm.ppf((1 + a["coverage"]) / 2))
        critical = float(t.ppf((1 + spec.confidence_level) / 2, n - 1))
        width = critical * sd * math.sqrt(1 / n + z * z / (2 * (n - 1)))
        for key, estimate in [
            ("lower_limit_of_agreement", bias - z * sd),
            ("upper_limit_of_agreement", bias + z * sd),
        ]:
            calculated["estimates"][key].update(
                estimate=estimate, ci_lower=estimate - width, ci_upper=estimate + width
            )
        calculated["agreement_coverage"] = a["coverage"]
        points = [
            dict(data_row=row, first=float(x), second=float(y), mean=float(m), difference=float(v))
            for row, x, y, m, v in zip(
                ledger["complete_data_rows"], first, second, mean, difference, strict=True
            )
        ]
        if a["acceptable_lower"] is not None:
            lo, hi = (
                calculated["estimates"]["lower_limit_of_agreement"],
                calculated["estimates"]["upper_limit_of_agreement"],
            )
            margin = dict(
                lower=a["acceptable_lower"],
                upper=a["acceptable_upper"],
                basis=a["margin_basis"],
                point_limits_within=lo["estimate"] >= a["acceptable_lower"]
                and hi["estimate"] <= a["acceptable_upper"],
                outer_ci_bounds_within=lo["ci_lower"] >= a["acceptable_lower"]
                and hi["ci_upper"] <= a["acceptable_upper"],
                within_count=int(
                    (
                        (difference >= a["acceptable_lower"])
                        & (difference <= a["acceptable_upper"])
                    ).sum()
                ),
                n=n,
                claim="Descriptive comparison to prespecified margins; not a formal equivalence or interchangeability test.",
            )
    result = dict(
        schema="clinical-measurement-v1",
        status="completed",
        **calculated,
        spec=spec.to_dict(),
        spec_sha256=digest(spec.to_dict()),
        dataframe_sha256=frame_hash,
        case_ledger=ledger,
        points=points,
        roc=roc,
        margin_comparison=margin,
        engine_versions={
            name: importlib.metadata.version(name)
            for name in ["numpy", "pandas", "scipy", "statsmodels", "scikit-learn"]
        },
    )
    result["receipt_sha256"] = digest(result)
    return result
