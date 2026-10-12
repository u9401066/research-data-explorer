"""Typed, non-executable specifications for relational research preparation."""

from typing import Literal
import math

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Source(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    path: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(ge=0, le=25 * 1024 * 1024)
    sheet: str | None = None
    encoding: Literal["utf-8-sig", "utf-8", "big5", "cp950"] = "utf-8-sig"
    delimiter: Literal[",", "\t", ";"] = ","
    synthetic: bool = False


class Predicate(StrictModel):
    column: str = Field(min_length=1, max_length=160)
    op: Literal["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "missing", "present"]
    value: str | float | list[str] | None = None

    @model_validator(mode="after")
    def literal_comparison(self):
        if self.op in {"gt", "gte", "lt", "lte"}:
            try:
                valid = not isinstance(self.value, (list, type(None))) and math.isfinite(
                    float(self.value)
                )
            except (TypeError, ValueError):
                valid = False
            if not valid:
                raise ValueError(
                    "Numeric filters require a finite constant; date comparisons and index-relative expressions belong in window, not filters."
                )
        if self.op in {"in", "not_in"} and not isinstance(self.value, list):
            raise ValueError("in/not_in filters require an explicit list of literal values")
        return self


class CohortRule(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    reason: str = Field(min_length=1, max_length=1000)
    stage: Literal["before_links", "after_links"] = "before_links"
    keep: Predicate


class ExcludedRow(StrictModel):
    source_id: str
    record_index: int = Field(ge=0)
    row_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=1000)


class ColumnRule(StrictModel):
    value_type: Literal["text", "number"] = "text"
    missing_tokens: list[str] = Field(default_factory=lambda: [""])


class Unit(StrictModel):
    source_id: str
    kind: Literal["patient", "encounter", "event"]
    keys: list[str] = Field(min_length=1, max_length=8)
    subject_keys: list[str] = Field(min_length=1, max_length=8)
    index_column: str | None = None
    timezone: str = "UTC"
    key_normalization: Literal["exact", "trim", "nfc_trim"] = "exact"
    null_keys: Literal["block", "exclude"] = "block"
    duplicates: Literal["block", "drop_identical", "exclude_conflicts"] = "block"
    retain_columns: list[str] | None = None
    columns: dict[str, ColumnRule] = Field(default_factory=dict)

    @model_validator(mode="after")
    def column_identity(self):
        for keys in (self.keys, self.subject_keys, self.retain_columns or []):
            if len(keys) != len(set(keys)):
                raise ValueError("column selections cannot repeat a column")
        for key in set(self.keys + self.subject_keys):
            if key in self.columns and (
                self.columns[key].value_type != "text"
                or any(v for v in self.columns[key].missing_tokens)
            ):
                raise ValueError(
                    "identifier columns must retain their lexical text; exclude sentinel-ID records explicitly"
                )
        return self


class Coverage(StrictModel):
    mode: Literal["complete", "unknown", "by_column"] = "unknown"
    column: str | None = None
    exported_values: list[str] = Field(default_factory=lambda: ["1", "yes", "true"])
    not_exported_values: list[str] = Field(default_factory=lambda: ["0", "no", "false"])


class Window(StrictModel):
    event_column: str
    available_column: str | None = None
    availability: Literal["column", "event_time_confirmed"] = "column"
    start_days: float
    end_days: float
    bounds: Literal["both", "left", "right", "neither"] = "both"
    purpose: Literal["baseline", "followup"] = "baseline"
    followup_end_column: str | None = None

    @model_validator(mode="after")
    def boundaries(self):
        if self.start_days > self.end_days:
            raise ValueError("window start must be <= end")
        if self.purpose == "baseline" and self.end_days > 0:
            raise ValueError("baseline cannot include events after the index time")
        if self.availability == "column" and not self.available_column:
            raise ValueError(
                "declare when data became available, or explicitly confirm event-time availability"
            )
        return self


class UnitConversion(StrictModel):
    scale: float = 1
    offset: float = 0


class Feature(StrictModel):
    output: str = Field(min_length=1, max_length=160)
    column: str | None = None
    aggregate: Literal[
        "unique", "count", "exists", "sum", "mean", "min", "max", "first", "last", "days_to_first"
    ]
    value_type: Literal["text", "number", "datetime"] = "text"
    unit_column: str | None = None
    unit_conversions: dict[str, UnitConversion] = Field(default_factory=dict)
    output_unit: str | None = None
    missing_tokens: list[str] = Field(default_factory=lambda: [""])

    @model_validator(mode="after")
    def semantic_shape(self):
        if self.output.startswith("_rde_"):
            raise ValueError("_rde_ is reserved for preparation identity and statuses")
        if self.aggregate not in {"count", "exists", "days_to_first"} and not self.column:
            raise ValueError("feature requires an explicit value column")
        if self.aggregate in {"sum", "mean"} and self.value_type != "number":
            raise ValueError("sum and mean require numeric values")
        if self.unit_column and (not self.unit_conversions or not self.output_unit):
            raise ValueError("unit conversion requires a complete reviewed mapping and output unit")
        return self


class Relation(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    source_id: str
    left_keys: list[str] = Field(min_length=1, max_length=8)
    right_keys: list[str] = Field(min_length=1, max_length=8)
    kind: Literal["lookup", "events"]
    # lookup enforces the entire right key, events requires explicit aggregation.
    record_keys: list[str] = Field(default_factory=list, max_length=8)
    duplicates: Literal["block", "drop_identical", "exclude_conflicts"] = "block"
    key_normalization: Literal["exact", "trim", "nfc_trim"] = "exact"
    coverage: Coverage = Field(default_factory=Coverage)
    filters: list[Predicate] = Field(default_factory=list, max_length=30)
    window: Window | None = None
    at_index_basis: str | None = Field(default=None, min_length=10, max_length=2000)
    features: list[Feature] = Field(min_length=1, max_length=50)
    reuse_events: Literal["block", "allow"] = "block"
    exclude_statuses: list[
        Literal[
            "no_record",
            "not_exported",
            "outside_window",
            "not_available",
            "link_failed",
            "unknown_coverage",
            "filtered_out",
            "matched_partial",
        ]
    ] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def matching(self):
        if len(self.left_keys) != len(self.right_keys):
            raise ValueError("composite join keys must have the same number of components")
        if self.kind == "lookup" and any(f.aggregate != "unique" for f in self.features):
            raise ValueError("lookup features use unique; events require explicit aggregation")
        if (
            self.kind == "events"
            and any(f.aggregate in {"first", "last", "days_to_first"} for f in self.features)
            and not self.window
        ):
            raise ValueError("first/last/days_to_first requires an explicit event-time window")
        if self.coverage.mode == "by_column" and not self.coverage.column:
            raise ValueError("per-unit export coverage requires a root-table column")
        if set(self.coverage.exported_values) & set(self.coverage.not_exported_values):
            raise ValueError("exported and not-exported values overlap")
        return self


class Definitions(StrictModel):
    unit: str = Field(default="", max_length=3000)
    linkage: str = Field(default="", max_length=3000)
    time: str = Field(default="", max_length=3000)
    missingness: str = Field(default="", max_length=3000)


class Review(StrictModel):
    kind: Literal["data_manager", "synthetic_oracle"]
    denominator_confirmed: bool
    reviewed_unit_ids: list[str] = Field(min_length=1, max_length=100)
    notes: str = Field(min_length=1, max_length=5000)


class Specification(StrictModel):
    schema_version: Literal["rde-preparation-spec-v1"] = "rde-preparation-spec-v1"
    unit: Unit
    relations: list[Relation] = Field(default_factory=list, max_length=15)
    cohort: list[CohortRule] = Field(default_factory=list, max_length=50)
    excluded_rows: list[ExcludedRow] = Field(default_factory=list, max_length=2000)
    omitted_sources: dict[str, str] = Field(default_factory=dict)
    definitions: Definitions = Field(default_factory=Definitions)

    @model_validator(mode="after")
    def unique_names(self):
        for values in (
            [r.id for r in self.relations],
            [r.id for r in self.cohort],
            [f.output for r in self.relations for f in r.features],
        ):
            if len(values) != len(set(values)):
                raise ValueError("relation, rule and output names must be unique")
        return self
