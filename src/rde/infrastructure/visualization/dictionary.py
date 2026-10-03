"""Source-bound, reviewed display annotations; never alter numerical study specifications."""

import re
import uuid
import unicodedata

from rde.infrastructure.clinical.survival import SurvivalSpec


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


def validate_dictionary(value, record, result):
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
    if result.get("spec", {}).get("family") != "survival":
        raise ValueError(
            "Reviewed display dictionaries currently support survival studies and their branches."
        )
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
    spec = SurvivalSpec.parse(result["spec"])
    # Branches retain the primary dictionary even when they omit a predictor.
    variables = set(SurvivalSpec.parse(result.get("population_spec", result["spec"])).variables())
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
        if column == spec.time and "unit" in entry and not same_unit(entry["unit"], spec.time_unit):
            raise ValueError(
                "Dictionary time unit conflicts with the saved study; labeling cannot convert time values."
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
    return value


class DisplayDictionary:
    def __init__(self, value=None):
        self.value = value
        self.entries = {e["column"]: e for e in (value or {}).get("entries", [])}

    def label(self, column):
        return self.entries.get(column, {}).get("label_en", column)

    def unit(self, column):
        return self.entries.get(column, {}).get("unit")

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
