"""An explicit workbook sheet remains the same evidence after MCP restart."""

import asyncio

import pandas as pd

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.server import create_server


def test_intake_sheet_selection_survives_session_restart(tmp_path):
    import rde.application.session as session_module
    from rde.interface.mcp.tools._shared.project_context import ensure_dataset

    raw = tmp_path / "raw"
    raw.mkdir()
    with pd.ExcelWriter(raw / "cohorts.xlsx") as writer:
        pd.DataFrame({"score": [999] * 12, "arm": ["A", "B"] * 6}).to_excel(
            writer, sheet_name="Wrong cohort", index=False
        )
        pd.DataFrame({"score": range(20, 44), "arm": ["C", "D"] * 12}).to_excel(
            writer, sheet_name="選定 cohort", index=False
        )

    async def intake():
        server = create_server()
        result = await server.call_tool("init_project", {"name": "sheet-recovery", "data_dir": str(raw)})
        assert not result.is_error
        project = session_module.get_session().get_project()
        result = await server.call_tool(
            "run_intake", {"directory": str(raw), "project_id": project.id, "sheet_name": "選定 cohort"}
        )
        assert not result.is_error, result
        assert not result.content[0].text.startswith("❌"), result
        dataset_id = project.dataset_ids[-1]
        result = await server.call_tool("build_schema", {"project_id": project.id, "dataset_id": dataset_id})
        assert not result.is_error
        receipt = ArtifactStore(project.artifacts_dir).load(PipelinePhase.DATA_INTAKE, "intake_report.json")
        assert receipt["sheet_name"] == "選定 cohort"
        return project.id, dataset_id

    project_id, dataset_id = asyncio.run(intake())
    session_module._session = None
    project = session_module.get_session().get_project(project_id)
    ok, message, entry = ensure_dataset(dataset_id, project=project)
    assert ok, message
    assert entry is not None
    assert entry.dataset.row_count == 24
    assert entry.dataframe["score"].tolist() == list(range(20, 44))
    assert set(entry.dataframe["arm"]) == {"C", "D"}
