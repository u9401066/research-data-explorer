"""Smoke test that launches RDE the way Codex does: MCP over stdio."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "iris_sample.csv"
DATASET_ID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
REQUIRED_TOOLS = {
    "init_project",
    "run_intake",
    "build_schema",
    "profile_dataset",
    "assess_quality",
    "get_approval_card",
    "get_harness_dashboard",
    "build_artifact_index",
    "get_blocker_playbook",
    "assemble_report",
    "propose_analysis_plan",
    "register_analysis_plan",
}


def _result_text(result: Any) -> str:
    content = getattr(result, "content", None)
    if isinstance(content, (list, tuple)):
        blocks = content
    elif isinstance(result, tuple) and result and isinstance(result[0], (list, tuple)):
        blocks = result[0]
    else:
        blocks = result if isinstance(result, (list, tuple)) else [result]
    parts: list[str] = []
    for block in blocks:
        text = getattr(block, "text", None)
        parts.append(text if isinstance(text, str) else str(block))
    return "\n".join(parts)


def _tool_names(list_tools_result: Any) -> list[str]:
    tools = getattr(list_tools_result, "tools", list_tools_result)
    return sorted(str(getattr(tool, "name", tool)) for tool in tools)


def _server_env(repo_root: Path, workspace: Path) -> dict[str, str]:
    env = os.environ.copy()
    src = str(repo_root / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src if not existing_pythonpath else src + os.pathsep + existing_pythonpath
    env["RDE_WORKSPACE"] = str(workspace)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


async def _open_session(repo_root: Path, workspace: Path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "rde"],
        env=_server_env(repo_root, workspace),
    )
    return stdio_client(params)


async def _call(session: ClientSession, name: str, args: dict[str, Any]) -> str:
    result = await session.call_tool(name, args)
    text = _result_text(result)
    lowered = text.lower()
    if "traceback" in lowered or "failed:" in lowered or "❌" in text:
        raise RuntimeError(f"{name} returned an error:\n{text}")
    return text


def _prepare_fixture(workspace: Path) -> Path:
    raw_dir = workspace / "rawdata"
    raw_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIXTURE, raw_dir / FIXTURE.name)
    return raw_dir


def _find_report(workspace: Path) -> Path:
    reports = sorted(
        (workspace / "data" / "projects").glob(
            "*/artifacts/phase_10_report_assembly/eda_report.md"
        )
    )
    if not reports:
        raise RuntimeError("No phase_10_report_assembly/eda_report.md artifact was created.")
    return reports[-1]


async def run_list_tools(repo_root: Path, workspace: Path) -> list[str]:
    async with await _open_session(repo_root, workspace) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = _tool_names(await session.list_tools())
            missing = sorted(REQUIRED_TOOLS - set(names))
            if missing:
                raise RuntimeError(f"Missing required RDE MCP tools: {', '.join(missing)}")
            return names


async def run_quick_explore(repo_root: Path, workspace: Path) -> Path:
    raw_dir = _prepare_fixture(workspace)
    async with await _open_session(repo_root, workspace) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = _tool_names(await session.list_tools())
            missing = sorted(REQUIRED_TOOLS - set(names))
            if missing:
                raise RuntimeError(f"Missing required RDE MCP tools: {', '.join(missing)}")

            await _call(
                session,
                "init_project",
                {
                    "name": "codex-rde-quick-smoke",
                    "data_dir": str(raw_dir),
                    "research_question": "Do iris species differ in petal length?",
                    "mode": "quick_explore",
                },
            )
            intake_text = await _call(session, "run_intake", {"directory": str(raw_dir)})
            dataset_ids = DATASET_ID_RE.findall(intake_text)
            if not dataset_ids:
                raise RuntimeError(
                    f"Could not parse dataset_id from run_intake output:\n{intake_text}"
                )
            dataset_id = dataset_ids[-1]

            await _call(session, "build_schema", {"dataset_id": dataset_id})
            await _call(session, "profile_dataset", {"dataset_id": dataset_id})
            await _call(session, "assess_quality", {"dataset_id": dataset_id})
            await _call(session, "get_approval_card", {})
            await _call(session, "get_harness_dashboard", {})
            await _call(session, "build_artifact_index", {})
            await _call(session, "get_blocker_playbook", {})
            await _call(
                session,
                "assemble_report",
                {
                    "title": "Quick Explore -- Not Audited",
                    "allow_incomplete": True,
                },
            )
    report = _find_report(workspace)
    report_text = report.read_text(encoding="utf-8")
    if "Quick Explore -- Not Audited" not in report_text:
        raise RuntimeError(f"Quick Explore report title missing from {report}")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-tools-only", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Workspace for generated smoke artifacts. Defaults to a temporary directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()

    if args.workspace is not None:
        workspace = args.workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        names = asyncio.run(run_list_tools(repo_root, workspace)) if args.list_tools_only else None
        if args.list_tools_only:
            required = " ".join(sorted(REQUIRED_TOOLS & set(names)))
            print(f"tools={len(names)} required=ok {required}")
            return 0
        report = asyncio.run(run_quick_explore(repo_root, workspace))
        print(f"workflow=ok report={report}")
        return 0

    with tempfile.TemporaryDirectory(prefix="rde-codex-smoke-") as tmp:
        workspace = Path(tmp)
        if args.list_tools_only:
            names = asyncio.run(run_list_tools(repo_root, workspace))
            required = " ".join(sorted(REQUIRED_TOOLS & set(names)))
            print(f"tools={len(names)} required=ok {required}")
            return 0
        report = asyncio.run(run_quick_explore(repo_root, workspace))
        print(f"workflow=ok report={report}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
