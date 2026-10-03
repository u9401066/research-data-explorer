"""Source-bound, reviewed display annotations; never alter numerical study specifications."""

import re
import uuid
import unicodedata

from rde.infrastructure.clinical.survival import SurvivalSpec
from rde.infrastructure.clinical.regression_contract import RegressionSpec
from rde.infrastructure.clinical.longitudinal_contract import LongitudinalSpec
from rde.infrastructure.clinical.weighting_contract import WeightingSpec
from rde.infrastructure.clinical.comparison_contract import ComparisonSpec
from rde.infrastructure.clinical.repeated_contract import RepeatedSpec
from rde.infrastructure.clinical.measurement import MeasurementSpec
from rde.infrastructure.prediction.contract import PredictionSpec


def submission_text(value):
    return value.isprintable() and all(
        char.isascii()
        or unicodedata.name(char, "").startswith(("LATIN", "GREEK"))
        or char in "µ°±×÷−≤≥²³¹‰·–—"
        for char in value
    )


def same_unit(first, second):
    groups = [
        ("s", "second", "seconds", "秒"),
        ("min", "minute", "minutes", "分鐘"),
        ("h", "hour", "hours", "小時"),
        ("d", "day", "days", "天", "日"),
        ("week", "weeks", "週"),
        ("month", "months", "月"),
        ("year", "years", "年"),
    ]
    aliases = {value: group[0] for group in groups for value in group}
    return aliases.get(first, first) == aliases.get(second, second)


def validate_dictionary(value, record, result, *, prediction=False):
    if value is None:
        return None
    required = {
        "schema",
        "source_sha256",
        "source_sheet",
        "dictionary_sha256",
        "dictionary_revision",
        "basis",
        "entries",
        "reviewed_at",
        "no_conversion_confirmed",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError(
            "Display dictionary must supply the complete publication-dictionary-v1 contract."
        )
    if (
        value["schema"] != "publication-dictionary-v1"
        or value["no_conversion_confirmed"] is not True
    ):
        raise ValueError("Explicit review of unchanged source units and codes is required.")
    # The caller verifies the typed source workflow before selecting this branch.
    # PredictionSpec has no clinical family field; do not infer it from missing fields.
    family = "prediction" if prediction else result.get("spec", {}).get("family")
    if family not in {
        "survival",
        "regression",
        "longitudinal",
        "weighting",
        "comparison",
        "repeated",
        "diagnostic_accuracy",
        "bland_altman",
        "cohens_kappa",
        "prediction",
    }:
        raise ValueError("Reviewed display dictionaries are not supported for this study family.")
    source = record.get("source", {})
    if value["source_sha256"] != source.get("sha256") or value["source_sheet"] != source.get(
        "sheet"
    ):
        raise ValueError("Display dictionary belongs to a different source file or worksheet.")
    if not isinstance(value["dictionary_sha256"], str) or not re.fullmatch(
        r"[a-f0-9]{64}", value["dictionary_sha256"]
    ):
        raise ValueError("The original reviewed dictionary SHA256 is required.")
    if type(value["dictionary_revision"]) is not int or value["dictionary_revision"] < 1:
        raise ValueError("Display dictionary must reference a reviewed revision.")
    basis = value["basis"]
    if not isinstance(basis, dict) or basis.get("kind") not in {
        "approved_plan",
        "reviewed_revision",
    }:
        raise ValueError(
            "Specify whether annotations came from the approved plan or a later reviewed revision."
        )
    if basis["kind"] == "approved_plan":
        if (
            set(basis) != {"kind", "plan_id"}
            or str(uuid.UUID(basis["plan_id"])) != basis["plan_id"]
        ):
            raise ValueError("Approved-plan dictionary needs its canonical plan UUID.")
    elif set(basis) != {"kind"}:
        raise ValueError("A later reviewed dictionary does not rewrite the approved plan.")
    if not isinstance(value["reviewed_at"], str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT[0-9:.]+Z", value["reviewed_at"]
    ):
        raise ValueError("Dictionary review timestamp is required.")
    entries = value["entries"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
        raise ValueError("Display dictionary requires 1..500 column entries.")
    if prediction:
        spec = PredictionSpec.parse(result["spec"])
        variables = {spec.target, *spec.predictors}
        variables.update(v for v in [spec.subject_variable, spec.time_variable] if v)
        # This contract never declared physical units. Reviewed units annotate the
        # source scale; the renderer must retain that limitation in every caption.
        units = {}
    elif family == "survival":
        spec = SurvivalSpec.parse(result["spec"])
        # Branches retain the primary dictionary even when they omit a predictor.
        variables = set(
            SurvivalSpec.parse(result.get("population_spec", result["spec"])).variables()
        )
        units = {spec.time: spec.time_unit}
    elif family == "regression":
        spec = RegressionSpec.parse(result["spec"])
        variables = set(spec.variables())
        units = {spec.outcome: spec.outcome_unit}
        units.update({p["column"]: p["unit"] for p in spec.predictors if p["kind"] == "continuous"})
        if spec.exposure:
            units[spec.exposure] = spec.exposure_unit
    elif family == "longitudinal":
        spec = LongitudinalSpec.parse(result["spec"])
        variables = set(spec.variables())
        units = {spec.time: spec.time_unit, spec.outcome: spec.outcome_unit}
        if spec.exposure:
            units[spec.exposure] = spec.exposure_unit
    elif family == "weighting":
        spec = WeightingSpec.parse(result["spec"])
        variables = set(spec.variables())
        units = {spec.outcome: spec.outcome_unit}
        units.update({p["column"]: p["unit"] for p in spec.covariates if p["kind"] == "continuous"})
    elif family == "comparison":
        spec = ComparisonSpec.parse(result["spec"])
        variables = set(spec.variables())
        units = {spec.outcome: spec.outcome_unit}
    elif family == "repeated":
        spec = RepeatedSpec.parse(result["spec"])
        variables = set(spec.variables())
        units = {column: spec.outcome_unit for column in spec.columns()}
    else:
        spec = MeasurementSpec.parse(result["spec"])
        variables = set(spec.variables())
        units = (
            {column: spec.agreement["unit"] for column in [spec.first, spec.second]}
            if spec.agreement
            else {}
        )
    columns = set()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) - {"column", "label_en", "unit", "source", "levels"}
            or not {"column", "source", "levels"} <= set(entry)
        ):
            raise ValueError(
                "A dictionary entry accepts column, label_en, unit, source and levels."
            )
        column = entry["column"]
        if not isinstance(column, str) or column not in variables or column in columns:
            raise ValueError("Dictionary columns must be unique and belong to the saved study.")
        columns.add(column)
        for key, limit in (("label_en", 180), ("unit", 80), ("source", 2000)):
            if key in entry and (
                not isinstance(entry[key], str)
                or not entry[key].strip()
                or len(entry[key]) > limit
                or "\x00" in entry[key]
            ):
                raise ValueError(f"Invalid dictionary {key}.")
        # English submission labels are explicit author input, not automatic translation.
        for key in ("label_en", "unit"):
            if key in entry and not submission_text(entry[key]):
                raise ValueError(
                    f"Dictionary {key} requires reviewed English text or scientific unit symbols."
                )
        if column in units and "unit" in entry and not same_unit(entry["unit"], units[column]):
            raise ValueError(
                f"Dictionary unit for {column!r} conflicts with the saved study; labeling cannot convert source values or comparison increments."
            )
        levels = entry["levels"]
        if not isinstance(levels, list) or len(levels) > 100:
            raise ValueError("A dictionary column accepts at most 100 code labels.")
        seen = set()
        for level in levels:
            if not isinstance(level, dict) or set(level) != {"value", "label_en"}:
                raise ValueError(
                    "Each code label requires its exact source value and reviewed English label."
                )
            code, label = level["value"], level["label_en"]
            if not isinstance(code, str) or len(code) > 400 or "\x00" in code or code in seen:
                raise ValueError("Dictionary codes must be unique original strings.")
            if (
                not isinstance(label, str)
                or not label.strip()
                or len(label) > 180
                or not submission_text(label)
            ):
                raise ValueError(
                    "Dictionary code labels require reviewed English text or scientific symbols."
                )
            seen.add(code)
    if family == "cohens_kappa":
        meanings = {
            entry["column"]: {level["value"]: level["label_en"] for level in entry["levels"]}
            for entry in entries
        }
        first, second = meanings.get(spec.first, {}), meanings.get(spec.second, {})
        for code in spec.categories:
            if code in first and code in second and first[code] != second[code]:
                raise ValueError(
                    "Kappa requires shared category meanings: conflicting reviewed labels for the same source code cannot be displayed as agreement."
                )
    return value


class DisplayDictionary:
    def __init__(self, value=None):
        self.value = value
        self.entries = {e["column"]: e for e in (value or {}).get("entries", [])}

    def label(self, column, fallback=None):
        return self.entries.get(column, {}).get(
            "label_en", column if fallback is None else fallback
        )

    def unit(self, column, fallback=None):
        return self.entries.get(column, {}).get("unit", fallback)

    def describe(self, column, levels=()):
        """Keep full reviewed meanings when a figure uses a compact variable/code label."""
        entry = self.entries.get(column)
        if not entry:
            return ""
        parts = []
        if "label_en" in entry:
            parts.append(f"label {entry['label_en']!r}")
        if "unit" in entry:
            parts.append(f"unit {entry['unit']!r}")
        parts.extend(
            f"code {code!r} denotes {self.level(column, code)!r}"
            for code in levels
            if self.level(column, code) != code
        )
        return (
            f"Reviewed display for source column {column!r}: {', '.join(parts)}. " if parts else ""
        )

    @staticmethod
    def compact(value, fallback, limit):
        return value if len(value) <= limit and submission_text(value) else fallback

    def level(self, column, value):
        return next(
            (
                e["label_en"]
                for e in self.entries.get(column, {}).get("levels", [])
                if e["value"] == value
            ),
            value,
        )

    def note(self):
        if not self.value:
            return ""
        basis = (
            "the approved plan"
            if self.value["basis"]["kind"] == "approved_plan"
            else "a separately reviewed source dictionary"
        )
        return (
            f"Display labels follow {basis} and were reviewed by the researcher. "
            "Original codes, numerical values and model specification are unchanged; "
            "no conversion or refitting was performed. "
        )
