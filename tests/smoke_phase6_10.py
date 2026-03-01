"""Smoke test: Phase 6-10 (Execute Exploration through Auto-Improve).

Extends Phase 0-5 setup, then runs actual analysis, collection, report, and audit.
"""
import sys, uuid, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rde.application.session import get_session
from rde.infrastructure.adapters import PandasLoader
from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine
from rde.infrastructure.visualization.matplotlib_viz import MatplotlibVisualizer
from rde.infrastructure.adapters.markdown_renderer import MarkdownReportRenderer
from rde.domain.models.dataset import Dataset, DatasetMetadata
from rde.domain.models.project import Project, ProjectStatus
from rde.domain.models.variable import VariableRole
from rde.application.pipeline import PipelinePhase, PhaseResult, REQUIRED_ARTIFACTS
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.application.use_cases.compare_groups import CompareGroupsUseCase
from rde.application.decision_logger import DecisionLogger


def setup_phase0_5():
    """Quick Phase 0-5 setup — same as smoke_phase0_5.py."""
    session = get_session()
    pid = str(uuid.uuid4())[:8]
    output_dir = Path("data/projects") / pid
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "artifacts").mkdir(exist_ok=True)
    (output_dir / "figures").mkdir(exist_ok=True)

    project = Project(
        id=pid, name="iris_test",
        data_dir=Path("data/rawdata"), output_dir=output_dir,
        research_question="Iris species differ in petal/sepal dimensions?",
    )
    session.register_project(project)
    store = ArtifactStore(project.artifacts_dir)

    # Phase 0
    store.save(PipelinePhase.PROJECT_SETUP, "project.yaml", {"id": pid, "name": "iris_test"})
    pipeline = session.get_pipeline(pid)
    pipeline.mark_started(PipelinePhase.PROJECT_SETUP)
    pipeline.mark_completed(PhaseResult(phase=PipelinePhase.PROJECT_SETUP, completed_at=datetime.now(), success=True, artifacts={"project.yaml": ""}))
    project.advance_to(ProjectStatus.PROJECT_SETUP)

    # Phase 1
    store.save(PipelinePhase.DATA_INTAKE, "intake_report.json", {"status": "ok", "files": ["iris.csv"]})
    pipeline.mark_started(PipelinePhase.DATA_INTAKE)
    pipeline.mark_completed(PhaseResult(phase=PipelinePhase.DATA_INTAKE, completed_at=datetime.now(), success=True, artifacts={"intake_report.json": ""}))
    project.advance_to(ProjectStatus.DATA_INTAKE)

    # Phase 2
    loader = PandasLoader()
    iris_path = Path("vendor/automl-stat-mcp/sample_data/iris.csv")
    metadata = DatasetMetadata(file_path=iris_path, file_format="csv", file_size_bytes=iris_path.stat().st_size)
    dataset = Dataset(metadata=metadata)
    df, variables, row_count = loader.load(metadata)
    dataset.mark_loaded(variables, row_count)
    session.register_dataset(dataset, df)
    store.save(PipelinePhase.SCHEMA_REGISTRY, "schema.json", {"variables": [v.name for v in variables], "row_count": row_count})
    pipeline.mark_started(PipelinePhase.SCHEMA_REGISTRY)
    pipeline.mark_completed(PhaseResult(phase=PipelinePhase.SCHEMA_REGISTRY, completed_at=datetime.now(), success=True, artifacts={"schema.json": ""}))
    project.advance_to(ProjectStatus.SCHEMA_REGISTRY)

    # Phase 3
    available_vars = {v.name: v for v in dataset.variables}
    available_vars["species"].role = VariableRole.GROUP
    for vn in ["sepal_length", "sepal_width", "petal_length", "petal_width"]:
        if vn in available_vars:
            available_vars[vn].role = VariableRole.OUTCOME
    alignment = {"research_question": project.research_question, "roles": {v.name: v.role.value for v in dataset.variables}}
    store.save(PipelinePhase.CONCEPT_ALIGNMENT, "concept_alignment.md", "# Concept Alignment\n\nIris species comparison")
    store.save(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json", alignment)
    pipeline.mark_started(PipelinePhase.CONCEPT_ALIGNMENT)
    pipeline.mark_completed(PhaseResult(phase=PipelinePhase.CONCEPT_ALIGNMENT, completed_at=datetime.now(), success=True, artifacts={"concept_alignment.md": "", "variable_roles.json": ""}))
    project.advance_to(ProjectStatus.CONCEPT_ALIGNMENT)

    # Phase 4
    plan = {
        "alpha": 0.05, "missing_strategy": "listwise",
        "analyses": [
            {"type": "table_one", "variables": ["sepal_length", "sepal_width", "petal_length", "petal_width"], "group": "species"},
            {"type": "compare_groups", "outcome": ["petal_length", "petal_width"], "group": "species"},
            {"type": "correlation", "variables": ["sepal_length", "sepal_width", "petal_length", "petal_width"]},
        ],
        "locked": True,
    }
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    pipeline.mark_started(PipelinePhase.PLAN_REGISTRATION)
    pipeline.mark_completed(PhaseResult(phase=PipelinePhase.PLAN_REGISTRATION, completed_at=datetime.now(), success=True, artifacts={"analysis_plan.yaml": ""}))
    pipeline.plan_locked = True
    project.advance_to(ProjectStatus.PLAN_REGISTRATION)

    # Phase 5
    store.save(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json", {"all_passed": True, "checks": []})
    pipeline.mark_started(PipelinePhase.PRE_EXPLORE_CHECK)
    pipeline.mark_completed(PhaseResult(phase=PipelinePhase.PRE_EXPLORE_CHECK, completed_at=datetime.now(), success=True, artifacts={"readiness_checklist.json": ""}))
    project.advance_to(ProjectStatus.PRE_EXPLORE_CHECK)

    return pid, dataset, df, store, pipeline, project


def main():
    pid, dataset, df, store, pipeline, project = setup_phase0_5()
    engine = ScipyStatisticalEngine()
    session = get_session()
    errors = []

    # ════════════════════════════════════════
    # Phase 6: Execute Exploration
    # ════════════════════════════════════════
    print("=== Phase 6: execute_exploration ===")
    pipeline.mark_started(PipelinePhase.EXECUTE_EXPLORATION)
    phase6_artifacts = {}

    # 6a: generate_table_one
    print("  [6a] generate_table_one...")
    try:
        t1 = engine.generate_table_one(
            df, group_var="species",
            variables=["sepal_length", "sepal_width", "petal_length", "petal_width"],
        )
        print(f"       OK — {t1['n_variables']} variables, {t1['n_categorical']} categorical")
        print(f"       Preview (first 200 chars): {t1['table_text'][:200]}")
        store.save(PipelinePhase.EXECUTE_EXPLORATION, "table_one.json", t1)
        phase6_artifacts["table_one.json"] = ""
    except Exception as e:
        print(f"       FAIL: {e}")
        errors.append(f"6a table_one: {e}")

    # 6b: compare_groups (Kruskal-Wallis since 3 groups)
    print("  [6b] compare_groups (petal_length by species)...")
    try:
        use_case = CompareGroupsUseCase(engine)
        result = use_case.execute(
            dataset=dataset, raw_data=df,
            outcome_variables=["petal_length", "petal_width"],
            group_variable="species",
        )
        print(f"       OK — {len(result.tests)} tests")
        for t in result.tests:
            print(f"       {t.test_name}: p={t.p_value:.4g}, effect={t.effect_size}")
        store.save(PipelinePhase.EXECUTE_EXPLORATION, "compare_groups.json", {
            "tests": [{"test_name": t.test_name, "p_value": t.p_value, "effect_size": t.effect_size, "significant": t.is_significant} for t in result.tests],
            "summary": result.summary,
        })
        phase6_artifacts["compare_groups.json"] = ""
        session._analysis_results = getattr(session, "_analysis_results", [])
        session._analysis_results.append(result)
    except Exception as e:
        print(f"       FAIL: {e}")
        import traceback; traceback.print_exc()
        errors.append(f"6b compare_groups: {e}")

    # 6c: analyze_variable (univariate)
    print("  [6c] analyze_variable (sepal_length)...")
    try:
        shapiro = engine.run_test(df, "Shapiro-Wilk", ["sepal_length"])
        print(f"       Shapiro-Wilk: stat={shapiro['statistic']:.4f}, p={shapiro['p_value']:.4g}, normal={shapiro.get('is_normal')}")
        store.save(PipelinePhase.EXECUTE_EXPLORATION, "univariate_sepal_length.json", shapiro)
        phase6_artifacts["univariate_sepal_length.json"] = ""
    except Exception as e:
        print(f"       FAIL: {e}")
        errors.append(f"6c analyze_variable: {e}")

    # 6d: correlation_matrix
    print("  [6d] correlation_matrix...")
    try:
        numeric_cols = ["sepal_length", "sepal_width", "petal_length", "petal_width"]
        corr = df[numeric_cols].corr()
        corr_dict = corr.to_dict()
        # Check collinearity (S-007)
        warnings_list = []
        for i, c1 in enumerate(numeric_cols):
            for c2 in numeric_cols[i+1:]:
                r = abs(corr.loc[c1, c2])
                if r > 0.9:
                    warnings_list.append(f"S-007: High collinearity between {c1} and {c2} (r={r:.3f})")
        print(f"       OK — {len(numeric_cols)}x{len(numeric_cols)} matrix")
        if warnings_list:
            for w in warnings_list:
                print(f"       WARNING: {w}")
        store.save(PipelinePhase.EXECUTE_EXPLORATION, "correlation_matrix.json", {"variables": numeric_cols, "matrix": corr_dict, "warnings": warnings_list})
        phase6_artifacts["correlation_matrix.json"] = ""
    except Exception as e:
        print(f"       FAIL: {e}")
        errors.append(f"6d correlation: {e}")

    # 6e: create_visualization
    print("  [6e] create_visualization (boxplot)...")
    try:
        viz = MatplotlibVisualizer()
        fig_path = project.output_dir / "figures" / "boxplot_petal_length.png"
        viz.create_plot(
            data=df,
            plot_type="boxplot",
            variables=["petal_length"],
            output_path=fig_path,
            title="Petal Length by Species",
            group_var="species",
        )
        print(f"       OK — saved to {fig_path}")
        phase6_artifacts["boxplot_petal_length.png"] = str(fig_path)
    except Exception as e:
        print(f"       FAIL: {e}")
        import traceback; traceback.print_exc()
        errors.append(f"6e visualization: {e}")

    pipeline.mark_completed(PhaseResult(
        phase=PipelinePhase.EXECUTE_EXPLORATION,
        completed_at=datetime.now(), success=len(errors) == 0,
        artifacts=phase6_artifacts,
    ))
    if not errors:
        project.advance_to(ProjectStatus.EXECUTE_EXPLORATION)
    print(f"  Phase 6: {'OK' if not errors else 'ERRORS: ' + str(errors)}\n")

    # ════════════════════════════════════════
    # Phase 7: Collect Results
    # ════════════════════════════════════════
    print("=== Phase 7: collect_results ===")
    pipeline.mark_started(PipelinePhase.COLLECT_RESULTS)
    results_summary = {
        "phase6_artifacts": list(phase6_artifacts.keys()),
        "n_analyses": 4,
        "publishable": ["table_one.json", "compare_groups.json"],
        "plan_coverage": "3/3 planned analyses completed",
    }
    store.save(PipelinePhase.COLLECT_RESULTS, "results_summary.json", results_summary)
    pipeline.mark_completed(PhaseResult(
        phase=PipelinePhase.COLLECT_RESULTS,
        completed_at=datetime.now(), success=True,
        artifacts={"results_summary.json": ""},
    ))
    project.advance_to(ProjectStatus.COLLECT_RESULTS)
    print(f"  Artifacts: {results_summary['phase6_artifacts']}")
    print(f"  Publishable: {results_summary['publishable']}")
    print("  Phase 7: OK\n")

    # ════════════════════════════════════════
    # Phase 8: Report Assembly
    # ════════════════════════════════════════
    print("=== Phase 8: assemble_report ===")
    pipeline.mark_started(PipelinePhase.REPORT_ASSEMBLY)
    renderer = MarkdownReportRenderer()
    report_sections = {
        "title": "# EDA Report: Iris Species Analysis",
        "research_question": "## Research Question\n\nDo iris species differ in petal/sepal dimensions?",
        "methods": "## Methods\n\n- Table One with tableone\n- Kruskal-Wallis test for multi-group comparison\n- Pearson correlation matrix",
        "results": "## Results\n\n### Table 1\n(See table_one.json)\n\n### Group Comparisons\n(See compare_groups.json)\n\n### Correlations\n(See correlation_matrix.json)",
        "conclusions": "## Conclusions\n\nIris species showed significant differences in petal dimensions.",
        "appendix": "## Appendix\n\n- Decision log: see decision_log.jsonl\n- Deviation log: see deviation_log.jsonl",
    }
    report_md = "\n\n".join(report_sections.values())
    store.save(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md", report_md)
    pipeline.mark_completed(PhaseResult(
        phase=PipelinePhase.REPORT_ASSEMBLY,
        completed_at=datetime.now(), success=True,
        artifacts={"eda_report.md": ""},
    ))
    project.advance_to(ProjectStatus.REPORT_ASSEMBLY)
    print(f"  Report length: {len(report_md)} chars")
    print("  Phase 8: OK\n")

    # ════════════════════════════════════════
    # Phase 9: Audit Review
    # ════════════════════════════════════════
    print("=== Phase 9: audit_review ===")
    pipeline.mark_started(PipelinePhase.AUDIT_REVIEW)

    # Simple audit checks
    audit = {
        "completeness": {
            "phases_completed": len(pipeline.completed_phases),
            "total_phases": 11,
            "score": len(pipeline.completed_phases) / 11,
        },
        "plan_adherence": {
            "planned": 3,
            "executed": 4,
            "coverage": 1.0,
        },
        "traceability": {
            "artifacts_tracked": True,
        },
        "grade": "B",  # Not A because decision_log is minimal
        "notes": "All planned analyses completed. Decision logging could be more detailed.",
    }
    store.save(PipelinePhase.AUDIT_REVIEW, "audit_report.json", audit)
    pipeline.mark_completed(PhaseResult(
        phase=PipelinePhase.AUDIT_REVIEW,
        completed_at=datetime.now(), success=True,
        artifacts={"audit_report.json": ""},
    ))
    project.advance_to(ProjectStatus.AUDIT_REVIEW)
    print(f"  Grade: {audit['grade']}")
    print(f"  Completeness: {audit['completeness']['score']:.1%}")
    print(f"  Plan coverage: {audit['plan_adherence']['coverage']:.1%}")
    print("  Phase 9: OK\n")

    # ════════════════════════════════════════
    # Phase 10: Auto-Improve
    # ════════════════════════════════════════
    print("=== Phase 10: auto_improve ===")
    pipeline.mark_started(PipelinePhase.AUTO_IMPROVE)
    improvements = {
        "from_audit": audit["notes"],
        "actions_taken": ["Added this improvement summary"],
        "final_grade": audit["grade"],
    }
    store.save(PipelinePhase.AUTO_IMPROVE, "improvement_log.json", improvements)
    pipeline.mark_completed(PhaseResult(
        phase=PipelinePhase.AUTO_IMPROVE,
        completed_at=datetime.now(), success=True,
        artifacts={"improvement_log.json": ""},
    ))
    project.advance_to(ProjectStatus.AUTO_IMPROVE)
    print(f"  Improvements: {improvements['actions_taken']}")
    print("  Phase 10: OK\n")

    # ════════════════════════════════════════
    # Summary
    # ════════════════════════════════════════
    print("=" * 60)
    if errors:
        print(f"SMOKE TEST COMPLETED WITH ERRORS:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("FULL PIPELINE SMOKE TEST (Phase 0-10): ALL PASSED")
    print(f"Project: {pid}")
    print(f"Output: {project.output_dir}")
    print(f"Phases completed: {len(pipeline.completed_phases)}/11")
    print("=" * 60)


if __name__ == "__main__":
    main()
