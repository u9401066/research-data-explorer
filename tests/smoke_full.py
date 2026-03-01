"""Full 11-Phase smoke test — Phase 0 → Phase 10."""
import asyncio
import json

from rde.interface.mcp.server import create_server


def extract_text(result) -> str:
    """Extract text from FastMCP call_tool result."""
    return result[0][0].text


async def main():
    server = create_server()
    passed = []
    failed = []

    def check(phase: str, text: str):
        if text.startswith("❌"):
            failed.append(phase)
            print(f"  FAIL: {text[:200]}")
        else:
            passed.append(phase)
            print(f"  OK: {text[:150]}")

    # ── Phase 0: Project Setup ───────────────────────────────
    print("=== Phase 0: Project Setup ===")
    r = await server.call_tool("init_project", {
        "name": "smoke_full",
        "description": "Full 11-phase smoke test",
    })
    text = extract_text(r)
    check("Phase 0", text)

    # ── Phase 1: Data Intake ─────────────────────────────────
    print("\n=== Phase 1: Data Intake ===")
    r = await server.call_tool("run_intake", {"folder_path": "data/rawdata"})
    text = extract_text(r)
    check("Phase 1", text)

    # Extract dataset_id from session
    from rde.application.session import get_session
    session = get_session()
    ds_ids = session.list_datasets()
    ds_id = ds_ids[0] if ds_ids else None
    print(f"  Dataset ID: {ds_id}")

    if not ds_id:
        print("FATAL: No dataset loaded")
        return

    # ── Phase 2: Schema Registry ─────────────────────────────
    print("\n=== Phase 2: Build Schema ===")
    r = await server.call_tool("build_schema", {"dataset_id": ds_id})
    text = extract_text(r)
    check("Phase 2", text)

    print("\n=== Phase 2b: Profile Dataset ===")
    r = await server.call_tool("profile_dataset", {"dataset_id": ds_id})
    text = extract_text(r)
    check("Phase 2b", text)

    # ── Phase 3: Concept Alignment ───────────────────────────
    print("\n=== Phase 3: Concept Alignment ===")
    r = await server.call_tool("align_concept", {
        "research_question": "Do iris species differ in sepal length?",
        "variable_roles": {
            "outcome": "sepal_length",
            "predictor": "species",
            "covariate": "petal_length",
        },
    })
    text = extract_text(r)
    check("Phase 3", text)

    # ── Phase 4: Plan Registration ───────────────────────────
    print("\n=== Phase 4: Register Plan ===")
    r = await server.call_tool("register_analysis_plan", {
        "analyses": [
            {"type": "compare_groups", "variables": ["sepal_length"], "group": "species"},
        ],
        "alpha": 0.05,
        "missing_strategy": "complete_case",
    })
    text = extract_text(r)
    check("Phase 4", text)

    # ── Phase 5: Pre-check ───────────────────────────────────
    print("\n=== Phase 5: Pre-check ===")
    r = await server.call_tool("check_readiness", {"dataset_id": ds_id})
    text = extract_text(r)
    check("Phase 5", text)

    # ── Phase 6: Execute Exploration ─────────────────────────
    print("\n=== Phase 6a: Analyze Variable ===")
    r = await server.call_tool("analyze_variable", {
        "dataset_id": ds_id,
        "variable_name": "sepal_length",
    })
    text = extract_text(r)
    check("Phase 6a", text)

    print("\n=== Phase 6b: Compare Groups ===")
    r = await server.call_tool("compare_groups", {
        "dataset_id": ds_id,
        "outcome_variables": ["sepal_length"],
        "group_variable": "species",
    })
    text = extract_text(r)
    check("Phase 6b", text)

    print("\n=== Phase 6c: Correlation Matrix ===")
    r = await server.call_tool("correlation_matrix", {"dataset_id": ds_id})
    text = extract_text(r)
    check("Phase 6c", text)

    print("\n=== Phase 6d: Generate Table One ===")
    r = await server.call_tool("generate_table_one", {
        "dataset_id": ds_id,
        "group_variable": "species",
    })
    text = extract_text(r)
    check("Phase 6d", text)

    print("\n=== Phase 6e: Create Visualization ===")
    r = await server.call_tool("create_visualization", {
        "dataset_id": ds_id,
        "plot_type": "boxplot",
        "variables": ["sepal_length"],
        "group_var": "species",
    })
    text = extract_text(r)
    check("Phase 6e", text)

    # ── Phase 7: Collect Results ─────────────────────────────
    print("\n=== Phase 7: Collect Results ===")
    r = await server.call_tool("collect_results", {})
    text = extract_text(r)
    check("Phase 7", text)

    # ── Phase 8: Report Assembly ─────────────────────────────
    print("\n=== Phase 8: Assemble Report ===")
    r = await server.call_tool("assemble_report", {
        "title": "Iris Species EDA Report",
    })
    text = extract_text(r)
    check("Phase 8", text)

    # ── Phase 9: Audit Review ────────────────────────────────
    print("\n=== Phase 9: Audit ===")
    r = await server.call_tool("run_audit", {})
    text = extract_text(r)
    check("Phase 9", text)

    # ── Phase 10: Auto-Improve ───────────────────────────────
    print("\n=== Phase 10a: Auto-Improve ===")
    r = await server.call_tool("auto_improve", {})
    text = extract_text(r)
    check("Phase 10a", text)

    print("\n=== Phase 10b: Export Handoff ===")
    r = await server.call_tool("export_handoff", {})
    text = extract_text(r)
    check("Phase 10b", text)

    # ── Summary ──────────────────────────────────────────────
    print("\n" + "=" * 50)
    print(f"PASSED: {len(passed)}/{len(passed) + len(failed)}")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    else:
        print("ALL PHASES PASSED ✅")

    # Check decision log
    print("\n=== Decision Log ===")
    r = await server.call_tool("get_decision_log", {})
    text = extract_text(r)
    print(text[:300])

    # Pipeline status
    print("\n=== Pipeline Status ===")
    r = await server.call_tool("get_pipeline_status", {})
    text = extract_text(r)
    print(text[:400])


if __name__ == "__main__":
    asyncio.run(main())
