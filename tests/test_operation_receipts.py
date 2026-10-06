import asyncio
import base64
import hashlib
import shutil
from pathlib import Path

from mcp import Client
from rde.interface.mcp.server import create_server
from rde.interface.mcp.operations import begin
from rde.application import session


def test_completed_receipts_survive_restart_and_ambiguous_operations_never_repeat(
    tmp_path, monkeypatch
):
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copy(Path(__file__).parent / "fixtures/iris_sample.csv", raw / "iris.csv")

    async def run():
        async with Client(create_server()) as client:
            setup = (
                await client.call_tool("init_project", {"name": "durable", "data_dir": str(raw)})
            ).structured_content
            pid = setup["context"]["project_id"]
            key = "a" * 64
            args = {"project_id": pid, "directory": str(raw), "execution_key": key}
            original = (await client.call_tool("run_intake", args)).structured_content
            assert original["status"] == "ok", original
            ref = next(r for r in original["artifacts"] if r["role"] == "intake")
            assert ref["relative_path"].startswith(".rde_operations/")
        monkeypatch.setattr(session, "_session", session.SessionRegistry())
        async with Client(create_server()) as restarted:
            again = await restarted.call_tool("run_intake", args)
            assert again.structured_content == original
            # Modifying a mutable original does not alter the completed immutable receipt.
            live = (
                Path(setup["context"]["project_root"])
                / "artifacts/phase_01_data_intake/intake_report.json"
            )
            old = live.read_bytes()
            live.write_bytes(old + b"\n")
            page = await restarted.call_tool(
                "read_artifact",
                {
                    "project_id": pid,
                    "artifact_id": ref["artifact_id"],
                    "expected_sha256": ref["sha256"],
                },
            )
            assert not page.is_error, page.content
            assert page.structured_content["data"]["artifact"] == ref
            assert (
                hashlib.sha256(
                    base64.b64decode(page.structured_content["data"]["content_base64"])
                ).hexdigest()
                == ref["sha256"]
            )
            conflict = await restarted.call_tool("run_intake", {**args, "allow_pii": True})
            assert conflict.structured_content["error"]["code"] == "EXECUTION_CONFLICT"
            project = session.get_session().get_project(pid)
            # A killed process may persist only intent. Recovery must not guess completion.
            begin(
                project, "b" * 64, "profile_dataset", {"dataset_id": original["data"]["dataset_id"]}
            )
            uncertain = await restarted.call_tool(
                "profile_dataset",
                {"dataset_id": original["data"]["dataset_id"], "execution_key": "b" * 64},
            )
            assert uncertain.structured_content["error"]["code"] == "EXECUTION_INDETERMINATE"
            snapshot = project.output_dir / ref["relative_path"]
            snapshot.write_bytes(b"corrupt")
            corrupt = await restarted.call_tool("run_intake", args)
            assert corrupt.structured_content["error"]["code"] == "CORRUPT_EXECUTION"

    asyncio.run(run())
