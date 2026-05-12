"""Shared report asset resolution contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rde.application.pipeline import PipelinePhase


def resolve_visualization_manifest_entries(project: Any, store: Any) -> list[dict[str, Any]]:
    """Return project-scoped visualization manifest entries.

    Keep one output entry per manifest row. Different analyses may reuse the
    same image file while still needing separate report evidence/captions.
    """

    manifest = store.load(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json") or []
    if not isinstance(manifest, list):
        return []

    entries: list[dict[str, Any]] = []
    seen_paths: dict[str, int] = {}
    for raw in manifest:
        if not isinstance(raw, dict):
            continue
        figure_path = _project_figure_path(project, raw.get("output_path"))
        if figure_path is None:
            continue
        try:
            path_key = figure_path.resolve().as_posix()
        except OSError:
            path_key = figure_path.as_posix()
        summary = str(raw.get("stats_summary") or raw.get("summary") or "").strip()
        category = str(raw.get("category") or "").strip()
        plot_type = str(raw.get("plot_type") or "").strip()
        duplicate_of = seen_paths.get(path_key)
        entries.append(
            {
                **raw,
                "name": figure_path.stem,
                "output_path": str(figure_path),
                "relative_path": _relative_to_output(project, figure_path),
                "summary": summary,
                "category": category,
                "plot_type": plot_type,
                "exists": figure_path.exists(),
                "duplicate_of": duplicate_of,
            }
        )
        if path_key not in seen_paths:
            seen_paths[path_key] = len(entries) - 1
    return entries


def project_figure_path(project: Any, path_value: object) -> Path | None:
    return _project_figure_path(project, path_value)


def figure_manifest_output_path(project: Any, path_value: object) -> str | None:
    path = _project_figure_path(project, path_value)
    if path is None:
        return None
    return _relative_to_output(project, path)


def _project_figure_path(project: Any, path_value: object) -> Path | None:
    if not path_value:
        return None
    figures_dir = (project.output_dir / "figures").resolve()
    candidate = Path(str(path_value))
    if not candidate.is_absolute():
        if candidate.parts and candidate.parts[0] == "figures":
            candidate = project.output_dir / candidate
        else:
            candidate = figures_dir / candidate.name
    try:
        resolved = candidate.resolve()
        resolved.relative_to(figures_dir)
    except (OSError, ValueError):
        return None
    return resolved


def _relative_to_output(project: Any, path: Path) -> str:
    try:
        return path.relative_to(project.output_dir.resolve()).as_posix()
    except ValueError:
        return path.name
