"""Pivot the pinned nlme Orthodont extract without calculating an analysis.

Input is the retained Workbench CRAN acquisition (nlme 3.1-168). Every wide
measurement records its exact original source row. Estimates must use RDE MCP.
"""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil

SOURCE_SHA256 = "ca7c0296405bb2bd5959cd5fff7c50a5035606f16ac308c7797f58666fcd7aa1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source, output):
    os.umask(0o077)
    if sha(source / "Orthodont.csv") != SOURCE_SHA256:
        raise ValueError("Orthodont source differs from pinned nlme 3.1-168 extraction.")
    with (source / "Orthodont.csv").open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["distance", "age", "Subject", "Sex"]:
            raise ValueError("Unexpected Orthodont columns.")
        rows = list(reader)
    if len(rows) != 108:
        raise ValueError("Expected exactly 108 original observations.")
    people, mapping = {}, []
    ages = ["8", "10", "12", "14"]
    for source_row, row in enumerate(rows, 1):
        subject, age = row["Subject"], row["age"]
        if not subject or age not in ages or not row["distance"]:
            raise ValueError("Review source identity, age or missing measurements.")
        person = people.setdefault(subject, {"study_code": subject, "sex": row["Sex"]})
        column = f"distance_age{age}"
        if column in person or person["sex"] != row["Sex"]:
            raise ValueError("Duplicated subject/age or conflicting subject sex.")
        person[column] = row["distance"]
        mapping.append(
            {
                "study_code": subject,
                "column": column,
                "source_data_row": source_row,
                "source_column": "distance",
                "value": row["distance"],
            }
        )
    columns = [f"distance_age{age}" for age in ages]
    if len(people) != 27 or any(set(p) != {"study_code", "sex", *columns} for p in people.values()):
        raise ValueError("Expected 27 subjects with all four observed ages; never impute.")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source, output / "original-acquisition")
    wide = output / "Orthodont-wide.csv"
    with wide.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["study_code", "sex", *columns])
        writer.writeheader()
        writer.writerows(people.values())
    wide_rows = {subject: i for i, subject in enumerate(people, 1)}
    mapping = [{"wide_data_row": wide_rows[r["study_code"]], **r} for r in mapping]
    (output / "derivation.json").write_text(
        json.dumps(
            {
                "source_sha256": SOURCE_SHA256,
                "derived_sha256": sha(wide),
                "operation": "Exact string-preserving pivot by Subject and age; no aggregation, estimation, imputation, unit conversion or row exclusion.",
                "source_rows": 108,
                "subjects": 27,
                "ages": ages,
                "measurement_unit": "mm",
                "script_sha256": sha(Path(__file__)),
                "cells": mapping,
                "documentation": "https://stat.ethz.ch/R-manual/R-devel/library/nlme/html/Orthodont.html",
                "caution": "Source prose lists inconsistent female ID endpoints; actual data contain 16 male and 11 female subjects. Observed growth differences are not treatment effects or a replication of the published multivariate model.",
            },
            indent=2,
        )
    )
    base = {
        "family": "repeated",
        "subject": "study_code",
        "measurements": [
            {"column": column, "label": f"Age {age} years"}
            for column, age in zip(columns, ages, strict=True)
        ],
        "contrasts": [[column, columns[0]] for column in columns[1:]],
        "outcome_name": "Orthodontic distance",
        "outcome_unit": "mm",
        "outcome_definition": "Pituitary-to-pterygomaxillary fissure distance measured on skull radiographs.",
        "context": "Engineering validation using nlme 3.1-168 Orthodont: within-child growth from ages 8 to 14; not a treatment effect or published model replication.",
        "independent_subjects": True,
        "same_outcome": True,
        "confidence_level": 0.95,
        "case_strategy": "complete",
        "multiplicity": "holm",
        "cohort_filter": None,
    }
    for name, options in [
        (
            "mean",
            {
                "method": "paired_mean",
                "primary_effect": "mean_difference",
                "omnibus": False,
                "bootstrap": None,
            },
        ),
        (
            "signed",
            {
                "method": "signed_rank",
                "primary_effect": "rank_biserial",
                "omnibus": True,
                "bootstrap": {"resamples": 1999, "seed": 20261002},
            },
        ),
    ]:
        (output / f"{name}.json").write_text(json.dumps({**base, **options}, indent=2))
    print(
        json.dumps(
            {
                "output": str(output),
                "source_sha256": SOURCE_SHA256,
                "derived_sha256": sha(wide),
                "source_rows": len(rows),
                "subjects": len(people),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source_directory, args.output)
