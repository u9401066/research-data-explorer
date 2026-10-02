"""Explicit source mapping and decisions for binary trial-arm preparation."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def nonblank(value: str):
    if not value.strip():
        raise ValueError("Text must contain a non-whitespace character.")
    return value


Text = Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(nonblank)]
Label = Annotated[
    str,
    Field(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$"),
    AfterValidator(nonblank),
]
Column = Annotated[int, Field(ge=1, le=100)]
Row = Annotated[int, Field(ge=1, le=10000)]


class ColumnValue(StrictModel):
    kind: Literal["column"]
    column: Column


class ConstantValue(StrictModel):
    kind: Literal["constant"]
    value: Text


ValueSource = Annotated[ColumnValue | ConstantValue, Field(discriminator="kind")]


class ArmColumns(StrictModel):
    study: Column
    arm: Column
    treatment: Column
    events: Column
    total: Column
    author_imputed: Column | None

    @model_validator(mode="after")
    def distinct_counts(self):
        if self.events == self.total:
            raise ValueError("Events and denominator must use different source columns.")
        return self


class MissingCode(StrictModel):
    value: Annotated[str, Field(max_length=80)]
    meaning: Text


class ImputationCodes(StrictModel):
    reported: Annotated[list[str], Field(min_length=1, max_length=20)]
    imputed: Annotated[list[str], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def disjoint(self):
        codes = self.reported + self.imputed
        if len(set(codes)) != len(codes) or any(not c or len(c) > 80 for c in codes):
            raise ValueError("Imputation codes must be nonempty, unique and disjoint.")
        return self


class TreatmentDecision(StrictModel):
    raw: Label
    treatment: Label
    decision: Literal["include", "exclude", "unresolved"]
    reason: Text


class RowDecision(StrictModel):
    row: Row
    decision: Literal["include", "exclude", "unresolved"]
    reason: Text


class StudyMetadata(StrictModel):
    report_id: ValueSource
    source: ValueSource
    population: ValueSource
    effect_modifiers: ValueSource
    risk_of_bias: ValueSource
    bias_reason: ValueSource
    design: ValueSource


class BinaryArmSpec(StrictModel):
    schema_version: Literal["binary-arm-spec-v1"]
    sheet: Annotated[str, Field(min_length=1, max_length=31)] | None
    first_data_row: Row
    last_data_row: Row
    outside_data_reason: Text
    columns: ArmColumns
    metadata: StudyMetadata
    missing_codes: Annotated[list[MissingCode], Field(min_length=1, max_length=20)]
    imputation_codes: ImputationCodes | None
    treatments: Annotated[list[TreatmentDecision], Field(min_length=2, max_length=500)]
    row_decisions: Annotated[list[RowDecision], Field(max_length=5000)]
    measure: Literal["OR", "RR"]
    outcome: Annotated[str, Field(min_length=1, max_length=200), AfterValidator(nonblank)]
    timepoint: Annotated[str, Field(min_length=1, max_length=200), AfterValidator(nonblank)]
    reference: Label
    independent_parallel_arms: bool
    merge_policy: Literal["reject", "sum_disjoint_arms"]
    fractional_events: Literal["reject", "author_imputed"]
    zero_cells: Literal["reject", "add_half_all_arms_in_affected_study"]
    uninformative_studies: Literal["reject", "exclude"]
    insufficient_treatments: Literal["reject", "exclude"]
    method_justification: Text

    @model_validator(mode="after")
    def complete(self):
        from decimal import Decimal, InvalidOperation

        if self.independent_parallel_arms is not True:
            raise ValueError("Independent parallel arms must be explicitly confirmed.")
        if (
            any(t.treatment != t.treatment.strip() for t in self.treatments)
            or self.reference != self.reference.strip()
        ):
            raise ValueError("Canonical treatment labels must be trimmed explicitly.")

        if self.last_data_row < self.first_data_row:
            raise ValueError("The last data row must follow the first data row.")
        if self.last_data_row - self.first_data_row + 1 > 5000:
            raise ValueError("At most 5000 source arm rows can be prepared at once.")
        for name, values in (
            ("missing", [m.value for m in self.missing_codes]),
            ("treatment", [t.raw for t in self.treatments]),
            ("row", [r.row for r in self.row_decisions]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {name} mapping.")
        missing = {m.value for m in self.missing_codes}
        if "" not in missing:
            raise ValueError("An explicit meaning for blank cells is required.")
        for code in missing:
            try:
                number = Decimal(code)
            except InvalidOperation:
                continue
            if number.is_finite():
                raise ValueError("A numeric count, including zero, cannot be a missing code.")
        if any(not self.first_data_row <= r.row <= self.last_data_row for r in self.row_decisions):
            raise ValueError("A row decision is outside the selected source range.")
        if (self.columns.author_imputed is None) != (self.imputation_codes is None):
            raise ValueError(
                "The imputation column and its code mapping must be specified together."
            )
        if self.fractional_events == "author_imputed" and self.imputation_codes is None:
            raise ValueError("Fractional events require explicit author-imputation flags.")
        if self.imputation_codes and missing.intersection(
            self.imputation_codes.reported + self.imputation_codes.imputed
        ):
            raise ValueError("Imputation flags cannot simultaneously denote missing values.")
        if self.reference not in {t.treatment for t in self.treatments}:
            raise ValueError("Reference treatment is absent from the vocabulary.")
        return self


UUIDText = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Confirmations(StrictModel):
    source_mapping_and_missingness: bool
    eligibility_and_treatment_merging: bool
    endpoint_denominator_and_imputation: bool
    zero_cells_and_method: bool
    independence_and_bias: bool

    @model_validator(mode="after")
    def confirmed(self):
        if any(value is not True for value in self.model_dump().values()):
            raise ValueError("Every required assumption must be explicitly confirmed after review.")
        return self


class ApprovalReview(StrictModel):
    reviewer: Text
    note: Text
    confirmations: Confirmations


class ContractRequest(StrictModel):
    op: Literal["contract"]


class DraftRequest(StrictModel):
    op: Literal["draft"]
    preparation_id: UUIDText
    filename: Annotated[str, Field(min_length=1, max_length=200)]
    source_sha256: Hash
    specification: BinaryArmSpec


class ReadRequest(StrictModel):
    op: Literal["read"]
    preparation_id: UUIDText
    part: Literal["plan", "grid", "review", "result"]
    run_id: UUIDText | None = None
    text_offset: Annotated[int, Field(ge=0)] = 0
    text_limit: Annotated[int, Field(ge=1, le=64000)] = 16000
    expected_text_sha256: Hash | None = None

    @model_validator(mode="after")
    def pinned(self):
        if (self.part == "result") != (self.run_id is not None):
            raise ValueError("Only a result read requires a run ID.")
        if self.text_offset and self.expected_text_sha256 is None:
            raise ValueError("Continuation requires expected_text_sha256.")
        return self


class ApproveRequest(StrictModel):
    op: Literal["approve"]
    preparation_id: UUIDText
    expected_plan_sha256: Hash
    review: ApprovalReview


class ExecuteRequest(StrictModel):
    op: Literal["execute"]
    preparation_id: UUIDText
    expected_plan_sha256: Hash
    expected_approval_sha256: Hash
    run_id: UUIDText


ArmRequest = Annotated[
    ContractRequest | DraftRequest | ReadRequest | ApproveRequest | ExecuteRequest,
    Field(discriminator="op"),
]
