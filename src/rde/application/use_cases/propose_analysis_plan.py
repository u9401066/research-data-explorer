"""ProposeAnalysisPlanUseCase — greedy autonomous EDA plan ideation.

Bridges the planning interface layer to the pure-domain autonomous EDA planner.
"""

from __future__ import annotations

from rde.domain.models.dataset import Dataset
from rde.domain.services.autonomous_eda_planner import (
    AutonomousEDAPlanner,
    GreedyPlanProposal,
)


class ProposeAnalysisPlanUseCase:
    """Generate a ranked, plan-ready blueprint before Phase 4 is locked."""

    def __init__(self, planner: AutonomousEDAPlanner | None = None) -> None:
        self._planner = planner or AutonomousEDAPlanner()

    def execute(
        self,
        dataset: Dataset,
        research_question: str = "",
        *,
        max_analyses: int = 8,
        enrich_rounds: int = 1,
        include_advanced: bool = True,
        include_visualizations: bool = True,
    ) -> GreedyPlanProposal:
        return self._planner.propose(
            dataset,
            research_question=research_question,
            max_analyses=max_analyses,
            enrich_rounds=enrich_rounds,
            include_advanced=include_advanced,
            include_visualizations=include_visualizations,
        )
