import asyncio
import json
import sqlite3

import pandas as pd
import pytest

from rde.infrastructure.adapters.descriptive_study import summarize, parse_options
from rde.interface.mcp.tools.descriptive_tools import planned_descriptive


OPTIONS = dict(
    columns=["subject", "event", "aki", "cr"],
    identifiers=["subject", "event"],
    unresolved=["Sampling and clinical definitions unknown"],
)


def frame():
    return pd.DataFrame(
        dict(
            subject=["A", "A", "B", "C", None, "C"],
            event=[1, 2, 3, 4, 5, 4],
            aki=[1, None, 0, 1, None, 1],
            cr=[2.0, None, 1.0, 4.0, None, 4.0],
        )
    )


def test_known_answers_and_independent_sql_do_not_count_repeat_events_as_people():
    df = frame()
    result = summarize(df, OPTIONS)
    conn = sqlite3.connect(":memory:")
    df.to_sql("source", conn, index=False)
    n, observed, codes = conn.execute(
        "select count(*),count(aki),count(distinct subject) from source"
    ).fetchone()
    rows = {x["column"]: x for x in result["columns"]}
    assert n == result["input_rows"] == 6
    assert observed == rows["aki"]["observed"] == 4
    assert codes == rows["subject"]["distinct"] == 3
    assert rows["aki"]["missing"] == 2
    assert rows["subject"]["rows_with_repeated_value"] == 4
    assert rows["subject"]["missing"] == 1
    assert "levels" not in rows["subject"]
    assert result["exact_duplicate_rows"] == 1
    assert rows["cr"]["summary"]["median"] == 3.0
    assert not result["inference_performed"]
    shuffled = summarize(df.sample(frac=1, random_state=5), OPTIONS)
    assert shuffled == result
    assert df.equals(frame())
    for wrong in [{**OPTIONS, "independent_rows": True}, {**OPTIONS, "identifiers": ["missing"]}]:
        with pytest.raises(ValueError):
            parse_options(wrong)
    with pytest.raises(ValueError):
        planned_descriptive([dict(type="run_descriptive_study"), dict(type="compare_groups")])


def test_equal_missing_denominators_do_not_imply_the_same_rows():
    df = pd.DataFrame(dict(a=[1.0, None, 3.0, None], b=[None, 2.0, 3.0, None]))
    result = summarize(df, dict(columns=["a", "b"], identifiers=[], unresolved=[]))
    assert [x["missing"] for x in result["columns"]] == [2, 2]
    assert {tuple(p["missing_columns"]): p["rows"] for p in result["missing_patterns"]} == {
        (): 1,
        ("a",): 1,
        ("b",): 1,
        ("a", "b"): 1,
    }
    assert (
        result["missing_patterns"]
        == summarize(df.iloc[::-1], dict(columns=["a", "b"], identifiers=[], unresolved=[]))[
            "missing_patterns"
        ]
    )


def test_real_mcp_locked_scope_saved_reuse_and_source_drift(tmp_path, monkeypatch):
    from test_clinical_survival import clinical_project
    from rde.application.pipeline import PipelinePhase
    from rde.interface.mcp.server import create_server
    import rde.interface.mcp.tools.descriptive_tools as module

    project, store, dataset, _ = clinical_project(tmp_path, frame=frame())
    plan = dict(
        locked=True,
        analyses=[
            dict(
                type="run_descriptive_study",
                variables=OPTIONS["columns"],
                execution_arguments=dict(descriptive_options=OPTIONS),
            )
        ],
    )
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)

    def call(options=OPTIONS):
        return asyncio.run(
            create_server().call_tool(
                "run_descriptive_study", dict(dataset_id=dataset.id, descriptive_options=options)
            )
        )

    result = call()
    assert not result.is_error, result.content
    assert json.loads(result.content[0].text)["result"]["input_rows"] == 6
    branch = asyncio.run(
        create_server().call_tool("start_autoresearch_run", dict(project_id=project.id))
    )
    assert branch.is_error and "Descriptive scope" in branch.content[0].text
    monkeypatch.setattr(module, "summarize", lambda *a: pytest.fail("recomputed saved study"))
    assert json.loads(call().content[0].text)["reused"]
    assert call({**OPTIONS, "unresolved": []}).is_error
    record = store.load(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_study.json")
    assert record["version"]["source_status"] == "verified"
    report = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_report.md")
    original = report.read_bytes()
    report.write_text("tampered")
    assert call().is_error
    report.write_bytes(original)
    dataset.metadata.file_path.write_text("changed source")
    assert call().is_error


def test_descriptive_full_mcp_audit_does_not_demand_inferential_publication_bundle(tmp_path):
    from test_clinical_survival import clinical_project
    from rde.application.pipeline import PipelinePhase
    from rde.interface.mcp.server import create_server

    project, store, dataset, _ = clinical_project(tmp_path, frame=frame())
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        dict(
            locked=True,
            alpha=0.05,
            missing_strategy="available",
            multiple_comparison_method="holm",
            analyses=[
                dict(
                    type="run_descriptive_study",
                    variables=OPTIONS["columns"],
                    execution_arguments=dict(descriptive_options=OPTIONS),
                )
            ],
        ),
    )
    server = create_server()

    def call(tool, **args):
        result = asyncio.run(server.call_tool(tool, args))
        assert not result.is_error, result.content
        return result

    call("run_descriptive_study", dataset_id=dataset.id, descriptive_options=OPTIONS)
    call("collect_results", project_id=project.id)
    call("assemble_report", project_id=project.id, allow_incomplete=False)
    call("run_audit", project_id=project.id)
    audit = store.load(PipelinePhase.AUDIT_REVIEW, "audit_report.json")
    bundle = next(c for c in audit["checks"] if c["category"] == "publication_bundle")
    assert bundle["passed"] and bundle["applicable"] is False
    assert bundle["score"] == bundle["max"] == 0
    assert not any("粗分析圖" in x or "細分析圖" in x for x in audit["suggestions"])
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert summary["deliverables"]["missing_components"] == []
    assert summary["deliverables"]["minimum_publication_bundle_met"] is False
    call("auto_improve", project_id=project.id)
    final = store.load(PipelinePhase.AUTO_IMPROVE, "final_report.md")
    assert "ready for descriptive_only" in final
    assert "**status:** production-ready" not in final
    assert "Why this is production-ready" not in final
    assert "not applicable (descriptive-only)" in final
    # A scoped audit must still detect missing real evidence; this is not a waiver.
    store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "descriptive_report.md").unlink()
    call("run_audit", project_id=project.id)
    invalid = store.load(PipelinePhase.AUDIT_REVIEW, "audit_report.json")
    assert (
        next(c for c in invalid["checks"] if c["category"] == "report_readiness")["passed"] is False
    )
