"""External MCP restart and pinned independent R check of synthetic binary arms."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests/fixtures/evidence-arms"


def save(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8"
    )


async def smoke(destination, r_image):
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
    counter = 0

    async def tool(session, name, args, *, error=False, parse=True):
        nonlocal counter
        response = await session.call_tool(name, args, read_timeout_seconds=120)
        text = "\n".join(c.text for c in response.content if hasattr(c, "text"))
        counter += 1
        save(
            calls / f"{counter:04d}-{name}.json",
            {"tool": name, "arguments": args, "is_error": response.is_error, "response": text},
        )
        assert response.is_error is error, text
        return json.loads(text) if parse and not error else text

    async def arm(session, project_id, request, **kwargs):
        return await tool(
            session,
            "evidence_arm_preparation",
            {"project_id": project_id, "request": request},
            **kwargs,
        )

    async def read_all(session, project_id, request):
        whole = ""
        while True:
            page = await arm(session, project_id, {**request, "text_limit": 6000})
            whole += page["text_excerpt"]
            if page["next_text_offset"] is None:
                break
            request = {
                **request,
                "text_offset": page["next_text_offset"],
                "expected_text_sha256": page["text_sha256"],
            }
        assert hashlib.sha256(whole.encode()).hexdigest() == page["text_sha256"]
        return json.loads(whole)

    runs, numeric = [], {}
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert "evidence_arm_preparation" in {t.name for t in tools.tools}
        save(destination / "live-tools.json", [t.name for t in tools.tools])
        await arm(session, "", {"op": "contract"})
        setup = await tool(
            session,
            "init_project",
            {
                "name": "Binary arm preparation software QA",
                "research_question": "Synthetic source, approval, arithmetic and restart verification only.",
            },
            parse=False,
        )
        project_id = re.search(r"專案 ID:\*\* ([a-f0-9]{8})", setup).group(1)
        metadata = json.loads(
            next((destination / "workspace/data/projects").glob("*.json")).read_text()
        )
        project_root = Path(metadata["output_dir"])
        for measure in ("OR", "RR"):
            preparation_id = str(uuid.uuid4())
            source = project_root / "incoming/evidence-arms" / preparation_id / "source.csv"
            source.parent.mkdir(parents=True)
            source.write_bytes((FIXTURES / "source.csv").read_bytes())
            specification = json.loads((FIXTURES / "spec.json").read_text())
            specification["measure"] = measure
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            request = {
                "op": "draft",
                "preparation_id": preparation_id,
                "filename": source.name,
                "source_sha256": source_hash,
                "specification": specification,
            }
            await arm(session, project_id, {**request, "source_sha256": "0" * 64}, error=True)
            plan = await arm(session, project_id, request)
            assert plan["ready_for_approval"]
            await read_all(
                session,
                project_id,
                {"op": "read", "preparation_id": preparation_id, "part": "plan"},
            )
            review = await read_all(
                session,
                project_id,
                {"op": "read", "preparation_id": preparation_id, "part": "review"},
            )
            assert not review["errors"] and len(review["arms"]) == 11
            execution = {
                "op": "execute",
                "preparation_id": preparation_id,
                "expected_plan_sha256": plan["receipt_sha256"],
                "expected_approval_sha256": "0" * 64,
                "run_id": str(uuid.uuid4()),
            }
            await arm(session, project_id, execution, error=True)
            approval = await arm(
                session,
                project_id,
                {
                    "op": "approve",
                    "preparation_id": preparation_id,
                    "expected_plan_sha256": plan["receipt_sha256"],
                    "review": {
                        "reviewer": "User-authorized engineering QA",
                        "note": "Read complete synthetic source mapping and method review; software verification only, no clinical adoption.",
                        "confirmations": {key: True for key in plan["required_confirmations"]},
                    },
                },
            )
            execution["expected_approval_sha256"] = approval["receipt_sha256"]
            await arm(
                session, project_id, {**execution, "expected_plan_sha256": "0" * 64}, error=True
            )
            receipt = await arm(session, project_id, execution)
            numeric[measure] = await read_all(
                session,
                project_id,
                {
                    "op": "read",
                    "preparation_id": preparation_id,
                    "part": "result",
                    "run_id": execution["run_id"],
                },
            )
            runs.append({"request": execution, "receipt": receipt})
        assert metadata["dataset_ids"] == []
    frozen = {
        str(path.relative_to(project_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (project_root / "artifacts/evidence_arm_preparation").rglob("*")
        if path.is_file()
    }
    # A new OS subprocess, not a reused in-memory MCP session.
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        for run in runs:
            assert await arm(session, project_id, run["request"]) == run["receipt"]
            await read_all(
                session,
                project_id,
                {
                    "op": "read",
                    "preparation_id": run["request"]["preparation_id"],
                    "part": "result",
                    "run_id": run["request"]["run_id"],
                },
            )
        await tool(session, "get_pipeline_status", {"project_id": project_id}, parse=False)
    assert all(
        hashlib.sha256((project_root / path).read_bytes()).hexdigest() == sha
        for path, sha in frozen.items()
    )
    save(destination / "frozen-hashes.json", frozen)
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--cpus",
        "2",
        "--memory",
        "2g",
        "--pids-limit",
        "128",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=128m",
        "-e",
        "OPENBLAS_NUM_THREADS=1",
        "-e",
        "OMP_NUM_THREADS=1",
        "--mount",
        f"type=bind,src={FIXTURES},dst=/fixtures,readonly",
        "--entrypoint",
        "Rscript",
        r_image,
        "/fixtures/reference.R",
    ]
    completed = await asyncio.to_thread(
        subprocess.run, command, capture_output=True, text=True, timeout=120, check=False
    )
    save(
        destination / "r-execution.json",
        {
            "argv": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "script_sha256": hashlib.sha256((FIXTURES / "reference.R").read_bytes()).hexdigest(),
            "source_sha256": hashlib.sha256((FIXTURES / "source.csv").read_bytes()).hexdigest(),
        },
    )
    assert completed.returncode == 0, completed.stderr
    reference = json.loads(completed.stdout)
    assert reference["versions"]["meta"] == "8.5.0" and reference["versions"]["netmeta"] == "3.7.0"
    max_difference = 0
    for measure, result in numeric.items():
        expected = reference["results"][measure]
        assert len(result["contrasts"]) == len(expected) == 4
        for actual, target in zip(result["contrasts"], expected, strict=True):
            assert all(actual[k] == target[k] for k in ("study_id", "treatment", "comparator"))
            for field in ("effect", "se"):
                assert math.isclose(actual[field], target[field], rel_tol=1e-12, abs_tol=1e-12), (
                    measure,
                    actual,
                    target,
                )
                max_difference = max(max_difference, abs(actual[field] - target[field]))
    summary = {
        "scope": "Synthetic engineering QA only; not the Cipriani clinical analysis",
        "project_id": project_id,
        "runs": runs,
        "independent_R": reference["versions"],
        "max_absolute_difference": max_difference,
        "restart_all_frozen_hashes_unchanged": True,
        "mcp_calls": counter,
    }
    save(destination / "summary.json", summary)
    print(
        json.dumps(
            {
                "destination": str(destination),
                "max_absolute_difference": max_difference,
                "mcp_calls": counter,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--r-image", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", args.r_image):
        parser.error("--r-image must be an immutable local Docker image SHA256")
    asyncio.run(smoke(args.destination.resolve(), args.r_image))
