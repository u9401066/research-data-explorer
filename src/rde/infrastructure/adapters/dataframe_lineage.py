"""Bind loaded/cleaned frames to immutable source bytes and replayable operations.

No pickle or arbitrary expression execution. Replaying cleaning uses the same
approved typed operations as the normal executor, and checks every transition.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

import pandas as pd

from rde.application.pipeline import PipelinePhase
from rde.domain.models.cleaning import CleaningAction, CleaningActionType, CleaningPlan
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.prediction.splits import digest
from .cleaning_executor import CleaningExecutor
from .pandas_loader import PandasLoader


PHASE = PipelinePhase.EXECUTE_EXPLORATION


def frame_record(frame):
    """Bind values, row order/index, column order and dtype/category semantics."""
    if not frame.columns.is_unique or any(not isinstance(c, str) for c in frame.columns):
        raise ValueError("Source-bound frames require unique string column names.")
    types = []
    for dtype in frame.dtypes:
        descriptor = {"dtype": str(dtype)}
        if isinstance(dtype, pd.CategoricalDtype):
            descriptor.update(categories=[str(v) for v in dtype.categories], ordered=dtype.ordered)
        types.append(descriptor)
    return {
        "rows": len(frame),
        "columns": [str(c) for c in frame.columns],
        "dtypes": types,
        "index_names": [str(name) if name is not None else None for name in frame.index.names],
        "index_dtype": str(frame.index.dtype),
        "values_and_index_sha256": hashlib.sha256(
            pd.util.hash_pandas_object(frame, index=True).values.tobytes()
        ).hexdigest(),
    }


def _name(dataset_id):
    # Dataset IDs may be native UUIDs or old import IDs; never interpolate paths.
    return f"data_lineage/{hashlib.sha256(dataset_id.encode()).hexdigest()}/cleaning.jsonl"


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _confined(root, reference):
    path = (root / reference).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Data lineage evidence must be a saved file inside this project.")
    return path


def _operations(plan):
    return [
        {
            "action_type": a.action_type.value,
            "target_variable": a.target_variable,
            "description": a.description,
            "rationale": a.rationale,
            "params": a.params,
        }
        for a in plan.approved_actions
        if not a.applied
    ]


def _replay(frame, operations):
    plan = CleaningPlan(dataset_id="lineage-replay")
    for item in operations:
        plan.add_action(
            CleaningAction(
                action_type=CleaningActionType(item["action_type"]),
                target_variable=item["target_variable"],
                description=item["description"],
                rationale=item["rationale"],
                params=item["params"],
                approved=True,
            )
        )
    return CleaningExecutor().execute(frame, plan)


def restore_cleaning(project, dataset_id, metadata, frame):
    """Rehydrate only a fully verified chain; original source drift is not ignored."""
    root = project.output_dir.resolve()
    store = ArtifactStore(project.artifacts_dir)
    entries = store.load(PHASE, _name(dataset_id)) or []
    previous = None
    source_sha = _hash(metadata.file_path) if entries else None
    for entry in entries:
        path = _confined(root, entry["path"])
        if _hash(path) != entry["sha256"]:
            raise ValueError("Saved cleaning evidence has changed.")
        record = json.loads(path.read_text(encoding="utf-8"))
        if (
            record.get("schema") != "data-cleaning-lineage-v1"
            or record.get("dataset_id") != dataset_id
            or record.get("previous") != previous
            or record.get("before") != frame_record(frame)
            or record["source"]["sha256"] != source_sha
            or record["source"].get("sheet") != metadata.sheet_name
            or record["source"].get("encoding") != metadata.encoding
            or record["source"].get("format") != metadata.file_format
            or _hash(_confined(root, record["source"]["snapshot"])) != source_sha
            or record.get("receipt_sha256")
            != digest({k: v for k, v in record.items() if k != "receipt_sha256"})
        ):
            raise ValueError(
                "Cleaning lineage does not match the source, sheet or preceding frame."
            )
        frame, logs = _replay(frame, record["operations"])
        if frame_record(frame) != record["after"] or logs != record["logs"]:
            raise ValueError("Saved cleaning operations no longer reproduce the recorded frame.")
        previous = entry
    return frame, entries


def bind_source(project, entry):
    """Copy source bytes, parse that exact copy, replay cleaning, compare live data."""
    metadata = entry.dataset.metadata
    if metadata is None or not metadata.file_path.is_file():
        return {"status": "unavailable", "reason": "No readable source file is attached."}
    root = project.output_dir.resolve()
    raw = metadata.file_path.read_bytes()
    source_sha = hashlib.sha256(raw).hexdigest()
    if not re.fullmatch(r"[a-z0-9]+", metadata.file_format):
        raise ValueError("Invalid source format for data lineage.")
    folder = (project.artifacts_dir / PHASE.value / "data_lineage" / "sources").resolve()
    if not folder.is_relative_to(root):
        raise ValueError("Data lineage source directory escapes the project.")
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / f"{source_sha}.{metadata.file_format}"
    pending = folder / f".pending-{uuid.uuid4()}"
    try:
        with pending.open("xb") as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(pending, snapshot)
        except FileExistsError:
            pass
    finally:
        pending.unlink(missing_ok=True)
    if snapshot.resolve() != snapshot or snapshot.is_symlink() or _hash(snapshot) != source_sha:
        raise ValueError("Saved original source bytes have changed.")
    parsed, _, _, normalization = PandasLoader().load(replace(metadata, file_path=snapshot))
    parsed_record = frame_record(parsed)
    restored, cleaning = restore_cleaning(project, entry.dataset.id, metadata, parsed)
    if frame_record(restored) != frame_record(entry.dataframe):
        raise ValueError(
            "The live dataframe differs from the original source and its recorded cleaning; untracked edits cannot be used as bound evidence."
        )
    if _hash(metadata.file_path) != source_sha:
        raise ValueError("The original source changed while binding the dataframe.")
    return {
        "schema": "data-source-binding-v1",
        "status": "verified",
        "dataset_id": entry.dataset.id,
        "source": {
            "path": str(metadata.file_path),
            "snapshot": str(snapshot.relative_to(root)),
            "sha256": source_sha,
            "bytes": len(raw),
            "format": metadata.file_format,
            "sheet": metadata.sheet_name,
            "encoding": metadata.encoding,
        },
        "parser": {
            "name": "PandasLoader",
            "pandas": pd.__version__,
            "normalization": normalization.as_dict(),
        },
        "parsed_frame": parsed_record,
        "input_frame": frame_record(entry.dataframe),
        "cleaning": cleaning,
        "row_locator_scope": "Model row positions address the bound input frame; normalized source indices are retained by cleaning operations. Raw file header/normalization locations are described by the parser report.",
        "input_source_indices": entry.dataframe.index.tolist(),
    }


def apply_recorded_cleaning(project, entry, approved_plan):
    """Commit evidence before the caller replaces its live frame or plan."""
    binding = bind_source(project, entry)
    if binding["status"] != "verified":
        raise ValueError("Recorded cleaning requires a readable original source file.")
    operations = _operations(approved_plan)
    # Validate immutable serialization before applying or recording anything.
    digest(operations)
    frame, logs = CleaningExecutor().execute(entry.dataframe, approved_plan)
    if not operations:
        return frame, logs
    record = {
        "schema": "data-cleaning-lineage-v1",
        "dataset_id": entry.dataset.id,
        "source": binding["source"],
        "previous": binding["cleaning"][-1] if binding["cleaning"] else None,
        "before": binding["input_frame"],
        "after": frame_record(frame),
        "operations": operations,
        "logs": logs,
    }
    record["receipt_sha256"] = digest(record)
    store = ArtifactStore(project.artifacts_dir)
    name = str(Path(_name(entry.dataset.id)).parent / f"{uuid.uuid4()}.json")
    path = store.get_path(PHASE, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path = store.save(PHASE, name, record)
    reference = {
        "path": str(path.resolve().relative_to(project.output_dir.resolve())),
        "sha256": _hash(path),
    }
    store.save(PHASE, _name(entry.dataset.id), reference)
    return frame, logs


def verify_source_binding(binding, root):
    """Check historical source/cleaning closure without parsing, cleaning or fitting.

    Initial bind_source compares the actual frame with a replay. Rendering checks
    that exact retained chain; it must not recompute cleaning-derived quantities.
    """
    root = Path(root).resolve()
    if binding.get("schema") != "data-source-binding-v1" or binding.get("status") != "verified":
        raise ValueError("Complete source-to-frame binding is required for publication.")
    source = binding["source"]
    snapshot = _confined(root, source["snapshot"])
    if _hash(snapshot) != source["sha256"] or snapshot.stat().st_size != source["bytes"]:
        raise ValueError("The retained original source differs from its binding.")
    previous, frame, seen = None, binding["parsed_frame"], set()
    for ref in binding["cleaning"]:
        path = _confined(root, ref["path"])
        if path in seen or _hash(path) != ref["sha256"]:
            raise ValueError("The retained cleaning chain is duplicated or modified.")
        seen.add(path)
        record = json.loads(path.read_text(encoding="utf8"))
        if (
            record.get("schema") != "data-cleaning-lineage-v1"
            or record.get("dataset_id") != binding["dataset_id"]
            or any(
                record.get("source", {}).get(k) != source.get(k)
                for k in ("sha256", "bytes", "format", "sheet", "encoding", "snapshot")
            )
            or record.get("previous") != previous
            or record.get("before") != frame
            or record.get("receipt_sha256")
            != digest({k: v for k, v in record.items() if k != "receipt_sha256"})
        ):
            raise ValueError(
                "The retained cleaning chain has inconsistent source or frame identities."
            )
        frame, previous = record["after"], ref
    if frame != binding["input_frame"] or len(binding["input_source_indices"]) != frame["rows"]:
        raise ValueError(
            "The retained source chain does not terminate at the analysis input frame."
        )


def synchronize_variables(variables, frame):
    """Reflect live columns/counts without silently transferring approved roles on rename."""
    from rde.domain.services.variable_classifier import VariableClassifier

    known = {v.name: v for v in variables}
    classifier = VariableClassifier()
    result = []
    for name in frame.columns:
        series = frame[name]
        if name in known:
            variable = replace(known[name], extra=dict(known[name].extra))
        else:
            variable = classifier.classify(
                name=name,
                dtype=str(series.dtype),
                n_unique=int(series.nunique(dropna=True)),
                n_total=len(frame),
                sample_values=series.dropna().head(20).tolist(),
            )
        variable.dtype = str(series.dtype)
        variable.n_unique = int(series.nunique(dropna=True))
        variable.n_missing = int(series.isna().sum())
        variable.extra["total_count"] = len(frame)
        result.append(variable)
    return result
