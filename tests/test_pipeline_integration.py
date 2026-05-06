# pyright: reportMissingImports=false

import asyncio
from datetime import datetime
from pathlib import Path
import re
import shutil

# mypy: disable-error-code="import-untyped, attr-defined"

from pandas import DataFrame
import pytest  # type: ignore

from rde.application.pipeline import PhaseResult, PipelinePhase, REQUIRED_ARTIFACTS
from rde.application.session import get_session
from rde.application.use_cases.compare_groups import CompareGroupsUseCase
from rde.application.use_cases.generate_report import GenerateReportUseCase
from rde.domain.models.dataset import Dataset, DatasetMetadata
from rde.domain.models.project import Project, ProjectStatus
from rde.domain.models.variable import Variable, VariableRole
from rde.domain.services.collinearity_checker import check_collinearity
from rde.infrastructure.adapters.markdown_renderer import MarkdownReportRenderer
from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.visualization.matplotlib_viz import MatplotlibVisualizer
from rde.interface.mcp.server import create_server


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


def _load_fixture_dataset() -> tuple[Dataset, DataFrame, list[Variable], int]:
    loader = PandasLoader()
    metadata = DatasetMetadata(
        file_path=FIXTURE_CSV,
        file_format="csv",
        file_size_bytes=FIXTURE_CSV.stat().st_size,
    )
    dataset = Dataset(metadata=metadata)
    df, variables, row_count, _ = loader.load(metadata)
    dataset.mark_loaded(variables, row_count)
    return dataset, df, variables, row_count


def test_phase_0_to_5_integration_creates_required_artifacts(tmp_path: Path) -> None:
    session = get_session()
    project, store = _setup_project(tmp_path)
    session.register_project(project)
    pipeline = session.get_pipeline(project.id)

    dataset, df, variables, row_count = _load_fixture_dataset()
    session.register_dataset(dataset, df)

    store.save(
        PipelinePhase.PROJECT_SETUP, "project.yaml", {"id": project.id, "name": project.name}
    )
    pipeline.mark_completed(
        PhaseResult(PipelinePhase.PROJECT_SETUP, datetime.now(), True, {"project.yaml": ""})
    )
    project.advance_to(ProjectStatus.PROJECT_SETUP)

    store.save(
        PipelinePhase.DATA_INTAKE,
        "intake_report.json",
        {
            "loaded_file": FIXTURE_CSV.name,
            "row_count": row_count,
            "column_count": len(variables),
        },
    )
    pipeline.mark_completed(
        PhaseResult(PipelinePhase.DATA_INTAKE, datetime.now(), True, {"intake_report.json": ""})
    )
    project.advance_to(ProjectStatus.DATA_INTAKE)

    store.save(
        PipelinePhase.SCHEMA_REGISTRY,
        "schema.json",
        {
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
        },
    )
    pipeline.mark_completed(
        PhaseResult(PipelinePhase.SCHEMA_REGISTRY, datetime.now(), True, {"schema.json": ""})
    )
    project.advance_to(ProjectStatus.SCHEMA_REGISTRY)

    for variable in dataset.variables:
        if variable.name == "species":
            variable.role = VariableRole.GROUP
        else:
            variable.role = VariableRole.OUTCOME

    store.save(PipelinePhase.CONCEPT_ALIGNMENT, "concept_alignment.md", "# Concept Alignment\n")
    store.save(
        PipelinePhase.CONCEPT_ALIGNMENT,
        "variable_roles.json",
        {"variable_roles": {v.name: v.role.value for v in dataset.variables}},
    )
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

    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        {
            "locked": True,
            "analyses": [
                {"type": "compare_groups", "variables": ["petal_length"], "group": "species"}
            ],
        },
    )
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

    store.save(
        PipelinePhase.PRE_EXPLORE_CHECK,
        "readiness_checklist.json",
        {
            "all_passed": True,
            "checks": [
                {"id": "H-003", "passed": True, "detail": f"n = {row_count}"},
                {"id": "H-004", "passed": True, "detail": "無 PII"},
            ],
        },
    )
    pipeline.mark_completed(
        PhaseResult(
            PipelinePhase.PRE_EXPLORE_CHECK, datetime.now(), True, {"readiness_checklist.json": ""}
        )
    )
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

    prerequisite_artifacts: dict[PipelinePhase, dict[str, object]] = {
        PipelinePhase.PROJECT_SETUP: {"project.yaml": {"id": project.id}},
        PipelinePhase.DATA_INTAKE: {
            "intake_report.json": {
                "loaded_file": FIXTURE_CSV.name,
                "row_count": row_count,
                "column_count": len(variables),
            }
        },
        PipelinePhase.SCHEMA_REGISTRY: {
            "schema.json": {
                "variables": [
                    {
                        "name": v.name,
                        "variable_type": v.variable_type.value,
                        "missing_rate": (v.n_missing / row_count if row_count else 0),
                    }
                    for v in variables
                ]
            }
        },
        PipelinePhase.CONCEPT_ALIGNMENT: {
            "concept_alignment.md": "# Concept Alignment\n",
            "variable_roles.json": {
                "variable_roles": {v.name: v.role.value for v in dataset.variables}
            },
        },
        PipelinePhase.PLAN_REGISTRATION: {
            "analysis_plan.yaml": {
                "locked": True,
                "analyses": [
                    {
                        "type": "compare_groups",
                        "variables": ["petal_length", "petal_width"],
                        "group": "species",
                    }
                ],
            }
        },
        PipelinePhase.PRE_EXPLORE_CHECK: {
            "readiness_checklist.json": {
                "all_passed": True,
                "checks": [{"id": "H-003", "passed": True, "detail": f"n = {row_count}"}],
            }
        },
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
                user_confirmed=phase
                in {PipelinePhase.CONCEPT_ALIGNMENT, PipelinePhase.PLAN_REGISTRATION},
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
        phase=PipelinePhase.EXECUTE_EXPLORATION.value,
        action="compare_groups",
        tool_used="compare_groups",
        parameters={
            "outcome_variables": ["petal_length", "petal_width"],
            "group_variable": "species",
        },
        rationale="integration test",
        result_summary=compare_result.summary,
        artifacts=["compare_groups.json"],
    )
    logger.log_deviation(
        phase=PipelinePhase.EXECUTE_EXPLORATION.value,
        planned_action="compare_groups",
        actual_action="compare_groups + correlation review",
        reason="integration coverage",
        impact_assessment="none",
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "compare_groups.json",
        {
            "summary": compare_result.summary,
            "tests": [
                {"test_name": t.test_name, "p_value": t.p_value} for t in compare_result.tests
            ],
        },
    )

    collinearity = check_collinearity(
        df, ["sepal_length", "sepal_width", "petal_length", "petal_width"]
    )
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "correlation_matrix.json",
        {
            "warnings": collinearity.format_warnings(),
        },
    )

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

    store.save(
        PipelinePhase.COLLECT_RESULTS,
        "results_summary.json",
        {
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
        },
    )
    pipeline.mark_completed(
        PhaseResult(
            PipelinePhase.COLLECT_RESULTS, datetime.now(), True, {"results_summary.json": ""}
        )
    )

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
    pipeline.mark_completed(
        PhaseResult(PipelinePhase.REPORT_ASSEMBLY, datetime.now(), True, {"eda_report.md": ""})
    )

    store.save(
        PipelinePhase.AUDIT_REVIEW,
        "audit_report.json",
        {"grade": "B", "decision_count": logger.decision_count},
    )
    pipeline.mark_completed(
        PhaseResult(PipelinePhase.AUDIT_REVIEW, datetime.now(), True, {"audit_report.json": ""})
    )

    store.save(PipelinePhase.AUTO_IMPROVE, "final_report.md", content + "\n\n# Final\n")
    pipeline.mark_completed(
        PhaseResult(PipelinePhase.AUTO_IMPROVE, datetime.now(), True, {"final_report.md": ""})
    )

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


def test_mcp_phase_6_marks_execute_phase_complete_for_collect_results(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mcp.server.fastmcp")

    raw_dir = tmp_path / "rawdata"
    raw_dir.mkdir()
    staged_csv = raw_dir / FIXTURE_CSV.name
    shutil.copy2(FIXTURE_CSV, staged_csv)

    def _textify(result: object) -> str:
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

    async def run_flow() -> str:
        server = create_server()
        session = get_session()

        await server.call_tool(
            "init_project",
            {
                "name": "mcp-phase6-collect",
                "data_dir": str(raw_dir),
                "research_question": "Do iris species differ in petal length?",
            },
        )
        project = session.get_project()

        await server.call_tool(
            "run_intake",
            {
                "directory": str(raw_dir),
                "project_id": project.id,
            },
        )

        dataset_id = session.list_datasets()[0]
        await server.call_tool(
            "build_schema",
            {
                "dataset_id": dataset_id,
                "project_id": project.id,
            },
        )
        await server.call_tool(
            "align_concept",
            {
                "project_id": project.id,
                "research_question": "Do iris species differ in petal length?",
                "variable_roles": {
                    "group": "species",
                    "outcome": ["petal_length"],
                },
                "confirm": True,
            },
        )
        await server.call_tool(
            "register_analysis_plan",
            {
                "project_id": project.id,
                "analyses": [
                    {
                        "type": "generate_table_one",
                        "variables": ["species", "sepal_length", "petal_length"],
                        "rationale": "paper-ready baseline table",
                    },
                    {
                        "type": "compare_groups",
                        "variables": ["species", "petal_length"],
                        "rationale": "integration regression",
                    },
                    {
                        "type": "descriptive",
                        "variables": ["petal_length"],
                        "rationale": "coverage regression",
                    },
                    {
                        "type": "visualization",
                        "variables": ["species", "petal_length"],
                        "rationale": "coverage regression",
                    },
                ],
                "confirm": True,
            },
        )
        await server.call_tool("check_readiness", {"project_id": project.id})
        pipeline = session.get_pipeline(project.id)
        await server.call_tool(
            "generate_table_one",
            {
                "dataset_id": dataset_id,
                "group_variable": "species",
                "variables": ["sepal_length", "petal_length"],
            },
        )
        assert PipelinePhase.EXECUTE_EXPLORATION not in pipeline.completed_phases
        early_collect = await server.call_tool("collect_results", {"project_id": project.id})
        assert "Phase 8" in _textify(early_collect)
        assert PipelinePhase.EXECUTE_EXPLORATION not in pipeline.completed_phases
        await server.call_tool(
            "compare_groups",
            {
                "dataset_id": dataset_id,
                "outcome_variables": ["petal_length"],
                "group_variable": "species",
            },
        )
        await server.call_tool(
            "analyze_variable",
            {
                "dataset_id": dataset_id,
                "variable_name": "petal_length",
            },
        )
        await server.call_tool(
            "create_visualization",
            {
                "dataset_id": dataset_id,
                "plot_type": "boxplot",
                "variables": ["petal_length"],
                "group_var": "species",
                "output_filename": "petal_length_by_species.png",
            },
        )

        collect_result = await server.call_tool("collect_results", {"project_id": project.id})
        pipeline = session.get_pipeline(project.id)
        store = ArtifactStore(project.artifacts_dir)
        results = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
        assert PipelinePhase.EXECUTE_EXPLORATION in pipeline.completed_phases
        assert store.exists(PipelinePhase.EXECUTE_EXPLORATION, "table_one.md")
        assert store.exists(PipelinePhase.EXECUTE_EXPLORATION, "table_one.json")
        assert results["total_analyses"] == 4
        assert results["plan_coverage"] == {"planned": 4, "executed": 4, "coverage": 1.0}
        return _textify(collect_result)

    collect_output = asyncio.run(run_flow())

    assert "❌" not in collect_output
    assert "結果彙整" in collect_output
    assert "100% (4/4)" in collect_output


def test_full_mcp_planning_flow_completes_phase_4_5_6_contract(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")

    raw_dir = tmp_path / "rawdata"
    raw_dir.mkdir()
    staged_csv = raw_dir / FIXTURE_CSV.name
    shutil.copy2(FIXTURE_CSV, staged_csv)

    async def run_flow() -> Project:
        server = create_server()
        session = get_session()

        await server.call_tool(
            "init_project",
            {
                "name": "mcp-planning-contract",
                "data_dir": str(raw_dir),
                "research_question": "Do iris species differ in petal length?",
            },
        )
        project = session.get_project()
        await server.call_tool("run_intake", {"directory": str(raw_dir), "project_id": project.id})
        dataset_id = session.list_datasets()[0]
        await server.call_tool(
            "build_schema",
            {
                "dataset_id": dataset_id,
                "project_id": project.id,
            },
        )
        await server.call_tool(
            "align_concept",
            {
                "project_id": project.id,
                "research_question": "Do iris species differ in petal length?",
                "variable_roles": {
                    "group": "species",
                    "outcome": ["petal_length"],
                },
                "confirm": True,
            },
        )
        await server.call_tool(
            "propose_analysis_plan",
            {
                "project_id": project.id,
                "dataset_id": dataset_id,
                "max_analyses": 4,
            },
        )
        await server.call_tool(
            "register_analysis_plan",
            {
                "project_id": project.id,
                "analyses": [
                    {
                        "type": "generate_table_one",
                        "variables": ["species", "sepal_length", "petal_length"],
                        "rationale": "paper-ready baseline table",
                    },
                    {
                        "type": "compare_groups",
                        "variables": ["species", "petal_length"],
                        "rationale": "compare outcome by species",
                    },
                    {
                        "type": "descriptive",
                        "variables": ["petal_length"],
                        "rationale": "describe primary outcome",
                    },
                    {
                        "type": "visualization",
                        "variables": ["species", "petal_length"],
                        "plot_type": "boxplot",
                        "rationale": "visualize group contrast",
                    },
                ],
                "allow_methodology_override": True,
                "confirm": True,
            },
        )
        return project

    project = asyncio.run(run_flow())
    session = get_session()
    pipeline = session.get_pipeline(project.id)
    store = ArtifactStore(project.artifacts_dir)

    assert PipelinePhase.CREATIVE_IDEATION in pipeline.completed_phases
    assert PipelinePhase.PLAN_COMPLETENESS_REVIEW in pipeline.completed_phases
    assert PipelinePhase.PLAN_REGISTRATION in pipeline.completed_phases
    assert pipeline.plan_locked is True
    assert store.exists(PipelinePhase.CREATIVE_IDEATION, "greedy_analysis_candidates.json")
    assert store.exists(PipelinePhase.PLAN_COMPLETENESS_REVIEW, "analysis_plan_review.json")
    assert store.exists(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")


def test_init_project_uses_timestamp_prefixed_readable_output_directory(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")

    raw_dir = tmp_path / "rawdata"
    raw_dir.mkdir()

    def _textify(result: object) -> str:
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

    async def run_flow() -> tuple[str, str, str]:
        server = create_server()
        session = get_session()

        result = await server.call_tool(
            "init_project",
            {
                "name": "timestamp-order-check",
                "data_dir": str(raw_dir),
            },
        )
        project = session.get_project()
        return _textify(result), project.id, project.output_dir.name

    output, project_id, folder_name = asyncio.run(run_flow())

    assert re.fullmatch(r"\d{8}_\d{6}_timestamp-order-check_[0-9a-f]{8}", folder_name)
    assert folder_name.endswith(f"_{project_id}")
    assert folder_name in output
    assert f"data/projects/{folder_name}" in output.replace("\\", "/")


def test_init_project_uses_workspace_env_for_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp.server.fastmcp")

    workspace_dir = tmp_path / "workspace"
    raw_dir = workspace_dir / "rawdata"
    raw_dir.mkdir(parents=True)
    server_cwd = tmp_path / "server-cwd"
    server_cwd.mkdir()

    monkeypatch.setenv("RDE_WORKSPACE", str(workspace_dir))
    monkeypatch.chdir(server_cwd)

    async def run_flow() -> Project:
        server = create_server()
        session = get_session()

        await server.call_tool(
            "init_project",
            {
                "name": "workspace-output-check",
                "data_dir": str(raw_dir),
            },
        )
        return session.get_project()

    project = asyncio.run(run_flow())
    expected_base = workspace_dir / "data" / "projects"

    assert project.output_dir.parent == expected_base
    assert project.output_dir.exists()
    assert "workspace-output-check" in project.output_dir.name
    assert project.output_dir.name.endswith(f"_{project.id}")


def test_init_project_persists_project_setup_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp.server.fastmcp")

    from rde.infrastructure.persistence import FileSystemProjectRepository, resolve_projects_base_dir

    workspace_dir = tmp_path / "workspace"
    raw_dir = workspace_dir / "rawdata"
    raw_dir.mkdir(parents=True)
    monkeypatch.setenv("RDE_WORKSPACE", str(workspace_dir))

    async def run_flow() -> Project:
        server = create_server()
        session = get_session()
        await server.call_tool(
            "init_project",
            {
                "name": "persisted-phase-zero-check",
                "data_dir": str(raw_dir),
            },
        )
        return session.get_project()

    project = asyncio.run(run_flow())

    repo = FileSystemProjectRepository(resolve_projects_base_dir())
    persisted = repo.load_project(project.id)

    assert persisted.status == ProjectStatus.PROJECT_SETUP
    assert ProjectStatus.PROJECT_SETUP in persisted.completed_phases


def test_check_readiness_uses_project_bound_dataset_when_session_has_multiple_datasets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp.server.fastmcp")

    from rde.infrastructure.persistence import FileSystemProjectRepository, resolve_projects_base_dir

    workspace_dir = tmp_path / "workspace"
    raw_dir = workspace_dir / "rawdata"
    raw_dir.mkdir(parents=True)
    monkeypatch.setenv("RDE_WORKSPACE", str(workspace_dir))

    legacy_csv = raw_dir / "legacy_session_dataset.csv"
    project_csv = raw_dir / "project_bound_dataset.csv"

    DataFrame(
        {
            "treatment": ["A", "B", "A", "B", "A"],
            "outcome": [1, 0, 1, 0, 1],
            "age": [61, 58, 64, 55, 67],
            "score": [3.2, 2.9, 3.5, 2.7, 3.1],
        }
    ).to_csv(legacy_csv, index=False)
    DataFrame(
        {
            "treatment": ["A", "B"] * 6,
            "outcome": [1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1],
            "age": [61, 58, 64, 55, 67, 59, 62, 60, 66, 57, 63, 68],
            "score": [3.2, 2.9, 3.5, 2.7, 3.1, 2.8, 3.0, 2.6, 3.4, 2.5, 3.3, 3.6],
        }
    ).to_csv(project_csv, index=False)

    def _textify(result: object) -> str:
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

    async def run_flow() -> tuple[str, Project]:
        server = create_server()
        session = get_session()

        await server.call_tool("load_dataset", {"file_path": str(legacy_csv)})
        await server.call_tool(
            "init_project",
            {
                "name": "dataset-scope-check",
                "data_dir": str(raw_dir),
                "research_question": "Does treatment affect outcome?",
            },
        )
        await server.call_tool("load_dataset", {"file_path": str(project_csv)})
        await server.call_tool("build_schema", {})
        await server.call_tool(
            "align_concept",
            {
                "research_question": "Does treatment affect outcome?",
                "variable_roles": {
                    "outcome": "outcome",
                    "group": "treatment",
                    "covariates": ["age", "score"],
                },
                "confirm": True,
            },
        )
        await server.call_tool(
            "register_analysis_plan",
            {
                "analyses": [
                    {
                        "type": "compare_groups",
                        "variables": ["outcome", "treatment"],
                        "rationale": "Compare outcome by treatment group",
                    }
                ],
                "allow_methodology_override": True,
                "confirm": True,
            },
        )
        readiness = await server.call_tool("check_readiness", {})
        return _textify(readiness), session.get_project()

    readiness_output, project = asyncio.run(run_flow())

    repo = FileSystemProjectRepository(resolve_projects_base_dir())
    persisted = repo.load_project(project.id)

    assert "n = 12" in readiness_output
    assert "n = 5" not in readiness_output
    assert "無 PII" in readiness_output
    assert "Shapiro-Wilk" in readiness_output
    assert persisted.dataset_ids == project.dataset_ids
    assert len(persisted.dataset_ids) == 1


def test_project_bound_dataset_rehydrates_after_session_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp.server.fastmcp")

    workspace_dir = tmp_path / "workspace"
    raw_dir = workspace_dir / "rawdata"
    raw_dir.mkdir(parents=True)
    staged_csv = raw_dir / FIXTURE_CSV.name
    shutil.copy2(FIXTURE_CSV, staged_csv)
    monkeypatch.setenv("RDE_WORKSPACE", str(workspace_dir))

    async def run_flow() -> tuple[str, str]:
        server = create_server()
        session = get_session()

        await server.call_tool(
            "init_project",
            {
                "name": "rehydrate-bound-dataset",
                "data_dir": str(raw_dir),
            },
        )
        project = session.get_project()
        await server.call_tool("run_intake", {"directory": str(raw_dir), "project_id": project.id})
        dataset_id = session.list_datasets()[0]
        await server.call_tool(
            "build_schema",
            {
                "dataset_id": dataset_id,
                "project_id": project.id,
            },
        )
        return project.id, dataset_id

    project_id, dataset_id = asyncio.run(run_flow())

    import rde.application.session as session_module
    from rde.interface.mcp.tools._shared.project_context import (
        ensure_dataset,
        ensure_project_context,
    )

    session_module._session = None
    ok, message, project = ensure_project_context(project_id)
    assert ok, message
    assert project is not None

    ok, message, entry = ensure_dataset(project=project)

    assert ok, message
    assert entry is not None
    assert entry.dataset.id == dataset_id
    assert entry.dataset.row_count == 12
    assert list(entry.dataframe.columns) == [
        "sepal_length",
        "sepal_width",
        "petal_length",
        "petal_width",
        "species",
    ]


def test_get_pipeline_status_rehydrates_persisted_project_after_session_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp.server.fastmcp")

    from rde.infrastructure.persistence import (
        FileSystemProjectRepository,
        resolve_projects_base_dir,
    )

    workspace_dir = tmp_path / "workspace"
    raw_dir = workspace_dir / "rawdata"
    raw_dir.mkdir(parents=True)
    monkeypatch.setenv("RDE_WORKSPACE", str(workspace_dir))

    projects_base_dir = resolve_projects_base_dir()
    output_dir = projects_base_dir / "20260414_120000_rehyd123"
    output_dir.mkdir(parents=True)
    (output_dir / "artifacts").mkdir(exist_ok=True)
    (output_dir / "figures").mkdir(exist_ok=True)

    project = Project(
        id="rehyd123",
        name="rehydrated-project",
        data_dir=raw_dir,
        output_dir=output_dir,
        created_at=datetime(2026, 4, 14, 12, 0, 0),
        research_question="Can a persisted project survive MCP session reset?",
    )
    project.advance_to(ProjectStatus.PROJECT_SETUP)
    project.advance_to(ProjectStatus.DATA_INTAKE)
    project.advance_to(ProjectStatus.SCHEMA_REGISTRY)
    project.advance_to(ProjectStatus.CONCEPT_ALIGNMENT)
    project.advance_to(ProjectStatus.PLAN_REGISTRATION)

    repo = FileSystemProjectRepository(projects_base_dir)
    repo.save(project)

    def _textify(result: object) -> str:
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

    async def run_flow() -> str:
        server = create_server()
        result = await server.call_tool("get_pipeline_status", {"project_id": project.id})
        return _textify(result)

    output = asyncio.run(run_flow())

    assert "rehydrated-project" in output
    assert "🔒 已鎖定" in output
    assert "phase_06_plan_registration" in output
    assert "phase_04_creative_ideation" in output


def test_get_pipeline_status_repairs_stale_project_state_from_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp.server.fastmcp")

    from rde.infrastructure.persistence import (
        FileSystemProjectRepository,
        resolve_projects_base_dir,
    )

    workspace_dir = tmp_path / "workspace"
    raw_dir = workspace_dir / "rawdata"
    raw_dir.mkdir(parents=True)
    monkeypatch.setenv("RDE_WORKSPACE", str(workspace_dir))

    projects_base_dir = resolve_projects_base_dir()
    output_dir = projects_base_dir / "20260414_150000_stalefix"
    output_dir.mkdir(parents=True)
    (output_dir / "artifacts").mkdir(exist_ok=True)
    (output_dir / "figures").mkdir(exist_ok=True)

    project = Project(
        id="stalefix",
        name="stale-artifact-project",
        data_dir=raw_dir,
        output_dir=output_dir,
        created_at=datetime(2026, 4, 14, 15, 0, 0),
        research_question="Can stale project JSON recover from later artifacts?",
        status=ProjectStatus.PRE_EXPLORE_CHECK,
        completed_phases=[
            ProjectStatus.PROJECT_SETUP,
            ProjectStatus.DATA_INTAKE,
            ProjectStatus.SCHEMA_REGISTRY,
            ProjectStatus.CONCEPT_ALIGNMENT,
            ProjectStatus.PLAN_REGISTRATION,
            ProjectStatus.PRE_EXPLORE_CHECK,
        ],
        plan_locked=True,
    )

    repo = FileSystemProjectRepository(projects_base_dir)
    repo.save(project)

    store = ArtifactStore(project.artifacts_dir)
    store.save(PipelinePhase.PROJECT_SETUP, "project.yaml", {"id": project.id})
    store.save(PipelinePhase.DATA_INTAKE, "intake_report.json", {"dataset_id": "legacy-ds"})
    store.save(PipelinePhase.SCHEMA_REGISTRY, "schema.json", {"variables": []})
    store.save(PipelinePhase.CONCEPT_ALIGNMENT, "concept_alignment.md", "aligned")
    store.save(
        PipelinePhase.CONCEPT_ALIGNMENT,
        "variable_roles.json",
        {"dataset": "legacy-ds", "group": "treatment"},
    )
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", {"analyses": []})
    store.save(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json", {"checks": []})
    store.save(
        PipelinePhase.EXECUTE_EXPLORATION,
        "decision_log.jsonl",
        {"action": "legacy execution"},
    )
    store.save(
        PipelinePhase.COLLECT_RESULTS,
        "results_summary.json",
        {"project_id": project.id, "summary": "results collected"},
    )
    store.save(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md", "# report")
    store.save(PipelinePhase.AUDIT_REVIEW, "audit_report.json", {"grade": "B"})
    store.save(PipelinePhase.AUTO_IMPROVE, "final_report.md", "# final")

    def _textify(result: object) -> str:
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

    async def run_flow() -> str:
        server = create_server()
        result = await server.call_tool("get_pipeline_status", {"project_id": project.id})
        return _textify(result)

    output = asyncio.run(run_flow())
    repaired = repo.load_project(project.id)

    assert "phase_12_auto_improve" in output
    assert repaired.status == ProjectStatus.AUTO_IMPROVE
    assert ProjectStatus.AUTO_IMPROVE in repaired.completed_phases
    assert ProjectStatus.COLLECT_RESULTS in repaired.completed_phases
    assert ProjectStatus.REPORT_ASSEMBLY in repaired.completed_phases
    assert ProjectStatus.AUDIT_REVIEW in repaired.completed_phases


def test_project_advance_to_does_not_regress_later_status() -> None:
    project = Project(
        id="phase-guard",
        name="phase-guard",
        data_dir=Path("data/rawdata"),
        output_dir=Path("data/projects/phase-guard"),
        status=ProjectStatus.AUTO_IMPROVE,
        completed_phases=[
            ProjectStatus.PROJECT_SETUP,
            ProjectStatus.DATA_INTAKE,
            ProjectStatus.SCHEMA_REGISTRY,
            ProjectStatus.CONCEPT_ALIGNMENT,
            ProjectStatus.PLAN_REGISTRATION,
            ProjectStatus.PRE_EXPLORE_CHECK,
            ProjectStatus.EXECUTE_EXPLORATION,
            ProjectStatus.COLLECT_RESULTS,
            ProjectStatus.REPORT_ASSEMBLY,
            ProjectStatus.AUDIT_REVIEW,
            ProjectStatus.AUTO_IMPROVE,
        ],
        plan_locked=True,
    )

    project.advance_to(ProjectStatus.EXECUTE_EXPLORATION)
    project.advance_to(ProjectStatus.AUDIT_REVIEW)

    assert project.status == ProjectStatus.AUTO_IMPROVE
    assert project.completed_phases[-1] == ProjectStatus.AUTO_IMPROVE
    assert project.plan_locked is True
