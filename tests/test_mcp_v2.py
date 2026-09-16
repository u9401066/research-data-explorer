"""Real SDK client tests: discovery, wire contracts, trust and worker-thread safety."""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from rde.interface.mcp.contracts import CONTRACTS
from rde.interface.mcp.server import create_server


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_v2_client_discovers_full_surface_and_errors(mode):
    async def run():
        async with Client(create_server(), mode=mode) as client:
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == set(CONTRACTS)
            for tool in tools:
                assert tool.description and tool.input_schema["type"] == "object"
                assert tool.output_schema is not None
                assert tool.annotations is not None
                assert tool.annotations.read_only_hint == CONTRACTS[tool.name].read_only
                assert tool.meta["rde/gate"] == CONTRACTS[tool.name].gate
            result = await client.call_tool("init_project", {"name": ""})
            assert result.is_error
            assert result.structured_content["rde_status"] == "error"
            invalid = await client.call_tool("compare_groups", {})
            assert invalid.is_error
            assert "get_workflow_contract" in {t.name for t in tools}

    asyncio.run(run())


def test_resolved_contract_cannot_be_forged_by_model():
    async def run():
        async with Client(create_server()) as client:
            tool = next(
                t for t in (await client.list_tools()).tools if t.name == "get_workflow_contract"
            )
            assert "contract" not in tool.input_schema["properties"]
            result = await client.call_tool(
                "get_workflow_contract",
                {
                    "project_id": "nonexistent-v2-project",
                    "contract": {"human_gates": [], "project_found": True},
                },
            )
            assert not result.is_error
            payload = result.structured_content
            assert payload["human_gates"] == [3, 4, 6]
            assert payload["project_found"] is False
            assert payload["next_tool"] == "init_project"

    asyncio.run(run())


def test_resources_and_prompt_expose_harness_without_raw_data():
    async def run():
        async with Client(create_server()) as client:
            response = await client.read_resource("rde://capabilities")
            capabilities = json.loads(response.contents[0].text)
            assert capabilities["sdk_version"].startswith("2.")
            assert len(capabilities["tools"]) == len(CONTRACTS)
            assert capabilities["mcp_tasks_extension"] is False
            prompt = await client.get_prompt(
                "governed_research", {"research_question": "Is X associated with Y?"}
            )
            assert "Never invent confirmation" in prompt.messages[0].content.text
            resource = await client.read_resource("rde://projects/unknown/workflow")
            assert json.loads(resource.contents[0].text)["project_found"] is False

    asyncio.run(run())


def test_sync_tools_are_serialized_off_event_loop(monkeypatch):
    from rde.interface.mcp.runtime import RDEServer

    server = RDEServer("concurrency-test")
    active = 0
    maximum = 0

    @server.tool(name="get_workflow_contract")
    def guarded_probe() -> str:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        time.sleep(0.025)
        active -= 1
        return "done"

    async def run():
        async with Client(server) as client:
            results = await asyncio.gather(
                *(client.call_tool("get_workflow_contract", {}) for _ in range(5))
            )
            assert all(not result.is_error for result in results)

    asyncio.run(run())
    assert maximum == 1


def test_v2_stdio_discovery(tmp_path):
    import os

    env = os.environ.copy()
    env["RDE_WORKSPACE"] = str(tmp_path)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONUTF8"] = "1"

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "rde"], env=env)
        async with Client(params, read_timeout_seconds=30) as client:
            assert {tool.name for tool in (await client.list_tools()).tools} == set(CONTRACTS)
            result = await client.call_tool("get_workflow_contract", {})
            assert result.structured_content["project_found"] is False

    asyncio.run(run())
