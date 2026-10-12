"""Prepared values and the entire source closure survive an actual MCP intake."""

import asyncio
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import zipfile

import pandas as pd
import pytest

from rde.domain.models.dataset import DatasetMetadata
from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.infrastructure.preparation import portable, workflow
from test_preparation_workflow import approve, setup


def released(tmp_path):
    project, request = setup(tmp_path)
    request["specification"]["unit"]["columns"] = {"age": {"value_type": "number"}}
    plan = workflow.execute(project, request)
    approval = approve(project, plan)
    release = workflow.execute(
        project,
        {
            "op": "release",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "approval_sha256": approval["receipt_sha256"],
        },
    )
    request = {
        "op": "bundle",
        "preparation_id": plan["preparation_id"],
        "expected_sha256": plan["receipt_sha256"],
        "release_sha256": release["receipt_sha256"],
    }
    bundle = workflow.execute(project, request)
    assert workflow.execute(project, request) == bundle
    return project, plan, release, bundle


def test_exact_typed_values_and_trace_closure(tmp_path):
    _, plan, release, bundle = released(tmp_path)
    target = SimpleNamespace(id="target", output_dir=tmp_path / "target")
    binding = portable.import_bundle(
        target, bundle["path"], bundle["sha256"], release["receipt_sha256"]
    )
    metadata = DatasetMetadata(
        Path(release["dataset"]["path"]), "csv", release["dataset"]["bytes"], preparation=binding
    )
    frame, variables, n, report = PandasLoader().load(metadata)
    assert n == 6
    assert frame.columns.tolist() == plan["summary"]["output_columns"]
    assert frame["pid"].tolist()[:2] == ["001", "003"]
    assert "1" in set(frame["pid"])  # 001 and 1 must not collapse.
    assert frame["age"].dtype == "float64"
    assert set(frame["age"]) == {30, 40, 50, 60, 70, 80}
    assert frame.loc[frame["pid"] == "004", "lab_count"].isna().all()
    assert not report.has_changes
    assert variables[0].role.value == "id"
    from rde.domain.services.variable_classifier import VariableClassifier

    coded = VariableClassifier().classify("treatment", "object", 2, 160, ["0", "1"] * 10)
    assert coded.variable_type.value == "binary"
    assert coded.dtype == "object"  # Statistical role must not coerce lexical values.
    folder = Path(binding["folder"])
    assert len(list((folder / "sources").glob("*.csv"))) == 3
    assert (folder / "trace.jsonl").exists()
    # No dependency on the original external files or bundle remains after import.
    Path(bundle["path"]).unlink()
    for item in plan["source_snapshots"]:
        Path(item["source"]["path"]).unlink()
    pd.testing.assert_frame_equal(PandasLoader().load(metadata)[0], frame)
    retained = next((folder / "sources").glob("*.csv"))
    retained.write_bytes(retained.read_bytes() + b" ")
    with pytest.raises(ValueError, match="CORRUPT_PREPARATION"):
        PandasLoader().load(metadata)


def test_bundle_checks_hash_closure_and_paths(tmp_path):
    _, _, release, bundle = released(tmp_path)
    target = SimpleNamespace(id="target", output_dir=tmp_path / "target")
    with pytest.raises(ValueError, match="hash"):
        portable.import_bundle(target, bundle["path"], "0" * 64, release["receipt_sha256"])
    with pytest.raises(ValueError, match="do not agree"):
        portable.import_bundle(target, bundle["path"], bundle["sha256"], "0" * 64)
    for bad_name in ("../escape", "extra.csv"):
        path = tmp_path / ("bad" + str(len(bad_name)) + ".zip")
        shutil.copyfile(bundle["path"], path)
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr(bad_name, "unapproved")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        with pytest.raises(ValueError, match="relative path|extra files"):
            portable.import_bundle(target, str(path), sha, release["receipt_sha256"])
    assert not (target.output_dir / "escape").exists()


def test_release_time_roles_and_frozen_cleaning_prevent_silent_new_versions(tmp_path):
    from rde.application.session import DatasetEntry
    from rde.domain.models.dataset import Dataset
    from rde.infrastructure.adapters.dataframe_lineage import apply_recorded_cleaning
    from test_dataframe_lineage import plan as cleaning_plan

    project, _, release, bundle = released(tmp_path)
    binding = portable.import_bundle(
        project, bundle["path"], bundle["sha256"], release["receipt_sha256"]
    )
    assert binding["population"]["subjects"] == 6
    assert binding["column_roles"] == {
        "lab_count": "baseline",
        "lab_mean": "baseline",
        "drug_count": "descriptive",
    }
    metadata = DatasetMetadata(
        Path(release["dataset"]["path"]), "csv", release["dataset"]["bytes"], preparation=binding
    )
    frame, variables, n, _ = PandasLoader().load(metadata)
    dataset = Dataset(metadata=metadata)
    dataset.mark_loaded(variables, n)
    entry = DatasetEntry(dataset, frame)
    before = frame.copy()
    with pytest.raises(ValueError, match="PREPARED_DATA_IMMUTABLE"):
        apply_recorded_cleaning(project, entry, cleaning_plan(entry, "drop_rows", "lab_mean"))
    pd.testing.assert_frame_equal(before, entry.dataframe)


def test_literal_unicode_sentinels_empty_columns_and_empty_strings(tmp_path):
    from test_preparation_engine import source

    project, request = setup(tmp_path)
    values = [["001", "NA", "", "", "Ａ　x", 20], ["1", "NULL", "", "", "=literal", 30]]
    table = source(
        tmp_path, "literals", ["id", "category", "empty", "missing", "text", "score"], values
    )
    request["sources"] = [table.model_copy(update={"synthetic": True}).model_dump()]
    request["specification"] = {
        "unit": {
            "kind": "patient",
            "source_id": "literals",
            "keys": ["id"],
            "subject_keys": ["id"],
            "columns": {"score": {"value_type": "number"}, "empty": {"missing_tokens": []}},
        },
        "definitions": {
            key: "Synthetic declared definition"
            for key in ("unit", "linkage", "time", "missingness")
        },
    }
    plan = workflow.execute(project, request)
    approval = approve(project, plan)
    release = workflow.execute(
        project,
        {
            "op": "release",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "approval_sha256": approval["receipt_sha256"],
        },
    )
    bundle = workflow.execute(
        project,
        {
            "op": "bundle",
            "preparation_id": plan["preparation_id"],
            "expected_sha256": plan["receipt_sha256"],
            "release_sha256": release["receipt_sha256"],
        },
    )
    binding = portable.import_bundle(
        project, bundle["path"], bundle["sha256"], release["receipt_sha256"]
    )
    frame, _, _, _ = PandasLoader().load(
        DatasetMetadata(
            Path(release["dataset"]["path"]),
            "csv",
            release["dataset"]["bytes"],
            preparation=binding,
        )
    )
    assert frame["id"].tolist() == ["001", "1"]
    assert frame["category"].tolist() == ["NA", "NULL"]
    assert frame["empty"].tolist() == ["", ""]
    assert frame["missing"].isna().all()
    assert frame["text"].tolist() == ["Ａ　x", "=literal"]


def test_mcp_intake_restart_and_data_version_bind_approved_recipe(tmp_path):
    import rde.application.session as sessions
    from rde.application.pipeline import PipelinePhase
    from rde.infrastructure.adapters.dataframe_lineage import dataset_version
    from rde.infrastructure.persistence.artifact_store import ArtifactStore
    from rde.interface.mcp.server import create_server
    from rde.interface.mcp.tools._shared.project_context import ensure_dataset

    _, _, release, bundle = released(tmp_path)
    raw = tmp_path / "analysis-raw"
    raw.mkdir()
    shutil.copyfile(release["dataset"]["path"], raw / "analysis.csv")

    async def intake():
        server = create_server()
        result = await server.call_tool(
            "init_project", {"name": "prepared-intake", "data_dir": str(raw)}
        )
        assert not result.is_error
        project = sessions.get_session().get_project()
        result = await server.call_tool(
            "run_intake",
            {
                "directory": str(raw),
                "project_id": project.id,
                "prepared_source": {
                    "bundle_path": bundle["path"],
                    "bundle_sha256": bundle["sha256"],
                    "release_sha256": release["receipt_sha256"],
                },
            },
        )
        assert not result.is_error and not result.content[0].text.startswith("❌"), result
        dataset_id = project.dataset_ids[-1]
        ok, message, entry = ensure_dataset(dataset_id, project=project)
        assert ok, message
        version = dataset_version(project, entry)
        assert version["source_status"] == "verified"
        result = await server.call_tool(
            "build_schema", {"project_id": project.id, "dataset_id": dataset_id}
        )
        assert not result.is_error, result
        schema = ArtifactStore(project.artifacts_dir).load(
            PipelinePhase.SCHEMA_REGISTRY, "schema.json"
        )
        json.dumps(schema, allow_nan=False)  # Sparse columns must remain valid JSON.
        sparse = next(v for v in schema["variables"] if v["name"] == "lab_mean")
        assert sparse["stats"]["mean"] == 20
        assert sparse["stats"]["std"] is None
        receipt = ArtifactStore(project.artifacts_dir).load(
            PipelinePhase.DATA_INTAKE, "intake_report.json"
        )
        assert receipt["preparation"]["release_sha256"] == release["receipt_sha256"]
        return project.id, dataset_id, version, entry.dataframe.copy()

    project_id, dataset_id, version, frame = asyncio.run(intake())
    sessions._session = None
    project = sessions.get_session().get_project(project_id)
    ok, message, entry = ensure_dataset(dataset_id, project=project)
    assert ok, message
    pd.testing.assert_frame_equal(entry.dataframe, frame)
    assert dataset_version(project, entry) == version
    # Changing the analysis CSV cannot silently become another prepared version.
    (raw / "analysis.csv").write_text("wrong,value\n1,2\n")
    with pytest.raises(ValueError, match="PREPARED_SOURCE_CHANGED"):
        PandasLoader().load(entry.dataset.metadata)
