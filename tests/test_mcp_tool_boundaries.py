"""Exercise every public tool in an isolated, empty/missing-context workspace.

This is boundary/error coverage, not a claim of exhaustive clinical validation.
Successful workflows and numerical edge cases have their own regression suites.
"""

import asyncio

import pytest

from rde.interface.mcp.contracts import CONTRACTS
from rde.interface.mcp.server import create_server


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_every_tool_returns_a_structured_boundary_result(name, tmp_path):
    async def call():
        server = create_server()
        tool = next(tool for tool in await server.list_tools() if tool.name == name)
        schema = tool.input_schema
        properties = schema.get("properties", {})
        values = {}
        for key in schema.get("required", []):
            definition = properties[key]
            kind = definition.get("type", "string")
            values[key] = {
                "string": "missing-context",
                "array": [],
                "object": {},
                "boolean": False,
                "integer": 1,
                "number": 1.0,
            }.get(kind, "missing-context")
        for key in ("project_id", "dataset_id"):
            if key in properties:
                values[key] = "missing-context"
        for key in ("directory", "data_dir", "output_dir"):
            if key in properties:
                values[key] = str(tmp_path / key)
        if "file_path" in properties:
            values["file_path"] = str(tmp_path / "nonexistent.csv")
        if name == "init_project":
            values["name"] = "boundary-review"
        result = await server.call_tool(name, values)
        assert result.content, name
        assert result.structured_content is not None, name
        assert result.structured_content["rde_tool"] == name
        if name not in {
            "init_project",
            "scan_data_folder",
            "get_approval_card",
            "get_blocker_playbook",
            "get_workflow_contract",
        }:
            assert result.is_error, (name, result)
        return result

    asyncio.run(call())
