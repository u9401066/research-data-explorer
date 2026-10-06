import asyncio
import hashlib
from uuid import uuid4

from mcp import Client
from rde.interface.mcp.server import create_server


def test_native_plan_revisions_approval_source_and_result_reuse(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("a,b\n1,2\n")
    ref = {
        "path": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "bytes": source.stat().st_size,
    }

    async def run():
        async with Client(create_server()) as client:
            setup = await client.call_tool("init_project", {"name": "native-versions"})
            pid = setup.structured_content["context"]["project_id"]

            async def call(request, error=False):
                result = await client.call_tool(
                    "research_plan", {"project_id": pid, "request": request}
                )
                assert bool(result.is_error) == error, result.content
                return result.structured_content["data"]

            plan_id = str(uuid4())
            protocol = {
                "question": "Synthetic research",
                "steps": [{"method": "mean"}],
                "sourceHash": ref["sha256"],
                "schemaHash": ref["sha256"],
                "sampleSizeBasis": {"n": 40, "assumptions": "synthetic"},
            }
            draft = {
                "op": "draft",
                "plan_id": plan_id,
                "protocol": protocol,
                "sources": [ref],
                "reason": "initial",
            }
            first = await call(draft)
            assert first == await call(draft)
            await call({**draft, "protocol": {**protocol, "question": "overwrite"}}, True)
            await call(
                {
                    "op": "approve",
                    "plan_id": plan_id,
                    "expected_sha256": "0" * 64,
                    "reviewer": {"kind": "human"},
                },
                True,
            )
            approved = await call(
                {
                    "op": "approve",
                    "plan_id": plan_id,
                    "expected_sha256": first["sha256"],
                    "reviewer": {"kind": "human", "account": "synthetic"},
                }
            )
            assert approved["approval"]
            eid = str(uuid4())
            await call(
                {
                    "op": "attach_results",
                    "plan_id": plan_id,
                    "expected_sha256": first["sha256"],
                    "execution_id": eid,
                    "artifacts": [ref],
                }
            )
            second_id = str(uuid4())
            second = await call(
                {
                    **draft,
                    "plan_id": second_id,
                    "intent": "append",
                    "parent": {"plan_id": plan_id, "sha256": first["sha256"]},
                }
            )
            assert second["reuse_eligible"] and len(second["available_results"]) == 1
            await call(
                {
                    "op": "approve",
                    "plan_id": second_id,
                    "expected_sha256": second["sha256"],
                    "reviewer": {"kind": "agent"},
                }
            )
            reused = await call(
                {
                    "op": "reuse",
                    "plan_id": second_id,
                    "expected_sha256": second["sha256"],
                    "execution_id": eid,
                }
            )
            assert reused["reuse"][0]["payload"]["kind"] == "reused_reference_only"
            revised_id = str(uuid4())
            revised = await call(
                {
                    **draft,
                    "plan_id": revised_id,
                    "protocol": {**protocol, "sampleSizeBasis": {"n": 50}},
                    "intent": "revise",
                    "parent": {"plan_id": plan_id, "sha256": first["sha256"]},
                }
            )
            assert not revised["reuse_eligible"]
            assert any(c["path"] == "/sampleSizeBasis/n" for c in revised["payload"]["changes"])
            source.write_text("changed")
            await call(
                {
                    "op": "approve",
                    "plan_id": revised_id,
                    "expected_sha256": revised["sha256"],
                    "reviewer": {"kind": "human"},
                },
                True,
            )
            assert (await call({"op": "read", "plan_id": plan_id}))["sha256"] == first["sha256"]

    asyncio.run(run())
