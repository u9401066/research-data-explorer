"""Promotion evaluator for Phase 8 exploration branches."""

from __future__ import annotations

from typing import Any

from rde.domain.models.exploration_branch import (
    BranchStatus,
    ExperimentEvent,
    ExplorationBranch,
)


class ExplorationBranchEvaluator:
    """Score exploratory evidence before it can amend a locked plan."""

    PROMOTION_THRESHOLD = 70.0
    STRUCTURED_METRIC_NAMES = {
        "p_value",
        "p_values",
        "effect_size",
        "effect_sizes",
        "odds_ratio",
        "odds_ratios",
        "hazard_ratio",
        "hazard_ratios",
        "auc",
        "roc_auc",
        "c_index",
        "standardized_mean_difference",
        "mean_difference",
        "coefficients",
        "confidence_interval",
        "ci_low",
        "ci_high",
        "power",
        "common_support",
        "balance_diagnostics",
    }
    SAMPLE_SIZE_METRIC_NAMES = {
        "n",
        "nobs",
        "sample_size",
        "n_total",
        "count",
        "n_complete",
        "n_positive",
        "n_negative",
        "event_count",
        "events",
    }
    EFFECT_METRIC_NAMES = {
        "effect_size",
        "effect_sizes",
        "odds_ratio",
        "odds_ratios",
        "hazard_ratio",
        "hazard_ratios",
        "auc",
        "roc_auc",
        "c_index",
        "standardized_mean_difference",
        "mean_difference",
        "coefficients",
        "power",
        "common_support",
    }
    UNCERTAINTY_OR_DIAGNOSTIC_METRIC_NAMES = {
        "p_value",
        "p_values",
        "confidence_interval",
        "ci_low",
        "ci_high",
        "standard_error",
        "standard_errors",
        "balance_diagnostics",
        "common_support",
    }

    def evaluate(
        self,
        branch: ExplorationBranch | dict[str, Any],
        experiments: list[ExperimentEvent | dict[str, Any]],
    ) -> dict[str, Any]:
        branch_model = (
            branch if isinstance(branch, ExplorationBranch) else ExplorationBranch.from_dict(branch)
        )
        experiment_models = [
            exp if isinstance(exp, ExperimentEvent) else ExperimentEvent.from_dict(exp)
            for exp in experiments
        ]

        component_scores = self._component_scores(branch_model, experiment_models)
        overall_score = round(
            component_scores["evidence"] * 0.45
            + component_scores["stability"] * 0.25
            + component_scores["plan_alignment"] * 0.20
            + component_scores["execution_quality"] * 0.10,
            2,
        )
        blockers = self._blockers(branch_model, experiment_models, overall_score)
        can_promote = not blockers
        recommendation = "promote_candidate" if can_promote else "discard"

        return {
            "branch_id": branch_model.branch_id,
            "overall_score": overall_score,
            "component_scores": component_scores,
            "recommendation": recommendation,
            "promotion_gate": {
                "can_promote": can_promote,
                "threshold": self.PROMOTION_THRESHOLD,
                "blockers": blockers,
            },
        }

    def _component_scores(
        self,
        branch: ExplorationBranch,
        experiments: list[ExperimentEvent],
    ) -> dict[str, float]:
        completed = [exp for exp in experiments if exp.status == "completed"]
        if not completed:
            return {
                "evidence": 0.0,
                "stability": 0.0,
                "plan_alignment": 0.0,
                "execution_quality": 0.0,
            }

        evidence = self._average_metric(completed, ("evidence_score", "effect_score"))
        if evidence == 0.0:
            evidence = self._score_from_p_values_and_effects(completed)

        stability = self._average_metric(
            completed,
            ("stability_score", "robustness_score", "reproducibility_score"),
        )
        alignment = self._average_metric(completed, ("alignment_score", "plan_alignment_score"))
        if alignment == 0.0:
            alignment = 80.0 if branch.parent_plan_item else 65.0

        sample_support = self._average_metric(completed, ("sample_support", "sample_score"))
        execution_quality = max(0.0, min(100.0, 55.0 + (len(completed) * 15.0)))
        if sample_support:
            execution_quality = (execution_quality + sample_support) / 2.0

        return {
            "evidence": round(self._clamp_score(evidence), 2),
            "stability": round(self._clamp_score(stability), 2),
            "plan_alignment": round(self._clamp_score(alignment), 2),
            "execution_quality": round(self._clamp_score(execution_quality), 2),
        }

    def _blockers(
        self,
        branch: ExplorationBranch,
        experiments: list[ExperimentEvent],
        overall_score: float,
    ) -> list[str]:
        blockers: list[str] = []
        if branch.status == BranchStatus.CRASHED:
            blockers.append("branch_crashed")
        if branch.status == BranchStatus.DISCARDED:
            blockers.append("branch_discarded")
        if branch.status == BranchStatus.PROMOTED:
            blockers.append("branch_already_promoted")
        if any(exp.status in {"crashed", "failed", "error"} for exp in experiments):
            blockers.append("experiment_crashed")
        completed = [exp for exp in experiments if exp.status == "completed"]
        if not completed:
            blockers.append("no_completed_experiments")
        elif not any(exp.artifacts for exp in completed):
            blockers.append("missing_evidence_artifact")
        elif not any(self._has_structured_statistical_metric(exp) for exp in completed):
            blockers.append("missing_structured_statistical_metric")
        elif not any(self._has_minimum_evidence_bundle(exp) for exp in completed):
            blockers.append("incomplete_statistical_evidence_bundle")
        if overall_score < self.PROMOTION_THRESHOLD:
            blockers.append("score_below_70")
        return blockers

    def _has_structured_statistical_metric(self, experiment: ExperimentEvent) -> bool:
        return any(name in experiment.metrics for name in self.STRUCTURED_METRIC_NAMES)

    def _has_minimum_evidence_bundle(self, experiment: ExperimentEvent) -> bool:
        metrics = experiment.metrics
        has_sample_size = any(name in metrics for name in self.SAMPLE_SIZE_METRIC_NAMES)
        has_effect = any(name in metrics for name in self.EFFECT_METRIC_NAMES)
        has_uncertainty_or_diagnostic = any(
            name in metrics for name in self.UNCERTAINTY_OR_DIAGNOSTIC_METRIC_NAMES
        )
        return has_sample_size and has_effect and has_uncertainty_or_diagnostic

    def _average_metric(
        self,
        experiments: list[ExperimentEvent],
        metric_names: tuple[str, ...],
    ) -> float:
        values: list[float] = []
        for exp in experiments:
            for name in metric_names:
                if name not in exp.metrics:
                    continue
                value = self._to_float(exp.metrics.get(name))
                if value is not None:
                    values.append(value)
                    break
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _score_from_p_values_and_effects(self, experiments: list[ExperimentEvent]) -> float:
        scores: list[float] = []
        for exp in experiments:
            p_value = self._to_float(exp.metrics.get("p_value"))
            effect_size = self._to_float(exp.metrics.get("effect_size"))
            score = 0.0
            if p_value is not None:
                score += 50.0 if p_value < 0.05 else max(0.0, 45.0 - (p_value * 100.0))
            if effect_size is not None:
                score += min(50.0, abs(effect_size) * 100.0)
            if score:
                scores.append(min(100.0, score))
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def _to_float(self, value: Any) -> float | None:
        try:
            if value is None or isinstance(value, bool):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _clamp_score(self, value: float) -> float:
        return max(0.0, min(100.0, value))
