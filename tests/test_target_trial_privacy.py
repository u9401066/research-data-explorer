"""Prepared raw evidence and its exact pseudonymized research view stay distinct."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.infrastructure.adapters import privacy
from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.infrastructure.clinical import weighting
from rde.infrastructure.preparation.portable import load_prepared
from rde.interface.mcp.tools.clinical_tools import clinical_records
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness
from test_target_trial_workflow import args, call, lock, native_fixture


def key_path():
    return Path(
        os.environ.get("RDE_PRIVACY_KEY_FILE")
        or Path(os.environ["RDE_WORKSPACE"]) / ".research-privacy.key"
    )


@pytest.mark.parametrize("outcome", ["binary", "continuous"])
def test_true_mcp_prepared_privacy_inspect_lock_run_report_and_reuse(
    tmp_path, monkeypatch, outcome
):
    project, store, dataset, frame, spec = native_fixture(
        tmp_path, outcome=outcome, pii_policy="pseudonymize"
    )
    source_bytes = dataset.metadata.file_path.read_bytes()
    key_bytes = key_path().read_bytes()
    bundle = Path(dataset.metadata.preparation["folder"])
    before = {
        str(p.relative_to(bundle)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in bundle.rglob("*")
        if p.is_file()
    }
    raw = load_prepared(dataset.metadata)[0]
    assert not frame["_rde_subject_id"].equals(raw["_rde_subject_id"])
    assert frame["_rde_subject_id"].str.startswith("RID_").all()
    pd.testing.assert_frame_equal(
        frame.drop(columns="_rde_subject_id"), raw.drop(columns="_rde_subject_id"), check_exact=True
    )
    view_result = weighting.run_weighting(frame, spec.weighting)
    raw_result = weighting.run_weighting(raw, spec.weighting)
    assert (
        view_result["effect"] == raw_result["effect"]
    ), "Subject pseudonyms must not change any estimate or uncertainty"
    preflight = json.loads(call("inspect_clinical_study", args(dataset, spec)))
    source_check = json.loads(
        (project.output_dir / preflight["source_check"]["artifact"]["path"]).read_text()
    )
    assert source_check["research_view"]["privacy"] == dataset.metadata.privacy
    assert (
        source_check["research_view"]["raw_typed_frame"]
        != source_check["research_view"]["analysis_frame"]
    )
    assert source_check["population"]["included"] == 60 and len(source_check["rows"]) == 61
    lock(project, spec)
    arguments = {**args(dataset, spec), "execution_key": "a" * 64}
    first = call("run_clinical_study", arguments)
    assert clinical_records(store)[0]["result"]["weighting_result"] == view_result
    monkeypatch.setattr(
        weighting, "run_weighting", lambda *a, **k: pytest.fail("Frozen privacy replay refitted")
    )
    assert call("run_clinical_study", arguments) == first
    call("collect_results", {"project_id": project.id})
    call("assemble_report", {"project_id": project.id})
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert _evaluate_report_readiness(summary, store)["ready"]
    assert dataset.metadata.file_path.read_bytes() == source_bytes
    assert key_path().read_bytes() == key_bytes
    assert before == {
        str(p.relative_to(bundle)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in bundle.rglob("*")
        if p.is_file()
    }, "Source snapshots and every original typed/trace/approval file must remain unchanged"


def test_private_key_policy_frame_and_analysis_role_drift_are_rejected(tmp_path, monkeypatch):
    _, _, dataset, frame, spec = native_fixture(tmp_path, pii_policy="pseudonymize")
    request = {**args(dataset, spec), "execution_key": "b" * 64}
    call("inspect_clinical_study", request)
    metadata = dataset.metadata
    key = key_path()
    original_key = key.read_bytes()
    key.write_bytes(bytes(reversed(original_key)))
    call("inspect_clinical_study", request, error="TTE_PRIVACY_VIEW")
    key.write_bytes(original_key)
    key.unlink()
    call("inspect_clinical_study", request, error="TTE_PRIVACY_VIEW")
    assert not key.exists(), "Readonly validation must not generate a replacement key"
    key.write_bytes(original_key)
    key.chmod(0o600)
    absent = tmp_path / "uncreated-key-parent/key"
    with monkeypatch.context() as context:
        context.setenv("RDE_PRIVACY_KEY_FILE", str(absent))
        call("inspect_clinical_study", args(dataset, spec), error="TTE_PRIVACY_VIEW")
        assert not absent.parent.exists()
    original_privacy = deepcopy(metadata.privacy)
    metadata.privacy["policy"] = "another-policy"
    call("inspect_clinical_study", args(dataset, spec), error="TTE_PRIVACY_VIEW")
    call("inspect_clinical_study", request, error="CLINICAL_REPLAY_SOURCE")
    metadata.privacy = deepcopy(original_privacy)
    entry = get_session().get_dataset_entry(dataset.id)
    original_frame = entry.dataframe.copy(deep=True)
    entry.dataframe.loc[0, "_rde_subject_id"] = "RID_changed"
    call("inspect_clinical_study", args(dataset, spec), error="TTE_DATAFRAME_CHANGED")
    call("inspect_clinical_study", request, error="CLINICAL_REPLAY_SOURCE")
    entry.dataframe = original_frame.copy(deep=True)
    entry.dataframe["age"] = entry.dataframe["age"].astype("int64")
    call("inspect_clinical_study", args(dataset, spec), error="TTE_DATAFRAME_CHANGED")
    entry.dataframe = original_frame.copy(deep=True)
    metadata.privacy["columns"].append({"column": "treatment", "action": "pseudonymize"})
    entry.dataframe = PandasLoader().load(metadata)[0]
    call("inspect_clinical_study", args(dataset, spec), error="TTE_PRIVACY_ANALYSIS_ROLE")
    metadata.privacy = original_privacy
    entry.dataframe = original_frame
    call("inspect_clinical_study", request)
    assert hashlib.sha256(key.read_bytes()).hexdigest() == metadata.privacy["key_id"]


def test_raw_trace_and_research_unit_ids_have_exact_ordered_correspondence(tmp_path):
    _, _, dataset, _, spec = native_fixture(tmp_path, pii_policy="pseudonymize")
    entry = get_session().get_dataset_entry(dataset.id)
    dataset.metadata.privacy["columns"].append({"column": "_rde_unit_id", "action": "pseudonymize"})
    raw, variables, _, _ = load_prepared(dataset.metadata)
    entry.dataframe, _ = privacy.apply_privacy(
        raw,
        variables,
        dataset.metadata.privacy,
        source_path=dataset.metadata.file_path,
        allow_key_creation=False,
    )
    assert entry.dataframe["_rde_unit_id"].str.startswith("RID_").all()
    call("inspect_clinical_study", args(dataset, spec))
    entry.dataframe = entry.dataframe.iloc[::-1].reset_index(drop=True)
    call("inspect_clinical_study", args(dataset, spec), error="TTE_DATAFRAME_CHANGED")


@pytest.mark.parametrize("absent_parent", [False, True])
def test_saved_privacy_loader_and_mcp_restart_never_create_missing_key(
    tmp_path, monkeypatch, absent_parent
):
    import rde.application.session as session_module
    from rde.infrastructure.persistence import (
        FileSystemProjectRepository,
        resolve_projects_base_dir,
    )

    project, store, dataset, _, spec = native_fixture(tmp_path, pii_policy="pseudonymize")
    lock(project, spec)
    request = {**args(dataset, spec), "execution_key": "e" * 64}
    first = call("run_clinical_study", request)
    FileSystemProjectRepository(resolve_projects_base_dir()).save(project)
    source_bytes = dataset.metadata.file_path.read_bytes()
    original_privacy = deepcopy(dataset.metadata.privacy)
    record = clinical_records(store)[0]
    result_path = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    frozen_result = result_path.read_bytes()
    key = key_path()
    original_key = key.read_bytes()
    if absent_parent:
        missing = tmp_path / "never-created-recovery-parent/key"
        monkeypatch.setenv("RDE_PRIVACY_KEY_FILE", str(missing))
    else:
        missing = key
        key.unlink()
    with pytest.raises(ValueError, match="key is missing"):
        PandasLoader().load(dataset.metadata)
    assert not missing.exists()
    if absent_parent:
        assert not missing.parent.exists()
    session_module._session = None
    get_session().get_project(project.id)
    monkeypatch.setattr(
        weighting, "run_weighting", lambda *a, **k: pytest.fail("Missing-key recovery refitted")
    )
    call("run_clinical_study", request, error="key is missing")
    assert not missing.exists()
    if absent_parent:
        assert not missing.parent.exists()
    assert result_path.read_bytes() == frozen_result
    assert dataset.metadata.file_path.read_bytes() == source_bytes
    assert dataset.metadata.privacy == original_privacy
    # The original identity key can be restored explicitly; no replacement or receipt rewrite.
    monkeypatch.setenv("RDE_PRIVACY_KEY_FILE", str(key))
    if not key.exists():
        key.write_bytes(original_key)
        key.chmod(0o600)
    session_module._session = None
    get_session().get_project(project.id)
    assert call("run_clinical_study", request) == first
