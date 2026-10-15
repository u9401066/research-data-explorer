"""Native pseudonymization continues intake without altering scientific values."""

import asyncio
import hashlib
from dataclasses import replace

import pandas as pd
import pytest

from rde.domain.models.dataset import DatasetMetadata
from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.infrastructure.adapters.privacy import propose_privacy, apply_privacy
from rde.infrastructure.adapters.dataframe_lineage import bind_source, frame_record
from rde.application.session import get_session
from rde.interface.mcp.server import create_server


def test_research_codes_keep_nulls_duplicates_cross_table_links_and_source(tmp_path, monkeypatch):
    monkeypatch.setenv("RDE_PRIVACY_KEY_FILE", str(tmp_path / "private" / "key"))
    path = tmp_path / "a.csv"
    pd.DataFrame(
        {
            "patient_id": ["003", "003", "004", None],
            "ANES_emr_empname": ["Dr QA", "Dr QA", "Dr Test", None],
            "score": [1.5, 2.5, 3.0, 4.0],
        }
    ).to_csv(path, index=False)
    raw = path.read_bytes()
    meta = DatasetMetadata(path, "csv", len(raw))
    before, variables, _, _ = PandasLoader().load(meta)
    privacy = propose_privacy(before, hashlib.sha256(raw).hexdigest())
    meta.privacy = privacy
    after, vs, _, _ = PandasLoader().load(meta)
    assert path.read_bytes() == raw
    pd.testing.assert_series_equal(before.score, after.score)
    assert after.patient_id.iloc[0] == after.patient_id.iloc[1]
    assert after.patient_id.iloc[0] != after.patient_id.iloc[2]
    assert pd.isna(after.patient_id.iloc[3])
    assert all(
        v.variable_type.value == "id" and not v.is_pii_suspect for v in vs if v.name != "score"
    )
    assert "Dr QA" not in str(privacy) and "Dr QA" not in after.to_csv(index=False)
    # A second table, differently named key, preserves exact matching inside a study.
    second = before.rename(columns={"patient_id": "subject_id"})
    spec = propose_privacy(second, hashlib.sha256(raw).hexdigest())
    out, _ = apply_privacy(
        second,
        [replace(v, name="subject_id" if v.name == "patient_id" else v.name) for v in variables],
        spec,
        source_path=path,
    )
    assert out.subject_id.iloc[0] == after.patient_id.iloc[0]
    assert frame_record(PandasLoader().load(meta)[0]) == frame_record(after)
    path.write_bytes(raw + b"\n")
    with pytest.raises(ValueError, match="source has changed"):
        PandasLoader().load(meta)
    path.write_bytes(raw)
    monkeypatch.setenv("RDE_PRIVACY_KEY_FILE", str(tmp_path / "other-key"))
    with pytest.raises(ValueError, match="key is missing"):
        PandasLoader().load(meta)
    assert not (tmp_path / "other-key").exists()


def test_full_scan_retains_dates_and_clinical_measurements(tmp_path, monkeypatch):
    monkeypatch.setenv("RDE_PRIVACY_KEY_FILE", str(tmp_path / "key"))
    frame = pd.DataFrame(
        {
            "notes": ["clear"] * 25 + ["qa@example.invalid"],
            "birthdate": ["1980-03-21"] * 26,
            "creatinine": list(range(26)),
        }
    )
    spec = propose_privacy(frame, "a" * 64)
    assert {i["column"]: i["action"] for i in spec["columns"]} == {
        "notes": "redact_identifier_spans",
        "birthdate": "retain_clinical_date",
    }


def test_native_intake_schema_lineage_and_restart_use_same_research_frame(tmp_path, monkeypatch):
    import rde.application.session as session_module
    from rde.interface.mcp.tools._shared.project_context import ensure_dataset

    monkeypatch.setenv("RDE_PRIVACY_KEY_FILE", str(tmp_path / "private-key"))
    raw = tmp_path / "raw"
    raw.mkdir()
    frame = pd.DataFrame(
        {"ANES_emr_empname": ["Dr Fixture A", "Dr Fixture B"] * 12, "score": range(24)}
    )
    frame.to_excel(raw / "clinical.xlsx", sheet_name="Sheet1", index=False)

    async def run():
        server = create_server()
        assert not (
            await server.call_tool(
                "init_project", {"name": "assisted-intake", "data_dir": str(raw)}
            )
        ).is_error
        project = get_session().get_project()
        args = {"directory": str(raw), "project_id": project.id, "sheet_name": "Sheet1"}
        blocked = await server.call_tool("run_intake", args)
        assert blocked.is_error
        result = await server.call_tool("run_intake", {**args, "pii_policy": "pseudonymize"})
        assert not result.is_error, result
        dsid = project.dataset_ids[-1]
        schema = await server.call_tool(
            "build_schema", {"dataset_id": dsid, "project_id": project.id}
        )
        assert not schema.is_error, schema
        v = schema.structured_content["data"]["variables"][0]
        assert not v["is_pii_suspect"] and v["privacy_action"] == "pseudonymize"
        entry = get_session().get_dataset_entry(dsid)
        expected = frame_record(entry.dataframe)
        bound = bind_source(project, entry)
        assert bound["parser"]["privacy"]["policy"] == "rde-research-privacy-v1"
        assert bound["input_frame"] == expected
        text = (project.artifacts_dir / "phase_01_data_intake/research_view.csv").read_text()
        assert "Dr Fixture" not in text and "RID_" in text
        return project.id, dsid, expected

    pid, dsid, expected = asyncio.run(run())
    session_module._session = None
    project = get_session().get_project(pid)
    ok, message, entry = ensure_dataset(dsid, project=project)
    assert ok, message
    assert frame_record(entry.dataframe) == expected
    assert bind_source(project, entry)["input_frame"] == expected


def test_technical_labels_are_not_person_names():
    from rde.domain.services.variable_classifier import VariableClassifier

    c = VariableClassifier()
    assert not c._check_pii("drug_name", ["Aspirin"])
    assert c._check_pii("drug_name", ["qa@example.invalid"])
    assert c._check_pii("id_number", [])
    assert c._check_pii("ANES_emr_empname", [])


def test_ambiguous_numeric_ranges_are_not_destroyed(tmp_path, monkeypatch):
    monkeypatch.setenv("RDE_PRIVACY_KEY_FILE", str(tmp_path / "key"))
    frame = pd.DataFrame({"notes": ["dose 1000-2000 units", "call qa@example.invalid; normal ECG"]})
    path = tmp_path / "source.csv"
    frame.to_csv(path, index=False)
    metadata = DatasetMetadata(path, "csv", path.stat().st_size)
    original, _, _, _ = PandasLoader().load(metadata)
    metadata.privacy = propose_privacy(original, hashlib.sha256(path.read_bytes()).hexdigest())
    result, _, _, _ = PandasLoader().load(metadata)
    assert result.notes.iloc[0] == "dose 1000-2000 units"
    assert result.notes.iloc[1].endswith("; normal ECG")
    assert "qa@example.invalid" not in result.notes.iloc[1]


def test_identifier_prefixes_do_not_pseudonymize_measurements(tmp_path, monkeypatch):
    monkeypatch.setenv("RDE_PRIVACY_KEY_FILE", str(tmp_path / "key"))
    frame = pd.DataFrame(
        {"mrna": [1, 2], "patient_identifier_available": [0, 1], "patient_id": ["a", "b"]}
    )
    spec = propose_privacy(frame, "a" * 64)
    assert [c["column"] for c in spec["columns"]] == ["patient_id"]
