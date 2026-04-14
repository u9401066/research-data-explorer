"""FileSystemProjectRepository — Adapter implementing ProjectRepositoryPort.

Persists projects as JSON files on the local file system.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
import os
from pathlib import Path
from typing import Any

from rde.domain.models.project import Project, ProjectStatus
from rde.domain.ports import ProjectRepositoryPort


def resolve_projects_base_dir() -> Path:
    """Resolve the persisted project root for the current runtime context."""

    workspace_dir = os.environ.get("RDE_WORKSPACE")
    if workspace_dir:
        return Path(workspace_dir).expanduser().resolve() / "data" / "projects"
    return Path("data/projects")


class FileSystemProjectRepository(ProjectRepositoryPort):
    """Persist projects as JSON files in data/projects/."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, project: Any) -> None:
        """Save project state to JSON file."""
        path = self._base_dir / f"{project.id}.json"
        data = asdict(project)
        # Convert non-serializable types
        data = self._make_serializable(data)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def load(self, project_id: str) -> Any:
        """Load project state from JSON file."""
        path = self._base_dir / f"{project_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Project not found: {project_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def load_project(self, project_id: str) -> Project:
        """Load a persisted project as a domain model."""

        data = self.load(project_id)
        return self._deserialize_project(data)

    def list_all(self) -> list[Any]:
        """List all projects."""
        results = []
        for path in self._base_dir.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            results.append(data)
        return results

    def _deserialize_project(self, data: dict[str, Any]) -> Project:
        """Convert persisted JSON data back into a Project model."""

        created_at_raw = data.get("created_at")
        if isinstance(created_at_raw, str):
            created_at = datetime.fromisoformat(created_at_raw)
        else:
            created_at = datetime.now()

        completed_phases = [
            ProjectStatus(phase)
            for phase in data.get("completed_phases", [])
            if isinstance(phase, str)
        ]

        status_raw = data.get("status", ProjectStatus.CREATED.value)
        status = ProjectStatus(status_raw) if isinstance(status_raw, str) else ProjectStatus.CREATED

        return Project(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            data_dir=Path(str(data.get("data_dir", "data/rawdata"))),
            output_dir=Path(str(data["output_dir"])),
            created_at=created_at,
            status=status,
            research_question=str(data.get("research_question", "")),
            dataset_ids=[str(dataset_id) for dataset_id in data.get("dataset_ids", [])],
            report_ids=[str(report_id) for report_id in data.get("report_ids", [])],
            completed_phases=completed_phases,
            plan_locked=bool(data.get("plan_locked", False)),
            config=dict(data.get("config", {})),
        )

    def _make_serializable(self, obj: Any) -> Any:
        """Recursively convert non-serializable objects."""
        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._make_serializable(v) for v in obj]
        if isinstance(obj, Path):
            return str(obj)
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if hasattr(obj, "value"):  # Enum
            return obj.value
        return obj
