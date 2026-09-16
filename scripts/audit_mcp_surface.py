"""Read-only, executable review of every live registered MCP tool.

Run with ``uv run python scripts/audit_mcp_surface.py``. The JSON output is a
review inventory, not a claim that every possible clinical input was tested.
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rde.interface.mcp.contracts import CONTRACTS  # noqa: E402
from rde.interface.mcp.server import create_server  # noqa: E402


async def audit() -> list[dict]:
    tools = await create_server().list_tools()
    manifest = json.loads((ROOT / "vscode-extension/package.json").read_text(encoding="utf-8"))
    names = {tool.name for tool in tools}
    assert names == set(CONTRACTS) == set(manifest["rde"]["expectedMcpTools"])
    rows = []
    for tool in sorted(tools, key=lambda item: item.name):
        assert tool.description and tool.input_schema and tool.output_schema
        assert tool.annotations is not None
        contract = CONTRACTS[tool.name]
        assert tool.annotations.read_only_hint == contract.read_only
        rows.append(
            {
                "tool": tool.name,
                "phase": contract.phase,
                "gate": contract.gate,
                "effects": contract.effects,
                "annotations": tool.annotations.model_dump(),
                "arguments": list(tool.input_schema.get("properties", {})),
                "required": tool.input_schema.get("required", []),
                "output_schema": tool.output_schema,
            }
        )
    return rows


if __name__ == "__main__":
    rows = asyncio.run(audit())
    print(json.dumps({"tool_count": len(rows), "tools": rows}, ensure_ascii=True, indent=2))
