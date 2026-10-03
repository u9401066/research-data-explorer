"""Source drift and cleaned-state restart regressions for publication evidence."""

from copy import deepcopy
from dataclasses import replace
import json

import pandas as pd
import pytest

from rde.application.session import DatasetEntry
from rde.domain.models.cleaning import CleaningAction, CleaningActionType, CleaningPlan
from rde.domain.models.dataset import Dataset, DatasetMetadata
from rde.domain.models.project import Project
from rde.infrastructure.adapters.dataframe_lineage import (
    apply_recorded_cleaning,
    bind_source,
    frame_record,
    restore_cleaning,
)
from rde.infrastructure.adapters.pandas_loader import PandasLoader


def setup(tmp_path, excel=False):
    path = tmp_path / ("original.xlsx" if excel else "original.csv")
    data = pd.DataFrame(
        {
            "group": [i % 2 for i in range(24)],
            "score": [float(i) if i not in (3, 8) else None for i in range(24)],
            "label": ["A" if i % 2 else "B" for i in range(24)],
        }
    )
    if excel:
        with pd.ExcelWriter(path) as writer:
            data.to_excel(writer, sheet_name="Reviewed", index=False)
            data.assign(score=100).to_excel(writer, sheet_name="Other", index=False)
    else:
        data.to_csv(path, index=False)
    metadata = DatasetMetadata(
        path,
        "xlsx" if excel else "csv",
        path.stat().st_size,
        sheet_name="Reviewed" if excel else None,
    )
    frame, variables, count, _ = PandasLoader().load(metadata)
    dataset = Dataset(id="source-dataset", metadata=metadata)
    dataset.mark_loaded(variables, count)
    project = Project(
        id="source-project",
        name="Lineage edge QA",
        data_dir=tmp_path,
        output_dir=tmp_path / "project",
        dataset_ids=[dataset.id],
    )
    return project, DatasetEntry(dataset, frame)


def plan(entry, kind, target=None, **params):
    return CleaningPlan(
        entry.dataset.id,
        [
            CleaningAction(
                CleaningActionType(kind),
                target,
                "Reviewed change",
                "Synthetic replay QA",
                params=params,
                approved=True,
            )
        ],
    )


@pytest.mark.parametrize("excel", [False, True])
def test_exact_source_and_sheet_then_sequential_cleaning_survive_restart(tmp_path, excel):
    project, entry = setup(tmp_path, excel)
    original = entry.dataframe.copy()
    first = bind_source(project, entry)
    assert first["status"] == "verified"
    assert (
        project.output_dir / first["source"]["snapshot"]
    ).read_bytes() == entry.dataset.metadata.file_path.read_bytes()
    # The second operation needs the first one's result; reordering fails.
    entry.dataframe, _ = apply_recorded_cleaning(project, entry, plan(entry, "drop_rows", "score"))
    entry.dataframe, _ = apply_recorded_cleaning(
        project, entry, plan(entry, "rename_column", "score", new_name="reviewed_score")
    )
    entry.dataframe, _ = apply_recorded_cleaning(
        project, entry, plan(entry, "fill_constant", "reviewed_score", value=999)
    )
    binding = bind_source(project, entry)
    assert len(binding["cleaning"]) == 3
    assert binding["input_source_indices"] == [i for i in range(24) if i not in (3, 8)]
    restored, references = restore_cleaning(
        project, entry.dataset.id, entry.dataset.metadata, original
    )
    pd.testing.assert_frame_equal(restored, entry.dataframe)
    assert references == binding["cleaning"]
    # A clean no-op still has an explicit receipt; original source bytes remain.
    assert first["source"] == binding["source"]
    assert binding["parsed_frame"] == first["parsed_frame"]


@pytest.mark.parametrize(
    "change", ["values", "row_order", "column_order", "index", "dtype", "source"]
)
def test_untracked_changes_are_not_claimed_as_original_source(tmp_path, change):
    project, entry = setup(tmp_path)
    bind_source(project, entry)
    if change == "values":
        entry.dataframe.loc[0, "score"] = 900
    if change == "row_order":
        entry.dataframe = entry.dataframe.iloc[::-1]
    if change == "column_order":
        entry.dataframe = entry.dataframe.iloc[:, ::-1]
    if change == "index":
        entry.dataframe.index = range(50, 74)
    if change == "dtype":
        entry.dataframe["group"] = entry.dataframe["group"].astype(float)
    if change == "source":
        entry.dataset.metadata.file_path.write_text("group,score,label\n0,900,A\n", encoding="utf8")
    with pytest.raises(ValueError, match="differs"):
        bind_source(project, entry)


def test_modified_cleaning_receipt_and_duplicate_ledger_are_rejected(tmp_path):
    project, entry = setup(tmp_path)
    entry.dataframe, _ = apply_recorded_cleaning(
        project, entry, plan(entry, "fill_median", "score")
    )
    binding = bind_source(project, entry)
    ref = binding["cleaning"][0]
    path = project.output_dir / ref["path"]
    before = path.read_bytes()
    record = json.loads(before)
    record["operations"][0]["action_type"] = "fill_mean"
    path.write_text(json.dumps(record), encoding="utf8")
    with pytest.raises(ValueError, match="evidence has changed"):
        bind_source(project, entry)
    path.write_bytes(before)
    ledger = path.parent / "cleaning.jsonl"
    with ledger.open("a") as file:
        file.write(json.dumps(ref) + "\n")
    with pytest.raises(ValueError, match="preceding frame"):
        bind_source(project, entry)


def test_cleaning_cannot_be_replayed_against_another_sheet(tmp_path):
    project, entry = setup(tmp_path, True)
    entry.dataframe, _ = apply_recorded_cleaning(
        project, entry, plan(entry, "fill_median", "score")
    )
    other = replace(entry.dataset.metadata, sheet_name="Other")
    frame, _, _, _ = PandasLoader().load(other)
    with pytest.raises(ValueError, match="source, sheet"):
        restore_cleaning(project, entry.dataset.id, other, frame)


def test_failed_source_check_does_not_mark_pending_cleaning_applied(tmp_path):
    project, entry = setup(tmp_path)
    pending = plan(entry, "drop_rows", "score")
    copy = deepcopy(pending)
    entry.dataframe.loc[0, "score"] = 900
    with pytest.raises(ValueError):
        apply_recorded_cleaning(project, entry, copy)
    assert not pending.actions[0].applied
    assert not list(project.artifacts_dir.rglob("cleaning.jsonl"))


def test_category_order_is_part_of_frame_identity():
    first = pd.DataFrame({"a": pd.Categorical(["a", "b"], categories=["a", "b"], ordered=True)})
    second = first.copy()
    second["a"] = second["a"].cat.reorder_categories(["b", "a"])
    assert frame_record(first) != frame_record(second)


def test_historical_binding_survives_later_cleaning_and_missing_original_without_replay(
    tmp_path, monkeypatch
):
    from rde.infrastructure.adapters.dataframe_lineage import verify_source_binding

    project, entry = setup(tmp_path)
    entry.dataframe, _ = apply_recorded_cleaning(
        project, entry, plan(entry, "fill_median", "score")
    )
    historical = bind_source(project, entry)
    entry.dataframe, _ = apply_recorded_cleaning(
        project, entry, plan(entry, "drop_columns", "label")
    )
    current = bind_source(project, entry)
    assert historical["cleaning"] != current["cleaning"]
    entry.dataset.metadata.file_path.unlink()
    monkeypatch.setattr(
        PandasLoader,
        "load",
        lambda *a: pytest.fail("Publication verification must not reload the table"),
    )
    verify_source_binding(historical, project.output_dir)
    verify_source_binding(current, project.output_dir)
    saved = project.output_dir / historical["source"]["snapshot"]
    saved.write_bytes(b"modified")
    with pytest.raises(ValueError, match="retained original"):
        verify_source_binding(historical, project.output_dir)


def test_actual_project_rehydration_restores_cleaned_rows_and_renamed_columns(tmp_path):
    from rde.application.pipeline import PipelinePhase
    from rde.infrastructure.persistence.artifact_store import ArtifactStore
    from rde.interface.mcp.tools._shared.project_context import _rehydrate_dataset_from_project

    project, entry = setup(tmp_path)
    store = ArtifactStore(project.artifacts_dir)
    store.save(
        PipelinePhase.DATA_INTAKE,
        "intake_report.json",
        {
            "loaded_file": entry.dataset.metadata.file_path.name,
            "directory": str(tmp_path),
            "dataset_id": entry.dataset.id,
        },
    )
    entry.dataframe, _ = apply_recorded_cleaning(project, entry, plan(entry, "drop_rows", "score"))
    entry.dataframe, _ = apply_recorded_cleaning(
        project, entry, plan(entry, "rename_column", "score", new_name="reviewed_score")
    )
    restored = _rehydrate_dataset_from_project(project, entry.dataset.id)
    pd.testing.assert_frame_equal(restored.dataframe, entry.dataframe)
    assert restored.dataset.row_count == 22
    assert [v.name for v in restored.dataset.variables] == list(entry.dataframe.columns)
    assert restored.dataset.tags["restored_cleaning"] == bind_source(project, entry)["cleaning"]


def test_interrupted_snapshot_publish_leaves_no_partial_source(tmp_path, monkeypatch):
    import rde.infrastructure.adapters.dataframe_lineage as lineage

    project, entry = setup(tmp_path)

    def interrupted(*args):
        raise OSError("simulated interruption before immutable source publication")

    monkeypatch.setattr(lineage.os, "link", interrupted)
    with pytest.raises(OSError, match="interruption"):
        bind_source(project, entry)
    assert not list(project.artifacts_dir.rglob("*.csv"))
    assert not list(project.artifacts_dir.rglob(".pending-*"))


def test_nonstring_or_duplicate_column_labels_cannot_alias_source_names(tmp_path):
    project, entry = setup(tmp_path)
    entry.dataframe.columns = ["group", "score", "score"]
    with pytest.raises(ValueError, match="unique string"):
        bind_source(project, entry)
    entry.dataframe.columns = ["group", "score", 123]
    with pytest.raises(ValueError, match="unique string"):
        bind_source(project, entry)
