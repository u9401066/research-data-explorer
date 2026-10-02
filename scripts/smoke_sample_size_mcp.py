"""External stdio MCP planning/figures/restart smoke; synthetic QA assumptions only."""

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


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def smoke(destination, font_dir):
    destination.mkdir(parents=True, exist_ok=False)
    catalog = json.loads((REPO / "tests/fixtures/sample-size/plans.json").read_text())
    summaries = []
    for case in catalog:
        workspace = destination / case["id"]
        calls = workspace / "calls"
        calls.mkdir(parents=True)
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "rde"],
            cwd=REPO,
            env={
                **os.environ,
                "PYTHONPATH": str(REPO / "src"),
                "RDE_WORKSPACE": str(workspace),
                **({"RDE_PUBLICATION_FONT_DIR": str(font_dir)} if font_dir else {}),
            },
        )

        async def call(session, name, arguments, tag, *, parse=True, expect_error=False):
            response = await session.call_tool(name, arguments, read_timeout_seconds=120)
            content = "\n".join(c.text for c in response.content if hasattr(c, "text"))
            (calls / f"{tag}.json").write_text(
                json.dumps(
                    {
                        "tool": name,
                        "arguments": arguments,
                        "is_error": response.is_error,
                        "response": content,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            assert response.is_error is expect_error, content
            return json.loads(content) if parse and not expect_error else content

        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            setup = await call(
                session,
                "init_project",
                {
                    "name": "Synthetic sample-size " + case["id"],
                    "research_question": "Engineering verification only; no clinical recommendation",
                },
                "00-init",
                parse=False,
            )
            project_id = re.search(r"專案 ID:\*\* ([a-f0-9]{8})", setup).group(1)
            identity = {"project_id": project_id, "plan_id": str(uuid.uuid4())}
            plan = await call(
                session,
                "draft_sample_size_plan",
                {**identity, "planning_options": case["planning_options"]},
                "01-draft",
            )
            review = await call(session, "get_sample_size_plan", identity, "02-review")
            assert review["approval"] is None and review["runs"] == []
            args = {
                **identity,
                "expected_plan_sha256": plan["receipt_sha256"],
                "expected_approval_sha256": "0" * 64,
                "run_id": str(uuid.uuid4()),
            }
            await call(
                session, "run_sample_size_plan", args, "03-unapproved-denied", expect_error=True
            )
            approved = await call(
                session,
                "approve_sample_size_plan",
                {
                    **identity,
                    "expected_plan_sha256": plan["receipt_sha256"],
                    "review": {
                        "reviewer": "User-authorized engineering QA",
                        "note": "Synthetic assumptions reviewed for numerical and workflow verification; not clinical advice.",
                        "confirmations": {k: True for k in plan["required_confirmations"]},
                    },
                },
                "04-approval",
            )
            args["expected_approval_sha256"] = approved["receipt_sha256"]
            run = await call(session, "run_sample_size_plan", args, "05-run")
            root = next((workspace / "data/projects").glob("*.json"))
            metadata = json.loads(root.read_text())
            root = Path(metadata["output_dir"])
            assert metadata["dataset_ids"] == []
            frozen = {str(root / a["path"]): a["sha256"] for a in run["artifacts"]}
            numerical = json.loads((root / run["result_path"]).read_text())
            for row in numerical["scenarios"]:
                assert row["achieved_power"] >= plan["spec"]["target_power"]
                assert row["previous_allocation"]["power"] < plan["spec"]["target_power"]
            edition_args, editions = [], []
            for preset in (
                ["nature-single-v1", "plos-column-v1"]
                if font_dir
                else ["journal-neutral-english-v1"]
            ):
                request = {
                    **identity,
                    "run_id": run["run_id"],
                    "expected_run_sha256": run["receipt_sha256"],
                    "preset_id": preset,
                    "edition_id": str(uuid.uuid4()),
                    "start_number": 3,
                }
                edition = await call(
                    session, "render_sample_size_publication", request, "06-" + preset
                )
                for first, second in zip(run["figures"], edition["figures"], strict=True):
                    assert (
                        Path(first["publication"]["files"]["data"]).read_bytes()
                        == Path(second["publication"]["files"]["data"]).read_bytes()
                    )
                    assert (
                        first["publication"]["original_caption"]
                        == second["publication"]["original_caption"]
                    )
                frozen.update({str(root / a["path"]): a["sha256"] for a in edition["artifacts"]})
                edition_args.append(request)
                editions.append(edition)
            assert all(sha(Path(p)) == expected for p, expected in frozen.items())
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            restored = await call(session, "get_sample_size_plan", identity, "07-restart-read")
            assert restored["runs"] == [run] and restored["approval"] == approved
            assert await call(session, "run_sample_size_plan", args, "08-restart-run") == run
            for i, request in enumerate(edition_args):
                assert (
                    await call(
                        session,
                        "render_sample_size_publication",
                        request,
                        f"09-restart-edition-{i}",
                    )
                    == editions[i]
                )
            assert all(sha(Path(p)) == expected for p, expected in frozen.items())
        summaries.append(
            {
                "case": case["id"],
                **identity,
                "run": run,
                "editions": editions,
                "verified_files": len(frozen),
                "restart_exact": True,
                "patient_datasets": 0,
            }
        )
        print(case["id"], "verified", len(frozen), "files; restart exact", flush=True)
    (destination / "verification.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New output directory; existing evidence is never overwritten",
    )
    parser.add_argument(
        "--font-dir", type=Path, help="Authorized Arial font directory for Nature/PLOS presets"
    )
    options = parser.parse_args()
    asyncio.run(smoke(options.output.resolve(), options.font_dir))
