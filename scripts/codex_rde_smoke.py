"""Smoke test that launches RDE the way Codex does: MCP over stdio."""

from __future__ import annotations

import argparse
import asyncio
import json
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
    "check_readiness",
    "suggest_cleaning",
    "apply_cleaning",
    "analyze_variable",
    "generate_table_one",
    "compare_groups",
    "correlation_matrix",
    "create_visualization",
    "run_advanced_analysis",
    "collect_results",
    "run_audit",
    "auto_improve",
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
        command="uv",
        args=["run", "--directory", str(repo_root), "python", "-m", "rde"],
        env=_server_env(repo_root, workspace),
    )
    return stdio_client(params)


async def _call(
    session: ClientSession,
    name: str,
    args: dict[str, Any],
    *,
    timeout_s: float = 180.0,
) -> str:
    print(f"[codex-rde-smoke] START {name}", flush=True)
    try:
        result = await asyncio.wait_for(session.call_tool(name, args), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{name} timed out after {timeout_s:.0f}s") from exc
    text = _result_text(result)
    lowered = text.lower()
    if (
        "traceback" in lowered
        or "failed:" in lowered
        or "tool call error" in lowered
        or text.lstrip().startswith("\u274c")
    ):
        raise RuntimeError(f"{name} returned an error:\n{text}")
    print(f"[codex-rde-smoke] DONE {name}", flush=True)
    return text


def _prepare_rawdata(workspace: Path, data_file: Path | None = None) -> Path:
    raw_dir = workspace / "rawdata"
    raw_dir.mkdir(parents=True, exist_ok=True)
    source = data_file if data_file is not None else FIXTURE
    shutil.copy2(source, raw_dir / source.name)
    return raw_dir


def _project_dirs(workspace: Path) -> list[Path]:
    projects_dir = workspace / "data" / "projects"
    if not projects_dir.exists():
        return []
    return sorted(path for path in projects_dir.iterdir() if path.is_dir())


def _latest_project_dir(workspace: Path) -> Path:
    project_dirs = _project_dirs(workspace)
    if not project_dirs:
        raise RuntimeError("No project directory was created.")
    return project_dirs[-1]


def _latest_project_id(workspace: Path) -> str:
    return _latest_project_dir(workspace).name.rsplit("_", 1)[-1]


def _find_report(workspace: Path) -> Path:
    reports = sorted(
        (workspace / "data" / "projects").glob(
            "*/artifacts/phase_10_report_assembly/eda_report.md"
        )
    )
    if not reports:
        raise RuntimeError("No phase_10_report_assembly/eda_report.md artifact was created.")
    return reports[-1]


def _load_latest_schema(workspace: Path) -> dict[str, Any]:
    schema_path = (
        _latest_project_dir(workspace)
        / "artifacts"
        / "phase_02_schema_registry"
        / "schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _infer_roles(schema: dict[str, Any]) -> dict[str, Any]:
    variables = schema.get("variables") or []
    names = [str(var.get("name")) for var in variables if var.get("name")]
    typed = {
        str(var.get("name")): str(var.get("variable_type", "")).lower()
        for var in variables
        if var.get("name")
    }

    def contains_any(name: str, terms: tuple[str, ...]) -> bool:
        lowered = name.lower()
        return any(term in lowered or term in name for term in terms)

    binary = [name for name in names if typed.get(name) == "binary"]
    continuous = [name for name in names if typed.get(name) == "continuous"]
    ordinal = [name for name in names if typed.get(name) == "ordinal"]
    ids = [name for name in names if typed.get(name) == "id"]

    group = next(
        (name for name in binary if contains_any(name, ("group", "treatment", "arm", "\u7d44", "\u4e2d\u7dda"))),
        binary[0] if binary else None,
    )
    success = next(
        (
            name
            for name in binary
            if name != group
            and contains_any(name, ("success", "mortality", "death", "outcome", "\u6210\u529f", "\u6b7b\u4ea1"))
        ),
        next((name for name in binary if name != group), None),
    )
    time_var = next(
        (name for name in continuous if contains_any(name, ("time", "sec", "minute", "\u6642\u9593"))),
        continuous[0] if continuous else None,
    )
    trial = next(
        (name for name in continuous if name != time_var and contains_any(name, ("trial", "order", "attempt", "\u6b21\u5e8f"))),
        next((name for name in continuous if name != time_var), None),
    )
    puncture = next(
        (name for name in ordinal if contains_any(name, ("puncture", "attempt", "\u6b21\u6578", "\u7a7f\u523a"))),
        ordinal[0] if ordinal else None,
    )
    operator = next(
        (name for name in ids if contains_any(name, ("operator", "doctor", "id", "\u65bd\u6253"))),
        ids[0] if ids else None,
    )
    outcomes = [name for name in (success, time_var, puncture) if name]
    analyzable = [name for name in names if typed.get(name) != "id"]
    numeric = [name for name in names if typed.get(name) in {"continuous", "ordinal", "binary"}]
    return {
        "all": names,
        "analyzable": analyzable,
        "numeric": numeric,
        "group": group,
        "success": success,
        "time": time_var,
        "trial": trial,
        "puncture": puncture,
        "operator": operator,
        "outcomes": outcomes,
    }


def _analysis_plan(roles: dict[str, Any]) -> list[dict[str, Any]]:
    group = roles.get("group")
    success = roles.get("success")
    time_var = roles.get("time")
    trial = roles.get("trial")
    puncture = roles.get("puncture")
    operator = roles.get("operator")
    outcomes = list(roles.get("outcomes") or [])
    analyses: list[dict[str, Any]] = [
        {
            "type": "analyze_variable",
            "variables": roles.get("analyzable") or outcomes,
            "rationale": "Profile high-value variables before downstream comparisons and models.",
        }
    ]
    for variable, plot_type, rationale in (
        (success, "bar", "Inspect binary outcome distribution."),
        (time_var, "histogram", "Inspect continuous time distribution."),
        (puncture, "bar", "Inspect ordinal attempt/count distribution."),
        (group, "bar", "Inspect group balance."),
    ):
        if variable:
            analyses.append(
                {
                    "type": "visualization",
                    "variables": [variable],
                    "plot_type": plot_type,
                    "rationale": rationale,
                }
            )
    if group and outcomes:
        analyses.extend(
            [
                {
                    "type": "generate_table_one",
                    "variables": [name for name in outcomes + ([trial] if trial else []) if name],
                    "group_variable": group,
                    "rationale": "Build a grouped cohort snapshot before inference.",
                },
                {
                    "type": "compare_groups",
                    "variables": [name for name in outcomes + ([trial] if trial else []) if name],
                    "group_variable": group,
                    "rationale": "Screen outcome differences by the primary group.",
                },
            ]
        )
    for variable, plot_type, rationale in (
        (success, "bar", "Compare binary outcome by group."),
        (time_var, "boxplot", "Compare time distribution by group."),
        (puncture, "bar", "Compare ordinal count by group."),
        (trial, "boxplot", "Check trial/order balance by group."),
    ):
        if variable and group:
            analyses.append(
                {
                    "type": "visualization",
                    "variables": [variable],
                    "plot_type": plot_type,
                    "group_variable": group,
                    "rationale": rationale,
                }
            )
    corr_vars = [name for name in (trial, time_var) if name]
    if len(corr_vars) >= 2:
        analyses.append(
            {
                "type": "correlation_matrix",
                "variables": corr_vars,
                "rationale": "Screen numeric association and collinearity structure.",
            }
        )
        analyses.append(
            {
                "type": "visualization",
                "variables": corr_vars,
                "plot_type": "heatmap",
                "rationale": "Visualize the numeric association structure.",
            }
        )
        if group:
            analyses.append(
                {
                    "type": "visualization",
                    "variables": corr_vars,
                    "plot_type": "scatter",
                    "group_variable": group,
                    "rationale": "Visualize trial/time relationship stratified by primary group.",
                }
            )
    if success and operator and trial:
        analyses.append(
            {
                "type": "run_advanced_analysis",
                "analysis_type": "learning_curve_cusum",
                "variables": [success, operator, trial],
                "target_variable": success,
                "group_variable": operator,
                "covariates": [trial],
                "rationale": "Preserve operator/trial learning-curve branch.",
            }
        )
        analyses.append(
            {
                "type": "visualization",
                "variables": [trial, success],
                "plot_type": "line",
                "group_variable": operator,
                "rationale": "Visualize learning progression by operator.",
            }
        )
    if success and group:
        covariates = [name for name in (group, trial) if name]
        analyses.append(
            {
                "type": "run_advanced_analysis",
                "analysis_type": "logistic_regression",
                "variables": [success] + covariates,
                "target_variable": success,
                "group_variable": group,
                "covariates": covariates,
                "problem_type": "binary",
                "rationale": "Estimate adjusted association with the binary outcome.",
            }
        )
    if time_var and group:
        covariates = [name for name in (group, trial, puncture) if name]
        analyses.append(
            {
                "type": "run_advanced_analysis",
                "analysis_type": "multiple_regression",
                "variables": [time_var] + covariates,
                "target_variable": time_var,
                "group_variable": group,
                "covariates": covariates,
                "problem_type": "regression",
                "rationale": "Estimate adjusted association with the continuous time outcome.",
            }
        )
    if group and trial:
        analyses.append(
            {
                "type": "run_advanced_analysis",
                "analysis_type": "propensity_score",
                "variables": [group, trial] + ([success] if success else []),
                "target_variable": success,
                "group_variable": group,
                "covariates": [trial],
                "problem_type": "binary" if success else None,
                "rationale": "Check lightweight propensity balance sensitivity.",
            }
        )
    return analyses


def _run_readiness_direct(repo_root: Path, workspace: Path, project_id: str) -> None:
    old_workspace = os.environ.get("RDE_WORKSPACE")
    os.environ["RDE_WORKSPACE"] = str(workspace)
    src = str(repo_root / "src")
    inserted = False
    if src not in sys.path:
        sys.path.insert(0, src)
        inserted = True
    try:
        class Server:
            def __init__(self) -> None:
                self.tools: dict[str, Any] = {}

            def tool(self):
                def decorator(fn):
                    self.tools[fn.__name__] = fn
                    return fn

                return decorator

        from rde.interface.mcp.tools.plan_tools import register_plan_tools

        server = Server()
        register_plan_tools(server)
        result = str(server.tools["check_readiness"](project_id))
        if result.lstrip().startswith("\u274c") or "失敗" in result[:100]:
            raise RuntimeError(result)
    finally:
        if inserted:
            try:
                sys.path.remove(src)
            except ValueError:
                pass
        if old_workspace is None:
            os.environ.pop("RDE_WORKSPACE", None)
        else:
            os.environ["RDE_WORKSPACE"] = old_workspace


async def run_list_tools(repo_root: Path, workspace: Path) -> list[str]:
    async with await _open_session(repo_root, workspace) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = _tool_names(await session.list_tools())
            missing = sorted(REQUIRED_TOOLS - set(names))
            if missing:
                raise RuntimeError(f"Missing required RDE MCP tools: {', '.join(missing)}")
            return names


async def run_quick_explore(
    repo_root: Path,
    workspace: Path,
    *,
    data_file: Path | None = None,
    research_question: str | None = None,
) -> Path:
    raw_dir = _prepare_rawdata(workspace, data_file)
    question = research_question or "Do iris species differ in petal length?"
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
                    "research_question": question,
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


async def run_full_yolo(
    repo_root: Path,
    workspace: Path,
    *,
    data_file: Path,
    research_question: str,
) -> Path:
    """Run a governed real-file smoke with a direct readiness fallback.

    Some Windows MCP clients can hang on the `check_readiness` response even though
    the underlying tool completes quickly. The fallback still executes the RDE
    tool implementation and persists the same Phase 7 artifact, then resumes the
    MCP workflow in a fresh session.
    """

    raw_dir = _prepare_rawdata(workspace, data_file)
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
                    "name": "codex-rde-full-yolo",
                    "data_dir": str(raw_dir),
                    "research_question": research_question,
                    "mode": "full_audit",
                },
            )
            project_id = _latest_project_id(workspace)
            intake_text = await _call(
                session,
                "run_intake",
                {"directory": str(raw_dir), "project_id": project_id, "allow_pii": False},
            )
            dataset_ids = DATASET_ID_RE.findall(intake_text)
            if not dataset_ids:
                raise RuntimeError(
                    f"Could not parse dataset_id from run_intake output:\n{intake_text}"
                )
            dataset_id = dataset_ids[-1]

            await _call(session, "build_schema", {"dataset_id": dataset_id, "project_id": project_id})
            await _call(session, "profile_dataset", {"dataset_id": dataset_id})
            await _call(session, "assess_quality", {"dataset_id": dataset_id})
            await _call(session, "get_approval_card", {"project_id": project_id})
            await _call(session, "get_harness_dashboard", {"project_id": project_id})
            await _call(session, "build_artifact_index", {"project_id": project_id})
            await _call(session, "get_blocker_playbook", {"project_id": project_id})

            schema = _load_latest_schema(workspace)
            roles = _infer_roles(schema)
            variable_roles = {
                "outcome": roles["outcomes"],
                "group": roles["group"],
                "predictors": [name for name in (roles["group"], roles["trial"]) if name],
                "covariates": [name for name in (roles["trial"], roles["operator"]) if name],
                "id": [roles["operator"]] if roles["operator"] else [],
            }
            await _call(
                session,
                "align_concept",
                {
                    "project_id": project_id,
                    "dataset_id": dataset_id,
                    "research_question": research_question,
                    "variable_roles": variable_roles,
                    "confirm": True,
                },
            )
            proposal_args = {
                "project_id": project_id,
                "dataset_id": dataset_id,
                "max_analyses": 10,
                "enrich_rounds": 3,
                "include_advanced": True,
                "include_visualizations": True,
            }
            await _call(session, "propose_analysis_plan", {**proposal_args, "confirm": False})
            await _call(session, "propose_analysis_plan", {**proposal_args, "confirm": True})
            plan = _analysis_plan(roles)
            await _call(
                session,
                "register_analysis_plan",
                {
                    "project_id": project_id,
                    "analyses": plan,
                    "alpha": 0.05,
                    "missing_strategy": "listwise",
                    "multiple_comparison_method": "fdr",
                    "allow_methodology_override": False,
                    "confirm": True,
                },
            )

            _run_readiness_direct(repo_root, workspace, project_id)
            cleaning_text = await _call(session, "suggest_cleaning", {"dataset_id": dataset_id})
            has_cleaning_actions = bool(re.search(r"(?m)^\s*\d+\.\s+\*\*\[", cleaning_text))
            no_cleaning_needed = any(
                marker in cleaning_text.lower()
                for marker in ("無需清理", "資料品質良好", "no cleaning", "no cleanup")
            ) or not has_cleaning_actions
            if not no_cleaning_needed:
                await _call(
                    session,
                    "apply_cleaning",
                    {"dataset_id": dataset_id, "approved_indices": []},
                )

            for variable in roles["analyzable"]:
                await _call(
                    session,
                    "analyze_variable",
                    {"dataset_id": dataset_id, "variable_name": variable},
                )

            if roles["group"] and roles["outcomes"]:
                table_vars = [
                    name
                    for name in roles["outcomes"] + ([roles["trial"]] if roles["trial"] else [])
                    if name
                ]
                await _call(
                    session,
                    "generate_table_one",
                    {
                        "dataset_id": dataset_id,
                        "group_variable": roles["group"],
                        "variables": table_vars,
                    },
                )
                await _call(
                    session,
                    "compare_groups",
                    {
                        "dataset_id": dataset_id,
                        "group_variable": roles["group"],
                        "outcome_variables": table_vars,
                        "is_paired": False,
                    },
                )

            corr_vars = [name for name in (roles["trial"], roles["time"]) if name]
            if len(corr_vars) >= 2:
                await _call(
                    session,
                    "correlation_matrix",
                    {"dataset_id": dataset_id, "variables": corr_vars},
                )

            for entry in plan:
                if entry.get("type") == "visualization":
                    await _call(
                        session,
                        "create_visualization",
                        {
                            "dataset_id": dataset_id,
                            "plot_type": entry.get("plot_type"),
                            "variables": entry.get("variables"),
                            "group_var": entry.get("group_variable"),
                        },
                    )
                elif entry.get("type") == "run_advanced_analysis":
                    await _call(
                        session,
                        "run_advanced_analysis",
                        {
                            "dataset_id": dataset_id,
                            "analysis_type": entry.get("analysis_type"),
                            "target_variable": entry.get("target_variable"),
                            "group_variable": entry.get("group_variable"),
                            "covariates": entry.get("covariates"),
                            "problem_type": entry.get("problem_type"),
                        },
                    )

            await _call(session, "collect_results", {"project_id": project_id, "force": False})
            await _call(
                session,
                "assemble_report",
                {
                    "project_id": project_id,
                    "title": "Codex RDE Full YOLO Report",
                    "allow_incomplete": False,
                },
            )
            await _call(session, "run_audit", {"project_id": project_id})
            await _call(session, "auto_improve", {"project_id": project_id})

    return _find_report(workspace)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-tools-only", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Workspace for generated smoke artifacts. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        help="Optional user data file to copy into an isolated rawdata folder.",
    )
    parser.add_argument(
        "--research-question",
        default="Explore the dataset, infer useful medical/clinical EDA branches, and produce an auditable report.",
    )
    parser.add_argument(
        "--full-yolo",
        action="store_true",
        help="Run the governed full-audit MCP flow instead of Quick Explore.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    data_file = args.data_file.resolve() if args.data_file else None
    if data_file is not None and not data_file.exists():
        raise FileNotFoundError(data_file)

    async def run_workflow(workspace: Path) -> Path:
        if args.full_yolo:
            if data_file is None:
                raise ValueError("--full-yolo requires --data-file")
            return await run_full_yolo(
                repo_root,
                workspace,
                data_file=data_file,
                research_question=args.research_question,
            )
        return await run_quick_explore(
            repo_root,
            workspace,
            data_file=data_file,
            research_question=args.research_question,
        )

    if args.workspace is not None:
        workspace = args.workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        names = asyncio.run(run_list_tools(repo_root, workspace)) if args.list_tools_only else None
        if args.list_tools_only:
            required = " ".join(sorted(REQUIRED_TOOLS & set(names)))
            print(f"tools={len(names)} required=ok {required}")
            return 0
        report = asyncio.run(run_workflow(workspace))
        print(f"workflow=ok report={report}")
        return 0

    with tempfile.TemporaryDirectory(prefix="rde-codex-smoke-") as tmp:
        workspace = Path(tmp)
        if args.list_tools_only:
            names = asyncio.run(run_list_tools(repo_root, workspace))
            required = " ".join(sorted(REQUIRED_TOOLS & set(names)))
            print(f"tools={len(names)} required=ok {required}")
            return 0
        report = asyncio.run(run_workflow(workspace))
        print(f"workflow=ok report={report}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
