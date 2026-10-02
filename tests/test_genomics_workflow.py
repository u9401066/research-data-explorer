"""Real Workbench/R fixture: multi-source guards, interrupted attempts and restart."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import uuid
import zipfile

import pytest

from rde.application.session import get_session
from rde.infrastructure.genomics import workflow as w
from rde.interface.mcp.server import create_server

FIXTURE = Path(__file__).parent / "fixtures/genomics-publication/workbench-handoff.zip"
FIXTURE_SHA = "9f1945f111cbc3ca5dda605bc5554d190258148267a910b8b5fde3e1491cb677"


def tool(name, args, *, error=False):
    response = asyncio.run(create_server().call_tool(name, args))
    assert response.is_error is error, response.content
    text = response.content[0].text
    return text if error or name == "init_project" else json.loads(text)


CHECKPOINT_FIXTURE = FIXTURE.with_name("workbench-checkpoint.zip")
CHECKPOINT_SHA = "046452fb160babe1fd237c195e20c35572fac6eb0b874d4202c00de4138c2960"


def prepare(fixture=FIXTURE, expected_sha=FIXTURE_SHA):
    tool(
        "init_project",
        {
            "name": "Genomics receipt QA",
            "research_question": "Synthetic software QA, no biological claims",
        },
    )
    project = get_session().get_project()
    assert w.file_hash(fixture) == expected_sha
    source_id = str(uuid.uuid4())
    directory = project.output_dir / "incoming/genomics" / source_id
    directory.mkdir(parents=True)
    with zipfile.ZipFile(fixture) as archive:
        archive.extractall(directory)
    path = directory / "bundle.json"
    bundle = json.loads(path.read_text())
    bundle.update(project_id=project.id, source_id=source_id)
    path.write_text(json.dumps(bundle, ensure_ascii=False) + "\n")
    return (
        project,
        directory,
        {
            "project_id": project.id,
            "source_id": source_id,
            "expected_bundle_sha256": w.file_hash(path),
        },
    )


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False))


def reseal(directory, args, changed=()):
    bundle = w.load_json(directory / "bundle.json")
    hashes = w.load_json(directory / "engine/output-hashes.json")
    for name in changed:
        if name.startswith("engine/"):
            hashes[name[7:]] = w.file_hash(directory / name)
    if any(name.startswith("engine/") for name in changed):
        write(directory / "engine/output-hashes.json", hashes)
        changed = [*changed, "engine/output-hashes.json"]
    for name in changed:
        path = directory / name
        bundle["files"][name] = {"sha256": w.file_hash(path), "bytes": path.stat().st_size}
    write(directory / "bundle.json", bundle)
    args["expected_bundle_sha256"] = w.file_hash(directory / "bundle.json")


def test_restarted_workbench_reuses_exact_r_bytes_with_all_source_lineage():
    project, directory, args = prepare(CHECKPOINT_FIXTURE, CHECKPOINT_SHA)
    origin = w.load_json(directory / "execution-origin.json")
    assert origin["kind"] == "reused"
    assert origin["identity"]["job_id"] != origin["origin"]["job_id"]
    before = (directory / "engine/numeric-result.json").read_bytes()
    imported = tool("import_genomics_source", args)
    saved, result = w.read_source(project, args["source_id"])
    assert saved == imported
    assert result["source"]["execution_origin"] == origin
    assert (
        w.source_directory(project, args["source_id"]) / "engine/numeric-result.json"
    ).read_bytes() == before


@pytest.mark.parametrize(
    "problem",
    [
        "new_execution",
        "original_project",
        "current_job",
        "plan",
        "inventory",
        "member",
        "location",
        "missing_origin",
        "missing_checkpoint",
        "counts_hash",
        "metadata_hash",
        "sets_hash",
        "sheet",
        "role_swap",
    ],
)
def test_mcp_rejects_rehashed_checkpoint_with_false_lineage_or_any_source_binding(problem):
    project, directory, args = prepare(CHECKPOINT_FIXTURE, CHECKPOINT_SHA)
    origin_path, checkpoint_path = (
        directory / "execution-origin.json",
        directory / "execution-checkpoint.json",
    )
    origin, checkpoint = w.load_json(origin_path), w.load_json(checkpoint_path)
    if problem == "new_execution":
        origin["kind"] = "executed"
    elif problem == "original_project":
        checkpoint["identity"]["project_id"] = str(uuid.uuid4())
        origin["origin"] = checkpoint["identity"]
    elif problem == "current_job":
        origin["identity"]["job_id"] = str(uuid.uuid4())
    elif problem == "plan":
        checkpoint["binding"]["planSha256"] = "0" * 64
    elif problem == "inventory":
        checkpoint["files"].pop("session.txt")
    elif problem == "member":
        checkpoint["files"]["numeric-result.json"]["sha256"] = "0" * 64
    elif problem == "location":
        checkpoint["files"]["numeric-result.json"]["sourcePath"] = (
            "datasets/other/numeric-result.json"
        )
    elif problem.endswith("_hash"):
        role = {
            "counts_hash": "counts",
            "metadata_hash": "sample_metadata",
            "sets_hash": "gene_sets",
        }[problem]
        checkpoint["binding"]["sources"][role]["sha256"] = "0" * 64
    elif problem == "sheet":
        checkpoint["binding"]["sources"]["sample_metadata"]["sheet"] = "Unreviewed sheet"
    elif problem == "role_swap":
        sources = checkpoint["binding"]["sources"]
        sources["sample_metadata"], sources["gene_sets"] = (
            sources["gene_sets"],
            sources["sample_metadata"],
        )
    write(checkpoint_path, checkpoint)
    origin["checkpointSha256"] = w.file_hash(checkpoint_path)
    write(origin_path, origin)
    reseal(directory, args, ["execution-checkpoint.json", "execution-origin.json"])
    if problem.startswith("missing_"):
        bundle = w.load_json(directory / "bundle.json")
        bundle["files"].pop(
            "execution-origin.json" if problem == "missing_origin" else "execution-checkpoint.json"
        )
        write(directory / "bundle.json", bundle)
        reseal(directory, args)
    tool("import_genomics_source", args, error=True)
    assert not w.source_directory(project, args["source_id"]).exists()


@pytest.mark.parametrize(
    "problem",
    [
        "counts_raw",
        "metadata_raw",
        "sets_raw",
        "counts_table",
        "metadata_table",
        "sets_table",
        "sheet",
        "roles",
        "dataset",
        "approval",
        "analysis_binding",
        "failed_execution",
        "csv",
        "missing_model",
        "foreign",
        "symlink",
        "path",
        "extra",
    ],
)
def test_rejects_rehashed_handoff_with_changed_source_roles_inputs_or_outputs(problem, tmp_path):
    project, directory, args = prepare()
    bundle = w.load_json(directory / "bundle.json")
    changed = []
    role = {"counts_raw": "counts", "metadata_raw": "sample_metadata", "sets_raw": "gene_sets"}.get(
        problem
    )
    if role:
        name = bundle["source"][role]["file"]
        (directory / name).write_bytes(b"changed original source")
        changed = [name]
    elif problem.endswith("_table"):
        role = {
            "counts_table": "counts",
            "metadata_table": "sample_metadata",
            "sets_table": "gene_sets",
        }[problem]
        name = bundle["source"][role]["table_file"]
        table = w.load_json(directory / name)
        if role == "counts":
            table["rows"][0][1] = str(int(table["rows"][0][1]) + 1)
        elif role == "sample_metadata":
            table["rows"][0][table["columns"].index("condition")] = "control"
        else:
            table["rows"][0][1] = "another-gene"
        write(directory / name, table)
        changed = [name]
    elif problem in {"approval", "analysis_binding", "failed_execution"}:
        name = {
            "approval": "approved-plan.json",
            "analysis_binding": "analysis-binding.json",
            "failed_execution": "engine/execution.json",
        }[problem]
        value = w.load_json(directory / name)
        if problem == "approval":
            value["question"] = "Unapproved research question"
        elif problem == "analysis_binding":
            value["audit"]["counts"][0][0] += 1
        else:
            value["status"] = "failed"
        write(directory / name, value)
        changed = [name]
    elif problem == "csv":
        name = "engine/pca-coordinates.csv"
        path = directory / name
        path.write_text(path.read_text().replace('"S01"', '"different-sample"'))
        changed = [name]
    else:
        if problem == "sheet":
            bundle["source"]["counts"]["sheet"] = "Another sheet with identical columns"
        elif problem == "roles":
            bundle["source"]["sample_metadata"], bundle["source"]["gene_sets"] = (
                bundle["source"]["gene_sets"],
                bundle["source"]["sample_metadata"],
            )
        elif problem == "dataset":
            bundle["source"]["sample_metadata"]["dataset_id"] = bundle["source"]["counts"][
                "dataset_id"
            ]
        elif problem == "missing_model":
            bundle["files"].pop("engine/deseq2-fit.rds")
        elif problem == "foreign":
            bundle["project_id"] = "12345678"
        elif problem == "symlink":
            target = directory / bundle["source"]["sample_metadata"]["file"]
            external = tmp_path / "external.csv"
            external.write_bytes(target.read_bytes())
            target.unlink()
            target.symlink_to(external)
        elif problem == "path":
            bundle["files"]["../outside.csv"] = {"sha256": "0" * 64, "bytes": 0}
        elif problem == "extra":
            name = "unbound.json"
            (directory / name).write_text("{}")
            changed = [name]
        write(directory / "bundle.json", bundle)
    reseal(directory, args, changed)
    tool("import_genomics_source", args, error=True)
    assert not w.source_directory(project, args["source_id"]).exists()


def test_real_source_import_is_idempotent_and_does_not_advance_eda():
    project, directory, args = prepare()
    before = deepcopy(get_session().get_pipeline(project.id).summary())
    original = {
        p.relative_to(directory).as_posix(): w.file_hash(p)
        for p in directory.rglob("*")
        if p.is_file()
    }
    source = tool("import_genomics_source", args)
    assert tool("import_genomics_source", args) == source
    receipt, result = w.read_source(project, args["source_id"])
    assert receipt == source
    assert result["analysis"]["summary"]["inputGenes"] == 603
    assert result["analysis"]["summary"]["samples"] == 12
    assert set(result["source"]["source"]) == {"counts", "sample_metadata", "gene_sets"}
    assert project.dataset_ids == []
    assert get_session().get_pipeline(project.id).summary() == before
    saved = w.source_directory(project, args["source_id"])
    assert all(w.file_hash(saved / name) == sha for name, sha in original.items())
    (saved / source["source"]["gene_sets"]["file"]).write_bytes(b"changed saved membership")
    tool("import_genomics_source", args, error=True)
    tool(
        "get_genomics_source",
        {"project_id": project.id, "source_id": args["source_id"]},
        error=True,
    )


def test_failed_attempt_keeps_files_then_recovers_and_editions_restore_without_rerender(
    monkeypatch,
):
    from rde.infrastructure.genomics import publication
    import rde.application.session as session_module

    project, _, args = prepare()
    source = tool("import_genomics_source", args)
    identity = {"project_id": project.id, "source_id": args["source_id"]}
    render = {
        **identity,
        "expected_source_sha256": source["receipt_sha256"],
        "render_id": str(uuid.uuid4()),
    }
    renderer = publication.figures

    def fail(result, directory, *a, **k):
        (directory / "partial.txt").write_text("partial figure")
        raise ValueError("injected figure failure")

    monkeypatch.setattr(publication, "figures", fail)
    assert "injected" in tool("render_genomics_study", render, error=True)
    failed = w.render_directory(project, args["source_id"], render["render_id"])
    original = {p.name: w.file_hash(p) for p in failed.iterdir()}
    assert "new render ID" in tool("render_genomics_study", render, error=True)
    assert tool("get_genomics_source", identity)["renders"][0]["status"] == "failed"
    monkeypatch.setattr(publication, "figures", renderer)
    render["render_id"] = str(uuid.uuid4())
    study = tool("render_genomics_study", render)
    assert len(study["figures"]) == 8
    edition_args = {
        **identity,
        "render_id": render["render_id"],
        "expected_study_sha256": study["receipt_sha256"],
        "edition_id": str(uuid.uuid4()),
        "preset_id": "nature-single-v1",
        "start_number": 4,
        "captions": {"1": {"title": "Synthetic filtering", "explanation_zh": "合成測試圖。"}},
    }
    edition = tool("render_genomics_publication", edition_args)
    assert edition["source_genomics_id"] == args["source_id"]
    assert "source_evidence_id" not in edition
    for a, b in zip(study["figures"], edition["figures"], strict=True):
        assert (
            Path(a["publication"]["files"]["data"]).read_bytes()
            == Path(b["publication"]["files"]["data"]).read_bytes()
        )
    assert original == {p.name: w.file_hash(p) for p in failed.iterdir()}
    session_module._session = None
    monkeypatch.setattr(
        publication, "figures", lambda *a, **k: pytest.fail("rerendered immutable study")
    )
    assert tool("render_genomics_study", render) == study
    assert tool("render_genomics_publication", edition_args) == edition
    tool("render_genomics_publication", {**edition_args, "start_number": 10}, error=True)
    tool("init_project", {"name": "Unrelated genomic project"})
    tool(
        "get_genomics_source",
        {**identity, "project_id": get_session().get_project().id},
        error=True,
    )
    Path(study["figures"][0]["path"]).write_bytes(b"modified figure")
    tool("get_genomics_source", identity, error=True)
    tool("render_genomics_publication", edition_args, error=True)


def test_limits_lock_and_large_frozen_receipt(tmp_path, monkeypatch):
    project, directory, args = prepare()
    bundle = w.load_json(directory / "bundle.json")
    largest = max(v["bytes"] for v in bundle["files"].values())
    monkeypatch.setattr(w, "MAX_FILE", largest - 1)
    with pytest.raises(ValueError, match="file size"):
        w.verify_bundle(project, args["source_id"], directory, args["expected_bundle_sha256"])
    monkeypatch.setattr(w, "MAX_FILE", largest)
    monkeypatch.setattr(w, "MAX_TOTAL", sum(v["bytes"] for v in bundle["files"].values()) - 1)
    with pytest.raises(ValueError, match="bundle exceeds"):
        w.verify_bundle(project, args["source_id"], directory, args["expected_bundle_sha256"])
    with w.locked(project), pytest.raises(ValueError, match="busy"), w.locked(project):
        pytest.fail("admitted concurrent writer")
    monkeypatch.setattr(w, "MAX_FILE", 256 * 1024 * 1024)
    large = w.sealed({"payload": "x" * (17 * 1024 * 1024)})
    path = tmp_path / "publication-result.json"
    w.write_new(path, large)
    assert w.read_sealed(path) == large
    ordinary = path.with_name("bundle.json")
    ordinary.write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match="size limit"):
        w.load_json(ordinary)
