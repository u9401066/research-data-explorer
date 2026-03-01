"""FileSystemProjectRepository — Adapter implementing ProjectRepositoryPort.

Persists projects as JSON files on the local file system.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rde.domain.ports import ProjectRepositoryPort


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

    def list_all(self) -> list[Any]:
        """List all projects."""
        results = []
        for path in self._base_dir.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            results.append(data)
        return results

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
