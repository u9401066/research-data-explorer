"""Ports — Abstract interfaces (Dependency Inversion).

These define WHAT the domain needs, not HOW it's provided.
Infrastructure layer provides concrete implementations (Adapters).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from rde.domain.models.dataset import Dataset, DatasetMetadata
from rde.domain.models.profile import DataProfile
from rde.domain.models.variable import Variable


class DataLoaderPort(ABC):
    """Port for loading data from files."""

    @abstractmethod
    def load(self, metadata: DatasetMetadata) -> tuple[Any, list[Variable], int]:
        """Load data and return (raw_dataframe, variables, row_count)."""
        ...

    @abstractmethod
    def scan_directory(self, directory: Path) -> list[DatasetMetadata]:
        """Scan a directory and return metadata for loadable files."""
        ...


class ProfilerPort(ABC):
    """Port for dataset profiling."""

    @abstractmethod
    def profile(self, data: Any, dataset_id: str) -> DataProfile:
        """Generate a DataProfile from raw data."""
        ...


class StatisticalEnginePort(ABC):
    """Port for running statistical tests."""

    @abstractmethod
    def run_test(
        self,
        data: Any,
        test_name: str,
        variables: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a specific statistical test and return raw results."""
        ...

    @abstractmethod
    def generate_table_one(
        self,
        data: Any,
        group_var: str,
        variables: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a Table 1 (baseline characteristics)."""
        ...


class VisualizationPort(ABC):
    """Port for creating visualizations."""

    @abstractmethod
    def create_plot(
        self,
        data: Any,
        plot_type: str,
        variables: list[str],
        output_path: Path,
        **kwargs: Any,
    ) -> str:
        """Create a plot and return the output file path."""
        ...


class ReportRendererPort(ABC):
    """Port for rendering reports to different formats."""

    @abstractmethod
    def render_markdown(self, report: Any) -> str:
        """Render report as Markdown."""
        ...

    @abstractmethod
    def render_html(self, report: Any) -> str:
        """Render report as HTML."""
        ...


class ProjectRepositoryPort(ABC):
    """Port for persisting projects."""

    @abstractmethod
    def save(self, project: Any) -> None:
        ...

    @abstractmethod
    def load(self, project_id: str) -> Any:
        ...

    @abstractmethod
    def list_all(self) -> list[Any]:
        ...


class AutomlGatewayPort(ABC):
    """Port for communicating with automl-stat-mcp services (Anti-Corruption Layer).

    Translates between RDE domain concepts and the two REST services:
    - stats-service (port 8003): statistical analysis, propensity, survival, ROC, etc.
    - automl-service (port 8001): AutoML training jobs
    """

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the stats service is reachable."""
        ...

    @abstractmethod
    def direct_analyze(
        self, csv_content: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run direct statistical analysis (stats-service /direct/analyze)."""
        ...

    @abstractmethod
    def run_propensity(
        self, csv_content: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run propensity score analysis (stats-service /propensity/*)."""
        ...

    @abstractmethod
    def run_survival(
        self, csv_content: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run survival analysis (stats-service /survival/*)."""
        ...

    @abstractmethod
    def run_roc(
        self, csv_content: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run ROC/AUC analysis (stats-service /roc/*)."""
        ...

    @abstractmethod
    def run_power(
        self, csv_content: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run power analysis (stats-service /power/*)."""
        ...

    @abstractmethod
    def submit_automl(
        self, csv_content: str, config: dict[str, Any],
    ) -> str:
        """Submit AutoML training job (automl-service). Returns job_id."""
        ...

    @abstractmethod
    def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Get job status (either service)."""
        ...


class DocumentExporterPort(ABC):
    """Port for exporting reports to document formats (docx, pdf).

    Mirrors medpaper's template-based export pattern:
    EDAReport → structured document with embedded figures & tables.
    """

    @abstractmethod
    def export_docx(
        self, report: Any, output_path: Path, *, figures_dir: Path | None = None,
    ) -> Path:
        """Export report as Word docx with embedded figures and tables."""
        ...

    @abstractmethod
    def export_pdf(
        self, report: Any, output_path: Path, *, figures_dir: Path | None = None,
    ) -> Path:
        """Export report as PDF. May require optional dependencies."""
        ...


class ArtifactStorePort(ABC):
    """Port for storing and retrieving pipeline phase artifacts."""

    @abstractmethod
    def save_artifact(
        self, project_id: str, phase: str, filename: str, content: str | bytes
    ) -> Path:
        """Save an artifact for a specific phase. Returns the saved path."""
        ...

    @abstractmethod
    def load_artifact(self, project_id: str, phase: str, filename: str) -> str | bytes:
        """Load a previously saved artifact."""
        ...

    @abstractmethod
    def list_artifacts(self, project_id: str, phase: str) -> list[str]:
        """List all artifact filenames for a phase."""
        ...

    @abstractmethod
    def phase_artifacts_exist(
        self, project_id: str, phase: str, required: list[str]
    ) -> tuple[bool, list[str]]:
        """Check if required artifacts exist. Returns (all_present, missing_list)."""
        ...
