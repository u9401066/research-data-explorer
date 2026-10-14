"""Prewritten relational truth and an independent SQLite aggregation oracle."""

import csv
import hashlib
import io
import random
import sqlite3
from pathlib import Path

import pytest

from rde.domain.models.preparation import Source, Specification
from rde.infrastructure.preparation.engine import Evaluation, timestamp
from rde.infrastructure.preparation.sources import inspect, load


def source(tmp_path, name, header, rows):
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    raw = text.getvalue().encode()
    path = tmp_path / f"{name}.csv"
    path.write_bytes(raw)
    return Source(id=name, path=str(path), sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def fixture(tmp_path):
    # Expected truth fixed before executing either implementation. IDs 001 and 1
    # are different people, as are site A/001 and site B/001.
    people = [
        ["A", "001", 40, "2025-01-10T00:00:00Z", "yes"],
        ["A", "1", 30, "2025-01-10T00:00:00Z", "yes"],
        ["B", "001", 50, "2025-01-10T00:00:00Z", "yes"],
        ["A", "003", 60, "2025-01-10T00:00:00Z", "yes"],
        ["A", "004", 70, "2025-01-10T00:00:00Z", "no"],
        ["A", "005", 80, "2025-01-10T00:00:00Z", "unknown"],
        ["A", "006", 16, "2025-01-10T00:00:00Z", "yes"],
    ]
    labs = [
        ["l1", "A", "001", "2025-01-07T00:00:00Z", "2025-01-07T01:00:00Z", 10],
        ["l2", "A", "001", "2025-01-08T00:00:00Z", "2025-01-08T01:00:00Z", 20],
        ["l3", "A", "001", "2025-01-09T00:00:00Z", "2025-01-09T01:00:00Z", 30],
        ["l4", "A", "1", "2024-12-01T00:00:00Z", "2024-12-01T01:00:00Z", 999],
        ["l5", "B", "001", "2025-01-09T00:00:00Z", "2025-01-11T01:00:00Z", 888],
        ["l6", "A", "006", "2025-01-09T00:00:00Z", "2025-01-09T01:00:00Z", 1],
        ["orphan", "Z", "999", "2025-01-09T00:00:00Z", "2025-01-09T01:00:00Z", 2],
    ]
    meds = [["m1", "A", "001"], ["m2", "A", "001"]]
    sources = [
        source(tmp_path, "people", ["site", "pid", "age", "index_at", "lab_exported"], people),
        source(tmp_path, "labs", ["lab_id", "site", "pid", "taken_at", "known_at", "value"], labs),
        source(tmp_path, "meds", ["med_id", "site", "pid"], meds),
    ]
    specification = {
        "unit": {
            "source_id": "people",
            "kind": "patient",
            "keys": ["site", "pid"],
            "subject_keys": ["site", "pid"],
            "index_column": "index_at",
        },
        "relations": [
            {
                "id": "labs",
                "source_id": "labs",
                "left_keys": ["site", "pid"],
                "right_keys": ["site", "pid"],
                "kind": "events",
                "record_keys": ["lab_id"],
                "coverage": {
                    "mode": "by_column",
                    "column": "lab_exported",
                    "exported_values": ["yes"],
                    "not_exported_values": ["no"],
                },
                "window": {
                    "event_column": "taken_at",
                    "available_column": "known_at",
                    "start_days": -7,
                    "end_days": 0,
                },
                "features": [
                    {"output": "lab_count", "aggregate": "count"},
                    {
                        "output": "lab_mean",
                        "column": "value",
                        "aggregate": "mean",
                        "value_type": "number",
                    },
                ],
                "reason": "Synthetic oracle: baseline available labs, retaining partial linkage states",
            },
            {
                "id": "meds",
                "source_id": "meds",
                "left_keys": ["site", "pid"],
                "right_keys": ["site", "pid"],
                "kind": "events",
                "record_keys": ["med_id"],
                "coverage": {"mode": "complete"},
                "features": [{"output": "drug_count", "aggregate": "count"}],
                "reason": "Synthetic oracle: count distinct medication records separately",
            },
        ],
        "cohort": [
            {
                "id": "adult",
                "reason": "Prewritten synthetic age eligibility",
                "keep": {"column": "age", "op": "gte", "value": 18},
            }
        ],
        "definitions": {
            "unit": "One patient per site and lexical patient ID",
            "linkage": "Synthetic identifiers share the site namespace",
            "time": "UTC index; labs must be known at index",
            "missingness": "Explicit export flags; unknown never means negative",
        },
    }
    return sources, specification, (people, labs, meds)


def evaluate(sources, specification):
    return Evaluation(
        {s.id: load(s) for s in sources}, Specification.model_validate(specification)
    ).evaluate()


def sql_oracle(rows):
    people, labs, meds = rows
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        create table people(site text, pid text, age integer, index_at text, exported text);
        create table labs(id text, site text, pid text, taken_at text, known_at text, value real);
        create table meds(id text, site text, pid text);
    """)
    connection.executemany("insert into people values(?,?,?,?,?)", people)
    connection.executemany("insert into labs values(?,?,?,?,?,?)", labs)
    connection.executemany("insert into meds values(?,?,?)", meds)
    # Independent SQL uses correlated aggregate queries, not the native rules or
    # native parsing/matching/aggregation helpers. Never a three-table raw join.
    result = connection.execute("""
        select p.site, p.pid,
          (select avg(l.value) from labs l where l.site=p.site and l.pid=p.pid
            and julianday(l.taken_at) between julianday(p.index_at)-7 and julianday(p.index_at)
            and julianday(l.known_at)<=julianday(p.index_at)),
          (select count(*) from meds m where m.site=p.site and m.pid=p.pid)
        from people p where p.age>=18 order by p.site,p.pid
    """).fetchall()
    connection.close()
    return result


def test_predeclared_truth_and_independent_sql_prevent_three_by_two_expansion(tmp_path):
    sources, specification, raw = fixture(tmp_path)
    result = evaluate(sources, specification)
    assert result.summary()["ready_for_approval"], result.issues
    assert len(result.rows) == 6
    by_key = {(r["site"], r["pid"]): r for r in result.rows}
    assert by_key["A", "001"]["lab_count"] == 3
    assert by_key["A", "001"]["lab_mean"] == 20
    assert by_key["A", "001"]["drug_count"] == 2
    expected = {
        ("A", "001"): ("matched", 3),
        ("A", "1"): ("outside_window", 0),
        ("B", "001"): ("not_available", None),
        ("A", "003"): ("no_record", 0),
        ("A", "004"): ("not_exported", None),
        ("A", "005"): ("unknown_coverage", None),
    }
    assert {k: (r["_rde_labs_status"], r["lab_count"]) for k, r in by_key.items()} == expected
    for site, pid, mean, count in sql_oracle(raw):
        assert by_key[site, pid]["lab_mean"] == mean
        assert by_key[site, pid]["drug_count"] == count
    assert [step["after"]["subjects"] for step in result.flow] == [7, 6, 6, 6]
    assert result.relationships[0]["unmatched_source_rows"] == 2  # excluded minor + orphan
    row = by_key["A", "001"]
    references = result.trace[row["_rde_unit_id"]]["cells"]["lab_mean"]["sources"]
    assert [r["record_index"] for r in references] == [0, 1, 2]
    assert all(
        r["source_sha256"] == sources[1].sha256 and r["column"] == "value" for r in references
    )


def test_observed_events_with_unknown_coverage_are_partial_not_complete(tmp_path):
    sources, spec, _ = fixture(tmp_path)
    spec["relations"][0]["coverage"] = {"mode": "unknown"}
    result = evaluate(sources, spec)
    row = next(r for r in result.rows if r["site"] == "A" and r["pid"] == "001")
    assert row["lab_count"] == 3
    assert row["_rde_labs_status"] == "matched_partial"
    assert any(i["code"] == "PARTIAL_OBSERVATIONS_labs" for i in result.issues)
    assert any(i["code"] == "UNVERIFIED_TIME_meds" for i in result.issues)


def test_retained_patients_do_not_hide_an_agent_filter_that_removed_every_lab(tmp_path):
    sources, spec, _ = fixture(tmp_path)
    spec["relations"][0]["filters"] = [{"column": "value", "op": "lte", "value": 0}]
    result = evaluate(sources, spec)
    assert len(result.rows) == 6
    assert result.summary()["feature_quality"]["lab_mean"] == {"observed": 0, "missing": 6}
    assert "ALL_MISSING_FEATURE_lab_mean" in result.summary()["warnings"]


def test_shuffled_records_preserve_every_output_value_and_unit_identity(tmp_path):
    sources, specification, _ = fixture(tmp_path)
    original = evaluate(sources, specification)
    shuffled = []
    for s in sources:
        table = load(s)
        rows = [[row.values[c] for c in table.columns] for row in table.rows]
        random.Random(124).shuffle(rows)
        shuffled.append(source(tmp_path, s.id, table.columns, rows))
    assert original.rows == evaluate(shuffled, specification).rows
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        load(sources[0])


@pytest.mark.parametrize(
    "policy,ready,people",
    [("block", False, 5), ("drop_identical", True, 6), ("exclude_conflicts", True, 5)],
)
def test_duplicate_unit_policy_is_explicit(tmp_path, policy, ready, people):
    sources, spec, raw = fixture(tmp_path)
    table = load(sources[0])
    sources[0] = source(tmp_path, "people", table.columns, raw[0] + [raw[0][0]])
    spec["unit"]["duplicates"] = policy
    result = evaluate(sources, spec)
    assert result.summary()["ready_for_approval"] is ready
    assert len(result.rows) == people
    assert any(e["reason"] in {"duplicate_key", "identical_duplicate"} for e in result.exceptions)


def test_conflicting_same_timestamp_does_not_pick_first_row(tmp_path):
    sources, spec, raw = fixture(tmp_path)
    source_table = load(sources[1])
    rows = raw[1] + [["tie", "A", "001", "2025-01-09T00:00:00Z", "2025-01-09T01:00:00Z", 55]]
    sources[1] = source(tmp_path, "labs", source_table.columns, rows)
    spec["relations"][0]["features"][1]["aggregate"] = "last"
    result = evaluate(sources, spec)
    assert not result.summary()["ready_for_approval"]
    assert any("same event time" in i["message"] for i in result.issues)


def test_last_accepts_different_earlier_values_while_unique_blocks_whole_window(tmp_path):
    sources, spec, _ = fixture(tmp_path)
    feature = spec["relations"][0]["features"][1]
    feature.update(output="lab_endpoint", aggregate="last")
    latest = evaluate(sources, spec)
    assert latest.summary()["ready_for_approval"], latest.issues
    row = next(r for r in latest.rows if r["site"] == "A" and r["pid"] == "001")
    assert row["lab_endpoint"] == 30
    assert row["_rde_labs_status"] == "matched"
    refs = latest.trace[row["_rde_unit_id"]]["cells"]["lab_endpoint"]["sources"]
    assert [ref["record_index"] for ref in refs] == [2]
    assert all(ref["source_sha256"] == sources[1].sha256 for ref in refs)

    # The same observations are not a single value across the whole window.
    feature["aggregate"] = "unique"
    unique = evaluate(sources, spec)
    assert not unique.summary()["ready_for_approval"]
    assert any(i["message"] == "lookup/unique has conflicting values" for i in unique.issues)
    blocked = next(r for r in unique.rows if r["_rde_unit_id"] == row["_rde_unit_id"])
    assert blocked["lab_endpoint"] is None
    assert blocked["_rde_labs_status"] == "link_failed"
    assert len(unique.rows) == len(latest.rows) == 6


def test_last_equal_timestamp_values_keep_all_members_independent_of_row_order(tmp_path):
    sources, spec, raw = fixture(tmp_path)
    header = load(sources[1]).columns
    rows = raw[1] + [["tie", "A", "001", "2025-01-09T00:00:00Z", "2025-01-09T01:00:00Z", "30.0"]]
    spec["relations"][0]["features"][1].update(output="lab_endpoint", aggregate="last")
    expected_unit_id = None
    for ordered in (rows, list(reversed(rows))):
        sources[1] = source(tmp_path, "labs", header, ordered)
        result = evaluate(sources, spec)
        assert result.summary()["ready_for_approval"], result.issues
        row = next(r for r in result.rows if r["site"] == "A" and r["pid"] == "001")
        assert row["lab_endpoint"] == 30
        assert row["lab_count"] == 4
        if expected_unit_id is None:
            expected_unit_id = row["_rde_unit_id"]
        assert row["_rde_unit_id"] == expected_unit_id
        refs = result.trace[row["_rde_unit_id"]]["cells"]["lab_endpoint"]["sources"]
        assert len(refs) == 2
        assert {ordered[ref["record_index"]][0] for ref in refs} == {"l3", "tie"}
        assert all(
            ref["source_sha256"] == sources[1].sha256 and ref["column"] == "value" for ref in refs
        )


def test_last_skips_latest_missing_value_and_never_turns_all_missing_into_zero(tmp_path):
    sources, spec, raw = fixture(tmp_path)
    header = load(sources[1]).columns
    rows = raw[1] + [
        ["blank", "A", "001", "2025-01-09T12:00:00Z", "2025-01-09T13:00:00Z", ""],
        ["token", "A", "001", "2025-01-09T15:00:00Z", "2025-01-09T16:00:00Z", "NA"],
    ]
    spec["relations"][0]["features"][1].update(
        output="lab_endpoint", aggregate="last", missing_tokens=["", "NA"]
    )
    sources[1] = source(tmp_path, "labs", header, rows)
    result = evaluate(sources, spec)
    assert result.summary()["ready_for_approval"], result.issues
    row = next(r for r in result.rows if r["site"] == "A" and r["pid"] == "001")
    assert row["lab_endpoint"] == 30
    assert row["lab_count"] == 5
    refs = result.trace[row["_rde_unit_id"]]["cells"]["lab_endpoint"]["sources"]
    assert [rows[ref["record_index"]][0] for ref in refs] == ["l3"]

    all_missing = [[*r[:-1], ""] if r[1:3] == ["A", "001"] else r for r in rows]
    sources[1] = source(tmp_path, "labs", header, all_missing)
    missing = evaluate(sources, spec)
    row = next(r for r in missing.rows if r["site"] == "A" and r["pid"] == "001")
    assert row["lab_endpoint"] is None
    assert row["lab_count"] == 5
    assert row["_rde_labs_status"] == "matched"
    assert len(missing.rows) == len(result.rows) == 6


def test_null_foreign_key_is_never_matched_or_interpreted_as_absence(tmp_path):
    sources, spec, raw = fixture(tmp_path)
    table = load(sources[1])
    sources[1] = source(
        tmp_path,
        "labs",
        table.columns,
        raw[1] + [["bad", "A", "", "2025-01-09", "2025-01-09", 123]],
    )
    result = evaluate(sources, spec)
    unmatched = next(r for r in result.rows if r["pid"] == "003")
    assert unmatched["_rde_labs_status"] == "link_failed"
    assert unmatched["lab_count"] is None
    assert result.relationships[0]["null_link_rows"] == 1
    assert "UNLINKABLE_ROWS_labs" in result.summary()["warnings"]


def test_composite_keys_do_not_collide_and_whitespace_needs_explicit_policy(tmp_path):
    src = source(tmp_path, "people", ["site", "pid"], [["A", "B|C"], ["A|B", "C"], [" A", "B|C"]])
    spec = {
        "unit": {
            "source_id": "people",
            "kind": "patient",
            "keys": ["site", "pid"],
            "subject_keys": ["site", "pid"],
        },
        "definitions": {
            k: "Synthetic explicit definition" for k in ("unit", "linkage", "time", "missingness")
        },
    }
    assert len(evaluate([src], spec).rows) == 3
    spec["unit"]["key_normalization"] = "trim"
    result = evaluate([src], spec)
    assert not result.summary()["ready_for_approval"]
    assert any(i["code"] == "DUPLICATE_KEY" for i in result.issues)


def test_inspection_returns_candidates_without_disclosing_raw_patient_values(tmp_path):
    sources, _, _ = fixture(tmp_path)
    result = inspect({s.id: load(s) for s in sources})
    assert result["candidate_relations"]
    assert "sample_values" not in str(result)
    assert any(
        c["columns"] == ["site", "pid"] and c["unique"]
        for c in result["sources"][0]["candidate_keys"]
    )


def test_cohort_requires_definitions_and_unknown_filter_columns_fail(tmp_path):
    sources, spec, _ = fixture(tmp_path)
    spec["definitions"] = {}
    result = evaluate(sources, spec)
    assert not result.summary()["ready_for_approval"]
    assert {i["code"] for i in result.issues} >= {
        "DEFINITION_UNIT",
        "DEFINITION_TIME",
        "DEFINITION_LINKAGE",
        "DEFINITION_MISSINGNESS",
    }
    spec["cohort"][0]["keep"]["column"] = "does_not_exist"
    result = evaluate(sources, spec)
    assert any(i["code"] == "INVALID_COHORT_VALUE" for i in result.issues)


def test_future_window_and_ambiguous_local_times_are_rejected(tmp_path):
    _, spec, _ = fixture(tmp_path)
    spec["relations"][0]["window"]["end_days"] = 1
    with pytest.raises(ValueError, match="baseline cannot"):
        Specification.model_validate(spec)
    for local in ("2025-11-02T01:30:00", "2025-03-09T02:30:00"):
        with pytest.raises(ValueError, match="ambiguous or nonexistent"):
            timestamp(local, "America/New_York")
    assert (
        timestamp("2025-11-02T01:30:00-04:00", "America/New_York").isoformat()
        == "2025-11-02T05:30:00+00:00"
    )


def test_output_can_omit_identifier_columns_without_losing_denominators(tmp_path):
    sources, spec, _ = fixture(tmp_path)
    spec["unit"]["retain_columns"] = ["age"]
    result = evaluate(sources, spec)
    assert result.summary()["population"]["subjects"] == 6
    assert "pid" not in result.rows[0]


def test_excel_formula_is_not_silently_treated_as_cached_measurement(tmp_path):
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["pid", "value"])
    sheet.append(["001", "=1+1"])
    path = tmp_path / "formulas.xlsx"
    book.save(path)
    s = Source(
        id="xlsx",
        path=str(path),
        bytes=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        sheet=sheet.title,
    )
    with pytest.raises(ValueError, match="values-only"):
        load(s)


def test_declared_cleaning_precedes_eligibility_and_invalid_numbers_block(tmp_path):
    inputs, spec, _ = fixture(tmp_path)
    spec["unit"]["columns"] = {"age": {"value_type": "number", "missing_tokens": ["", "40"]}}
    spec["cohort"] = [
        {
            "id": "observed_age",
            "reason": "Synthetic explicit sentinel",
            "keep": {"column": "age", "op": "present"},
        }
    ]
    result = evaluate(inputs, spec)
    assert result.summary()["ready_for_approval"]
    assert len(result.rows) == 6
    assert not any(r["site"] == "A" and r["pid"] == "001" for r in result.rows)
    spec["cohort"][0]["keep"] = {"column": "age", "op": "in", "value": ["30", "50"]}
    result = evaluate(inputs, spec)
    assert sorted(r["age"] for r in result.rows) == [30, 50]
    spec["unit"]["columns"]["lab_exported"] = {"value_type": "number"}
    blocked = evaluate(inputs, spec)
    assert not blocked.summary()["ready_for_approval"]
    assert any(
        i["code"] == "INVALID_OUTPUT_TYPE" and i["column"] == "lab_exported" for i in blocked.issues
    )


def test_encounters_keep_subject_denominator_and_reused_events_are_explicit(tmp_path):
    inputs, spec, _ = fixture(tmp_path)
    people = source(
        tmp_path,
        "encounters",
        ["site", "pid", "visit", "index_at", "lab_exported", "age"],
        [
            ["A", "001", "v1", "2025-01-10T00:00:00Z", "yes", 40],
            ["A", "001", "v2", "2025-01-11T00:00:00Z", "yes", 40],
        ],
    )
    inputs[0] = people
    spec["unit"].update(source_id="encounters", kind="encounter", keys=["site", "pid", "visit"])
    result = evaluate(inputs, spec)
    assert result.summary()["population"]["subjects"] == 1
    assert result.summary()["population"]["units"] == 2
    assert not result.summary()["ready_for_approval"]
    assert any(i["code"] == "REUSED_EVENTS_labs" for i in result.issues)
    for relation in spec["relations"]:
        relation["reuse_events"] = "allow"
    allowed = evaluate(inputs, spec)
    assert allowed.summary()["ready_for_approval"]
    assert [r["lab_count"] for r in allowed.rows] == [3, 3]
    assert allowed.summary()["population"]["encounters"] == 2


def test_independent_sql_compares_every_analysis_value_and_identity(tmp_path):
    import json

    inputs, spec, _ = fixture(tmp_path)
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    for source in inputs:
        with Path(source.path).open(newline="") as file:
            reader = csv.reader(file)
            columns = next(reader)
            # All raw columns remain lexical strings in the reference import.
            db.execute(
                f'CREATE TABLE "{source.id}" (' + ",".join(f'"{c}" TEXT' for c in columns) + ")"
            )
            db.executemany(
                f'INSERT INTO "{source.id}" VALUES (' + ",".join("?" for _ in columns) + ")", reader
            )
    sql = (Path(__file__).parent / "fixtures/relational-preparation/reference.sql").read_text()
    expected = [dict(row) for row in db.execute(sql)]
    db.close()
    actual = evaluate(inputs, spec).rows
    assert len(actual) == len(expected) == 6
    for row, reference in zip(actual, expected, strict=True):
        assert {
            k: v for k, v in row.items() if k not in {"_rde_unit_id", "_rde_subject_id"}
        } == reference
        key = [row["site"], row["pid"]]

        # Reference identities use only stdlib JSON/SHA, no native key helpers.
        def independent_hash(value):
            return hashlib.sha256(
                json.dumps(
                    value,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()

        assert row["_rde_unit_id"] == "u_" + independent_hash(["preparation", "patient", key])
        assert row["_rde_subject_id"] == "s_" + independent_hash(["preparation", key])
