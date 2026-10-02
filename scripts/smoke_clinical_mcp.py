"""Run a source-pinned clinical study only through the actual stdio MCP server.

This engineering harness confirms its supplied study specification, retains all tool
responses, and verifies restart/reuse. It never reads a dataframe or fits a model.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run(args):
    repo = Path(__file__).resolve().parents[1]
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    spec = json.loads(args.spec.read_text())
    if spec.get("family") not in {
        "longitudinal",
        "regression",
        "weighting",
        "comparison",
        "repeated",
    }:
        raise ValueError("An explicit supported clinical engineering specification is required")
    if sha(args.source) != args.source_sha256:
        raise ValueError("Source bytes differ from the pinned acquisition")
    raw = workspace / "rawdata"
    raw.mkdir()
    shutil.copyfile(args.source, raw / args.source.name)
    (workspace / "approved-engineering-specification.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2)
    )
    calls = workspace / "calls"
    calls.mkdir()
    covariates = (
        [p["column"] for p in spec["covariates"]]
        if spec["family"] == "weighting"
        else spec.get("covariates", [])
    )
    predictors = [p["column"] for p in spec.get("predictors", [])]
    outcomes = (
        [m["column"] for m in spec["measurements"]]
        if spec["family"] == "repeated"
        else [spec["outcome"]]
    )
    variables = list(
        dict.fromkeys(
            [
                *outcomes,
                *([spec["time"]] if spec["family"] == "longitudinal" else predictors),
                *covariates,
                *[
                    name
                    for name in [
                        spec.get("group"),
                        spec.get("treatment"),
                        spec.get("subject"),
                        spec.get("exposure"),
                        (spec.get("cohort_filter") or {}).get("column"),
                    ]
                    if name
                ],
            ]
        )
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(repo / "src"),
        "RDE_WORKSPACE": str(workspace),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    params = StdioServerParameters(command=sys.executable, args=["-m", "rde"], cwd=repo, env=env)
    counter = 0

    async def call(session, tool, arguments):
        nonlocal counter
        counter += 1
        print(f"{counter}: {tool}", flush=True)
        response = await session.call_tool(tool, arguments, read_timeout_seconds=240)
        text = "\n".join(block.text for block in response.content if hasattr(block, "text"))
        (calls / f"{counter:02}_{tool}.json").write_text(
            json.dumps(dict(arguments=arguments, response=text), ensure_ascii=False, indent=2)
        )
        if getattr(
            response, "isError", getattr(response, "is_error", False)
        ) or text.lstrip().startswith("❌"):
            raise RuntimeError(f"{tool}: {text}")
        return text

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        catalog = await session.list_tools()
        names = {tool.name for tool in catalog.tools}
        assert {
            "inspect_clinical_study",
            "run_clinical_study",
            "render_publication_figures",
            "run_audit",
        } <= names
        (workspace / "live-tools.json").write_text(
            json.dumps(catalog.model_dump(mode="json"), indent=2, ensure_ascii=False)
        )
        await call(
            session,
            "init_project",
            dict(
                name=args.name,
                data_dir=str(raw),
                research_question=spec["context"],
                mode="full_audit",
            ),
        )
        roots = [path for path in (workspace / "data" / "projects").iterdir() if path.is_dir()]
        assert len(roots) == 1
        root = roots[0]
        project_id = root.name.rsplit("_", 1)[-1]
        intake = await call(
            session, "run_intake", dict(directory=str(raw), project_id=project_id, allow_pii=False)
        )
        ids = re.findall(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", intake
        )
        assert ids, intake
        dataset_id = ids[-1]
        await call(session, "build_schema", dict(dataset_id=dataset_id, project_id=project_id))
        await call(session, "profile_dataset", dict(dataset_id=dataset_id))
        await call(session, "assess_quality", dict(dataset_id=dataset_id))
        arguments = dict(dataset_id=dataset_id, clinical_options=spec)
        preflight = json.loads(await call(session, "inspect_clinical_study", arguments))
        assert preflight["source_sha256"] == args.source_sha256
        await call(
            session,
            "align_concept",
            dict(
                project_id=project_id,
                dataset_id=dataset_id,
                research_question=spec["context"],
                confirm=True,
                variable_roles={
                    "outcome": outcomes,
                    **({"id": spec["subject"]} if spec.get("subject") else {}),
                    "covariates": [spec["time"], *covariates]
                    if spec["family"] == "longitudinal"
                    else covariates
                    if spec["family"] == "weighting"
                    else predictors,
                    **({"group": spec["group"]} if spec.get("group") else {}),
                    **({"group": spec["treatment"]} if spec.get("treatment") else {}),
                },
            ),
        )
        proposal = dict(
            project_id=project_id,
            dataset_id=dataset_id,
            max_analyses=1,
            include_advanced=True,
            include_visualizations=True,
        )
        await call(session, "propose_analysis_plan", {**proposal, "confirm": False})
        await call(session, "propose_analysis_plan", {**proposal, "confirm": True})
        await call(
            session,
            "register_analysis_plan",
            dict(
                project_id=project_id,
                analyses=[
                    dict(
                        type="run_clinical_study",
                        variables=variables,
                        rationale="Source-pinned engineering validation of an explicit clinical model, not a new clinical claim.",
                        execution_arguments={"clinical_options": spec},
                    )
                ],
                alpha=1 - spec.get("confidence_level", 0.95),
                missing_strategy="listwise",
                multiple_comparison_method=spec.get(
                    "multiplicity", "none" if spec["family"] == "weighting" else "holm"
                ),
                allow_methodology_override=False,
                confirm=True,
            ),
        )
        await call(session, "check_readiness", dict(project_id=project_id))
        await call(session, "run_clinical_study", arguments)
        await call(session, "collect_results", dict(project_id=project_id))
        await call(session, "assemble_report", dict(project_id=project_id, title=args.name))
        await call(session, "run_audit", dict(project_id=project_id))
        await call(session, "auto_improve", dict(project_id=project_id))
        sources = list(
            (root / "artifacts" / "phase_08_execute_exploration").glob("clinical_study_*.json")
        )
        assert len(sources) == 1
        receipt_path = sources[0]
        receipt = json.loads(receipt_path.read_text())
        result = receipt["result"]
        assert result["dataframe_sha256"] == preflight["dataframe_sha256"]
        assert result["case_ledger"] == preflight["case_ledger"]
        assert receipt["source"]["sha256"] == args.source_sha256
        frozen = {
            str(receipt_path): sha(receipt_path),
            **{str(root / a["path"]): a["sha256"] for a in receipt["artifacts"]},
        }
        assert all(sha(Path(path)) == expected for path, expected in frozen.items())
        editions = []
        for preset in args.preset:
            edition = json.loads(
                await call(
                    session,
                    "render_publication_figures",
                    dict(
                        project_id=project_id,
                        study_artifact=receipt_path.name,
                        expected_record_sha256=sha(receipt_path),
                        preset_id=preset,
                        edition_id=str(uuid.uuid4()),
                        start_number=7,
                    ),
                )
            )
            for old, new in zip(receipt["figures"], edition["figures"], strict=True):
                assert (
                    Path(old["publication"]["files"]["data"]).read_bytes()
                    == Path(new["publication"]["files"]["data"]).read_bytes()
                )
            editions.append(edition)
            frozen.update({str(root / a["path"]): a["sha256"] for a in edition["artifacts"]})
        results = json.loads(
            (root / "artifacts" / "phase_09_collect_results" / "results_summary.json").read_text()
        )
        assert results["report_readiness"]["ready"], results["report_readiness"]
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        await call(session, "get_pipeline_status", dict(project_id=project_id))
        reused = await call(session, "run_clinical_study", arguments)
        assert "沒有重新估計" in reused
        assert all(sha(Path(path)) == expected for path, expected in frozen.items())
    summary = dict(
        name=args.name,
        root=str(root),
        project_id=project_id,
        dataset_id=dataset_id,
        receipt_path=str(receipt_path),
        receipt_sha256=result["receipt_sha256"],
        n=result["n"],
        n_subjects=result.get("n_subjects"),
        model=result.get("model"),
        contrasts=result.get("contrasts"),
        coefficients=result.get("coefficients"),
        effect=result.get("effect"),
        warnings=result["warnings"],
        figures=receipt["figures"],
        editions=editions,
        checked_artifacts=len(frozen),
        restart_reuse="verified without numerical or artifact changes",
    )
    (workspace / "verification.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(
        json.dumps(
            {
                key: summary[key]
                for key in [
                    "name",
                    "root",
                    "n",
                    "n_subjects",
                    "receipt_sha256",
                    "checked_artifacts",
                    "restart_reuse",
                ]
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--preset", action="append", default=[])
    os.umask(0o077)
    asyncio.run(run(parser.parse_args()))
