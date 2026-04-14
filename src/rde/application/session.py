"""Session Registry — In-memory state for the current MCP server session.

Holds loaded datasets (DataFrame + Dataset entity), projects, profiles,
cleaning plans, analysis results, etc. so MCP tools can reference them by ID.

This is a singleton shared across all tool calls within one server process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from rde.application.decision_logger import DecisionLogger
from rde.application.pipeline import (
    PipelinePhase,
    PipelineState,
    PhaseResult,
    USER_CONFIRMATION_REQUIRED,
)
from rde.domain.models.cleaning import CleaningPlan
from rde.domain.models.dataset import Dataset
from rde.domain.models.profile import DataProfile
from rde.domain.models.project import PIPELINE_ORDER, Project
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

    def register_dataset(self, dataset: Dataset, dataframe: pd.DataFrame) -> None:
        self._datasets[dataset.id] = DatasetEntry(dataset=dataset, dataframe=dataframe)

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
            project = self._load_project_from_repository(pid)
            if project is None:
                raise KeyError(f"Project '{pid}' not found.")
            return project
        return self._projects[pid]

    @property
    def active_project_id(self) -> str | None:
        return self._active_project_id

    # ── Pipeline ─────────────────────────────────────────────────────

    def get_pipeline(self, project_id: str) -> PipelineState:
        if project_id not in self._pipelines:
            self._pipelines[project_id] = PipelineState(project_id=project_id)
        return self._pipelines[project_id]

    def _load_project_from_repository(self, project_id: str) -> Project | None:
        from rde.infrastructure.persistence import (
            FileSystemProjectRepository,
            resolve_projects_base_dir,
        )

        repo = FileSystemProjectRepository(resolve_projects_base_dir())
        try:
            project = repo.load_project(project_id)
        except FileNotFoundError:
            return None

        self.register_project(project)
        self._rehydrate_pipeline(project)
        return project

    def _rehydrate_pipeline(self, project: Project) -> None:
        if project.id in self._pipelines:
            return

        pipeline = PipelineState(project_id=project.id)
        completed_statuses = set(project.completed_phases)

        for project_status in PIPELINE_ORDER:
            if project_status not in completed_statuses:
                continue
            pipeline_phase = PipelinePhase(project_status.value)
            completed_at = (
                project.created_at if isinstance(project.created_at, datetime) else datetime.now()
            )
            pipeline.mark_completed(
                PhaseResult(
                    phase=pipeline_phase,
                    completed_at=completed_at,
                    success=True,
                    artifacts={},
                    user_confirmed=pipeline_phase in USER_CONFIRMATION_REQUIRED,
                )
            )

        if project.plan_locked:
            pipeline.plan_locked = True
            pipeline.plan_locked_at = project.created_at

        self._pipelines[project.id] = pipeline

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
