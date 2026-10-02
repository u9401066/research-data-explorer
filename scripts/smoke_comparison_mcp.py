"""Exercise corrected comparisons through external MCP, with independent R references.

Synthetic engineering fixtures only. All analyses use governed MCP calls; this
script creates CSV inputs and inspects saved receipts, never fits an analysis.
Requires the already-installed evidence R image for independent reference tests.
"""

import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


REPO = Path(__file__).resolve().parents[1]
R_IMAGE = "research-workbench/evidence:netmeta-3.7.0"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixtures():
    for name, samples, expression in [
        (
            "rank-exact",
            [[None, 10, 11, 12, 13, 14], [1, 2, 3, 4, 5, 6]],
            "wilcox.test(c(10,11,12,13,14),1:6,exact=TRUE)",
        ),
        (
            "rank-ties",
            [[1, 1, 2, 2, 5], [2, 2, 3, 4, 4]],
            "wilcox.test(c(1,1,2,2,5),c(2,2,3,4,4),exact=FALSE,correct=TRUE)",
        ),
        (
            "kruskal-ties",
            [[1, 1, 2, 2, 2], [2, 2, 3, 3, 3], [3, 3, 4, 4, 4]],
            "kruskal.test(list(c(1,1,2,2,2),c(2,2,3,3,3),c(3,3,4,4,4)))",
        ),
    ]:
        # Interleave so a missing first observation can change observed order
        # after complete-case selection unless identity is explicitly retained.
        rows = [
            [samples[j][i], ["Z-first", "A-second", "M-third"][j]]
            for i in range(max(map(len, samples)))
            for j in range(len(samples))
            if i < len(samples[j])
        ]
        yield name, rows, expression, None
    for name, table, expected_test in [
        ("fisher-small", [[8, 2], [1, 5]], "Fisher's exact test"),
        ("fisher-infinite", [[6, 0], [0, 6]], "Fisher's exact test"),
        ("fisher-large-margins", [[1, 0], [29, 30]], "Fisher's exact test"),
        ("pearson", [[20, 10], [15, 25]], "Chi-squared test"),
    ]:
        rows = [
            [f"level{i+1}", ["Z-first", "A-second"][j]]
            for i, row in enumerate(table)
            for j, count in enumerate(row)
            for _ in range(count)
        ]
        matrix = "matrix(c(" + ",".join(str(n) for row in table for n in row) + "),2,byrow=TRUE)"
        expression = (
            f"fisher.test({matrix})"
            if name.startswith("fisher")
            else f"chisq.test({matrix},correct=FALSE)"
        )
        yield name, rows, expression, expected_test


async def run(destination):
    os.umask(0o077)
    destination.mkdir(parents=True, exist_ok=False)
    cases = list(fixtures())
    # R's fisher.test reports the conditional MLE OR. Only its exact p-value is
    # compared to SciPy's sample (unconditional) odds ratio contract.
    expression = (
        "library(jsonlite); out <- list(); "
        + "; ".join(
            f"x <- {expr}; out[['{name}']] <- list(p_value=unname(x$p.value), statistic=if(is.null(x$statistic)) NULL else unname(x$statistic))"
            for name, _, expr, _ in cases
        )
        + "; cat(toJSON(list(r_version=R.version.string, results=out),auto_unbox=TRUE,digits=17))"
    )
    reference = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "Rscript",
            R_IMAGE,
            "-e",
            expression,
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    (destination / "reference-R.json").write_text(reference.stdout)
    (destination / "reference-R.stderr").write_text(reference.stderr)
    (destination / "reference-R-expression.txt").write_text(expression)
    (destination / "reference-image.json").write_text(
        subprocess.check_output(["docker", "image", "inspect", R_IMAGE], text=True)
    )
    expected = json.loads(reference.stdout)["results"]
    summaries = []
    for name, rows, _, expected_test in cases:
        workspace = destination / name
        raw = workspace / "rawdata"
        raw.mkdir(parents=True)
        source = raw / "synthetic.csv"
        with source.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["outcome", "group"])
            writer.writerows(rows)
        source_hash = sha(source)
        calls = workspace / "calls"
        calls.mkdir()
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "rde"],
            cwd=REPO,
            env={**os.environ, "PYTHONPATH": str(REPO / "src"), "RDE_WORKSPACE": str(workspace)},
        )
        counter = 0

        async def call(session, tool, arguments):
            nonlocal counter
            counter += 1
            response = await session.call_tool(tool, arguments, read_timeout_seconds=180)
            text = "\n".join(c.text for c in response.content if hasattr(c, "text"))
            (calls / f"{counter:02}_{tool}.json").write_text(
                json.dumps(
                    {"arguments": arguments, "is_error": response.is_error, "response": text},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            assert not response.is_error and not text.lstrip().startswith("❌"), text
            return text

        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            await call(
                session,
                "init_project",
                {
                    "name": f"Synthetic comparison integrity {name}",
                    "data_dir": str(raw),
                    "mode": "full_audit",
                    "research_question": "Synthetic engineering verification of group comparison; no clinical claim.",
                },
            )
            (root,) = [p for p in (workspace / "data/projects").iterdir() if p.is_dir()]
            project_id = root.name.rsplit("_", 1)[-1]
            intake = await call(
                session,
                "run_intake",
                {"directory": str(raw), "project_id": project_id, "allow_pii": False},
            )
            dataset_id = re.findall(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", intake)[-1]
            await call(
                session, "build_schema", {"dataset_id": dataset_id, "project_id": project_id}
            )
            await call(session, "profile_dataset", {"dataset_id": dataset_id})
            await call(session, "assess_quality", {"dataset_id": dataset_id})
            await call(
                session,
                "align_concept",
                {
                    "project_id": project_id,
                    "dataset_id": dataset_id,
                    "confirm": True,
                    "research_question": "Compare synthetic outcomes by group; user-authorized engineering verification only.",
                    "variable_roles": {"outcome": "outcome", "group": "group"},
                },
            )
            for confirm in (False, True):
                await call(
                    session,
                    "propose_analysis_plan",
                    {
                        "project_id": project_id,
                        "dataset_id": dataset_id,
                        "confirm": confirm,
                        "include_advanced": False,
                        "include_visualizations": False,
                        "max_analyses": 1,
                    },
                )
            await call(
                session,
                "register_analysis_plan",
                {
                    "project_id": project_id,
                    "confirm": True,
                    "alpha": 0.05,
                    "allow_methodology_override": True,
                    "missing_strategy": "pairwise",
                    "multiple_comparison_method": "holm",
                    "analyses": [
                        {
                            "type": "compare_groups",
                            "variables": ["outcome"],
                            "group_variable": "group",
                            "rationale": "Synthetic source-pinned numerical engineering verification.",
                        }
                    ],
                },
            )
            await call(session, "check_readiness", {"project_id": project_id})
            report = await call(
                session,
                "compare_groups",
                {
                    "dataset_id": dataset_id,
                    "outcome_variables": ["outcome"],
                    "group_variable": "group",
                },
            )
            (record_path,) = (root / "artifacts/phase_08_execute_exploration").glob(
                "compare_groups_*.json"
            )
            record = json.loads(record_path.read_text())
            json.dumps(record, allow_nan=False)
            test = record["tests"][0]
            details = record["test_details"]["outcome"]
            assert record["method_contract"] == "comparison-inference-v2"
            assert details["group_labels"] == record["case_sets"]["outcome"]["group_order"]
            assert details["sample_sizes"] == test["sample_sizes"]
            assert math.isclose(
                test["p_value"], expected[name]["p_value"], rel_tol=1e-10, abs_tol=1e-13
            )
            if expected_test:
                assert test["test_name"] == expected_test
            elif name == "rank-exact":
                assert test["effect_size"] == 1 and test["group_labels"] == ["Z-first", "A-second"]
                assert test["sample_sizes"] == [5, 6]
            if not name.startswith("fisher"):
                assert math.isclose(test["statistic"], expected[name]["statistic"], rel_tol=1e-12)
            if name in {"fisher-infinite", "fisher-large-margins"}:
                assert test["statistic"] is None and test["statistic_status"] == "positive_infinity"
                assert "+∞" in report and "未計算效果量" not in report
            await call(session, "collect_results", {"project_id": project_id})
            await call(
                session,
                "assemble_report",
                {
                    "project_id": project_id,
                    "title": f"Synthetic comparison {name}",
                    "allow_incomplete": True,
                },
            )
            await call(session, "run_audit", {"project_id": project_id})
            await call(session, "auto_improve", {"project_id": project_id})
            assembled = (root / "artifacts/phase_10_report_assembly/eda_report.md").read_text()
            assert details["p_value_method"] in assembled
            assert "此比較未估計效果量信賴區間" in assembled
            if name in {"fisher-infinite", "fisher-large-margins"}:
                assert "+∞" in assembled and "不代表母體效果無限大" in assembled
            frozen = {str(p): sha(p) for p in (root / "artifacts").rglob("*") if p.is_file()}
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            await call(session, "get_pipeline_status", {"project_id": project_id})
            assert all(sha(Path(p)) == digest for p, digest in frozen.items())
        assert sha(source) == source_hash
        summaries.append(
            {
                "case": name,
                "source_sha256": source_hash,
                "record": str(record_path),
                "record_sha256": sha(record_path),
                "p_value": test["p_value"],
                "reference": expected[name],
                "artifacts_preserved_after_restart": len(frozen),
            }
        )
        print(json.dumps(summaries[-1]), flush=True)
    (destination / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    asyncio.run(run(parser.parse_args().destination.resolve()))
