from datetime import datetime
from pathlib import Path

from rde.application.pipeline import PhaseResult, PipelinePhase, REQUIRED_ARTIFACTS
from rde.application.session import get_session
from rde.application.use_cases.compare_groups import CompareGroupsUseCase
from rde.application.use_cases.generate_report import GenerateReportUseCase
from rde.domain.models.dataset import Dataset, DatasetMetadata
from rde.domain.models.project import Project, ProjectStatus
from rde.domain.models.variable import VariableRole
from rde.domain.services.collinearity_checker import check_collinearity
from rde.infrastructure.adapters.markdown_renderer import MarkdownReportRenderer
from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.visualization.matplotlib_viz import MatplotlibVisualizer


FIXTURE_CSV = Path(__file__).parent / "fixtures" / "iris_sample.csv"


def _setup_project(tmp_path: Path) -> tuple[Project, ArtifactStore]:
    project = Project(
        id="proj-int",
        name="integration",
        data_dir=tmp_path / "rawdata",
        output_dir=tmp_path / "project-output",
        research_question="Do iris species differ in sepal and petal measurements?",
    )
    project.output_dir.mkdir(parents=True, exist_ok=True)
    (project.output_dir / "artifacts").mkdir(exist_ok=True)
    (project.output_dir / "figures").mkdir(exist_ok=True)
    store = ArtifactStore(project.artifacts_dir)
    return project, store


def _load_fixture_dataset() -> tuple[Dataset, object, list[object], int]:
    loader = PandasLoader()
    metadata = DatasetMetadata(
        file_path=FIXTURE_CSV,
        file_format="csv",
        file_size_bytes=FIXTURE_CSV.stat().st_size,
    )
    dataset = Dataset(metadata=metadata)
    df, variables, row_count = loader.load(metadata)
    dataset.mark_loaded(variables, row_count)
    return dataset, df, variables, row_count


def test_phase_0_to_5_integration_creates_required_artifacts(tmp_path: Path) -> None:
    session = get_session()
    project, store = _setup_project(tmp_path)
    session.register_project(project)
    pipeline = session.get_pipeline(project.id)

    dataset, df, variables, row_count = _load_fixture_dataset()
    session.register_dataset(dataset, df)

    store.save(PipelinePhase.PROJECT_SETUP, "project.yaml", {"id": project.id, "name": project.name})
    pipeline.mark_completed(PhaseResult(PipelinePhase.PROJECT_SETUP, datetime.now(), True, {"project.yaml": ""}))
    project.advance_to(ProjectStatus.PROJECT_SETUP)

    store.save(PipelinePhase.DATA_INTAKE, "intake_report.json", {
        "loaded_file": FIXTURE_CSV.name,
        "row_count": row_count,
        "column_count": len(variables),
    })
    pipeline.mark_completed(PhaseResult(PipelinePhase.DATA_INTAKE, datetime.now(), True, {"intake_report.json": ""}))
    project.advance_to(ProjectStatus.DATA_INTAKE)

    store.save(PipelinePhase.SCHEMA_REGISTRY, "schema.json", {
        "row_count": row_count,
        "column_count": len(variables),
        "variables": [
            {
                "name": v.name,
                "variable_type": v.variable_type.value,
                "missing_rate": (v.n_missing / row_count if row_count else 0),
            }
            for v in variables
        ],
    })
    pipeline.mark_completed(PhaseResult(PipelinePhase.SCHEMA_REGISTRY, datetime.now(), True, {"schema.json": ""}))
    project.advance_to(ProjectStatus.SCHEMA_REGISTRY)

    for variable in dataset.variables:
        if variable.name == "species":
            variable.role = VariableRole.GROUP
        else:
            variable.role = VariableRole.OUTCOME

    store.save(PipelinePhase.CONCEPT_ALIGNMENT, "concept_alignment.md", "# Concept Alignment\n")
    store.save(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json", {
        "variable_roles": {v.name: v.role.value for v in dataset.variables}
    })
    pipeline.mark_completed(
        PhaseResult(
            PipelinePhase.CONCEPT_ALIGNMENT,
            datetime.now(),
            True,
            {"concept_alignment.md": "", "variable_roles.json": ""},
            user_confirmed=True,
        )
    )
    project.advance_to(ProjectStatus.CONCEPT_ALIGNMENT)

    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", {
        "locked": True,
        "analyses": [{"type": "compare_groups", "variables": ["petal_length"], "group": "species"}],
    })
    pipeline.mark_completed(
        PhaseResult(
            PipelinePhase.PLAN_REGISTRATION,
            datetime.now(),
            True,
            {"analysis_plan.yaml": ""},
            user_confirmed=True,
        )
    )
    project.advance_to(ProjectStatus.PLAN_REGISTRATION)

    store.save(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json", {
        "all_passed": True,
        "checks": [
            {"id": "H-003", "passed": True, "detail": f"n = {row_count}"},
            {"id": "H-004", "passed": True, "detail": "無 PII"},
        ],
    })
    pipeline.mark_completed(PhaseResult(PipelinePhase.PRE_EXPLORE_CHECK, datetime.now(), True, {"readiness_checklist.json": ""}))
    project.advance_to(ProjectStatus.PRE_EXPLORE_CHECK)

    for phase in [
        PipelinePhase.PROJECT_SETUP,
        PipelinePhase.DATA_INTAKE,
        PipelinePhase.SCHEMA_REGISTRY,
        PipelinePhase.CONCEPT_ALIGNMENT,
        PipelinePhase.PLAN_REGISTRATION,
        PipelinePhase.PRE_EXPLORE_CHECK,
    ]:
        present, missing = store.check_artifacts(phase)
        assert present, f"{phase.value} missing {missing}"

    can_execute, reason = pipeline.can_execute(PipelinePhase.EXECUTE_EXPLORATION)
    assert can_execute is True, reason


def test_phase_6_to_10_integration_produces_audit_trail_and_report(tmp_path: Path) -> None:
    session = get_session()
    project, store = _setup_project(tmp_path)
    session.register_project(project)
    pipeline = session.get_pipeline(project.id)
    logger = session.get_logger(project.id)

    dataset, df, variables, row_count = _load_fixture_dataset()
    session.register_dataset(dataset, df)
    for variable in dataset.variables:
        if variable.name == "species":
            variable.role = VariableRole.GROUP
        else:
            variable.role = VariableRole.OUTCOME

    prerequisite_artifacts = {
        PipelinePhase.PROJECT_SETUP: {"project.yaml": {"id": project.id}},
        PipelinePhase.DATA_INTAKE: {"intake_report.json": {"loaded_file": FIXTURE_CSV.name, "row_count": row_count, "column_count": len(variables)}},
        PipelinePhase.SCHEMA_REGISTRY: {"schema.json": {"variables": [{"name": v.name, "variable_type": v.variable_type.value, "missing_rate": (v.n_missing / row_count if row_count else 0)} for v in variables]}},
        PipelinePhase.CONCEPT_ALIGNMENT: {
            "concept_alignment.md": "# Concept Alignment\n",
            "variable_roles.json": {"variable_roles": {v.name: v.role.value for v in dataset.variables}},
        },
        PipelinePhase.PLAN_REGISTRATION: {"analysis_plan.yaml": {"locked": True, "analyses": [{"type": "compare_groups", "variables": ["petal_length", "petal_width"], "group": "species"}]}},
        PipelinePhase.PRE_EXPLORE_CHECK: {"readiness_checklist.json": {"all_passed": True, "checks": [{"id": "H-003", "passed": True, "detail": f"n = {row_count}"}] }},
    }
    for phase, artifact_map in prerequisite_artifacts.items():
        for filename, payload in artifact_map.items():
            store.save(phase, filename, payload)
        pipeline.mark_completed(
            PhaseResult(
                phase,
                datetime.now(),
                True,
                {filename: "" for filename in artifact_map},
                user_confirmed=phase in {PipelinePhase.CONCEPT_ALIGNMENT, PipelinePhase.PLAN_REGISTRATION},
            )
        )

    engine = ScipyStatisticalEngine()
    compare_result = CompareGroupsUseCase(engine).execute(
        dataset=dataset,
        raw_data=df,
        outcome_variables=["petal_length", "petal_width"],
        group_variable="species",
    )
    session.get_dataset_entry(dataset.id).analysis_results.append(compare_result)
    logger.log_decision(
        phase="phase_06",
        action="compare_groups",
        tool_used="compare_groups",
        parameters={"outcome_variables": ["petal_length", "petal_width"], "group_variable": "species"},
        rationale="integration test",
        result_summary=compare_result.summary,
        artifacts=["compare_groups.json"],
    )
    logger.log_deviation(
        phase="phase_06",
        planned_action="compare_groups",
        actual_action="compare_groups + correlation review",
        reason="integration coverage",
        impact_assessment="none",
    )
    store.save(PipelinePhase.EXECUTE_EXPLORATION, "compare_groups.json", {
        "summary": compare_result.summary,
        "tests": [{"test_name": t.test_name, "p_value": t.p_value} for t in compare_result.tests],
    })

    collinearity = check_collinearity(df, ["sepal_length", "sepal_width", "petal_length", "petal_width"])
    store.save(PipelinePhase.EXECUTE_EXPLORATION, "correlation_matrix.json", {
        "warnings": collinearity.format_warnings(),
    })

    figure_path = project.output_dir / "figures" / "boxplot_petal_length.png"
    MatplotlibVisualizer().create_plot(
        data=df,
        plot_type="boxplot",
        variables=["petal_length"],
        output_path=figure_path,
        group_var="species",
    )

    pipeline.mark_completed(
        PhaseResult(
            PipelinePhase.EXECUTE_EXPLORATION,
            datetime.now(),
            True,
            {
                "decision_log.jsonl": "",
                "compare_groups.json": "",
                "correlation_matrix.json": "",
            },
        )
    )

    store.save(PipelinePhase.COLLECT_RESULTS, "results_summary.json", {
        "total_analyses": 1,
        "publishable_count": len(compare_result.significant_tests),
        "publishable_items": [
            {
                "test_name": t.test_name,
                "variables": list(t.variables_involved),
                "p_value": t.p_value,
                "effect_size": t.effect_size,
                "effect_size_name": t.effect_size_name,
            }
            for t in compare_result.significant_tests
        ],
        "decision_count": logger.decision_count,
        "deviation_count": logger.deviation_count,
        "plan_coverage": {"planned": 1, "executed": 1, "coverage": 1.0},
    })
    pipeline.mark_completed(PhaseResult(PipelinePhase.COLLECT_RESULTS, datetime.now(), True, {"results_summary.json": ""}))

    report = GenerateReportUseCase(MarkdownReportRenderer()).execute(
        dataset_id=dataset.id,
        project_id=project.id,
        title="Integration Report",
        artifacts={
            "data_overview": f"rows={row_count}",
            "data_quality": "all passed",
            "variable_profiles": "variables ready",
            "key_findings": "petal variables differ across species",
            "statistical_analyses": compare_result.summary,
            "recommendations": "run audit",
        },
    )
    content = GenerateReportUseCase(MarkdownReportRenderer()).render(report, "markdown")
    store.save(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md", content)
    pipeline.mark_completed(PhaseResult(PipelinePhase.REPORT_ASSEMBLY, datetime.now(), True, {"eda_report.md": ""}))

    store.save(PipelinePhase.AUDIT_REVIEW, "audit_report.json", {"grade": "B", "decision_count": logger.decision_count})
    pipeline.mark_completed(PhaseResult(PipelinePhase.AUDIT_REVIEW, datetime.now(), True, {"audit_report.json": ""}))

    store.save(PipelinePhase.AUTO_IMPROVE, "final_report.md", content + "\n\n# Final\n")
    pipeline.mark_completed(PhaseResult(PipelinePhase.AUTO_IMPROVE, datetime.now(), True, {"final_report.md": ""}))

    assert logger.decision_count == 1
    assert logger.deviation_count == 1
    assert project.decision_log_path.exists()
    assert project.deviation_log_path.exists()
    assert figure_path.exists()
    assert "Integration Report" in content

    for phase in [
        PipelinePhase.EXECUTE_EXPLORATION,
        PipelinePhase.COLLECT_RESULTS,
        PipelinePhase.REPORT_ASSEMBLY,
        PipelinePhase.AUDIT_REVIEW,
        PipelinePhase.AUTO_IMPROVE,
    ]:
        present, missing = store.check_artifacts(phase)
        required = REQUIRED_ARTIFACTS.get(phase, [])
        if required:
            assert present, f"{phase.value} missing {missing}"