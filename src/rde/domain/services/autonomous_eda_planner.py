"""Autonomous EDA planner — greedy candidate analysis generation.

Builds a ranked Phase 4 plan blueprint from schema metadata and concept-alignment
roles. The planner is deterministic and transparent by design so the agent can
autonomously expand candidate analyses without bypassing governance.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from rde.domain.models.dataset import Dataset
from rde.domain.models.variable import Variable, VariableRole, VariableType


MIN_METHOD_ANALYSIS_FLOOR = 4
ACADEMIC_ANALYSIS_TARGET = 6
PRODUCTION_ANALYSIS_TARGET = 8


GROUP_KEYWORDS = (
    "group",
    "arm",
    "treat",
    "therapy",
    "cohort",
    "cluster",
    "exposure",
    "random",
    "allocation",
    "method",
    "technique",
    "approach",
    "device",
    "guided",
    "guidance",
    "ultrasound",
    "central",
    "line",
    "catheter",
    "arterial",
    "intervention",
    "組別",
    "方式",
    "處置",
    "介入",
    "超音波",
    "導管",
    "中線",
)
OUTCOME_KEYWORDS = (
    "outcome",
    "mortality",
    "death",
    "event",
    "status",
    "success",
    "failure",
    "fail",
    "response",
    "readmission",
    "complication",
    "adverse",
    "infection",
    "bleeding",
    "pain",
    "score",
    "rate",
    "time",
    "duration",
    "sec",
    "second",
    "minute",
    "min",
    "成功",
    "失敗",
    "併發",
    "感染",
    "出血",
    "疼痛",
    "時間",
    "耗時",
    "花費",
)
TIME_TO_EVENT_KEYWORDS = (
    "time",
    "duration",
    "survival",
    "followup",
    "follow_up",
    "sec",
    "min",
    "hour",
    "day",
)
ROC_KEYWORDS = ("score", "risk", "prob", "probability", "marker", "biomarker", "rate")
OPERATOR_KEYWORDS = ("operator", "surgeon", "provider", "physician", "doctor")
TRIAL_KEYWORDS = ("trial", "case", "order", "sequence", "attempt", "procedure")
REPEATED_PATTERNS = (
    re.compile(r"^(?P<base>.+?)_(?P<tp>t\d+)$", re.IGNORECASE),
    re.compile(r"^(?P<base>.+?)_(?P<tp>\d+(?:hr|h|min|m|day|d|wk|w|mo))$", re.IGNORECASE),
    re.compile(
        r"^(?P<base>.+?)_(?P<tp>baseline|pre|post|followup|follow_up|discharge)$",
        re.IGNORECASE,
    ),
)

MIN_DESCRIPTIVE_VISUALIZATIONS = 3
MIN_ANALYTICAL_VISUALIZATIONS = 6


@dataclass(frozen=True)
class VisualizationSuggestion:
    plot_type: str
    variables: tuple[str, ...]
    rationale: str
    group_variable: str | None = None

    def key(self) -> tuple[str, tuple[str, ...], str | None]:
        return (self.plot_type, self.variables, self.group_variable)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "plot_type": self.plot_type,
            "variables": list(self.variables),
            "rationale": self.rationale,
        }
        if self.group_variable:
            result["group_variable"] = self.group_variable
        return result

    def to_plan_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "type": "visualization",
            "variables": list(self.variables),
            "plot_type": self.plot_type,
            "rationale": self.rationale,
        }
        if self.group_variable:
            entry["group_variable"] = self.group_variable
        return entry


@dataclass(frozen=True)
class AnalysisCandidate:
    type: str
    variables: tuple[str, ...]
    rationale: str
    coverage_tags: tuple[str, ...]
    base_score: float
    analysis_type: str | None = None
    group_variable: str | None = None
    target_variable: str | None = None
    time_variable: str | None = None
    covariates: tuple[str, ...] = ()
    priority: str = "medium"
    visualizations: tuple[VisualizationSuggestion, ...] = ()

    def family(self) -> str:
        return self.analysis_type or self.type

    def label(self) -> str:
        return self.family()

    def key(self) -> tuple[str, str | None, str | None, str | None, str | None, tuple[str, ...]]:
        return (
            self.type,
            self.analysis_type,
            self.group_variable,
            self.target_variable,
            self.time_variable,
            self.variables,
        )

    def to_dict(self, score: float) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "variables": list(self.variables),
            "rationale": self.rationale,
            "coverage_tags": list(self.coverage_tags),
            "score": round(score, 2),
            "priority": self.priority,
            "visualizations": [item.to_dict() for item in self.visualizations],
        }
        if self.analysis_type:
            data["analysis_type"] = self.analysis_type
        if self.group_variable:
            data["group_variable"] = self.group_variable
        if self.target_variable:
            data["target_variable"] = self.target_variable
        if self.time_variable:
            data["time_variable"] = self.time_variable
        if self.covariates:
            data["covariates"] = list(self.covariates)
        return data

    def to_plan_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "type": self.type,
            "variables": list(self.variables),
            "rationale": self.rationale,
        }
        if self.analysis_type:
            entry["analysis_type"] = self.analysis_type
        if self.group_variable:
            entry["group_variable"] = self.group_variable
        if self.target_variable:
            entry["target_variable"] = self.target_variable
        if self.time_variable:
            entry["time_variable"] = self.time_variable
        if self.covariates:
            entry["covariates"] = list(self.covariates)
        return entry


@dataclass(frozen=True)
class RankedCandidate:
    candidate: AnalysisCandidate
    score: float

    def to_dict(self) -> dict[str, Any]:
        return self.candidate.to_dict(self.score)


@dataclass(frozen=True)
class ReviewCheck:
    name: str
    status: str
    detail: str
    required: bool = True
    satisfied_by: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "required": self.required,
            "satisfied_by": list(self.satisfied_by),
        }


@dataclass(frozen=True)
class RepairAction:
    action: str
    reason: str
    candidate_label: str
    replaced_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "action": self.action,
            "reason": self.reason,
            "candidate_label": self.candidate_label,
        }
        if self.replaced_label:
            data["replaced_label"] = self.replaced_label
        return data


@dataclass(frozen=True)
class ExecutionStep:
    order: int
    step_id: str
    stage: str
    tool_name: str
    analysis_label: str
    variables: tuple[str, ...]
    rationale: str
    depends_on: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "step_id": self.step_id,
            "stage": self.stage,
            "tool_name": self.tool_name,
            "analysis_label": self.analysis_label,
            "variables": list(self.variables),
            "rationale": self.rationale,
            "depends_on": list(self.depends_on),
        }


@dataclass(frozen=True)
class EnrichmentRound:
    round_index: int
    added_candidate_labels: tuple[str, ...]
    coverage_before: tuple[str, ...]
    coverage_after: tuple[str, ...]
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "added_candidate_labels": list(self.added_candidate_labels),
            "coverage_before": list(self.coverage_before),
            "coverage_after": list(self.coverage_after),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class PlanMethodologyReview:
    status: str
    recommended_analysis_floor: int
    academic_analysis_target: int
    production_analysis_target: int
    completeness_tier: str
    candidate_pool_size: int
    requested_analysis_budget: int
    soft_analysis_budget: int
    draft_analysis_count: int
    final_analysis_count: int
    coverage_before: tuple[str, ...]
    coverage_after: tuple[str, ...]
    draft_families: tuple[str, ...]
    final_families: tuple[str, ...]
    complexity_signals: dict[str, Any] = field(default_factory=dict)
    checks: tuple[ReviewCheck, ...] = ()
    repair_actions: tuple[RepairAction, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "recommended_analysis_floor": self.recommended_analysis_floor,
            "academic_analysis_target": self.academic_analysis_target,
            "production_analysis_target": self.production_analysis_target,
            "completeness_tier": self.completeness_tier,
            "candidate_pool_size": self.candidate_pool_size,
            "requested_analysis_budget": self.requested_analysis_budget,
            "soft_analysis_budget": self.soft_analysis_budget,
            "draft_analysis_count": self.draft_analysis_count,
            "final_analysis_count": self.final_analysis_count,
            "coverage_before": list(self.coverage_before),
            "coverage_after": list(self.coverage_after),
            "draft_families": list(self.draft_families),
            "final_families": list(self.final_families),
            "complexity_signals": self.complexity_signals,
            "checks": [item.to_dict() for item in self.checks],
            "repair_actions": [item.to_dict() for item in self.repair_actions],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class GreedyPlanProposal:
    dataset_id: str
    research_question: str
    strategy: str
    candidate_pool_size: int
    draft_selected: tuple[RankedCandidate, ...]
    selected: tuple[RankedCandidate, ...]
    plan_blueprint: tuple[dict[str, Any], ...]
    coverage_tags: tuple[str, ...]
    execution_schedule: tuple[ExecutionStep, ...]
    enrichment_rounds: tuple[EnrichmentRound, ...] = ()
    review: PlanMethodologyReview | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "research_question": self.research_question,
            "strategy": self.strategy,
            "candidate_pool_size": self.candidate_pool_size,
            "draft_selected": [item.to_dict() for item in self.draft_selected],
            "selected": [item.to_dict() for item in self.selected],
            "plan_blueprint": list(self.plan_blueprint),
            "coverage_tags": list(self.coverage_tags),
            "execution_schedule": [item.to_dict() for item in self.execution_schedule],
            "enrichment_rounds": [item.to_dict() for item in self.enrichment_rounds],
            "review": self.review.to_dict() if self.review else None,
            "warnings": list(self.warnings),
        }


class AutonomousEDAPlanner:
    """Generate a greedy pre-lock analysis plan blueprint."""

    def propose(
        self,
        dataset: Dataset,
        research_question: str = "",
        *,
        max_analyses: int = 8,
        enrich_rounds: int = 1,
        include_advanced: bool = True,
        include_visualizations: bool = True,
    ) -> GreedyPlanProposal:
        analysis_vars = [
            variable
            for variable in dataset.variables
            if variable.is_analyzable() and not variable.is_pii_suspect
        ]
        all_non_pii = [variable for variable in dataset.variables if not variable.is_pii_suspect]
        warnings: list[str] = []

        if not analysis_vars:
            warnings.append("No analyzable non-PII variables are available for autonomous EDA.")
            return GreedyPlanProposal(
                dataset_id=dataset.id,
                research_question=research_question,
                strategy="greedy_coverage_under_budget",
                candidate_pool_size=0,
                draft_selected=(),
                selected=(),
                plan_blueprint=(),
                coverage_tags=(),
                execution_schedule=(),
                enrichment_rounds=(),
                review=None,
                warnings=tuple(warnings),
            )

        question_terms = self._question_terms(research_question)
        outcomes = self._pick_outcomes(analysis_vars, question_terms=question_terms)
        groups = self._pick_groups(analysis_vars, outcomes=outcomes, question_terms=question_terms)
        continuous = [
            variable
            for variable in analysis_vars
            if variable.variable_type in {VariableType.CONTINUOUS, VariableType.BIOMARKER}
        ]
        categorical = [
            variable
            for variable in analysis_vars
            if variable.variable_type
            in {VariableType.CATEGORICAL, VariableType.BINARY, VariableType.ORDINAL}
        ]
        predictors = self._pick_predictors(
            analysis_vars,
            outcomes,
            groups,
            question_terms=question_terms,
        )
        repeated_cluster = self._detect_repeated_measure_cluster(continuous)
        cusum_candidate = self._detect_learning_curve_candidate(all_non_pii, outcomes)
        survival_candidate = self._detect_time_to_event_candidate(
            all_non_pii,
            outcomes,
            groups,
            predictors,
            question_terms=question_terms,
        )
        model_family = self._recommend_model_family(outcomes, predictors, include_advanced)

        if not any(variable.role == VariableRole.OUTCOME for variable in analysis_vars):
            warnings.append(
                "No explicit outcome role found; outcome-sensitive candidates use name/type heuristics."
            )
        if not any(variable.role == VariableRole.GROUP for variable in analysis_vars):
            warnings.append(
                "No explicit group role found; comparison/Table 1 candidates use binary/categorical heuristics."
            )

        candidate_pool = self._build_candidate_pool(
            analysis_vars=analysis_vars,
            all_non_pii=all_non_pii,
            outcomes=outcomes,
            groups=groups,
            predictors=predictors,
            continuous=continuous,
            categorical=categorical,
            include_advanced=include_advanced,
            model_family=model_family,
            repeated_cluster=repeated_cluster,
            cusum_candidate=cusum_candidate if include_advanced else None,
            survival_candidate=survival_candidate if include_advanced else None,
        )
        variable_missing = {variable.name: variable.missing_rate for variable in all_non_pii}
        draft_selected = tuple(
            self._greedy_select(
                candidate_pool,
                max_analyses=max_analyses,
                variable_missing=variable_missing,
            )
        )
        selected, review = self._review_and_repair(
            draft_selected=draft_selected,
            candidate_pool=candidate_pool,
            max_analyses=max_analyses,
            variable_missing=variable_missing,
            groups=groups,
            continuous=continuous,
            model_family=model_family,
            repeated_cluster=repeated_cluster,
            has_cusum=include_advanced and cusum_candidate is not None,
            has_survival=include_advanced and survival_candidate is not None,
        )
        if review.warnings:
            warnings.extend(review.warnings)
        selected, enrichment_history, enrich_warnings = self._enrich_selection(
            selected=selected,
            candidate_pool=candidate_pool,
            variable_missing=variable_missing,
            enrich_rounds=enrich_rounds,
        )
        warnings.extend(enrich_warnings)

        coverage_tags = sorted(
            {tag for ranked in selected for tag in ranked.candidate.coverage_tags}
        )

        blueprint: list[dict[str, Any]] = []
        seen_viz: set[tuple[str, tuple[str, ...], str | None]] = set()
        for ranked in selected:
            blueprint.append(ranked.candidate.to_plan_entry())
            if not include_visualizations:
                continue
            for viz in ranked.candidate.visualizations:
                if viz.key() in seen_viz:
                    continue
                seen_viz.add(viz.key())
                blueprint.append(viz.to_plan_entry())

        if include_visualizations and groups:
            blueprint = self._ensure_publication_visualization_floor(
                blueprint,
                candidate_pool=candidate_pool,
                seen_viz=seen_viz,
            )

        execution_schedule = self.build_execution_schedule(blueprint)

        return GreedyPlanProposal(
            dataset_id=dataset.id,
            research_question=research_question,
            strategy="greedy_coverage_under_budget",
            candidate_pool_size=len(candidate_pool),
            draft_selected=draft_selected,
            selected=tuple(selected),
            plan_blueprint=tuple(blueprint),
            coverage_tags=tuple(coverage_tags),
            execution_schedule=execution_schedule,
            enrichment_rounds=tuple(enrichment_history),
            review=review,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def review_registered_plan(
        self,
        dataset: Dataset,
        analyses: list[dict[str, Any]],
        *,
        include_advanced: bool = True,
        max_analyses: int | None = None,
    ) -> PlanMethodologyReview:
        analysis_vars = [
            variable
            for variable in dataset.variables
            if variable.is_analyzable() and not variable.is_pii_suspect
        ]
        all_non_pii = [variable for variable in dataset.variables if not variable.is_pii_suspect]
        outcomes = self._pick_outcomes(analysis_vars, question_terms=())
        groups = self._pick_groups(analysis_vars, outcomes=outcomes, question_terms=())
        continuous = [
            variable
            for variable in analysis_vars
            if variable.variable_type in {VariableType.CONTINUOUS, VariableType.BIOMARKER}
        ]
        predictors = self._pick_predictors(analysis_vars, outcomes, groups, question_terms=())
        repeated_cluster = self._detect_repeated_measure_cluster(continuous)
        has_cusum = (
            include_advanced
            and self._detect_learning_curve_candidate(all_non_pii, outcomes) is not None
        )
        model_family = self._recommend_model_family(outcomes, predictors, include_advanced)
        candidate_pool = self._build_candidate_pool(
            analysis_vars=analysis_vars,
            all_non_pii=all_non_pii,
            outcomes=outcomes,
            groups=groups,
            predictors=predictors,
            continuous=continuous,
            categorical=[
                variable
                for variable in analysis_vars
                if variable.variable_type
                in {VariableType.CATEGORICAL, VariableType.BINARY, VariableType.ORDINAL}
            ],
            include_advanced=include_advanced,
            model_family=model_family,
            repeated_cluster=repeated_cluster,
            cusum_candidate=self._detect_learning_curve_candidate(all_non_pii, outcomes)
            if include_advanced
            else None,
            survival_candidate=None,
        )
        selected_families = tuple(
            family
            for entry in analyses
            for family in [self._entry_family(entry)]
            if family is not None
        )
        required_checks = self._build_methodology_requirements(
            has_groups=bool(groups),
            has_association=len(continuous) >= 2,
            model_family=model_family,
            has_repeated=repeated_cluster is not None,
            has_cusum=has_cusum,
            has_survival=False,
        )
        recommended_floor = self._recommended_analysis_floor(
            candidate_pool_size=len(candidate_pool),
            has_groups=bool(groups),
            has_association=len(continuous) >= 2,
            model_family=model_family,
            has_repeated=repeated_cluster is not None,
            has_cusum=has_cusum,
            has_survival=False,
        )
        academic_target = self._target_analysis_floor(
            recommended_floor=recommended_floor,
            candidate_pool_size=len(candidate_pool),
            target="academic",
        )
        production_target = self._target_analysis_floor(
            recommended_floor=recommended_floor,
            candidate_pool_size=len(candidate_pool),
            target="production",
        )
        checks = self._materialize_review_checks(
            draft_families=selected_families,
            final_families=selected_families,
            requirements=required_checks,
        )
        checks.extend(
            self._materialize_visualization_bundle_checks(
                *self._count_visualization_entries(analyses),
                has_groups=bool(groups),
            )
        )
        missing_required_count = sum(1 for check in checks if check.status == "missing")
        requested_budget = len(selected_families)
        soft_budget = self._soft_analysis_budget(
            requested_max_analyses=requested_budget,
            recommended_floor=recommended_floor,
            candidate_pool_size=len(candidate_pool),
            missing_required_count=missing_required_count,
        )
        warnings: list[str] = []
        if len(selected_families) < recommended_floor:
            warnings.append(
                f"Submitted plan has {len(selected_families)} analyses, below the methodology floor {recommended_floor}."
            )
        elif len(selected_families) < academic_target:
            warnings.append(
                f"Submitted plan clears the minimum floor but is below the academic-ready target {academic_target}."
            )
        elif len(selected_families) < production_target:
            warnings.append(
                f"Submitted plan is academically complete but below the production-ready target {production_target}."
            )
        if soft_budget > requested_budget:
            warnings.append(
                f"A reviewed greedy expansion would likely grow this plan from {requested_budget} to about {soft_budget} analyses to preserve additional EDA branches."
            )
        if max_analyses is not None and max_analyses < recommended_floor:
            warnings.append(
                f"Configured max_analyses={max_analyses} is below the methodology floor {recommended_floor}."
            )

        missing_required = any(check.status == "missing" for check in checks)
        completeness_tier = self._plan_completeness_tier(
            candidate_pool_size=len(candidate_pool),
            final_analysis_count=len(selected_families),
            recommended_floor=recommended_floor,
            academic_target=academic_target,
            production_target=production_target,
            has_missing_checks=missing_required,
        )
        status = "pass"
        if missing_required or len(selected_families) < recommended_floor:
            status = "needs_override"

        return PlanMethodologyReview(
            status=status,
            recommended_analysis_floor=recommended_floor,
            academic_analysis_target=academic_target,
            production_analysis_target=production_target,
            completeness_tier=completeness_tier,
            candidate_pool_size=len(candidate_pool),
            requested_analysis_budget=requested_budget,
            soft_analysis_budget=soft_budget,
            draft_analysis_count=len(selected_families),
            final_analysis_count=len(selected_families),
            coverage_before=tuple(
                self._coverage_tags_for_families(candidate_pool, selected_families)
            ),
            coverage_after=tuple(
                self._coverage_tags_for_families(candidate_pool, selected_families)
            ),
            draft_families=selected_families,
            final_families=selected_families,
            complexity_signals=self._complexity_signals(
                has_groups=bool(groups),
                n_continuous=len(continuous),
                model_family=model_family,
                has_repeated=repeated_cluster is not None,
                has_cusum=has_cusum,
            ),
            checks=tuple(checks),
            repair_actions=(),
            warnings=tuple(warnings),
        )

    def build_execution_schedule(
        self,
        analyses: list[dict[str, Any]],
    ) -> tuple[ExecutionStep, ...]:
        plan_entries = [entry for entry in analyses if isinstance(entry, dict)]
        analysis_entries = [
            entry
            for entry in plan_entries
            if self._entry_family(entry) not in {None, "visualization"}
        ]
        has_visualizations = any(
            self._entry_family(entry) == "visualization" for entry in plan_entries
        )

        if not analysis_entries:
            return ()

        ordered_entries = sorted(
            enumerate(analysis_entries),
            key=lambda pair: (
                self._execution_stage_metadata(self._entry_family(pair[1]) or "unknown")[0],
                pair[0],
            ),
        )

        steps: list[ExecutionStep] = [
            ExecutionStep(
                order=1,
                step_id="apply_cleaning",
                stage="prepare_dataset",
                tool_name="apply_cleaning",
                analysis_label="apply_cleaning",
                variables=(),
                rationale=(
                    "Apply the registered cleaning and missing-data strategy before branching into inferential analyses."
                ),
            )
        ]
        completed_by_family: dict[str, list[str]] = {}
        family_counts: dict[str, int] = {}

        for _, entry in ordered_entries:
            family = self._entry_family(entry) or "unknown_analysis"
            _, tool_name, stage = self._execution_stage_metadata(family)
            family_counts[family] = family_counts.get(family, 0) + 1
            step_id = family if family_counts[family] == 1 else f"{family}_{family_counts[family]}"
            dependencies = ("apply_cleaning",) + self._dependencies_for_family(
                family,
                completed_by_family,
            )
            steps.append(
                ExecutionStep(
                    order=len(steps) + 1,
                    step_id=step_id,
                    stage=stage,
                    tool_name=tool_name,
                    analysis_label=family,
                    variables=tuple(str(variable) for variable in entry.get("variables", [])),
                    rationale=str(
                        entry.get("rationale") or self._default_schedule_rationale(family)
                    ),
                    depends_on=tuple(dict.fromkeys(dep for dep in dependencies if dep)),
                )
            )
            completed_by_family.setdefault(family, []).append(step_id)

        if has_visualizations:
            steps.append(
                ExecutionStep(
                    order=len(steps) + 1,
                    step_id="visualization_bundle",
                    stage="visualization",
                    tool_name="create_visualization",
                    analysis_label="visualization_bundle",
                    variables=(),
                    rationale=(
                        "Render the reviewed visualization bundle after the core analytical branches have completed."
                    ),
                    depends_on=tuple(
                        step.step_id for step in steps if step.step_id != "apply_cleaning"
                    ),
                )
            )

        return tuple(steps)

    def build_statsmodels_analysis_script(
        self,
        dataset: Dataset,
        analyses: list[dict[str, Any]],
        execution_schedule: tuple[ExecutionStep, ...] | list[ExecutionStep],
        *,
        research_question: str = "",
    ) -> str:
        variable_types = {variable.name: variable.variable_type for variable in dataset.variables}
        schedule_payload = [
            step.to_dict() if isinstance(step, ExecutionStep) else step
            for step in execution_schedule
        ]
        lines = [
            '"""Statsmodels-centered baseline analysis script generated by AutonomousEDAPlanner.',
            "",
            "This script is intentionally explicit and auditable:",
            "- pandas handles data IO and reshaping",
            "- statsmodels is the primary modeling boundary",
            "- seaborn/matplotlib follow the reviewed plotting plan",
            '"""',
            "",
            "from __future__ import annotations",
            "",
            "from pathlib import Path",
            "import json",
            "",
            "import matplotlib.pyplot as plt",
            "import numpy as np",
            "import pandas as pd",
            "import seaborn as sns",
            "import statsmodels.api as sm",
            "import statsmodels.formula.api as smf",
            "from statsmodels.stats.multitest import multipletests",
            "",
            "DATA_PATH = Path('path/to/dataset.csv')",
            "OUTPUT_DIR = Path('artifacts/statsmodels_base_analysis')",
            "FIGURES_DIR = OUTPUT_DIR / 'figures'",
            "OUTPUT_DIR.mkdir(parents=True, exist_ok=True)",
            "FIGURES_DIR.mkdir(parents=True, exist_ok=True)",
            "sns.set_theme(style='whitegrid')",
            "",
            f"RESEARCH_QUESTION = {research_question!r}",
            f"EXECUTION_SCHEDULE = {json.dumps(schedule_payload, indent=2, ensure_ascii=False)}",
            "",
            "def save_json(name: str, payload: object) -> None:",
            "    (OUTPUT_DIR / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding='utf-8')",
            "",
            "def finalize_figure(name: str) -> None:",
            "    plt.tight_layout()",
            "    plt.savefig(FIGURES_DIR / name, dpi=160, bbox_inches='tight')",
            "    plt.close()",
            "",
            "def ensure_binary(series: pd.Series) -> pd.Series:",
            "    numeric = pd.to_numeric(series, errors='coerce')",
            "    if numeric.notna().all() and set(numeric.dropna().unique()).issubset({0, 1}):",
            "        return numeric.astype(int)",
            "    encoded = pd.Categorical(series).codes",
            "    return pd.Series(encoded, index=series.index, name=series.name).astype(int)",
            "",
            "def odds_ratio_table(result: object) -> list[dict[str, object]]:",
            "    params = result.params",
            "    conf = result.conf_int()",
            "    return [",
            "        {",
            "            'term': str(term),",
            "            'coef': float(params.loc[term]),",
            "            'odds_ratio': float(np.exp(params.loc[term])),",
            "            'ci_low': float(np.exp(conf.loc[term, 0])),",
            "            'ci_high': float(np.exp(conf.loc[term, 1])),",
            "            'p_value': float(result.pvalues.loc[term]),",
            "        }",
            "        for term in params.index",
            "    ]",
            "",
            "df = pd.read_csv(DATA_PATH)",
            "analysis_results: dict[str, object] = {}",
        ]

        analysis_entries = [
            entry
            for entry in analyses
            if isinstance(entry, dict) and self._entry_family(entry) not in {None, "visualization"}
        ]
        visualization_entries = [
            entry
            for entry in analyses
            if isinstance(entry, dict) and self._entry_family(entry) == "visualization"
        ]

        for index, entry in enumerate(analysis_entries, 1):
            lines.extend(
                self._statsmodels_script_block(
                    entry=entry,
                    index=index,
                    variable_types=variable_types,
                )
            )

        if visualization_entries:
            lines.append("\n# Visualization bundle\n")
            for index, entry in enumerate(visualization_entries, 1):
                plot_type = str(entry.get("plot_type") or "plot")
                variables = [str(value) for value in entry.get("variables", [])]
                group_variable = str(entry.get("group_variable") or "")
                if not variables:
                    continue
                if plot_type == "heatmap":
                    lines.extend(
                        [
                            f"corr_plot_{index} = df[{variables!r}].dropna().corr()",
                            "plt.figure(figsize=(8, 6))",
                            f"sns.heatmap(corr_plot_{index}, annot=True, cmap='coolwarm', fmt='.2f')",
                            f"finalize_figure('visualization_{index}_{plot_type}.png')",
                        ]
                    )
                elif plot_type == "boxplot" and group_variable:
                    lines.extend(
                        [
                            "plt.figure(figsize=(8, 5))",
                            f"sns.boxplot(data=df.dropna(subset={[variables[0], group_variable]!r}), x={group_variable!r}, y={variables[0]!r})",
                            f"finalize_figure('visualization_{index}_{plot_type}.png')",
                        ]
                    )
                elif plot_type == "histogram":
                    lines.extend(
                        [
                            "plt.figure(figsize=(8, 5))",
                            f"sns.histplot(data=df, x={variables[0]!r}, kde=True)",
                            f"finalize_figure('visualization_{index}_{plot_type}.png')",
                        ]
                    )
                elif plot_type == "line" and len(variables) >= 2:
                    lines.extend(
                        [
                            "plt.figure(figsize=(8, 5))",
                            f"sns.lineplot(data=df.dropna(subset={variables!r}), x={variables[0]!r}, y={variables[1]!r}"
                            + (f", hue={group_variable!r})" if group_variable else ")"),
                            f"finalize_figure('visualization_{index}_{plot_type}.png')",
                        ]
                    )

        lines.extend(
            [
                "",
                "save_json('analysis_results.json', analysis_results)",
                "print(f'Completed statsmodels-centered baseline analysis for {DATA_PATH}')",
            ]
        )
        return "\n".join(lines) + "\n"

    def _build_candidate_pool(
        self,
        *,
        analysis_vars: list[Variable],
        all_non_pii: list[Variable],
        outcomes: list[Variable],
        groups: list[Variable],
        predictors: list[Variable],
        continuous: list[Variable],
        categorical: list[Variable],
        include_advanced: bool,
        model_family: str | None,
        repeated_cluster: list[str] | None,
        cusum_candidate: AnalysisCandidate | None,
        survival_candidate: AnalysisCandidate | None,
    ) -> list[AnalysisCandidate]:
        candidates: list[AnalysisCandidate] = []

        overview_vars = self._limit_variables(
            self._unique_variables(outcomes + groups + predictors + continuous + categorical),
            limit=6,
        )
        if overview_vars:
            visualizations = tuple(self._default_visualizations_for_variables(overview_vars[:3]))
            candidates.append(
                AnalysisCandidate(
                    type="analyze_variable",
                    variables=tuple(variable.name for variable in overview_vars),
                    rationale=(
                        "Greedy baseline pass: profile the highest-value variables first so later "
                        "comparisons and models inherit distribution, missingness, and scale context."
                    ),
                    coverage_tags=("overview", "distribution", "quality"),
                    base_score=9.4,
                    priority="high",
                    visualizations=visualizations,
                )
            )

        if groups:
            group_variable = groups[0]
            grouped_targets = [
                variable
                for variable in self._unique_variables(outcomes + predictors + categorical + continuous)
                if variable.name != group_variable.name
            ]
            table_one_vars = self._limit_variables(
                grouped_targets,
                limit=8,
            )
            if table_one_vars:
                candidates.append(
                    AnalysisCandidate(
                        type="generate_table_one",
                        variables=tuple(variable.name for variable in table_one_vars),
                        group_variable=group_variable.name,
                        rationale=(
                            "A baseline table creates a compact cohort snapshot before the planner spends "
                            "budget on pairwise comparisons."
                        ),
                        coverage_tags=("overview", "comparison", "cohort_balance"),
                        base_score=8.9,
                        priority="high",
                        visualizations=(
                            VisualizationSuggestion(
                                plot_type="bar",
                                variables=(group_variable.name,),
                                rationale="Show the group split before comparing downstream variables.",
                            ),
                        ),
                    )
                )

            comparison_targets = self._limit_variables(
                grouped_targets,
                limit=6,
            )
            if comparison_targets:
                comparison_viz = self._comparison_visualizations(
                    group_variable=group_variable.name,
                    variables=comparison_targets,
                )
                candidates.append(
                    AnalysisCandidate(
                        type="compare_groups",
                        variables=tuple(variable.name for variable in comparison_targets),
                        group_variable=group_variable.name,
                        rationale=(
                            "A greedy EDA pass should spend early budget on the main group split to surface "
                            "effect sizes and distribution shifts quickly."
                        ),
                        coverage_tags=("comparison", "effect_size", "hypothesis_screen"),
                        base_score=8.7,
                        priority="high",
                        visualizations=tuple(comparison_viz),
                    )
                )

        if len(continuous) >= 2:
            corr_vars = self._limit_variables(continuous, limit=6)
            corr_names = tuple(variable.name for variable in corr_vars)
            candidates.append(
                AnalysisCandidate(
                    type="correlation_matrix",
                    variables=corr_names,
                    rationale=(
                        "Greedy search should reserve one slot for pairwise structure discovery so collinearity "
                        "and redundant signals are visible before regression choices."
                    ),
                    coverage_tags=("association", "collinearity", "screening"),
                    base_score=7.8,
                    priority="medium",
                    visualizations=(
                        VisualizationSuggestion(
                            plot_type="heatmap",
                            variables=corr_names,
                            rationale="Visualize the correlation structure of the highest-value numeric variables.",
                        ),
                    ),
                )
            )

        if repeated_cluster:
            candidates.append(
                AnalysisCandidate(
                    type="run_repeated_measures",
                    variables=tuple(repeated_cluster),
                    rationale=(
                        "Detected a repeated-measure naming cluster; reserving a dedicated repeated-measures "
                        "slot avoids flattening longitudinal structure into independent comparisons."
                    ),
                    coverage_tags=("longitudinal", "within_subject", "trend"),
                    base_score=8.1,
                    priority="high",
                    visualizations=(
                        VisualizationSuggestion(
                            plot_type="paired",
                            variables=tuple(repeated_cluster),
                            rationale="Inspect within-subject trajectories across detected timepoints.",
                        ),
                    ),
                )
            )

        if include_advanced and outcomes and model_family:
            primary_outcome = outcomes[0]
            covariates = tuple(
                variable.name for variable in self._limit_variables(predictors, limit=4)
            )
            if model_family == "logistic_regression" and len(covariates) >= 2:
                model_vars = (primary_outcome.name, *covariates)
                candidates.append(
                    AnalysisCandidate(
                        type="run_advanced_analysis",
                        analysis_type="logistic_regression",
                        variables=model_vars,
                        target_variable=primary_outcome.name,
                        covariates=covariates,
                        rationale=(
                            "Binary outcome with multiple predictors detected; a logistic model gives the autonomous "
                            "workflow a compact multivariable summary beyond pairwise screens."
                        ),
                        coverage_tags=("modeling", "multivariable", "risk_estimation"),
                        base_score=7.7,
                        priority="medium",
                    )
                )

                roc_predictors = self._pick_roc_predictors(analysis_vars, covariates)
                if roc_predictors:
                    roc_vars = (primary_outcome.name, *roc_predictors)
                    candidates.append(
                        AnalysisCandidate(
                            type="run_advanced_analysis",
                            analysis_type="roc_auc",
                            variables=roc_vars,
                            target_variable=primary_outcome.name,
                            covariates=tuple(roc_predictors),
                            rationale=(
                                "A binary outcome plus score-like predictors suggests a discrimination check via ROC/AUC."
                            ),
                            coverage_tags=("modeling", "discrimination", "thresholding"),
                            base_score=7.2,
                            priority="medium",
                        )
                    )

            if model_family == "multiple_regression" and len(covariates) >= 2:
                model_vars = (primary_outcome.name, *covariates)
                candidates.append(
                    AnalysisCandidate(
                        type="run_advanced_analysis",
                        analysis_type="multiple_regression",
                        variables=model_vars,
                        target_variable=primary_outcome.name,
                        covariates=covariates,
                        rationale=(
                            "Continuous outcome with multiple predictors detected; multiple regression gives a compact "
                            "multivariable signal after the greedy screening pass."
                        ),
                        coverage_tags=("modeling", "multivariable", "adjustment"),
                        base_score=7.5,
                        priority="medium",
                    )
                )

        if include_advanced and cusum_candidate is not None:
            candidates.append(cusum_candidate)
        if include_advanced and survival_candidate is not None:
            candidates.append(survival_candidate)

        unique: dict[
            tuple[str, str | None, str | None, str | None, str | None, tuple[str, ...]],
            AnalysisCandidate,
        ] = {}
        for candidate in candidates:
            unique[candidate.key()] = candidate
        return list(unique.values())

    def _greedy_select(
        self,
        candidates: list[AnalysisCandidate],
        *,
        max_analyses: int,
        variable_missing: dict[str, float],
    ) -> list[RankedCandidate]:
        remaining = list(candidates)
        coverage_seen: set[str] = set()
        used_variables: set[str] = set()
        used_families: set[str] = set()
        selected: list[RankedCandidate] = []

        while remaining and len(selected) < max_analyses:
            best: AnalysisCandidate | None = None
            best_score = float("-inf")

            for candidate in remaining:
                score = self._score_candidate(
                    candidate,
                    coverage_seen=coverage_seen,
                    used_variables=used_variables,
                    used_families=used_families,
                    variable_missing=variable_missing,
                )
                if score > best_score:
                    best = candidate
                    best_score = score

            if best is None or best_score <= 0:
                break

            selected.append(RankedCandidate(candidate=best, score=best_score))
            coverage_seen.update(best.coverage_tags)
            used_variables.update(best.variables)
            used_families.add(best.family())
            remaining = [candidate for candidate in remaining if candidate.key() != best.key()]

        return selected

    def _score_candidate(
        self,
        candidate: AnalysisCandidate,
        *,
        coverage_seen: set[str],
        used_variables: set[str],
        used_families: set[str],
        variable_missing: dict[str, float],
    ) -> float:
        candidate_vars = set(candidate.variables)
        overlap = len(candidate_vars & used_variables)
        new_coverage = len(set(candidate.coverage_tags) - coverage_seen)
        family_bonus = 0.8 if candidate.family() not in used_families else 0.0
        missing_penalty = self._average_missing_penalty(candidate.variables, variable_missing)
        return (
            candidate.base_score
            + (1.1 * new_coverage)
            + family_bonus
            - (0.35 * overlap)
            - missing_penalty
        )

    def _review_and_repair(
        self,
        *,
        draft_selected: tuple[RankedCandidate, ...],
        candidate_pool: list[AnalysisCandidate],
        max_analyses: int,
        variable_missing: dict[str, float],
        groups: list[Variable],
        continuous: list[Variable],
        model_family: str | None,
        repeated_cluster: list[str] | None,
        has_cusum: bool,
        has_survival: bool = False,
    ) -> tuple[list[RankedCandidate], PlanMethodologyReview]:
        selected = list(draft_selected)
        required_checks = self._build_methodology_requirements(
            has_groups=bool(groups),
            has_association=len(continuous) >= 2,
            model_family=model_family,
            has_repeated=repeated_cluster is not None,
            has_cusum=has_cusum,
            has_survival=has_survival,
        )
        recommended_floor = self._recommended_analysis_floor(
            candidate_pool_size=len(candidate_pool),
            has_groups=bool(groups),
            has_association=len(continuous) >= 2,
            model_family=model_family,
            has_repeated=repeated_cluster is not None,
            has_cusum=has_cusum,
            has_survival=has_survival,
        )
        academic_target = self._target_analysis_floor(
            recommended_floor=recommended_floor,
            candidate_pool_size=len(candidate_pool),
            target="academic",
        )
        production_target = self._target_analysis_floor(
            recommended_floor=recommended_floor,
            candidate_pool_size=len(candidate_pool),
            target="production",
        )
        warnings: list[str] = []
        if max_analyses < recommended_floor:
            warnings.append(
                f"max_analyses={max_analyses} is below the methodology floor {recommended_floor}; some required families may remain unsatisfied."
            )

        protected_families = {family for _, families, _ in required_checks for family in families}
        repair_actions: list[RepairAction] = []
        draft_families = tuple(item.candidate.family() for item in draft_selected)
        missing_requirements = [
            (requirement_name, families, detail)
            for requirement_name, families, detail in required_checks
            if not self._has_family(selected, families)
        ]
        soft_budget = self._soft_analysis_budget(
            requested_max_analyses=max_analyses,
            recommended_floor=recommended_floor,
            candidate_pool_size=len(candidate_pool),
            missing_required_count=len(missing_requirements),
        )
        if soft_budget > max_analyses:
            warnings.append(
                f"Methodology review expanded the analysis budget from {max_analyses} to {soft_budget} to keep emergent EDA branches instead of pruning them away."
            )

        for requirement_name, families, detail in required_checks:
            if self._has_family(selected, families):
                continue
            candidate = self._best_matching_candidate(
                candidate_pool,
                families=families,
                selected=selected,
                variable_missing=variable_missing,
            )
            if candidate is None:
                warnings.append(
                    f"No candidate available to satisfy methodology requirement: {requirement_name}."
                )
                continue
            action = self._append_or_replace_candidate(
                selected,
                candidate,
                analysis_budget=soft_budget,
                protected_families=protected_families,
                variable_missing=variable_missing,
                reason=detail,
                action_name=(
                    "expand_required_family"
                    if len(selected) >= max_analyses
                    else "add_required_family"
                ),
            )
            if action is None:
                warnings.append(
                    f"Could not repair missing methodology family '{requirement_name}' within the current analysis budget."
                )
                continue
            repair_actions.append(action)

        target_count = soft_budget
        while len(selected) < target_count:
            candidate = self._best_diversity_candidate(
                candidate_pool,
                selected=selected,
                variable_missing=variable_missing,
            )
            if candidate is None:
                break
            action = self._append_or_replace_candidate(
                selected,
                candidate,
                analysis_budget=soft_budget,
                protected_families=protected_families,
                variable_missing=variable_missing,
                reason="Keep promising exploratory branches instead of prematurely converging to the original budget.",
                action_name=(
                    "expand_exploratory_branch"
                    if len(selected) >= max_analyses
                    else "add_diversity_candidate"
                ),
            )
            if action is None:
                break
            repair_actions.append(action)

        final_families = tuple(item.candidate.family() for item in selected)
        checks = self._materialize_review_checks(
            draft_families=draft_families,
            final_families=final_families,
            requirements=required_checks,
        )
        draft_descriptive, draft_analytical = self._count_selected_visualizations(draft_selected)
        final_descriptive, final_analytical = self._count_selected_visualizations(selected)
        checks.extend(
            self._materialize_visualization_bundle_checks(
                draft_descriptive,
                draft_analytical,
                has_groups=bool(groups),
                repaired_descriptive=final_descriptive,
                repaired_analytical=final_analytical,
            )
        )
        has_missing_checks = any(check.status == "missing" for check in checks)
        completeness_tier = self._plan_completeness_tier(
            candidate_pool_size=len(candidate_pool),
            final_analysis_count=len(selected),
            recommended_floor=recommended_floor,
            academic_target=academic_target,
            production_target=production_target,
            has_missing_checks=has_missing_checks,
        )
        if not has_missing_checks and len(selected) >= recommended_floor and len(selected) < academic_target:
            warnings.append(
                f"Review repaired this plan to minimum completeness, but academic-ready coverage would target about {academic_target} analyses."
            )
        elif not has_missing_checks and len(selected) >= academic_target and len(selected) < production_target:
            warnings.append(
                f"Review achieved academic-ready coverage; production-ready planning would target about {production_target} analyses."
            )
        status = "pass"
        if has_missing_checks:
            status = "budget_limited" if max_analyses < recommended_floor else "partial"
        elif repair_actions:
            status = "repaired"

        return selected, PlanMethodologyReview(
            status=status,
            recommended_analysis_floor=recommended_floor,
            academic_analysis_target=academic_target,
            production_analysis_target=production_target,
            completeness_tier=completeness_tier,
            candidate_pool_size=len(candidate_pool),
            requested_analysis_budget=max_analyses,
            soft_analysis_budget=soft_budget,
            draft_analysis_count=len(draft_selected),
            final_analysis_count=len(selected),
            coverage_before=tuple(self._coverage_tags_for_selected(draft_selected)),
            coverage_after=tuple(self._coverage_tags_for_selected(selected)),
            draft_families=draft_families,
            final_families=final_families,
            complexity_signals=self._complexity_signals(
                has_groups=bool(groups),
                n_continuous=len(continuous),
                model_family=model_family,
                has_repeated=repeated_cluster is not None,
                has_cusum=has_cusum,
                has_survival=has_survival,
            ),
            checks=tuple(checks),
            repair_actions=tuple(repair_actions),
            warnings=tuple(warnings),
        )

    def _build_methodology_requirements(
        self,
        *,
        has_groups: bool,
        has_association: bool,
        model_family: str | None,
        has_repeated: bool,
        has_cusum: bool,
        has_survival: bool = False,
    ) -> list[tuple[str, tuple[str, ...], str]]:
        requirements: list[tuple[str, tuple[str, ...], str]] = [
            (
                "foundational_overview",
                ("analyze_variable",),
                "Autonomous EDA should always include a univariate overview before downstream inference.",
            )
        ]
        if has_groups:
            requirements.extend(
                [
                    (
                        "cohort_snapshot",
                        ("generate_table_one",),
                        "A grouped dataset should include a cohort snapshot instead of jumping straight into isolated tests.",
                    ),
                    (
                        "group_difference",
                        ("compare_groups",),
                        "A grouped dataset should include an explicit group-comparison family.",
                    ),
                ]
            )
        if has_association:
            requirements.append(
                (
                    "association_structure",
                    ("correlation_matrix",),
                    "When multiple continuous variables exist, the plan should screen association/collinearity structure.",
                )
            )
        if model_family:
            requirements.append(
                (
                    "adjusted_model",
                    (model_family,),
                    "A structured outcome plus multiple predictors should reserve one adjusted-model family.",
                )
            )
        if has_repeated:
            requirements.append(
                (
                    "longitudinal_structure",
                    ("run_repeated_measures",),
                    "Detected repeated-measure structure should not be flattened into only independent-group tests.",
                )
            )
        if has_cusum:
            requirements.append(
                (
                    "learning_curve_structure",
                    ("learning_curve_cusum",),
                    "Detected operator/trial/success structure should reserve a learning-curve family.",
                )
            )
        if has_survival:
            requirements.append(
                (
                    "time_to_event_structure",
                    ("survival_analysis",),
                    "Detected time-to-event columns should reserve a survival/Kaplan-Meier family.",
                )
            )
        return requirements

    def _recommended_analysis_floor(
        self,
        *,
        candidate_pool_size: int,
        has_groups: bool,
        has_association: bool,
        model_family: str | None,
        has_repeated: bool,
        has_cusum: bool,
        has_survival: bool = False,
    ) -> int:
        raw_floor = 1
        if has_groups:
            raw_floor += 2
        if has_association:
            raw_floor += 1
        if model_family:
            raw_floor += 1
        if has_repeated:
            raw_floor += 1
        if has_cusum:
            raw_floor += 1
        if has_survival:
            raw_floor += 1
        baseline_floor = min(candidate_pool_size, MIN_METHOD_ANALYSIS_FLOOR)
        return min(candidate_pool_size, max(raw_floor, baseline_floor))

    def _target_analysis_floor(
        self,
        *,
        recommended_floor: int,
        candidate_pool_size: int,
        target: str,
    ) -> int:
        if target == "production":
            baseline = PRODUCTION_ANALYSIS_TARGET
        else:
            baseline = ACADEMIC_ANALYSIS_TARGET
        return min(candidate_pool_size, max(recommended_floor, baseline))

    def _plan_completeness_tier(
        self,
        *,
        candidate_pool_size: int,
        final_analysis_count: int,
        recommended_floor: int,
        academic_target: int,
        production_target: int,
        has_missing_checks: bool,
    ) -> str:
        if has_missing_checks or final_analysis_count < recommended_floor:
            return "underpowered"
        if candidate_pool_size >= PRODUCTION_ANALYSIS_TARGET and final_analysis_count >= production_target:
            return "production_ready"
        if final_analysis_count >= academic_target:
            return "academic_ready"
        return "minimum_complete"

    def _soft_analysis_budget(
        self,
        *,
        requested_max_analyses: int,
        recommended_floor: int,
        candidate_pool_size: int,
        missing_required_count: int,
    ) -> int:
        base_budget = max(requested_max_analyses, recommended_floor)
        exploratory_headroom = 0
        if candidate_pool_size > base_budget:
            exploratory_headroom += 1
        if candidate_pool_size >= base_budget + 3:
            exploratory_headroom += 1
        return min(
            candidate_pool_size,
            base_budget + missing_required_count + exploratory_headroom,
        )

    def _materialize_review_checks(
        self,
        *,
        draft_families: tuple[str, ...],
        final_families: tuple[str, ...],
        requirements: list[tuple[str, tuple[str, ...], str]],
    ) -> list[ReviewCheck]:
        checks: list[ReviewCheck] = []
        for name, families, detail in requirements:
            draft_matches = tuple(family for family in draft_families if family in families)
            final_matches = tuple(family for family in final_families if family in families)
            if draft_matches:
                status = "pass"
                satisfied_by = draft_matches
            elif final_matches:
                status = "repaired"
                satisfied_by = final_matches
            else:
                status = "missing"
                satisfied_by = ()
            checks.append(
                ReviewCheck(
                    name=name,
                    status=status,
                    detail=detail,
                    satisfied_by=satisfied_by,
                )
            )
        return checks

    def _materialize_visualization_bundle_checks(
        self,
        descriptive_count: int,
        analytical_count: int,
        *,
        has_groups: bool,
        repaired_descriptive: int | None = None,
        repaired_analytical: int | None = None,
    ) -> list[ReviewCheck]:
        if not has_groups:
            return []

        final_descriptive = repaired_descriptive if repaired_descriptive is not None else descriptive_count
        final_analytical = repaired_analytical if repaired_analytical is not None else analytical_count
        checks: list[ReviewCheck] = []
        requirements = [
            (
                "descriptive_figure_bundle",
                descriptive_count,
                final_descriptive,
                MIN_DESCRIPTIVE_VISUALIZATIONS,
                f"Grouped publication-oriented analysis should include at least {MIN_DESCRIPTIVE_VISUALIZATIONS} crude/descriptive figures before inferential interpretation.",
            ),
            (
                "detailed_figure_bundle",
                analytical_count,
                final_analytical,
                MIN_ANALYTICAL_VISUALIZATIONS,
                f"Grouped publication-oriented analysis should include at least {MIN_ANALYTICAL_VISUALIZATIONS} detailed figures (comparison/post-hoc/model-support plots).",
            ),
        ]
        for name, draft_count, final_count, minimum, detail in requirements:
            if draft_count >= minimum:
                status = "pass"
                satisfied_by = (f"count={draft_count}",)
            elif final_count >= minimum:
                status = "repaired"
                satisfied_by = (f"count={final_count}",)
            else:
                status = "missing"
                satisfied_by = (f"count={final_count}",)
            checks.append(
                ReviewCheck(
                    name=name,
                    status=status,
                    detail=detail,
                    satisfied_by=satisfied_by,
                )
            )
        return checks

    def _count_selected_visualizations(
        self,
        selected: tuple[RankedCandidate, ...] | list[RankedCandidate],
    ) -> tuple[int, int]:
        descriptive = 0
        analytical = 0
        for ranked in selected:
            for viz in ranked.candidate.visualizations:
                if self._visualization_category(viz.plot_type, viz.group_variable) == "descriptive":
                    descriptive += 1
                else:
                    analytical += 1
        return descriptive, analytical

    def _count_visualization_entries(self, analyses: list[dict[str, Any]]) -> tuple[int, int]:
        descriptive = 0
        analytical = 0
        for entry in analyses:
            if not isinstance(entry, dict) or self._entry_family(entry) != "visualization":
                continue
            if self._visualization_category(
                str(entry.get("plot_type") or ""),
                str(entry.get("group_variable")) if entry.get("group_variable") is not None else None,
            ) == "descriptive":
                descriptive += 1
            else:
                analytical += 1
        return descriptive, analytical

    def _ensure_publication_visualization_floor(
        self,
        blueprint: list[dict[str, Any]],
        *,
        candidate_pool: list[AnalysisCandidate],
        seen_viz: set[tuple[str, tuple[str, ...], str | None]],
    ) -> list[dict[str, Any]]:
        descriptive_count, analytical_count = self._count_visualization_entries(blueprint)
        additional_viz = [
            viz
            for candidate in candidate_pool
            for viz in candidate.visualizations
            if viz.key() not in seen_viz
        ]
        additional_viz.sort(
            key=lambda viz: (
                0 if self._visualization_category(viz.plot_type, viz.group_variable) == "descriptive" else 1,
                viz.plot_type,
                viz.variables,
            )
        )

        for viz in additional_viz:
            category = self._visualization_category(viz.plot_type, viz.group_variable)
            if category == "descriptive" and descriptive_count >= MIN_DESCRIPTIVE_VISUALIZATIONS:
                continue
            if category == "analytical" and analytical_count >= MIN_ANALYTICAL_VISUALIZATIONS:
                continue
            blueprint.append(viz.to_plan_entry())
            seen_viz.add(viz.key())
            if category == "descriptive":
                descriptive_count += 1
            else:
                analytical_count += 1
            if (
                descriptive_count >= MIN_DESCRIPTIVE_VISUALIZATIONS
                and analytical_count >= MIN_ANALYTICAL_VISUALIZATIONS
            ):
                break
        return blueprint

    def _visualization_category(self, plot_type: str, group_variable: str | None) -> str:
        normalized = str(plot_type).strip().lower()
        if normalized == "histogram":
            return "descriptive"
        if normalized == "bar" and not group_variable:
            return "descriptive"
        return "analytical"

    def _best_matching_candidate(
        self,
        candidate_pool: list[AnalysisCandidate],
        *,
        families: tuple[str, ...],
        selected: list[RankedCandidate],
        variable_missing: dict[str, float],
    ) -> AnalysisCandidate | None:
        coverage_seen = {tag for item in selected for tag in item.candidate.coverage_tags}
        used_variables = {name for item in selected for name in item.candidate.variables}
        used_families = {item.candidate.family() for item in selected}
        remaining = [
            candidate
            for candidate in candidate_pool
            if candidate.family() in families
            and candidate.key() not in {item.candidate.key() for item in selected}
        ]
        if not remaining:
            return None
        return max(
            remaining,
            key=lambda candidate: self._score_candidate(
                candidate,
                coverage_seen=coverage_seen,
                used_variables=used_variables,
                used_families=used_families,
                variable_missing=variable_missing,
            ),
        )

    def _best_diversity_candidate(
        self,
        candidate_pool: list[AnalysisCandidate],
        *,
        selected: list[RankedCandidate],
        variable_missing: dict[str, float],
    ) -> AnalysisCandidate | None:
        selected_keys = {item.candidate.key() for item in selected}
        coverage_seen = {tag for item in selected for tag in item.candidate.coverage_tags}
        used_variables = {name for item in selected for name in item.candidate.variables}
        used_families = {item.candidate.family() for item in selected}
        remaining = [
            candidate for candidate in candidate_pool if candidate.key() not in selected_keys
        ]
        if not remaining:
            return None
        ranked = sorted(
            remaining,
            key=lambda candidate: self._score_candidate(
                candidate,
                coverage_seen=coverage_seen,
                used_variables=used_variables,
                used_families=used_families,
                variable_missing=variable_missing,
            ),
            reverse=True,
        )
        for candidate in ranked:
            if (
                candidate.family() not in used_families
                or set(candidate.coverage_tags) - coverage_seen
            ):
                return candidate
        return ranked[0] if ranked else None

    def _enrich_selection(
        self,
        *,
        selected: list[RankedCandidate],
        candidate_pool: list[AnalysisCandidate],
        variable_missing: dict[str, float],
        enrich_rounds: int,
    ) -> tuple[list[RankedCandidate], list[EnrichmentRound], list[str]]:
        if enrich_rounds <= 1:
            return selected, [], []

        history: list[EnrichmentRound] = []
        warnings: list[str] = []

        for round_index in range(1, enrich_rounds):
            coverage_before = tuple(self._coverage_tags_for_selected(selected))
            added_labels: list[str] = []
            growth_budget = min(2, max(0, len(candidate_pool) - len(selected)))

            for _ in range(growth_budget):
                candidate = self._best_diversity_candidate(
                    candidate_pool,
                    selected=selected,
                    variable_missing=variable_missing,
                )
                if candidate is None:
                    break
                action = self._append_or_replace_candidate(
                    selected,
                    candidate,
                    analysis_budget=len(selected) + 1,
                    protected_families=set(),
                    variable_missing=variable_missing,
                    reason="Iterative plan enrich keeps following promising, not-yet-executed branches.",
                    action_name="enrich_exploratory_branch",
                )
                if action is None:
                    break
                added_labels.append(action.candidate_label)

            coverage_after = tuple(self._coverage_tags_for_selected(selected))
            if not added_labels:
                warnings.append(
                    f"Enrich round {round_index} found no additional branches beyond the reviewed blueprint."
                )
                break

            history.append(
                EnrichmentRound(
                    round_index=round_index,
                    added_candidate_labels=tuple(added_labels),
                    coverage_before=coverage_before,
                    coverage_after=coverage_after,
                    rationale="Add one more controlled exploration layer before Phase 4 lock.",
                )
            )

        return selected, history, warnings

    def _statsmodels_script_block(
        self,
        *,
        entry: dict[str, Any],
        index: int,
        variable_types: dict[str, VariableType],
    ) -> list[str]:
        family = self._entry_family(entry) or "unknown_analysis"
        variables = [str(value) for value in entry.get("variables", [])]
        result_key = f"{family}_{index}"
        lines = ["", f"# Step {index}: {family}"]

        if family == "analyze_variable":
            lines.extend(
                [
                    f"analysis_results[{result_key!r}] = df[{variables!r}].describe(include='all').transpose().to_dict(orient='index')",
                ]
            )
            for variable in variables[:2]:
                if variable_types.get(variable) in {
                    VariableType.CONTINUOUS,
                    VariableType.BIOMARKER,
                }:
                    lines.extend(
                        [
                            "plt.figure(figsize=(8, 5))",
                            f"sns.histplot(data=df, x={variable!r}, kde=True)",
                            f"finalize_figure('{result_key}_{variable}_hist.png')",
                        ]
                    )
        elif family == "generate_table_one":
            group_variable = str(entry.get("group_variable") or variables[0] if variables else "")
            compare_vars = [value for value in variables if value != group_variable]
            lines.extend(
                [
                    f"table_one_df_{index} = df.dropna(subset={[group_variable]!r}).copy()",
                    f"analysis_results[{result_key!r}] = table_one_df_{index}.groupby({group_variable!r})[{compare_vars!r}].agg(['count', 'mean', 'std', 'median']).to_dict()",
                ]
            )
        elif family == "compare_groups":
            group_variable = str(entry.get("group_variable") or variables[-1] if variables else "")
            compare_vars = [value for value in variables if value != group_variable]
            lines.append(f"analysis_results[{result_key!r}] = {{}}")
            for variable in compare_vars[:3]:
                if variable_types.get(variable) in {
                    VariableType.CONTINUOUS,
                    VariableType.BIOMARKER,
                }:
                    formula = f"{variable} ~ C({group_variable})"
                    lines.extend(
                        [
                            f"compare_df_{index}_{variable} = df.dropna(subset={[variable, group_variable]!r}).copy()",
                            f"model_{index}_{variable} = smf.ols({formula!r}, data=compare_df_{index}_{variable}).fit()",
                            f"anova_{index}_{variable} = sm.stats.anova_lm(model_{index}_{variable}, typ=2)",
                            f"analysis_results[{result_key!r}][{variable!r}] = {{'formula': {formula!r}, 'anova': anova_{index}_{variable}.reset_index().to_dict(orient='records')}}",
                            "plt.figure(figsize=(8, 5))",
                            f"sns.boxplot(data=compare_df_{index}_{variable}, x={group_variable!r}, y={variable!r})",
                            f"finalize_figure('{result_key}_{variable}_boxplot.png')",
                        ]
                    )
        elif family == "correlation_matrix":
            lines.extend(
                [
                    f"corr_df_{index} = df[{variables!r}].dropna()",
                    f"corr_matrix_{index} = corr_df_{index}.corr()",
                    f"analysis_results[{result_key!r}] = corr_matrix_{index}.to_dict()",
                    "plt.figure(figsize=(8, 6))",
                    f"sns.heatmap(corr_matrix_{index}, annot=True, cmap='coolwarm', fmt='.2f')",
                    f"finalize_figure('{result_key}_heatmap.png')",
                ]
            )
        elif family in {"logistic_regression", "multiple_regression", "glm"}:
            target = str(entry.get("target_variable") or (variables[0] if variables else ""))
            predictors = [str(value) for value in entry.get("covariates", [])] or [
                value for value in variables if value != target
            ]
            encoded_target = target
            formula = f"{target} ~ " + " + ".join(
                self._statsmodels_formula_term(value, variable_types) for value in predictors
            )
            lines.extend(
                [
                    f"model_df_{index} = df.dropna(subset={[target, *predictors]!r}).copy()",
                ]
            )
            if family == "logistic_regression":
                encoded_target = f"__encoded_{target}"
                formula = f"{encoded_target} ~ " + " + ".join(
                    self._statsmodels_formula_term(value, variable_types) for value in predictors
                )
                lines.extend(
                    [
                        f"model_df_{index}[{encoded_target!r}] = ensure_binary(model_df_{index}[{target!r}])",
                        f"model_{index} = smf.logit({formula!r}, data=model_df_{index}).fit(disp=False)",
                        f"analysis_results[{result_key!r}] = {{",
                        f"    'formula': {formula!r},",
                        "    'n_obs': int(model_" + str(index) + ".nobs),",
                        "    'pseudo_r2': float(model_" + str(index) + ".prsquared),",
                        "    'aic': float(model_" + str(index) + ".aic),",
                        "    'bic': float(model_" + str(index) + ".bic),",
                        "    'coefficients': odds_ratio_table(model_" + str(index) + "),",
                        "}",
                    ]
                )
            elif family == "multiple_regression":
                lines.extend(
                    [
                        f"model_{index} = smf.ols({formula!r}, data=model_df_{index}).fit()",
                        f"anova_{index} = sm.stats.anova_lm(model_{index}, typ=2)",
                        f"analysis_results[{result_key!r}] = {{",
                        f"    'formula': {formula!r},",
                        "    'n_obs': int(model_" + str(index) + ".nobs),",
                        "    'r_squared': float(model_" + str(index) + ".rsquared),",
                        "    'adjusted_r_squared': float(model_" + str(index) + ".rsquared_adj),",
                        "    'aic': float(model_" + str(index) + ".aic),",
                        "    'bic': float(model_" + str(index) + ".bic),",
                        "    'anova': anova_"
                        + str(index)
                        + ".reset_index().to_dict(orient='records'),",
                        "    'coefficients': model_"
                        + str(index)
                        + ".summary2().tables[1].reset_index().to_dict(orient='records'),",
                        "}",
                        "plt.figure(figsize=(7, 5))",
                        f"sns.scatterplot(x=model_{index}.fittedvalues, y=model_{index}.resid)",
                        f"finalize_figure('{result_key}_residuals.png')",
                    ]
                )
            else:
                family_name = self._statsmodels_glm_family_name(target, variable_types)
                lines.extend(
                    [
                        f"family_{index} = sm.families.{family_name}()",
                        f"model_{index} = smf.glm({formula!r}, data=model_df_{index}, family=family_{index}).fit()",
                        f"analysis_results[{result_key!r}] = {{",
                        f"    'formula': {formula!r},",
                        f"    'family': {family_name!r},",
                        "    'n_obs': int(model_" + str(index) + ".nobs),",
                        "    'aic': float(model_" + str(index) + ".aic),",
                        "    'coefficients': model_"
                        + str(index)
                        + ".summary2().tables[1].reset_index().to_dict(orient='records'),",
                        "}",
                    ]
                )
        elif family == "learning_curve_cusum":
            target = str(entry.get("target_variable") or (variables[0] if variables else ""))
            operator = str(
                entry.get("group_variable") or (variables[1] if len(variables) > 1 else "")
            )
            trial = str((entry.get("covariates") or variables[2:3] or [""])[0])
            lines.extend(
                [
                    f"cusum_df_{index} = df.dropna(subset={[target, operator, trial]!r}).copy()",
                    f"cusum_df_{index}[{target!r}] = ensure_binary(cusum_df_{index}[{target!r}])",
                    f"cusum_df_{index} = cusum_df_{index}.sort_values([{operator!r}, {trial!r}])",
                    f"target_rate_{index} = float(cusum_df_{index}[{target!r}].mean())",
                    f"cusum_df_{index}['_cusum_increment'] = cusum_df_{index}[{target!r}] - target_rate_{index}",
                    f"cusum_df_{index}['_cusum'] = cusum_df_{index}.groupby({operator!r})['_cusum_increment'].cumsum()",
                    f"analysis_results[{result_key!r}] = cusum_df_{index}[[{operator!r}, {trial!r}, '_cusum']].to_dict(orient='records')",
                    "plt.figure(figsize=(8, 5))",
                    f"sns.lineplot(data=cusum_df_{index}, x={trial!r}, y='_cusum', hue={operator!r})",
                    f"finalize_figure('{result_key}_cusum.png')",
                ]
            )
        elif family == "run_repeated_measures":
            lines.extend(
                [
                    f"analysis_results[{result_key!r}] = {{",
                    "    'warning': 'Repeated-measures analysis needs a subject identifier for statsmodels AnovaRM.',",
                    f"    'variables': {variables!r},",
                    "}",
                    "# TODO: provide SUBJECT_ID and reshape to long format before calling statsmodels.stats.anova.AnovaRM.",
                ]
            )
        elif family == "roc_auc":
            score_var = str((entry.get("covariates") or variables[1:2] or [""])[0])
            target = str(entry.get("target_variable") or (variables[0] if variables else ""))
            lines.extend(
                [
                    f"roc_df_{index} = df.dropna(subset={[target, score_var]!r}).copy()",
                    f"roc_df_{index}[{target!r}] = ensure_binary(roc_df_{index}[{target!r}])",
                    f"roc_df_{index}['_rank'] = roc_df_{index}[{score_var!r}].rank(method='average')",
                    f"n_pos_{index} = int(roc_df_{index}[{target!r}].sum())",
                    f"n_total_{index} = len(roc_df_{index})",
                    f"n_neg_{index} = n_total_{index} - n_pos_{index}",
                    f"auc_{index} = float(((roc_df_{index}.loc[roc_df_{index}[{target!r}] == 1, '_rank'].sum()) - (n_pos_{index} * (n_pos_{index} + 1) / 2)) / max(1, n_pos_{index} * n_neg_{index}))",
                    f"analysis_results[{result_key!r}] = {{'score_variable': {score_var!r}, 'auc': auc_{index}, 'n_positive': n_pos_{index}, 'n_negative': n_neg_{index}}}",
                ]
            )
        else:
            lines.extend(
                [
                    f"analysis_results[{result_key!r}] = {{'family': {family!r}, 'variables': {variables!r}, 'note': 'Manual implementation still required for this family.'}}",
                ]
            )

        return lines

    def _statsmodels_formula_term(
        self,
        variable_name: str,
        variable_types: dict[str, VariableType],
    ) -> str:
        if variable_types.get(variable_name) in {
            VariableType.BINARY,
            VariableType.CATEGORICAL,
            VariableType.ORDINAL,
        }:
            return f"C({variable_name})"
        return variable_name

    def _statsmodels_glm_family_name(
        self,
        target: str,
        variable_types: dict[str, VariableType],
    ) -> str:
        target_type = variable_types.get(target)
        if target_type == VariableType.BINARY:
            return "Binomial"
        return "Gaussian"

    def _append_or_replace_candidate(
        self,
        selected: list[RankedCandidate],
        candidate: AnalysisCandidate,
        *,
        analysis_budget: int,
        protected_families: set[str],
        variable_missing: dict[str, float],
        reason: str,
        action_name: str = "add_required_family",
    ) -> RepairAction | None:
        if candidate.key() in {item.candidate.key() for item in selected}:
            return None
        if len(selected) < analysis_budget:
            coverage_seen = {tag for item in selected for tag in item.candidate.coverage_tags}
            used_variables = {name for item in selected for name in item.candidate.variables}
            used_families = {item.candidate.family() for item in selected}
            selected.append(
                RankedCandidate(
                    candidate=candidate,
                    score=self._score_candidate(
                        candidate,
                        coverage_seen=coverage_seen,
                        used_variables=used_variables,
                        used_families=used_families,
                        variable_missing=variable_missing,
                    ),
                )
            )
            return RepairAction(
                action=action_name,
                reason=reason,
                candidate_label=candidate.label(),
            )

        replace_index = self._replaceable_index(selected, protected_families)
        if replace_index is None:
            return None
        removed = selected.pop(replace_index)
        coverage_seen = {tag for item in selected for tag in item.candidate.coverage_tags}
        used_variables = {name for item in selected for name in item.candidate.variables}
        used_families = {item.candidate.family() for item in selected}
        selected.append(
            RankedCandidate(
                candidate=candidate,
                score=self._score_candidate(
                    candidate,
                    coverage_seen=coverage_seen,
                    used_variables=used_variables,
                    used_families=used_families,
                    variable_missing=variable_missing,
                ),
            )
        )
        return RepairAction(
            action="replace_with_required_family",
            reason=reason,
            candidate_label=candidate.label(),
            replaced_label=removed.candidate.label(),
        )

    def _replaceable_index(
        self,
        selected: list[RankedCandidate],
        protected_families: set[str],
    ) -> int | None:
        replaceable = [
            (index, item)
            for index, item in enumerate(selected)
            if item.candidate.family() not in protected_families
        ]
        if not replaceable:
            return None
        return min(replaceable, key=lambda pair: pair[1].score)[0]

    def _has_family(
        self,
        selected: list[RankedCandidate],
        families: tuple[str, ...],
    ) -> bool:
        selected_families = {item.candidate.family() for item in selected}
        return any(family in selected_families for family in families)

    def _coverage_tags_for_selected(
        self,
        selected: list[RankedCandidate] | tuple[RankedCandidate, ...],
    ) -> list[str]:
        return sorted({tag for item in selected for tag in item.candidate.coverage_tags})

    def _coverage_tags_for_families(
        self,
        candidate_pool: list[AnalysisCandidate],
        families: tuple[str, ...],
    ) -> list[str]:
        family_set = set(families)
        return sorted(
            {
                tag
                for candidate in candidate_pool
                if candidate.family() in family_set
                for tag in candidate.coverage_tags
            }
        )

    def _complexity_signals(
        self,
        *,
        has_groups: bool,
        n_continuous: int,
        model_family: str | None,
        has_repeated: bool,
        has_cusum: bool,
        has_survival: bool = False,
    ) -> dict[str, Any]:
        return {
            "has_groups": has_groups,
            "n_continuous": n_continuous,
            "model_family": model_family,
            "has_repeated_structure": has_repeated,
            "has_learning_curve_signature": has_cusum,
            "has_time_to_event_signature": has_survival,
        }

    def _execution_stage_metadata(self, family: str) -> tuple[int, str, str]:
        mapping = {
            "analyze_variable": (10, "analyze_variable", "baseline_overview"),
            "descriptive": (10, "analyze_variable", "baseline_overview"),
            "univariate": (10, "analyze_variable", "baseline_overview"),
            "generate_table_one": (20, "generate_table_one", "cohort_snapshot"),
            "table_one": (20, "generate_table_one", "cohort_snapshot"),
            "compare_groups": (30, "compare_groups", "group_screen"),
            "correlation_matrix": (40, "correlation_matrix", "association_screen"),
            "run_repeated_measures": (50, "run_repeated_measures", "longitudinal_branch"),
            "propensity_score": (60, "run_advanced_analysis", "balancing_branch"),
            "survival_analysis": (60, "run_advanced_analysis", "time_to_event_branch"),
            "logistic_regression": (70, "run_advanced_analysis", "adjusted_model"),
            "multiple_regression": (70, "run_advanced_analysis", "adjusted_model"),
            "roc_auc": (80, "run_advanced_analysis", "specialized_followup"),
            "learning_curve_cusum": (80, "run_advanced_analysis", "specialized_followup"),
            "power_analysis_advanced": (90, "run_advanced_analysis", "sensitivity_followup"),
        }
        return mapping.get(family, (85, family, "specialized_followup"))

    def _dependencies_for_family(
        self,
        family: str,
        completed_by_family: dict[str, list[str]],
    ) -> tuple[str, ...]:
        dependency_map = {
            "generate_table_one": ("analyze_variable",),
            "table_one": ("analyze_variable",),
            "compare_groups": ("generate_table_one", "analyze_variable"),
            "correlation_matrix": ("analyze_variable",),
            "run_repeated_measures": ("analyze_variable",),
            "propensity_score": ("generate_table_one", "compare_groups"),
            "survival_analysis": ("generate_table_one", "compare_groups", "analyze_variable"),
            "logistic_regression": ("compare_groups", "correlation_matrix", "analyze_variable"),
            "multiple_regression": ("compare_groups", "correlation_matrix", "analyze_variable"),
            "roc_auc": ("logistic_regression", "compare_groups", "analyze_variable"),
            "learning_curve_cusum": ("analyze_variable",),
            "power_analysis_advanced": (
                "logistic_regression",
                "multiple_regression",
                "compare_groups",
            ),
        }
        dependencies: list[str] = []
        for dependency_family in dependency_map.get(family, ()):
            dependencies.extend(completed_by_family.get(dependency_family, [])[-1:])
        return tuple(dict.fromkeys(dependencies))

    def _default_schedule_rationale(self, family: str) -> str:
        default_rationales = {
            "analyze_variable": "Start with a univariate overview so later comparisons and models inherit distribution and missingness context.",
            "generate_table_one": "Freeze the cohort snapshot before branching into pairwise or multivariable analyses.",
            "compare_groups": "Screen the main group split early so large shifts and effect sizes surface quickly.",
            "correlation_matrix": "Inspect association and collinearity before fitting adjusted models.",
            "run_repeated_measures": "Preserve longitudinal structure as a dedicated branch rather than flattening it into independent tests.",
            "logistic_regression": "Fit the adjusted model after baseline and association screening are complete.",
            "multiple_regression": "Fit the adjusted model after baseline and association screening are complete.",
            "roc_auc": "Assess discrimination after baseline and adjusted-model context are available.",
            "learning_curve_cusum": "Run the specialized learning-curve branch after the main structure is understood.",
        }
        return default_rationales.get(
            family,
            "Execute this branch after the foundational overview so the autonomous workflow keeps expanding methodically.",
        )

    def _recommend_model_family(
        self,
        outcomes: list[Variable],
        predictors: list[Variable],
        include_advanced: bool,
    ) -> str | None:
        if not include_advanced or not outcomes or len(predictors) < 2:
            return None
        primary_outcome = outcomes[0]
        if primary_outcome.variable_type == VariableType.BINARY:
            return "logistic_regression"
        if primary_outcome.variable_type in {VariableType.CONTINUOUS, VariableType.BIOMARKER}:
            return "multiple_regression"
        return None

    def _entry_family(self, entry: dict[str, Any]) -> str | None:
        entry_type = str(entry.get("type", "")).strip()
        if not entry_type:
            return None
        normalized = entry_type.lower().replace("-", "_").replace(" ", "_")
        if normalized == "run_advanced_analysis":
            analysis_type = str(entry.get("analysis_type", "")).strip()
            if analysis_type:
                return analysis_type.lower().replace("-", "_").replace(" ", "_")
        alias_map = {
            "descriptive": "analyze_variable",
            "univariate": "analyze_variable",
            "table_one": "generate_table_one",
        }
        return alias_map.get(normalized, normalized)

    def _average_missing_penalty(
        self,
        variables: tuple[str, ...],
        variable_missing: dict[str, float],
    ) -> float:
        if not variables:
            return 0.0
        rates = [variable_missing.get(variable, 0.0) for variable in variables]
        return (sum(rates) / len(rates)) * 1.5

    def _pick_outcomes(
        self,
        variables: list[Variable],
        *,
        question_terms: tuple[str, ...] = (),
    ) -> list[Variable]:
        explicit = [variable for variable in variables if variable.role == VariableRole.OUTCOME]
        if explicit:
            return self._sort_variables(explicit)
        keyword_matches = [
            variable
            for variable in variables
            if self._name_has_keyword(variable.name, OUTCOME_KEYWORDS)
            and variable.variable_type
            in {VariableType.BINARY, VariableType.CONTINUOUS, VariableType.BIOMARKER}
        ]
        if keyword_matches:
            return self._sort_variables_by_question(keyword_matches, question_terms)
        return []

    def _pick_groups(
        self,
        variables: list[Variable],
        *,
        outcomes: list[Variable] | None = None,
        question_terms: tuple[str, ...] = (),
    ) -> list[Variable]:
        explicit = [variable for variable in variables if variable.role == VariableRole.GROUP]
        if explicit:
            return self._sort_variables(explicit)
        outcome_names = {variable.name for variable in outcomes or []}
        inferred = [
            variable
            for variable in variables
            if variable.name not in outcome_names
            if variable.variable_type in {VariableType.BINARY, VariableType.CATEGORICAL}
            and 2 <= max(variable.n_unique, 2) <= 8
        ]
        keyword_first = [
            variable
            for variable in inferred
            if self._name_has_keyword(variable.name, GROUP_KEYWORDS)
        ]
        if keyword_first:
            return self._sort_variables_by_question(keyword_first, question_terms)
        if outcome_names:
            return []
        return self._sort_variables_by_question(inferred, question_terms)

    def _pick_predictors(
        self,
        variables: list[Variable],
        outcomes: list[Variable],
        groups: list[Variable],
        *,
        question_terms: tuple[str, ...] = (),
    ) -> list[Variable]:
        excluded = {variable.name for variable in outcomes + groups}
        explicit = [
            variable
            for variable in variables
            if variable.role in {VariableRole.PREDICTOR, VariableRole.COVARIATE}
            and variable.name not in excluded
        ]
        if explicit:
            return self._sort_variables(explicit)
        inferred = [
            variable
            for variable in variables
            if variable.name not in excluded
            and variable.variable_type
            in {
                VariableType.CONTINUOUS,
                VariableType.BIOMARKER,
                VariableType.BINARY,
                VariableType.CATEGORICAL,
                VariableType.ORDINAL,
            }
        ]
        return self._sort_variables_by_question(inferred, question_terms)

    def _pick_roc_predictors(
        self,
        variables: list[Variable],
        covariates: tuple[str, ...],
    ) -> list[str]:
        ranked = []
        covariate_set = set(covariates)
        for variable in variables:
            if variable.name not in covariate_set:
                continue
            if variable.variable_type not in {VariableType.CONTINUOUS, VariableType.BIOMARKER}:
                continue
            boost = 1 if self._name_has_keyword(variable.name, ROC_KEYWORDS) else 0
            ranked.append((boost, -variable.missing_rate, variable.name))
        ranked.sort(reverse=True)
        return [name for _, _, name in ranked[:3]]

    def _detect_repeated_measure_cluster(self, variables: list[Variable]) -> list[str] | None:
        clusters: dict[str, list[str]] = {}
        for variable in variables:
            if variable.variable_type not in {VariableType.CONTINUOUS, VariableType.BIOMARKER}:
                continue
            for pattern in REPEATED_PATTERNS:
                match = pattern.match(variable.name)
                if not match:
                    continue
                base = match.group("base")
                clusters.setdefault(base, []).append(variable.name)
                break

        if not clusters:
            return None
        base, members = max(clusters.items(), key=lambda item: len(item[1]))
        if len(members) < 3:
            return None
        return sorted(members)

    def _detect_learning_curve_candidate(
        self,
        variables: list[Variable],
        outcomes: list[Variable],
    ) -> AnalysisCandidate | None:
        operator = self._first_keyword_match(variables, OPERATOR_KEYWORDS)
        trial = self._first_keyword_match(variables, TRIAL_KEYWORDS)
        success = self._pick_learning_curve_outcome(variables, outcomes)

        if not operator or not trial or not success or not self._is_sequence_variable(trial):
            return None

        return AnalysisCandidate(
            type="run_advanced_analysis",
            analysis_type="learning_curve_cusum",
            variables=(success.name, operator.name, trial.name),
            target_variable=success.name,
            group_variable=operator.name,
            covariates=(trial.name,),
            rationale=(
                "Detected operator + trial-order + binary-success columns; reserve a dedicated learning-curve "
                "CUSUM slot instead of flattening sequential performance into ordinary group comparisons."
            ),
            coverage_tags=("specialized", "sequence", "learning_curve"),
            base_score=8.0,
            priority="high",
            visualizations=(
                VisualizationSuggestion(
                    plot_type="line",
                    variables=(trial.name, success.name),
                    group_variable=operator.name,
                    rationale="Inspect learning progression by operator before committing to CUSUM interpretation.",
                ),
            ),
        )

    def _pick_learning_curve_outcome(
        self,
        variables: list[Variable],
        outcomes: list[Variable],
    ) -> Variable | None:
        binary_outcomes = [
            variable for variable in outcomes if variable.variable_type == VariableType.BINARY
        ]
        if binary_outcomes:
            return self._sort_variables(binary_outcomes)[0]
        inferred = [
            variable
            for variable in variables
            if variable.variable_type == VariableType.BINARY
            and self._name_has_keyword(variable.name, ("success", "pass", "failure", "outcome"))
        ]
        if inferred:
            return self._sort_variables(inferred)[0]
        return None

    def _detect_time_to_event_candidate(
        self,
        variables: list[Variable],
        outcomes: list[Variable],
        groups: list[Variable],
        predictors: list[Variable],
        *,
        question_terms: tuple[str, ...],
    ) -> AnalysisCandidate | None:
        event = self._first_keyword_match(
            [variable for variable in outcomes if variable.variable_type == VariableType.BINARY],
            ("event", "death", "mortality", "complication", "failure", "success"),
        )
        if event is None:
            event = self._first_keyword_match(
                [variable for variable in variables if variable.variable_type == VariableType.BINARY],
                ("event", "death", "mortality", "complication", "failure"),
            )
        time_var = self._first_keyword_match(
            [
                variable
                for variable in variables
                if variable.variable_type in {VariableType.CONTINUOUS, VariableType.BIOMARKER}
            ],
            TIME_TO_EVENT_KEYWORDS,
        )
        if event is None or time_var is None:
            return None
        if question_terms and not (
            self._question_score(event.name, question_terms)
            or self._question_score(time_var.name, question_terms)
            or any(term in {"survival", "event", "complication", "time"} for term in question_terms)
        ):
            return None
        group = groups[0] if groups else None
        covariates = tuple(
            variable.name
            for variable in self._limit_variables(
                [
                    variable
                    for variable in self._unique_variables(predictors)
                    if variable.name not in {event.name, time_var.name, group.name if group else ""}
                ],
                limit=4,
            )
        )
        variables_tuple = tuple(
            value
            for value in (event.name, time_var.name, group.name if group else None, *covariates)
            if value
        )
        return AnalysisCandidate(
            type="run_advanced_analysis",
            analysis_type="survival_analysis",
            variables=variables_tuple,
            target_variable=event.name,
            group_variable=group.name if group else None,
            time_variable=time_var.name,
            covariates=covariates,
            rationale=(
                "Detected a time-like variable plus binary event endpoint; reserve a Kaplan-Meier/local-lite survival branch."
            ),
            coverage_tags=("time_to_event", "survival", "specialized"),
            base_score=7.6,
            priority="medium",
            visualizations=(
                VisualizationSuggestion(
                    plot_type="line",
                    variables=(time_var.name, event.name),
                    group_variable=groups[0].name if groups else None,
                    rationale="Inspect event timing before survival interpretation.",
                ),
            ),
        )

    def _default_visualizations_for_variables(
        self,
        variables: list[Variable],
    ) -> list[VisualizationSuggestion]:
        suggestions: list[VisualizationSuggestion] = []
        for variable in variables:
            if variable.variable_type in {VariableType.CONTINUOUS, VariableType.BIOMARKER}:
                suggestions.append(
                    VisualizationSuggestion(
                        plot_type="histogram",
                        variables=(variable.name,),
                        rationale=f"Inspect the distribution of {variable.name} before downstream comparisons.",
                    )
                )
            elif variable.variable_type in {
                VariableType.CATEGORICAL,
                VariableType.BINARY,
                VariableType.ORDINAL,
            }:
                suggestions.append(
                    VisualizationSuggestion(
                        plot_type="bar",
                        variables=(variable.name,),
                        rationale=f"Inspect the category balance of {variable.name} before downstream comparisons.",
                    )
                )
        return suggestions

    def _comparison_visualizations(
        self,
        *,
        group_variable: str,
        variables: list[Variable],
    ) -> list[VisualizationSuggestion]:
        suggestions: list[VisualizationSuggestion] = []
        for variable in variables:
            if variable.variable_type in {VariableType.CONTINUOUS, VariableType.BIOMARKER}:
                suggestions.append(
                    VisualizationSuggestion(
                        plot_type="boxplot",
                        variables=(variable.name,),
                        group_variable=group_variable,
                        rationale=f"Compare {variable.name} distributions across {group_variable}.",
                    )
                )
            else:
                suggestions.append(
                    VisualizationSuggestion(
                        plot_type="bar",
                        variables=(variable.name,),
                        group_variable=group_variable,
                        rationale=f"Compare category composition of {variable.name} across {group_variable}.",
                    )
                )
        return suggestions

    def _sort_variables(self, variables: list[Variable]) -> list[Variable]:
        role_rank = {
            VariableRole.OUTCOME: 0,
            VariableRole.GROUP: 1,
            VariableRole.PREDICTOR: 2,
            VariableRole.COVARIATE: 3,
            VariableRole.UNASSIGNED: 4,
            VariableRole.ID: 5,
        }
        type_rank = {
            VariableType.BINARY: 0,
            VariableType.CONTINUOUS: 1,
            VariableType.BIOMARKER: 1,
            VariableType.CATEGORICAL: 2,
            VariableType.ORDINAL: 3,
            VariableType.DATETIME: 4,
            VariableType.TEXT: 5,
            VariableType.ID: 6,
            VariableType.UNKNOWN: 7,
        }
        return sorted(
            variables,
            key=lambda variable: (
                role_rank.get(variable.role, 9),
                variable.missing_rate,
                type_rank.get(variable.variable_type, 9),
                variable.name,
            ),
        )

    def _sort_variables_by_question(
        self,
        variables: list[Variable],
        question_terms: tuple[str, ...],
    ) -> list[Variable]:
        base_rank = {variable.name: index for index, variable in enumerate(self._sort_variables(variables))}
        return sorted(
            variables,
            key=lambda variable: (
                -self._question_score(variable.name, question_terms),
                base_rank.get(variable.name, 999),
            ),
        )

    def _limit_variables(self, variables: list[Variable], *, limit: int) -> list[Variable]:
        return variables[:limit]

    def _unique_variables(self, variables: list[Variable]) -> list[Variable]:
        seen: set[str] = set()
        result: list[Variable] = []
        for variable in self._sort_variables(variables):
            if variable.name in seen:
                continue
            seen.add(variable.name)
            result.append(variable)
        return result

    def _first_keyword_match(
        self,
        variables: list[Variable],
        keywords: tuple[str, ...],
    ) -> Variable | None:
        matches = [
            variable for variable in variables if self._name_has_keyword(variable.name, keywords)
        ]
        if not matches:
            return None
        return self._sort_variables(matches)[0]

    def _name_has_keyword(self, name: str, keywords: tuple[str, ...]) -> bool:
        lowered = name.lower()
        return any(keyword in lowered for keyword in keywords)

    def _question_terms(self, research_question: str) -> tuple[str, ...]:
        lowered = research_question.lower()
        terms = re.findall(r"[a-z0-9_]+", lowered)
        aliases: list[str] = []
        if (
            "中線" in research_question
            or "導管" in research_question
            or "central line" in lowered
            or "arterial" in lowered
            or "catheter" in lowered
        ):
            aliases.extend(["success", "time", "complication", "rate", "trial", "attempt"])
        if "超音波" in research_question or "ultrasound" in lowered or "guided" in lowered:
            aliases.extend(["ultrasound", "guided", "method", "group"])
        if "成功" in research_question:
            aliases.append("success")
        if "時間" in research_question or "花費" in research_question:
            aliases.extend(["time", "duration", "sec"])
        if "併發" in research_question or "complication" in lowered:
            aliases.append("complication")
        return tuple(dict.fromkeys([*terms, *aliases]))

    def _question_score(self, name: str, question_terms: tuple[str, ...]) -> int:
        if not question_terms:
            return 0
        normalized = name.lower()
        tokens = set(re.findall(r"[a-z0-9]+", normalized.replace("_", " ")))
        score = 0
        for term in question_terms:
            term = term.lower()
            if term in tokens or term in normalized:
                score += 2
            elif any(token in term or term in token for token in tokens):
                score += 1
        return score

    def _is_sequence_variable(self, variable: Variable) -> bool:
        if variable.variable_type not in {
            VariableType.CONTINUOUS,
            VariableType.ORDINAL,
            VariableType.BIOMARKER,
        }:
            return False
        lowered = variable.name.lower()
        if "id" in lowered and not self._name_has_keyword(lowered, ("trial", "case_order", "attempt")):
            return False
        return True
