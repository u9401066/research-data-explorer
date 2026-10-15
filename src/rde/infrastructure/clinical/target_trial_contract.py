"""Finite baseline point-treatment protocol; source checks do not authorize a run.

The protocol is intentionally separate from WeightingSpec until all native
inspect/locked-run/reuse gates consume it. There is no tte=True shortcut.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Name = Annotated[str, Field(min_length=1, max_length=160)]
Explanation = Annotated[str, Field(min_length=10, max_length=3000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)


class PreparedBinding(Strict):
    preparation_id: Name
    preparation_project_id: Name
    bundle_sha256: Hash
    release_sha256: Hash
    plan_sha256: Hash
    approval_sha256: Hash
    review_sha256: Hash
    source_set_sha256: Hash
    specification_sha256: Hash
    files_sha256: Hash
    inventory_sha256: Hash
    dataset_sha256: Hash
    schema_sha256: Hash
    typed_rows_sha256: Hash
    trace_sha256: Hash
    validation_sha256: Hash
    exceptions_sha256: Hash


class TimedField(Strict):
    column: Name
    source_id: Name
    event_column: Name
    available_column: Name
    definition: Explanation


class Eligibility(Strict):
    definition: Explanation
    rule_ids: list[Name] = Field(min_length=1, max_length=50)
    fields: list[TimedField] = Field(min_length=1, max_length=50)
    missing_policy: Literal["only_prespecified_baseline_eligibility_rules"]


class TimeZero(Strict):
    index_column: Name
    timezone: Literal["UTC"]
    selection: Literal["one_prespecified_root_record_per_person"]
    subject_column: Literal["_rde_subject_id"]
    definition: Explanation


class Treatment(Strict):
    strategy: Literal["baseline_point_treatment"]
    field: TimedField
    levels: list[Name] = Field(min_length=2, max_length=2)
    definitions: list[Explanation] = Field(min_length=2, max_length=2)


class Assignment(Strict):
    hypothetical_trial: Literal["random_assignment_at_time_zero"]
    observational_mapping: Literal["recorded_treatment_at_time_zero"]
    selection_basis: Explanation
    confounder_selection_basis: Explanation


class FollowUp(Strict):
    mode: Literal["complete_fixed_horizon"]
    horizon_days: int = Field(gt=0, le=3650)
    coverage_start_column: Name
    coverage_end_column: Name
    export_status_column: Name
    complete_export_value: Name
    intercurrent_status_column: Name
    no_intercurrent_value: Name
    intercurrent_policy: Literal["reject_any_recorded_intercurrent_event"]
    definition: Explanation


class Outcome(Strict):
    kind: Literal["binary", "continuous"]
    column: Name
    relation_id: Name
    assessment_start_days: int = Field(ge=0, le=3650)
    assessment_end_days: int = Field(gt=0, le=3650)
    bounds: Literal["both", "right"]
    unit: Name
    definition: Explanation


class Estimand(Strict):
    kind: Literal["ATE", "ATT", "ATO"]
    contrast: Literal["baseline_level_1_minus_level_0"]
    target_population: Explanation
    interpretation: Literal["baseline_point_treatment_effect"]


class Analysis(Strict):
    weighting_spec_sha256: Hash
    population_policy: Literal["all_prepared_eligible_no_further_exclusion"]
    missing_policy: Literal["reject_any_missing_analysis_role"]
    consistency_basis: Explanation
    exchangeability_basis_and_limitations: Explanation
    positivity_basis_and_limitations: Explanation


class TargetTrialProtocol(Strict):
    schema_version: Literal["rde-baseline-target-trial-v1"]
    binding: PreparedBinding
    eligibility: Eligibility
    time_zero: TimeZero
    treatment: Treatment
    assignment: Assignment
    followup: FollowUp
    outcome: Outcome
    estimand: Estimand
    baseline: list[TimedField] = Field(min_length=1, max_length=12)
    analysis: Analysis

    @model_validator(mode="after")
    def finite_scope(self):
        for values in (
            self.eligibility.rule_ids,
            [f.column for f in self.eligibility.fields],
            [f.column for f in self.baseline],
            self.treatment.levels,
        ):
            if len(values) != len(set(values)):
                raise ValueError("TTE_DUPLICATE_ROLE: identities and role mappings cannot repeat")
        if (
            not self.outcome.assessment_start_days
            <= self.outcome.assessment_end_days
            <= self.followup.horizon_days
        ):
            raise ValueError("TTE_OUTCOME_WINDOW: assessment must be within the fixed horizon")
        if self.outcome.kind == "binary" and (
            self.outcome.assessment_start_days != 0
            or self.outcome.assessment_end_days != self.followup.horizon_days
            or self.outcome.bounds != "right"
        ):
            raise ValueError("TTE_BINARY_WINDOW: incident events require (time zero, horizon]")
        if self.outcome.column in {f.column for f in self.eligibility.fields + self.baseline}:
            raise ValueError(
                "TTE_FUTURE_ELIGIBILITY: outcome cannot define baseline eligibility or adjustment"
            )
        return self

    @classmethod
    def parse(cls, value):
        return cls.model_validate(value)

    def to_dict(self):
        return self.model_dump()
