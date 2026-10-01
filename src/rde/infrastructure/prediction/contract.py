from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class PredictionSpec:
    target: str
    predictors: list[str]
    prediction_time_definition: str
    study_design: str
    sampling: str
    sampling_description: str
    target_definition: str
    features_available_at_prediction: bool = False
    task: str = "binary"
    positive_class: str = "1"
    categorical_predictors: list[str] | None = None
    split: str = "random"
    subject_variable: str | None = None
    time_variable: str | None = None
    cutoff: str | None = None
    test_fraction: float = 0.2
    seed: int = 20260923
    candidates: list[str] | None = None
    cv_folds: int = 3
    threshold: float = 0.5
    confidence_level: float = 0.95
    bootstrap_samples: int = 200
    decision_curve: dict | None = None

    @classmethod
    def parse(cls, options: dict) -> "PredictionSpec":
        if not isinstance(options, dict):
            raise ValueError("Prediction options must be an object.")
        unknown = set(options) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown prediction options: {sorted(unknown)}")
        required = {
            "target",
            "predictors",
            "prediction_time_definition",
            "study_design",
            "sampling",
            "sampling_description",
            "target_definition",
        }
        if not required.issubset(options):
            raise ValueError(f"Missing prediction design fields: {sorted(required - set(options))}")
        spec = cls(**options)
        spec.validate()
        return spec

    def validate(self) -> None:
        if not isinstance(self.target, str) or not self.target:
            raise ValueError("Specify a target column.")
        if not isinstance(self.predictors, list) or not 1 <= len(self.predictors) <= 50:
            raise ValueError("Specify 1..50 prespecified predictors.")
        if any(not isinstance(p, str) or not p for p in self.predictors) or len(
            set(self.predictors)
        ) != len(self.predictors):
            raise ValueError("Predictors must be distinct, nonempty column names.")
        if self.task not in {"binary", "regression"}:
            raise ValueError("task must be binary or regression.")
        if self.study_design not in {"observational_cohort", "diagnostic_accuracy", "case_control"}:
            raise ValueError("Specify the actual cohort, diagnostic or case-control study design.")
        if self.sampling not in {"single_gate", "two_gate", "unknown"}:
            raise ValueError("sampling must be single_gate, two_gate or unknown.")
        for name in ["sampling_description", "target_definition"]:
            value = getattr(self, name)
            if not isinstance(value, str) or not 5 <= len(value.strip()) <= 4000:
                raise ValueError(
                    f"{name} must describe known design facts and unknowns (5..4000 characters)."
                )
        if self.study_design == "case_control" and self.sampling != "two_gate":
            raise ValueError(
                "Case-control studies require explicit outcome-selected (two_gate) sampling."
            )
        if self.study_design == "observational_cohort" and self.sampling == "two_gate":
            raise ValueError("Outcome-selected sampling cannot be labeled an observational cohort.")
        if self.task != "binary" and self.study_design != "observational_cohort":
            raise ValueError(
                "Diagnostic and case-control prediction currently support binary outcomes only."
            )
        if self.decision_curve is not None:
            curve = self.decision_curve
            if not isinstance(curve, dict) or set(curve) != {
                "thresholds",
                "action",
                "threshold_basis",
                "independent_observations",
            }:
                raise ValueError(
                    "decision_curve requires thresholds, action, threshold_basis and independent_observations."
                )
            if self.task != "binary" or self.sampling != "single_gate":
                raise ValueError(
                    "Decision curves require binary outcomes and declared single-gate sampling; unknown or outcome-selected samples cannot establish population net benefit."
                )
            if curve["independent_observations"] is not True:
                raise ValueError(
                    "Decision curves require confirmation of one independent decision per participant."
                )
            for name in ["action", "threshold_basis"]:
                if not isinstance(curve[name], str) or not 5 <= len(curve[name].strip()) <= 2000:
                    raise ValueError(
                        f"decision_curve.{name} must describe the intended decision and prespecified utility trade-off."
                    )
            thresholds = curve["thresholds"]
            if (
                not isinstance(thresholds, list)
                or not 1 <= len(thresholds) <= 19
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or not 0.001 <= value <= 0.999
                    for value in thresholds
                )
                or thresholds != sorted(set(thresholds))
            ):
                raise ValueError(
                    "Decision thresholds must be 1..19 distinct increasing probabilities between 0.001 and 0.999."
                )
        if self.split not in {"random", "group", "temporal"}:
            raise ValueError("split must be random, group or temporal.")
        for name in ["subject_variable", "time_variable", "cutoff"]:
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a nonempty string or null.")
        if self.split != "temporal" and (self.time_variable is not None or self.cutoff is not None):
            raise ValueError("Time variable and cutoff apply only to temporal splits.")
        if (
            self.features_available_at_prediction is not True
            or not isinstance(self.prediction_time_definition, str)
            or len(self.prediction_time_definition.strip()) < 5
        ):
            raise ValueError(
                "Confirm predictor availability and define the prediction time before fitting."
            )
        if self.split == "group" and not self.subject_variable:
            raise ValueError("Group split requires subject_variable.")
        if self.split == "random" and self.subject_variable:
            raise ValueError(
                "Use group split when a subject key is provided; independent-row splitting is not allowed."
            )
        if self.split == "temporal" and (not self.time_variable or not self.cutoff):
            raise ValueError("Temporal split requires time_variable and an explicit ISO cutoff.")
        reserved = {self.target, self.subject_variable, self.time_variable} - {None}
        if reserved.intersection(self.predictors):
            raise ValueError("Target, subject key and split time cannot be predictors.")
        if len(reserved) != len(
            [v for v in [self.target, self.subject_variable, self.time_variable] if v]
        ):
            raise ValueError("Target, subject and time roles must use different columns.")
        if self.categorical_predictors is not None and (
            not isinstance(self.categorical_predictors, list)
            or any(not isinstance(p, str) for p in self.categorical_predictors)
            or not set(self.categorical_predictors).issubset(self.predictors)
            or len(set(self.categorical_predictors)) != len(self.categorical_predictors)
        ):
            raise ValueError("Categorical predictors must be a distinct subset of predictors.")
        for name, low, high in [
            ("test_fraction", 0.1, 0.5),
            ("threshold", 0.001, 0.999),
            ("confidence_level", 0.8, 0.999),
        ]:
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError(f"{name} must be finite, between {low} and {high}.")
        for name, low, high in [
            ("seed", 0, 2**32 - 1),
            ("cv_folds", 2, 5),
            ("bootstrap_samples", 0, 1000),
        ]:
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}.")
        if self.candidates is not None and (
            not isinstance(self.candidates, list)
            or not self.candidates
            or any(not isinstance(p, str) for p in self.candidates)
            or len(self.candidates) != len(set(self.candidates))
            or not set(self.candidates).issubset({"linear", "random_forest"})
        ):
            raise ValueError(
                "candidates must be a nonempty distinct subset of linear/random_forest."
            )
        if not isinstance(self.positive_class, str):
            raise ValueError("positive_class must be the explicit source label as text.")

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "categorical_predictors": self.categorical_predictors or [],
            "candidates": self.candidates or ["linear", "random_forest"],
        }
