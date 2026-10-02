"""Create and completely read a source-arm draft via external MCP; never approve."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO = Path(__file__).resolve().parents[1]


async def review(destination, source, expected_sha, specification):
    original = source.read_bytes()
    if hashlib.sha256(original).hexdigest() != expected_sha:
        raise ValueError("Original source differs from the explicitly supplied SHA256.")
    options = json.loads(specification.read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=False)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "rde"],
        cwd=REPO,
        env={
            **os.environ,
            "PYTHONPATH": str(REPO / "src"),
            "RDE_WORKSPACE": str(destination / "workspace"),
        },
    )
    calls = destination / "calls"
    calls.mkdir()
    count = 0

    async def call(session, name, arguments, *, parse=True):
        nonlocal count
        response = await session.call_tool(name, arguments, read_timeout_seconds=120)
        text = "\n".join(c.text for c in response.content if hasattr(c, "text"))
        count += 1
        (calls / f"{count:04d}-{name}.json").write_text(
            json.dumps(
                {
                    "tool": name,
                    "arguments": arguments,
                    "is_error": response.is_error,
                    "response": text,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        assert not response.is_error, text
        return json.loads(text) if parse else text

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        await call(
            session, "evidence_arm_preparation", {"project_id": "", "request": {"op": "contract"}}
        )
        setup = await call(
            session,
            "init_project",
            {
                "name": "Aggregate trial arm source review",
                "research_question": "Review source mapping and unresolved clinical eligibility; no analysis approval or model execution.",
            },
            parse=False,
        )
        project_id = re.search(r"專案 ID:\*\* ([a-f0-9]{8})", setup).group(1)
        metadata = json.loads(
            next((destination / "workspace/data/projects").glob("*.json")).read_text()
        )
        project_root = Path(metadata["output_dir"])
        preparation_id = str(uuid.uuid4())
        incoming = project_root / "incoming/evidence-arms" / preparation_id / source.name
        incoming.parent.mkdir(parents=True)
        incoming.write_bytes(original)
        draft = await call(
            session,
            "evidence_arm_preparation",
            {
                "project_id": project_id,
                "request": {
                    "op": "draft",
                    "preparation_id": preparation_id,
                    "filename": source.name,
                    "source_sha256": expected_sha,
                    "specification": options,
                },
            },
        )
        for part in ("plan", "grid", "review"):
            request = {
                "op": "read",
                "preparation_id": preparation_id,
                "part": part,
                "text_limit": 64000,
            }
            whole = ""
            while True:
                page = await call(
                    session,
                    "evidence_arm_preparation",
                    {"project_id": project_id, "request": request},
                )
                assert page["approval"] is None and page["attempts"] == []
                whole += page["text_excerpt"]
                if page["next_text_offset"] is None:
                    break
                request.update(
                    text_offset=page["next_text_offset"], expected_text_sha256=page["text_sha256"]
                )
            assert hashlib.sha256(whole.encode()).hexdigest() == page["text_sha256"]
            (destination / (part + ".json")).write_text(whole, encoding="utf-8")
        await call(session, "get_pipeline_status", {"project_id": project_id}, parse=False)
        assert metadata["dataset_ids"] == []
    summary = {
        "scope": "Source review only; no approval, contrast calculation or meta-analysis",
        "project_id": project_id,
        "preparation_id": preparation_id,
        "draft": draft,
        "mcp_calls": count,
    }
    (destination / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--specification", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(
        review(
            args.destination.resolve(),
            args.source.resolve(),
            args.source_sha256,
            args.specification.resolve(),
        )
    )
