"""Project & dataset context helpers — reusable validation across tools."""

from __future__ import annotations

from typing import Any

from rde.application.session import SessionRegistry, get_session, DatasetEntry
from rde.domain.models.project import Project


def ensure_project_context(
    project_id: str | None = None,
) -> tuple[bool, str, Project | None]:
    """Validate and return the active project.

    Returns:
        (is_valid, message, project_or_none)
    """
    session = get_session()
    try:
        project = session.get_project(project_id)
        return True, f"專案: {project.name} ({project.id})", project
    except KeyError as e:
        available = session.list_datasets()  # proxy — no list_projects on session
        return False, str(e), None


def ensure_dataset(
    dataset_id: str | None = None,
) -> tuple[bool, str, DatasetEntry | None]:
    """Validate and return a dataset entry.

    If dataset_id is None, uses the first loaded dataset.

    Returns:
        (is_valid, message, entry_or_none)
    """
    session = get_session()
    if dataset_id is None:
        ids = session.list_datasets()
        if not ids:
            return False, "尚未載入任何資料集。請先使用 load_dataset()。", None
        dataset_id = ids[0]

    try:
        entry = session.get_dataset_entry(dataset_id)
        return True, f"資料集: {dataset_id}", entry
    except KeyError as e:
        available = session.list_datasets()
        return False, f"資料集 '{dataset_id}' 不存在。可用: {available}", None
