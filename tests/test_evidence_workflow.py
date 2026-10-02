"""Actual R handoff, approval/source guards, immutable figures and restart through MCP."""

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import uuid
import zipfile

import pytest

from rde.application.session import get_session
from rde.infrastructure.evidence import workflow as w
from rde.interface.mcp.server import create_server

FIXTURE = Path(__file__).parent / "fixtures/evidence-publication/workbench-handoff.zip"
FIXTURE_SHA = "3cedb20b499dfe23fc203ba55c22620327b67ab5be63be8bd8044ba1436492ae"
CHECKPOINT_FIXTURE = FIXTURE.with_name("workbench-checkpoint.zip")
CHECKPOINT_SHA = "e2b5ffc2f3c63134c8bcb21c9e8872efed0ec67977e50396e945f9ab4f6290b4"


def tool(name, arguments, *, error=False):
    response = asyncio.run(create_server().call_tool(name, arguments))
    assert response.is_error is error, response.content
    text = response.content[0].text
    return text if error or name == "init_project" else json.loads(text)


def prepare(fixture=FIXTURE, expected_sha=FIXTURE_SHA):
    tool(
        "init_project",
        {
            "name": "Frozen evidence handoff QA",
            "research_question": "Synthetic software verification only",
        },
    )
    project = get_session().get_project()
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == expected_sha
    source_id = str(uuid.uuid4())
    directory = project.output_dir / "incoming/evidence" / source_id
    directory.mkdir(parents=True)
    with zipfile.ZipFile(fixture) as archive:
        archive.extractall(directory)
    # Only transport identity changes for this isolated project. All original R,
    # source, schema, review and approved-plan bytes remain exactly as executed.
    path = directory / "bundle.json"
    bundle = json.loads(path.read_text())
    bundle.update(project_id=project.id, source_id=source_id)
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n")
    args = {
        "project_id": project.id,
        "source_id": source_id,
        "expected_bundle_sha256": w.file_hash(path),
    }
    return project, directory, args


def reseal_bundle(directory, args, changed=None):
    path = directory / "bundle.json"
    bundle = json.loads(path.read_text())
    if changed:
        p = directory / changed
        bundle["files"][changed] = {"sha256": w.file_hash(p), "bytes": p.stat().st_size}
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n")
    args["expected_bundle_sha256"] = w.file_hash(path)


def test_full_r_model_has_separate_limit_without_relaxing_total_or_json_limits(monkeypatch):
    project, directory, args = prepare(CHECKPOINT_FIXTURE, CHECKPOINT_SHA)
    bundle = w.load_json(directory / "bundle.json")
    sizes = {name: item["bytes"] for name, item in bundle["files"].items()}
    model_size = sizes["engine/network-model.rds"]
    ordinary_size = max(size for name, size in sizes.items() if name != "engine/network-model.rds")
    total = sum(sizes.values())
    # Scale limits to the genuine immutable R fixture. The live Workbench
    # capacity check separately imports the complete 280 MB model through MCP.
    assert model_size > ordinary_size
    monkeypatch.setattr(w, "MAX_FILE", ordinary_size)
    monkeypatch.setattr(w, "MAX_R_MODEL", model_size)
    monkeypatch.setattr(w, "MAX_TOTAL", total)
    source_id, expected = args["source_id"], args["expected_bundle_sha256"]
    w.verify_bundle(project, source_id, directory, expected)
    monkeypatch.setattr(w, "MAX_R_MODEL", model_size - 1)
    with pytest.raises(ValueError, match="file size"):
        w.verify_bundle(project, source_id, directory, expected)
    monkeypatch.setattr(w, "MAX_R_MODEL", model_size)
    monkeypatch.setattr(w, "MAX_FILE", ordinary_size - 1)
    with pytest.raises(ValueError, match="file size"):
        w.verify_bundle(project, source_id, directory, expected)
    monkeypatch.setattr(w, "MAX_FILE", ordinary_size)
    monkeypatch.setattr(w, "MAX_TOTAL", total - 1)
    with pytest.raises(ValueError, match="bundle exceeds limit"):
        w.verify_bundle(project, source_id, directory, expected)


def test_real_workbench_reused_execution_retains_original_checkpoint():
    project, directory, args = prepare(CHECKPOINT_FIXTURE, CHECKPOINT_SHA)
    origin = w.load_json(directory / "execution-origin.json")
    assert origin["kind"] == "reused"
    assert origin["identity"]["job_id"] != origin["origin"]["job_id"]
    original_numeric = (directory / "engine/numeric-result.json").read_bytes()
    imported = tool("import_evidence_source", args)
    saved, result = w.read_source(project, args["source_id"])
    assert saved == imported
    assert result["source"]["execution_origin"] == origin
    assert (
        w.source_directory(project, args["source_id"]) / "engine/numeric-result.json"
    ).read_bytes() == original_numeric


@pytest.mark.parametrize(
    "problem",
    [
        "new_execution",
        "original_project",
        "plan",
        "inventory",
        "member",
        "location",
        "current_job",
        "missing_origin",
    ],
)
def test_mcp_rejects_self_consistent_hashes_with_false_checkpoint_lineage(problem):
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
    elif problem == "current_job":
        origin["identity"]["job_id"] = str(uuid.uuid4())
    checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False))
    origin["checkpointSha256"] = w.file_hash(checkpoint_path)
    origin_path.write_text(json.dumps(origin, ensure_ascii=False))
    reseal_bundle(directory, args, "execution-checkpoint.json")
    reseal_bundle(directory, args, "execution-origin.json")
    if problem == "missing_origin":
        bundle_path = directory / "bundle.json"
        bundle = w.load_json(bundle_path)
        bundle["files"].pop("execution-origin.json")
        bundle_path.write_text(json.dumps(bundle))
        reseal_bundle(directory, args)
    tool("import_evidence_source", args, error=True)
    assert not w.source_directory(project, args["source_id"]).exists()


@pytest.mark.parametrize(
    "problem",
    [
        "raw",
        "approved",
        "draft",
        "table",
        "numeric",
        "execution",
        "inventory",
        "cross_project",
        "symlink",
        "path",
        "hash",
    ],
)
def test_mcp_refuses_changed_or_redirected_source_even_with_new_bundle_hash(tmp_path, problem):
    project, directory, args = prepare()
    filename = {
        "raw": "source/data.csv",
        "approved": "approved-plan.json",
        "draft": "reviewed-plan.json",
        "table": "source-table.json",
        "numeric": "engine/numeric-result.json",
        "execution": "engine/execution.json",
    }.get(problem)
    if problem == "raw":
        (directory / filename).write_bytes(b"different raw data")
    elif filename:
        path = directory / filename
        data = json.loads(path.read_text())
        if problem == "approved":
            data["evidence"]["reference"] = "Different intervention"
        elif problem == "draft":
            data["question"] = "Unapproved question"
        elif problem == "table":
            data["rows"][0][0] = "Another study"
        elif problem == "numeric":
            data["observations"][0]["effect"] += 0.1
        else:
            data["status"] = "failed"
        path.write_text(json.dumps(data, ensure_ascii=False))
    else:
        path = directory / "bundle.json"
        data = json.loads(path.read_text())
        if problem == "inventory":
            data["files"].pop("engine/session.txt")
        elif problem == "cross_project":
            data["project_id"] = "other-project"
        elif problem == "path":
            data["files"]["../outside"] = {"sha256": "0" * 64, "bytes": 0}
        elif problem == "symlink":
            outside = tmp_path / "outside-source"
            shutil.move(directory / "source", outside)
            (directory / "source").symlink_to(outside, target_is_directory=True)
        path.write_text(json.dumps(data))
    reseal_bundle(directory, args, filename)
    if problem == "hash":
        args["expected_bundle_sha256"] = "0" * 64
    tool("import_evidence_source", args, error=True)
    assert not w.source_directory(project, args["source_id"]).exists()


def test_full_mcp_render_editions_and_restart_preserve_source_and_eda_state(monkeypatch):
    project, incoming, args = prepare()
    before = deepcopy(get_session().get_pipeline(project.id).summary())
    source = tool("import_evidence_source", args)
    source_dir = w.source_directory(project, args["source_id"])
    original = {
        str(p.relative_to(source_dir)): w.file_hash(p) for p in source_dir.rglob("*") if p.is_file()
    }
    shutil.rmtree(incoming)
    assert (
        tool("import_evidence_source", args) == source
    )  # No dependency on the mutable incoming copy.
    render_args = {
        "project_id": project.id,
        "source_id": args["source_id"],
        "expected_source_sha256": source["receipt_sha256"],
        "render_id": str(uuid.uuid4()),
    }
    run = tool("render_evidence_study", render_args)
    assert len(run["figures"]) == 9 and len(run["artifacts"]) == 55
    assert (
        "中文解釋"
        in (
            project.output_dir
            / next(a["path"] for a in run["artifacts"] if a["format"] == "report")
        ).read_text()
    )
    edition_args = {
        "project_id": project.id,
        "source_id": args["source_id"],
        "render_id": run["render_id"],
        "expected_study_sha256": run["receipt_sha256"],
        "edition_id": str(uuid.uuid4()),
        "preset_id": "journal-neutral-english-v1",
        "start_number": 11,
        "captions": {
            "1": {
                "title": "Reviewed comparison rows",
                "caption_en": "Synthetic study-comparison rows for software verification only.",
                "explanation_zh": "此圖僅作合成研究比較列的軟體驗證。",
            }
        },
    }
    edition = tool("render_evidence_publication", edition_args)
    assert edition["source_evidence_id"] == args["source_id"]
    assert edition["figures"][0]["publication"]["figure_number"] == 11
    assert "Reviewed comparison rows" in edition["figures"][0]["publication"]["caption_en"]
    for a, b in zip(run["figures"], edition["figures"], strict=True):
        assert (
            Path(a["publication"]["files"]["data"]).read_bytes()
            == Path(b["publication"]["files"]["data"]).read_bytes()
        )
    assert get_session().get_pipeline(project.id).summary() == before
    assert project.dataset_ids == []
    assert all(w.file_hash(source_dir / path) == value for path, value in original.items())
    frozen = {
        str(project.output_dir / a["path"]): a["sha256"]
        for a in [*run["artifacts"], *edition["artifacts"]]
    }
    import rde.application.session as session_module
    from rde.infrastructure.evidence import publication

    session_module._session = None
    monkeypatch.setattr(
        publication, "figures", lambda *a, **k: pytest.fail("redrew immutable figures")
    )
    assert tool("render_evidence_study", render_args) == run
    assert tool("render_evidence_publication", edition_args) == edition
    view = tool("get_evidence_source", {"project_id": project.id, "source_id": args["source_id"]})
    assert view == {"source": source, "renders": [{"status": "completed", "record": run}]}
    assert all(w.file_hash(Path(path)) == value for path, value in frozen.items())
    tool("render_evidence_publication", {**edition_args, "start_number": 12}, error=True)
    Path(run["figures"][0]["path"]).write_bytes(b"changed figure")
    tool(
        "get_evidence_source",
        {"project_id": project.id, "source_id": args["source_id"]},
        error=True,
    )
    tool("render_evidence_study", render_args, error=True)


def test_interrupted_render_can_retry_from_frozen_numbers_without_overwriting_attempt(monkeypatch):
    from rde.infrastructure.evidence import publication

    project, _, args = prepare()
    source = tool("import_evidence_source", args)
    render_args = {
        "project_id": project.id,
        "source_id": args["source_id"],
        "expected_source_sha256": source["receipt_sha256"],
        "render_id": str(uuid.uuid4()),
    }
    original = publication.figures

    def fail(result, directory, *a, **k):
        (directory / "partial.txt").write_text("interrupted rendering")
        raise ValueError("injected rendering failure")

    monkeypatch.setattr(publication, "figures", fail)
    assert "injected" in tool("render_evidence_study", render_args, error=True)
    failed = w.render_directory(project, args["source_id"], render_args["render_id"])
    snapshot = {p.name: w.file_hash(p) for p in failed.iterdir()}
    assert "new render ID" in tool("render_evidence_study", render_args, error=True)
    # A hard process interruption may leave only a started marker and partial output.
    unfinished = w.render_directory(project, args["source_id"], str(uuid.uuid4()))
    unfinished.mkdir()
    (unfinished / "started.json").write_text("{}")
    view = tool("get_evidence_source", {"project_id": project.id, "source_id": args["source_id"]})
    assert sorted(r["status"] for r in view["renders"]) == ["failed", "unfinished"]
    monkeypatch.setattr(publication, "figures", original)
    run = tool("render_evidence_study", {**render_args, "render_id": str(uuid.uuid4())})
    assert run["source_numerical_receipt_sha256"] == source["numerical_receipt_sha256"]
    assert {p.name: w.file_hash(p) for p in failed.iterdir()} == snapshot
    with w.locked(project), pytest.raises(ValueError, match="busy"), w.locked(project):
        pytest.fail("concurrent writer was admitted")


def test_saved_source_refuses_mutation_and_cross_project_restore():
    project, _, args = prepare()
    source = tool("import_evidence_source", args)
    directory = w.source_directory(project, args["source_id"])
    tool("init_project", {"name": "Another evidence project"})
    other = get_session().get_project()
    tool(
        "get_evidence_source",
        {"project_id": other.id, "source_id": source["source_id"]},
        error=True,
    )
    (directory / "source/data.csv").write_bytes(b"different source")
    tool("import_evidence_source", args, error=True)
    tool(
        "get_evidence_source",
        {"project_id": project.id, "source_id": source["source_id"]},
        error=True,
    )
