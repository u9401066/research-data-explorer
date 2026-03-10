"""Session Registry — In-memory state for the current MCP server session.

Holds loaded datasets (DataFrame + Dataset entity), projects, profiles,
cleaning plans, analysis results, etc. so MCP tools can reference them by ID.

This is a singleton shared across all tool calls within one server process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from rde.application.decision_logger import DecisionLogger
from rde.application.pipeline import PipelineState
from rde.domain.models.cleaning import CleaningPlan
from rde.domain.models.dataset import Dataset
from rde.domain.models.profile import DataProfile
from rde.domain.models.project import Project
from rde.domain.models.quality import QualityReport
from rde.domain.models.analysis import AnalysisResult


@dataclass
class DatasetEntry:
    """A loaded dataset and its associated objects."""

    dataset: Dataset
    dataframe: pd.DataFrame
    profile: DataProfile | None = None
    quality_report: QualityReport | None = None
    cleaning_plan: CleaningPlan | None = None
    analysis_results: list[AnalysisResult] = field(default_factory=list)


class SessionRegistry:
    """In-memory registry for the current server session.

    Thread-safe enough for a single-process MCP server.
    """

    def __init__(self) -> None:
        self._datasets: dict[str, DatasetEntry] = {}
        self._projects: dict[str, Project] = {}
        self._pipelines: dict[str, PipelineState] = {}
        self._loggers: dict[str, DecisionLogger] = {}
        self._active_project_id: str | None = None

    # ── Dataset ──────────────────────────────────────────────────────

    def register_dataset(
        self, dataset: Dataset, dataframe: pd.DataFrame
    ) -> None:
        self._datasets[dataset.id] = DatasetEntry(
            dataset=dataset, dataframe=dataframe
        )

    def get_dataset_entry(self, dataset_id: str) -> DatasetEntry:
        if dataset_id not in self._datasets:
            raise KeyError(f"Dataset '{dataset_id}' not found in session.")
        return self._datasets[dataset_id]

    def list_datasets(self) -> list[str]:
        return list(self._datasets.keys())

    # ── Project ──────────────────────────────────────────────────────

    def register_project(self, project: Project) -> None:
        self._projects[project.id] = project
        self._active_project_id = project.id

    def get_project(self, project_id: str | None = None) -> Project:
        pid = project_id or self._active_project_id
        if pid is None:
            raise KeyError("No active project. Create one with create_project().")
        if pid not in self._projects:
            raise KeyError(f"Project '{pid}' not found.")
        return self._projects[pid]

    @property
    def active_project_id(self) -> str | None:
        return self._active_project_id

    # ── Pipeline ─────────────────────────────────────────────────────

    def get_pipeline(self, project_id: str) -> PipelineState:
        if project_id not in self._pipelines:
            self._pipelines[project_id] = PipelineState(project_id=project_id)
        return self._pipelines[project_id]

    # ── Decision Logger ──────────────────────────────────────────────

    def get_logger(self, project_id: str) -> DecisionLogger:
        if project_id not in self._loggers:
            project = self.get_project(project_id)
            logger = DecisionLogger(project.artifacts_dir)
            logger.snapshot_line_counts()
            self._loggers[project_id] = logger
        return self._loggers[project_id]


# ── Module-level singleton ───────────────────────────────────────────

_session: SessionRegistry | None = None


def get_session() -> SessionRegistry:
    """Get or create the global session registry singleton."""
    global _session
    if _session is None:
        _session = SessionRegistry()
    return _session
