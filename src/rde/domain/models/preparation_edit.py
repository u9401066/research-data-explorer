"""Typed local edits; scientific rule types stay in preparation.py."""

from typing import Annotated, Literal, Union

from pydantic import Field, TypeAdapter, model_validator

from .preparation import (
    CohortRule,
    Coverage,
    Definitions,
    ExcludedRow,
    Feature,
    Predicate,
    Relation,
    Source,
    Specification,
    StrictModel,
    Unit,
    Window,
)

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Uuid = Annotated[
    str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
]
Name = Annotated[str, Field(min_length=1, max_length=160)]


class CandidateReference(StrictModel):
    candidate_id: Uuid
    revision_id: Uuid
    revision: int = Field(ge=1, strict=True)
    receipt_sha256: Hash
    specification_sha256: Hash
    source_set_sha256: Hash


class UnitSet(StrictModel):
    op: Literal["unit_set"]
    unit: Unit


class DefinitionSet(StrictModel):
    op: Literal["definition_set"]
    field: Literal["unit", "linkage", "time", "missingness"]
    value: str = Field(max_length=5000)


class RelationAdd(StrictModel):
    op: Literal["relation_add"]
    relation: Relation


class RelationRemove(StrictModel):
    op: Literal["relation_remove"]
    relation_id: Name


class RelationChanges(StrictModel):
    left_keys: list[str] | None = None
    right_keys: list[str] | None = None
    kind: Literal["lookup", "events"] | None = None
    record_keys: list[str] | None = None
    duplicates: Literal["block", "drop_identical", "exclude_conflicts"] | None = None
    key_normalization: Literal["exact", "trim", "nfc_trim"] | None = None
    coverage: Coverage | None = None
    reuse_events: Literal["block", "allow"] | None = None
    at_index_basis: str | None = None
    exclude_statuses: list[str] | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError("relation_update needs explicit settings")
        return self


class RelationUpdate(StrictModel):
    op: Literal["relation_update"]
    relation_id: Name
    changes: RelationChanges


class FeatureSet(StrictModel):
    op: Literal["feature_set"]
    relation_id: Name
    feature: Feature


class FeatureRemove(StrictModel):
    op: Literal["feature_remove"]
    relation_id: Name
    feature_output: Name


class WindowSet(StrictModel):
    op: Literal["window_set"]
    relation_id: Name
    window: Window | None


class FiltersSet(StrictModel):
    op: Literal["filters_set"]
    relation_id: Name
    filters: list[Predicate] = Field(max_length=30)


class CohortSet(StrictModel):
    op: Literal["cohort_set"]
    rule: CohortRule


class CohortRemove(StrictModel):
    op: Literal["cohort_remove"]
    rule_id: Name


class CohortOrder(StrictModel):
    op: Literal["cohort_order"]
    rule_ids: list[Name] = Field(max_length=50)


class OmissionSet(StrictModel):
    op: Literal["omission_set"]
    source_id: Name
    reason: str = Field(min_length=1, max_length=5000)


class OmissionRemove(StrictModel):
    op: Literal["omission_remove"]
    source_id: Name


class ExclusionAdd(StrictModel):
    op: Literal["exclusion_add"]
    row: ExcludedRow


class ExclusionRemove(StrictModel):
    op: Literal["exclusion_remove"]
    source_id: Name
    record_index: int = Field(ge=0, strict=True)
    row_sha256: Hash


Operation = Annotated[
    Union[
        UnitSet,
        DefinitionSet,
        RelationAdd,
        RelationRemove,
        RelationUpdate,
        FeatureSet,
        FeatureRemove,
        WindowSet,
        FiltersSet,
        CohortSet,
        CohortRemove,
        CohortOrder,
        OmissionSet,
        OmissionRemove,
        ExclusionAdd,
        ExclusionRemove,
    ],
    Field(discriminator="op"),
]
operation_adapter = TypeAdapter(Operation)


class ComposeRequest(StrictModel):
    op: Literal["aggregation_compose"]
    candidate_id: Uuid
    revision_id: Uuid
    sources: list[Source] = Field(min_length=1, max_length=16)
    unit: Unit | None = None
    definitions: Definitions | None = None
    from_specification: Specification | None = None
    author: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def exactly_one_basis(self):
        if self.from_specification is not None:
            if "unit" in self.model_fields_set or "definitions" in self.model_fields_set:
                raise ValueError("from_specification cannot be mixed with unit/definitions")
        elif self.unit is None:
            raise ValueError("compose requires unit or from_specification")
        if not self.author.strip() or not self.reason.strip():
            raise ValueError("author and reason cannot be blank")
        if len({s.id for s in self.sources}) != len(self.sources):
            raise ValueError("source IDs must be unique")
        return self


class PatchRequest(StrictModel):
    op: Literal["aggregation_patch"]
    candidate_ref: CandidateReference
    revision_id: Uuid
    operations: list[Operation] = Field(min_length=1, max_length=32)
    author: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def attributed(self):
        if not self.author.strip() or not self.reason.strip():
            raise ValueError("author and reason cannot be blank")
        return self
