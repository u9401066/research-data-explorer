"""Registry helpers for branch-derived variables."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rde.application.pipeline import PipelinePhase


DERIVED_VARIABLE_REGISTRY = "derived_variable_registry.json"


def upsert_derived_variable_registry(
    store: Any,
    derived_variables: list[dict[str, Any]],
    *,
    branch_id: str | None = None,
    experiment_id: str | None = None,
    contract: dict[str, Any] | None = None,
    source: str = "autoresearch",
) -> tuple[list[dict[str, Any]], str | None]:
    """Persist branch-derived variables as a first-class Phase 8 artifact."""

    if not derived_variables:
        return [], None

    registry = store.load(PipelinePhase.EXECUTE_EXPLORATION, DERIVED_VARIABLE_REGISTRY) or {}
    if not isinstance(registry, dict):
        registry = {}
    entries = registry.get("derived_variables")
    if not isinstance(entries, list):
        entries = []

    created_at = datetime.now().isoformat()
    normalized_contract = dict(contract or {})
    updated = list(entries)
    written: list[dict[str, Any]] = []
    for raw in derived_variables:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        source_variable = str(raw.get("source") or raw.get("source_variable") or "").strip()
        operation = str(raw.get("operation") or raw.get("type") or "").strip()
        if not name or not source_variable:
            continue
        entry = dict(raw)
        entry.update(
            {
                "name": name,
                "source": source_variable,
                "operation": operation,
                "branch_id": branch_id,
                "experiment_id": experiment_id,
                "origin": source,
                "analysis_type": normalized_contract.get("analysis_type"),
                "created_at": created_at,
            }
        )
        key = (
            entry["name"],
            entry["source"],
            entry["operation"],
            entry.get("branch_id"),
            entry.get("experiment_id"),
        )
        updated = [
            item
            for item in updated
            if (
                item.get("name"),
                item.get("source"),
                item.get("operation"),
                item.get("branch_id"),
                item.get("experiment_id"),
            )
            != key
        ]
        updated.append(entry)
        written.append(entry)

    if not written:
        return [], None

    payload = {
        "registry_version": 1,
        "updated_at": created_at,
        "derived_variables": updated,
    }
    path = store.save(PipelinePhase.EXECUTE_EXPLORATION, DERIVED_VARIABLE_REGISTRY, payload)
    return written, str(path)
