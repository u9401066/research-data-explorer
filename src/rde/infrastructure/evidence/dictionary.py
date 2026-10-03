"""Reviewed comparison-table labels retain treatment identity and input effect scale."""

from rde.infrastructure.visualization.dictionary import DisplayDictionary

from .workflow import JS_SPACE

DISPLAY_COLUMNS = {
    "study_id",
    "report_id",
    "treatment",
    "comparator",
    "effect",
    "se",
    "outcome",
    "timepoint",
    "population",
    "effect_modifiers",
}


def source_units(result):
    options = result["analysis"]["options"]
    unit = options["outcomeUnit"] if options["measure"] == "MD" else f"log {options['measure']}"
    return {"effect": unit, "se": unit, **({"outcome": unit} if options["measure"] == "MD" else {})}


def validate_bindings(value, record, result):
    if (
        value["basis"]["kind"] == "approved_plan"
        and value["basis"]["plan_id"] != result["source"]["identity"]["plan_id"]
    ):
        raise ValueError("Evidence dictionary belongs to a different approved plan.")
    table = record["dictionary_source_table"]
    shared = {}
    for entry in value["entries"]:
        column = entry["column"]
        index = table["columns"].index(column)
        original = {row[index] if index < len(row) else "" for row in table["rows"]}
        normalized = {}
        for level in entry["levels"]:
            raw, label = level["value"], level["label_en"]
            if raw not in original:
                raise ValueError(
                    "Evidence dictionary code is absent from the pinned source column."
                )
            code = raw.strip(JS_SPACE)
            if code in normalized and normalized[code] != label:
                raise ValueError(
                    "Source codes normalized to one evidence identity have conflicting labels."
                )
            normalized[code] = label
            if column in {"treatment", "comparator"}:
                if code in shared and shared[code] != label:
                    raise ValueError(
                        "Treatment and comparator must use the same meaning for one treatment identity."
                    )
                shared[code] = label


class EvidenceDisplayDictionary(DisplayDictionary):
    def level(self, column, value):
        # The saved evidence executor explicitly trims JS whitespace. Preserve the
        # original dictionary code in the receipt, and only resolve its display.
        return next(
            (
                level["label_en"]
                for level in self.entries.get(column, {}).get("levels", [])
                if level["value"].strip(JS_SPACE) == value.strip(JS_SPACE)
            ),
            value,
        )

    def treatment(self, value):
        for column in ("treatment", "comparator"):
            label = self.level(column, value)
            if label != value:
                return label
        return value
