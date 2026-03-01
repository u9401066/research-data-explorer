"""ArtifactStore — File system storage for pipeline phase artifacts.

Each phase produces artifacts (JSON, JSONL, Markdown) stored under
  project.artifacts_dir / phase.value / filename

Enforces H-008 (Artifact Gate) and H-010 (append-only logs).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rde.application.pipeline import PipelinePhase, REQUIRED_ARTIFACTS


class ArtifactStore:
    """Store and retrieve pipeline phase artifacts on the file system."""

    def __init__(self, artifacts_dir: Path) -> None:
        self._base = artifacts_dir
        self._base.mkdir(parents=True, exist_ok=True)

    # ── write ─────────────────────────────────────────────────────────

    def save(
        self,
        phase: PipelinePhase,
        filename: str,
        data: Any,
    ) -> Path:
        """Save an artifact for a phase. Returns the written path."""
        phase_dir = self._base / phase.value
        phase_dir.mkdir(parents=True, exist_ok=True)
        path = phase_dir / filename

        if filename.endswith(".json"):
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        elif filename.endswith(".md"):
            path.write_text(str(data), encoding="utf-8")
        elif filename.endswith(".yaml") or filename.endswith(".yml"):
            try:
                import yaml
                path.write_text(
                    yaml.dump(data, allow_unicode=True, default_flow_style=False),
                    encoding="utf-8",
                )
            except ImportError:
                # Fallback to JSON
                path = path.with_suffix(".json")
                path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )
        elif filename.endswith(".jsonl"):
            # JSONL is append-only (H-010)
            with open(path, "a", encoding="utf-8") as f:
                if isinstance(data, list):
                    for entry in data:
                        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
                else:
                    f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
        else:
            path.write_text(str(data), encoding="utf-8")

        return path

    # ── read ──────────────────────────────────────────────────────────

    def load(self, phase: PipelinePhase, filename: str) -> Any:
        """Load an artifact. Returns None if not found."""
        path = self._base / phase.value / filename
        if not path.exists():
            return None

        if filename.endswith(".json"):
            return json.loads(path.read_text(encoding="utf-8"))
        elif filename.endswith(".jsonl"):
            entries = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
            return entries
        elif filename.endswith(".yaml") or filename.endswith(".yml"):
            try:
                import yaml
                return yaml.safe_load(path.read_text(encoding="utf-8"))
            except ImportError:
                return path.read_text(encoding="utf-8")
        else:
            return path.read_text(encoding="utf-8")

    def exists(self, phase: PipelinePhase, filename: str) -> bool:
        return (self._base / phase.value / filename).exists()

    def get_path(self, phase: PipelinePhase, filename: str) -> Path:
        return self._base / phase.value / filename

    # ── artifact gate (H-008) ─────────────────────────────────────────

    def check_artifacts(self, phase: PipelinePhase) -> tuple[bool, list[str]]:
        """Check if all required artifacts for a phase exist.

        Returns (all_present, list_of_missing).
        """
        required = REQUIRED_ARTIFACTS.get(phase, [])
        missing = [f for f in required if not self.exists(phase, f)]
        return len(missing) == 0, missing

    def list_phase_artifacts(self, phase: PipelinePhase) -> list[str]:
        """List all artifact files for a phase."""
        phase_dir = self._base / phase.value
        if not phase_dir.exists():
            return []
        return [f.name for f in phase_dir.iterdir() if f.is_file()]

    def list_all_artifacts(self) -> dict[str, list[str]]:
        """List artifacts for all phases."""
        result = {}
        for phase in PipelinePhase:
            files = self.list_phase_artifacts(phase)
            if files:
                result[phase.value] = files
        return result
