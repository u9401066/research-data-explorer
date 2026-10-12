"""A durable research run cannot silently advance to a newer cleaning chain."""

import asyncio
import json

import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.infrastructure.adapters.dataframe_lineage import apply_recorded_cleaning
from rde.interface.mcp.server import create_server
from test_dataframe_lineage import setup, plan as cleaning_plan
from test_exploration_branch_loop import _make_phase8_ready_project


def fixture(tmp_path):
    project, store = _make_phase8_ready_project(tmp_path)
    _, entry = setup(tmp_path)
    get_session().register_dataset(entry.dataset, entry.dataframe)
    project.dataset_ids = [entry.dataset.id]
    # A non-executable idea is sufficient: drift must block before leasing work,
    # not merely appear in an analysis receipt after computation.
    arguments = {
        "project_id": project.id,
        "include_builtin_suggestions": False,
        "agent_proposals": [{"hypothesis": "Review missingness", "reason": "Synthetic QA"}],
    }
    return project, store, get_session().get_dataset_entry(entry.dataset.id), arguments


@pytest.mark.parametrize("change", ["cleaning", "noop_receipt", "frame", "source", "dataset"])
def test_changed_data_blocks_before_leasing_or_creating_experiment(tmp_path, change):
    project, store, entry, arguments = fixture(tmp_path)

    async def run():
        server = create_server()
        started = await server.call_tool("start_autoresearch_run", arguments)
        assert not started.is_error
        if change in {"cleaning", "noop_receipt"}:
            entry.dataframe, _ = apply_recorded_cleaning(
                project,
                entry,
                cleaning_plan(entry, "fill_median", "score" if change == "cleaning" else "group"),
            )
        elif change == "frame":
            entry.dataframe.loc[0, "score"] = 900
        elif change == "source":
            entry.dataset.metadata.file_path.write_text("group,score\n0,1\n")
        else:
            from dataclasses import replace

            other = replace(entry.dataset, id="another-dataset")
            get_session().register_dataset(other, entry.dataframe.copy())
            project.dataset_ids.append(other.id)
        return await server.call_tool("run_autoresearch_next_task", {"project_id": project.id})

    result = asyncio.run(run())
    assert result.is_error
    assert "data baseline" in result.content[0].text.lower()
    assert not store.exists(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl")
    updates = store.load(PipelinePhase.EXECUTE_EXPLORATION, "work_events.jsonl") or []
    assert not any(item.get("event_type") == "work_item_started" for item in updates)


def test_resume_rechecks_data_and_retains_stopped_run(tmp_path):
    project, store, entry, arguments = fixture(tmp_path)

    async def run():
        server = create_server()
        assert not (await server.call_tool("start_autoresearch_run", arguments)).is_error
        assert not (
            await server.call_tool("stop_autoresearch_run", {"project_id": project.id})
        ).is_error
        entry.dataframe, _ = apply_recorded_cleaning(
            project, entry, cleaning_plan(entry, "fill_median", "score")
        )
        result = await server.call_tool("resume_autoresearch_run", {"project_id": project.id})
        assert result.is_error
        assert "data baseline" in result.content[0].text.lower()

    asyncio.run(run())
    assert store.load(PipelinePhase.EXECUTE_EXPLORATION, "budget_state.json")["status"] == "stopped"


def test_data_version_survives_reload_and_identifies_same_values_with_new_receipt(tmp_path):
    from rde.infrastructure.adapters.dataframe_lineage import dataset_version, restore_cleaning
    from rde.infrastructure.adapters.pandas_loader import PandasLoader

    project, _, entry, _ = fixture(tmp_path)
    initial = dataset_version(project, entry)
    entry.dataframe, _ = apply_recorded_cleaning(
        project, entry, cleaning_plan(entry, "fill_median", "score")
    )
    cleaned = dataset_version(project, entry)
    assert initial["version_sha256"] != cleaned["version_sha256"]
    raw, _, _, _ = PandasLoader().load(entry.dataset.metadata)
    entry.dataframe, _ = restore_cleaning(project, entry.dataset.id, entry.dataset.metadata, raw)
    assert dataset_version(project, entry) == cleaned
    entry.dataframe, _ = apply_recorded_cleaning(
        project, entry, cleaning_plan(entry, "fill_median", "score")
    )
    same_values = dataset_version(project, entry)
    assert same_values["frame"] == cleaned["frame"]
    assert same_values["version_sha256"] != cleaned["version_sha256"]
    assert initial["cleaning_count"] == 0
    assert same_values["cleaning_count"] == 2


def test_missing_run_binding_fails_closed(tmp_path):
    project, store, _, arguments = fixture(tmp_path)

    async def run():
        server = create_server()
        assert not (await server.call_tool("start_autoresearch_run", arguments)).is_error
        event = store.load(PipelinePhase.EXECUTE_EXPLORATION, "autoresearch_runs.jsonl")[-1]
        path = store.get_path(
            PipelinePhase.EXECUTE_EXPLORATION, f"autoresearch_baselines/{event['run_id']}.json"
        )
        record = json.loads(path.read_text())
        record.pop("data_version", None)
        path.write_text(json.dumps(record))
        return await server.call_tool("run_autoresearch_next_task", {"project_id": project.id})

    result = asyncio.run(run())
    assert result.is_error
    assert "data baseline" in result.content[0].text.lower()


def test_public_version_tool_checks_ownership_and_returns_typed_identity(tmp_path):
    project, _, entry, _ = fixture(tmp_path)

    async def run():
        server = create_server()
        result = await server.call_tool(
            "get_dataset_version", {"project_id": project.id, "dataset_id": entry.dataset.id}
        )
        assert not result.is_error
        version = result.structured_content["data"]
        assert version["schema"] == "rde-data-version-v1"
        assert version["source_status"] == "verified"
        assert version["frame"]["rows"] == 24
        assert version["cleaning_count"] == 0
        assert len(version["version_sha256"]) == 64
        assert "path" not in version["source"]
        foreign = await server.call_tool(
            "get_dataset_version", {"project_id": project.id, "dataset_id": "foreign-dataset"}
        )
        assert foreign.is_error
        assert foreign.structured_content["error"]["code"] == "DATA_VERSION_ERROR"

    asyncio.run(run())
