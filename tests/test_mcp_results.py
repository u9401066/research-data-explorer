"""Real MCP contract checks for identity, complete bytes and stale references."""

import asyncio
import base64
import hashlib
import shutil
from pathlib import Path

from mcp import Client

from rde.interface.mcp.results import RdeResult, artifact_paths, artifact_reference
from rde.interface.mcp.server import create_server


def test_bootstrap_and_paged_artifacts_are_machine_readable_and_project_scoped(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copy(Path(__file__).parent / "fixtures/iris_sample.csv", raw / "iris.csv")

    async def run():
        async with Client(create_server()) as client:

            async def call(tool, **args):
                result = await client.call_tool(tool, args)
                payload = RdeResult.model_validate(result.structured_content)
                assert result.is_error == (payload.status == "error")
                return payload

            setup = await call("init_project", name="研究_日本語_underscores", data_dir=str(raw))
            pid = setup.context.project_id
            assert pid and setup.context.project_root and setup.artifacts
            intake = await call("run_intake", project_id=pid, directory=str(raw))
            assert intake.status == "ok", intake.message
            ds = intake.data["dataset_id"]
            assert ds in intake.context.dataset_ids
            assert (
                intake.context.sources[0].sha256
                == hashlib.sha256((raw / "iris.csv").read_bytes()).hexdigest()
            )
            assert intake.context.sources[0].dataset_id == ds
            built = await call("build_schema", project_id=pid, dataset_id=ds)
            ref = next(item for item in built.artifacts if item.role == "schema")
            assert built.data["dataset_id"] == ds and ref.project_id == pid
            pieces = []
            offset = 0
            while True:
                page = await call(
                    "read_artifact",
                    project_id=pid,
                    artifact_id=ref.artifact_id,
                    expected_sha256=ref.sha256,
                    offset=offset,
                    limit=97,
                )
                assert page.status == "ok", page.message
                assert page.data["artifact"] == ref.model_dump()
                pieces.append(base64.b64decode(page.data["content_base64"], validate=True))
                offset = page.data["next_offset"]
                if offset is None:
                    break
            complete = b"".join(pieces)
            assert len(complete) == ref.bytes
            assert hashlib.sha256(complete).hexdigest() == ref.sha256

            other = await call("init_project", name="other")
            wrong = await call(
                "read_artifact",
                project_id=other.context.project_id,
                artifact_id=ref.artifact_id,
                expected_sha256=ref.sha256,
            )
            assert wrong.status == "error" and not wrong.error.retryable
            missing = await call(
                "read_artifact",
                project_id="unknown",
                artifact_id=ref.artifact_id,
                expected_sha256=ref.sha256,
            )
            assert missing.status == "error" and missing.context.project_id is None
            # A failed bootstrap must not leak the previously active project.
            invalid = await call("init_project", name="")
            assert invalid.context.project_id is None and invalid.artifacts == []

            target = Path(setup.context.project_root) / ref.relative_path
            target.write_bytes(complete + b"\n")
            stale = await call(
                "read_artifact",
                project_id=pid,
                artifact_id=ref.artifact_id,
                expected_sha256=ref.sha256,
            )
            assert stale.error.code == "STALE_ARTIFACT"

    asyncio.run(run())


def test_artifact_pages_keep_unicode_and_exclude_symlinks(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch
    from rde.interface.mcp.results import read_artifact_page

    root = tmp_path / "project"
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    text = artifacts / "中文.md"
    original = "研究問題🧪\n".encode()
    text.write_bytes(original)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("unrelated")
    (artifacts / "escape").symlink_to(outside, target_is_directory=True)
    (artifacts / "alias.txt").symlink_to(outside / "secret.txt")
    project = SimpleNamespace(id="project", output_dir=root)
    paths = artifact_paths(project)
    assert list(paths) == ["artifacts/中文.md"]
    ref = artifact_reference(project, "artifacts/中文.md", text)
    with patch("rde.application.session.get_session") as session:
        session.return_value.get_project.return_value = project
        chunks = [
            base64.b64decode(
                read_artifact_page(project.id, ref.artifact_id, ref.sha256, offset=index, limit=1)[
                    "content_base64"
                ]
            )
            for index in range(len(original))
        ]
    assert b"".join(chunks) == original


def test_intake_refuses_source_changed_during_parse(tmp_path, monkeypatch):
    from rde.infrastructure.adapters import PandasLoader

    raw = tmp_path / "raw"
    raw.mkdir()
    source = raw / "iris.csv"
    shutil.copy(Path(__file__).parent / "fixtures/iris_sample.csv", source)
    original = PandasLoader.load

    def changed(self, metadata, *args, **kwargs):
        result = original(self, metadata, *args, **kwargs)
        source.write_bytes(source.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(PandasLoader, "load", changed)

    async def run():
        async with Client(create_server()) as client:
            setup = await client.call_tool("init_project", {"name": "changing-source"})
            pid = setup.structured_content["context"]["project_id"]
            result = await client.call_tool(
                "run_intake", {"project_id": pid, "directory": str(raw)}
            )
            payload = RdeResult.model_validate(result.structured_content)
            assert result.is_error and payload.error.code == "SOURCE_CHANGED"
            assert payload.context.sources == [] and payload.context.dataset_ids == []

    asyncio.run(run())
