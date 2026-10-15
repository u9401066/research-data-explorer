"""Actual MCP invocation replay cannot bypass typed clinical evidence guards."""

import asyncio
import hashlib

import pytest

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.server import create_server
from rde.interface.mcp.runtime import CLINICAL_REPLAY_ONLY
from rde.interface.mcp.tools.clinical_tools import clinical_records
from test_missing_stratified_workflow import fixture as standard_fixture


def fixture(tmp_path, family):
    if family == "matching":
        from test_matching_workflow import setup

        return setup(tmp_path)
    return standard_fixture(tmp_path, family)


def call(arguments):
    return asyncio.run(create_server().call_tool("run_clinical_study", arguments))


@pytest.mark.parametrize("family", ["imputation", "stratified", "matching"])
@pytest.mark.parametrize("damage", ["source", "record", "table", "figure", "inventory"])
def test_same_execution_key_checks_live_evidence_without_refit(
    tmp_path, monkeypatch, family, damage
):
    from rde.infrastructure.clinical import imputation, stratified, matching, report

    project, store, dataset, spec = fixture(tmp_path, family)
    arguments = {
        "dataset_id": dataset.id,
        "clinical_options": spec.to_dict(),
        "execution_key": hashlib.sha256(b"first-run").hexdigest(),
    }
    first = call(arguments)
    assert not first.is_error, first.content
    record = clinical_records(store)[0]
    source = dataset.metadata.file_path
    record_path = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])

    def forbidden(*args, **kwargs):
        pytest.fail("Invocation replay refitted or rebuilt clinical evidence")

    monkeypatch.setattr(imputation, "run_imputation", forbidden)
    monkeypatch.setattr(stratified, "run_stratified", forbidden)
    monkeypatch.setattr(matching, "run_matching", forbidden)
    monkeypatch.setattr(report, "figures", forbidden)

    async def parallel_replays():
        server = create_server()
        return await asyncio.gather(
            *(server.call_tool("run_clinical_study", arguments) for _ in range(2))
        )

    for again in asyncio.run(parallel_replays()):
        assert not again.is_error, again.content
        assert (
            again.structured_content["invocation_id"] == first.structured_content["invocation_id"]
        )
    assert not CLINICAL_REPLAY_ONLY.get()
    if damage == "source":
        source.write_bytes(source.read_bytes() + b"\n")
        missing = None
    elif damage == "record":
        missing = record_path
        missing.unlink()
    elif damage == "inventory":
        value = store.load(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
        value["artifacts"] = []
        store.save(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"], value)
        missing = None
    else:
        extension = ".png" if damage == "figure" else ".csv"
        missing = project.output_dir / next(
            item["path"] for item in record["artifacts"] if item["path"].endswith(extension)
        )
        missing.unlink()
    denied = call(arguments)
    assert denied.is_error, denied.content
    assert not CLINICAL_REPLAY_ONLY.get()
    if missing:
        assert not missing.exists()
    # The sealed original operation stays available for audit; rejection is not
    # an overwrite of the historical success or an attempt at cache healing.
    operation = project.output_dir / ".rde_operations" / arguments["execution_key"] / "result.json"
    assert operation.is_file()


def test_replay_exception_resets_context_and_new_execution_still_fits(tmp_path, monkeypatch):
    from rde.interface.mcp.tools import clinical_tools
    from rde.infrastructure.clinical import stratified

    project, store, dataset, spec = fixture(tmp_path / "first", "stratified")
    arguments = {
        "dataset_id": dataset.id,
        "clinical_options": spec.to_dict(),
        "execution_key": "a" * 64,
    }
    assert not call(arguments).is_error
    seen = []

    def crash(*args, **kwargs):
        seen.append(CLINICAL_REPLAY_ONLY.get())
        raise RuntimeError("Deliberate evidence-reader failure")

    with monkeypatch.context() as patch:
        patch.setattr(clinical_tools, "verify_clinical_artifacts", crash)
        assert call(arguments).is_error
    assert seen == [True] and not CLINICAL_REPLAY_ONLY.get()
    second, _, second_dataset, second_spec = fixture(tmp_path / "second", "stratified")
    original = stratified.run_stratified

    def fit(*args, **kwargs):
        seen.append(CLINICAL_REPLAY_ONLY.get())
        return original(*args, **kwargs)

    monkeypatch.setattr(stratified, "run_stratified", fit)
    new = call(
        {
            "dataset_id": second_dataset.id,
            "clinical_options": second_spec.to_dict(),
            "execution_key": "b" * 64,
        }
    )
    assert not new.is_error, new.content
    assert seen == [True, False] and not CLINICAL_REPLAY_ONLY.get()
