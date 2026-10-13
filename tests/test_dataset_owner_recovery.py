"""Dataset-only MCP tools recover exact durable identity after an idle restart."""

import asyncio
from dataclasses import replace

import pandas as pd
import pytest

import rde.application.session as session_module
from rde.application.pipeline import PipelinePhase
from rde.domain.models.cleaning import CleaningAction, CleaningActionType, CleaningPlan
from rde.infrastructure.adapters.dataframe_lineage import apply_recorded_cleaning, bind_source
from rde.infrastructure.persistence import FileSystemProjectRepository, resolve_projects_base_dir
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools._shared.project_context import ensure_dataset


def source(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    path = raw / "cohort.csv"
    path.write_text("group,score\nA,10\nB,\nA,30\nB,40\n", encoding="utf-8")

    async def intake():
        server = create_server()
        for tool, args in [
            ("init_project", {"name": "owner-recovery", "data_dir": str(raw)}),
            ("run_intake", {"directory": str(raw)}),
            ("build_schema", {}),
        ]:
            result = await server.call_tool(tool, args)
            assert not result.is_error, result
            assert not result.content[0].text.startswith("❌"), result
        project = session_module.get_session().get_project()
        dataset_id = project.dataset_ids[-1]
        return project, session_module.get_session().get_dataset_entry(dataset_id)

    project, entry = asyncio.run(intake())
    return path, project, entry


def test_unique_owner_recovers_schema_and_preserves_profile_prerequisite(tmp_path):
    _, project, entry = source(tmp_path)
    schema = ArtifactStore(project.artifacts_dir).load(PipelinePhase.SCHEMA_REGISTRY, "schema.json")
    session_module._session = None
    ok, message, recovered = ensure_dataset(entry.dataset.id)
    assert ok, message
    pd.testing.assert_frame_equal(recovered.dataframe, entry.dataframe)
    assert recovered.dataset.tags["schema_registry"] == schema
    assert recovered.dataset.tags["intake_report"]["dataset_id"] == entry.dataset.id
    assert session_module.get_session().active_project_id == project.id
    assert [(v.name, v.variable_type, v.role) for v in recovered.dataset.variables] == [
        (v.name, v.variable_type, v.role) for v in entry.dataset.variables
    ]
    assert recovered.profile is None
    assert recovered is session_module.get_session().get_dataset_entry(entry.dataset.id)

    async def quality():
        server = create_server()
        args = {"dataset_id": entry.dataset.id}
        required = await server.call_tool("assess_quality", args)
        assert "profile_dataset" in required.content[0].text
        # A first profiling call after restart must mutate the registered entry,
        # not a detached recovery copy that loses its profile before quality.
        session_module._session = None
        profiled = await server.call_tool("profile_dataset", args)
        assert not profiled.is_error, profiled
        result = await server.call_tool("assess_quality", args)
        assert not result.is_error, result
        assert "品質分數" in result.content[0].text

    asyncio.run(quality())


def test_dataset_only_recovery_rejects_ambiguous_owners(tmp_path):
    _, project, entry = source(tmp_path)
    repo = FileSystemProjectRepository(resolve_projects_base_dir())
    repo.save(replace(project, id="second-owner", name="Not an implicit choice"))
    session_module._session = None
    ok, message, recovered = ensure_dataset(entry.dataset.id)
    assert not ok
    assert "多個專案" in message
    assert recovered is None
    assert session_module.get_session().list_datasets() == []


def test_intake_source_drift_is_rejected_even_without_a_cleaning_chain(tmp_path):
    path, _, entry = source(tmp_path)
    path.write_text(path.read_text().replace("A,10", "A,99"), encoding="utf-8")
    session_module._session = None
    with pytest.raises(ValueError, match="source identity has changed"):
        ensure_dataset(entry.dataset.id)
    assert session_module.get_session().list_datasets() == []


def test_dataset_only_recovery_replays_the_exact_cleaning_version(tmp_path):
    _, project, entry = source(tmp_path)
    for kind, target, params in [
        (CleaningActionType.DROP_ROWS, "score", {}),
        (CleaningActionType.RENAME_COLUMN, "score", {"new_name": "reviewed_score"}),
    ]:
        plan = CleaningPlan(
            entry.dataset.id,
            [CleaningAction(kind, target, "QA", "Saved replay", params=params, approved=True)],
        )
        entry.dataframe, _ = apply_recorded_cleaning(project, entry, plan)
    expected = bind_source(project, entry)
    session_module._session = None
    ok, message, recovered = ensure_dataset(entry.dataset.id)
    assert ok, message
    pd.testing.assert_frame_equal(recovered.dataframe, entry.dataframe)
    assert recovered.dataset.row_count == 3
    actual = bind_source(project, recovered)
    assert actual["source"] == expected["source"]
    assert actual["cleaning"] == expected["cleaning"]
    assert actual["input_frame"] == expected["input_frame"]


def test_recovery_uses_the_verified_owner_when_other_project_metadata_is_active(tmp_path):
    _, project, entry = source(tmp_path)
    repo = FileSystemProjectRepository(resolve_projects_base_dir())
    other = replace(
        project, id="other-project", name="Other", dataset_ids=[], output_dir=tmp_path / "other"
    )
    repo.save(other)
    session_module._session = None
    session = session_module.get_session()
    session.get_project(project.id)
    session.get_project(other.id)
    assert session.active_project_id == other.id

    async def profile():
        server = create_server()
        result = await server.call_tool("profile_dataset", {"dataset_id": entry.dataset.id})
        assert not result.is_error, result
        assert session.active_project_id == project.id
        assert (
            ArtifactStore(project.artifacts_dir).load(
                PipelinePhase.SCHEMA_REGISTRY, "profile_summary.json"
            )
            is not None
        )
        assert (
            ArtifactStore(other.artifacts_dir).load(
                PipelinePhase.SCHEMA_REGISTRY, "profile_summary.json"
            )
            is None
        )
        assert result.structured_content["context"]["project_id"] == project.id
        assert result.structured_content["artifacts"]

    asyncio.run(profile())
