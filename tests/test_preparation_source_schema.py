"""Raw-source schema is evidence about parser output, not clinical inference."""

from datetime import date
import hashlib
import json

import pytest

from rde.domain.models.preparation import Source
from rde.infrastructure.preparation import sources, workflow
from test_preparation_engine import source


def inspect_one(value):
    table = sources.load(value)
    profile = sources.inspect({value.id: table})["sources"][0]
    schema = profile["source_schema"]
    assert schema["schema_sha256"] == sources.digest(
        {k: v for k, v in schema.items() if k != "schema_sha256"}
    )
    assert schema["schema"] == "rde-source-table-schema-v1"
    return table, profile, schema


def test_csv_schema_preserves_lexical_ids_and_literal_tokens_without_disclosing_values(tmp_path):
    value = source(
        tmp_path,
        "patients",
        ["patient_id", "value", "date"],
        [
            ["001", "NA", "2025-01-01"],
            ["1", " ", "2025-01-02"],
            ["002", "", "2025-01-03"],
            ["003", "NULL", "2025-01-04"],
        ],
    )
    table, profile, schema = inspect_one(value)
    assert schema["source_sha256"] == value.sha256
    assert schema["source_bytes"] == value.bytes
    assert schema["column_order"] == ["patient_id", "value", "date"]
    assert [c["index"] for c in schema["columns"]] == [0, 1, 2]
    assert [c["storage_type"] for c in schema["columns"]] == ["text"] * 3
    assert schema["clinical_semantics"] == "not_inferred"
    assert schema["columns"][0]["observed_constraints"] == {
        "missing_rows": 0,
        "distinct_nonmissing": 4,
        "numeric_excel_cells": 0,
        "unique_nonmissing": True,
        "no_missing": True,
    }
    assert schema["columns"][1]["observed_constraints"]["missing_rows"] == 2
    assert schema["columns"][1]["observed_constraints"]["distinct_nonmissing"] == 2
    assert table.rows[0].values == {"patient_id": "001", "value": "NA", "date": "2025-01-01"}
    assert table.rows[1].values["patient_id"] == "1" and table.rows[1].values["value"] == " "
    assert schema["missing_convention"]["automatic_null_coercion"] is False
    assert "2025-01-01" not in json.dumps(profile)
    assert schema["parser"] == {
        "format": "csv",
        "encoding": "utf-8-sig",
        "delimiter": ",",
        "sheet": None,
        "implicit_single_sheet": False,
    }
    assert profile["columns"][1] == {
        "name": "value",
        "missing": 2,
        "distinct": 2,
        "numeric_excel_cells": 0,
    }


def test_schema_binds_actual_bytes_and_rejects_changed_source(tmp_path):
    value = source(tmp_path, "patients", ["id"], [["001"], ["002"]])
    _, _, original = inspect_one(value)
    revised = source(tmp_path, "patients", ["id"], [["002"], ["001"]])
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        inspect_one(value)
    _, _, changed = inspect_one(revised)
    assert changed["columns"] == original["columns"]
    assert changed["source_sha256"] != original["source_sha256"]
    assert changed["schema_sha256"] != original["schema_sha256"]


def test_xlsx_parser_normalization_and_sheet_identity_are_explicit(tmp_path):
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "first"
    sheet.append(["id", "date", "flag", "number", "empty"])
    sheet.append(["001", date(2025, 1, 1), True, 12, None])
    second = book.create_sheet("second")
    second.append(["id", "date", "flag", "number", "empty"])
    second.append(["001", date(2025, 1, 1), True, 12, None])
    path = tmp_path / "book.xlsx"
    book.save(path)
    value = Source(
        id="book",
        path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bytes=path.stat().st_size,
        sheet="first",
    )
    table, _, schema = inspect_one(value)
    assert table.rows[0].values == {
        "id": "001",
        "date": "2025-01-01T00:00:00",
        "flag": "true",
        "number": "12",
        "empty": "",
    }
    assert schema["columns"][3]["observed_constraints"]["numeric_excel_cells"] == 1
    assert all(c["storage_type"] == "text" for c in schema["columns"])
    assert schema["parser"]["sheet"] == "first"
    _, _, other = inspect_one(value.model_copy(update={"sheet": "second"}))
    assert schema["source_sha256"] == other["source_sha256"]
    assert schema["schema_sha256"] != other["schema_sha256"]


def test_contract_distinguishes_raw_typed_and_semantic_schemas():
    semantics = workflow.execute(None, {"op": "contract"})["execution_semantics"]["source_schema"]
    assert "rde-source-table-schema-v1" in semantics
    assert "analysis.schema.json" in semantics
    assert "semantic variable classification" in semantics
