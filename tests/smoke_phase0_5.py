"""Smoke test: Phase 0-5 (Project Setup through Pre-Explore Check)."""
import sys, uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rde.application.session import get_session
from rde.infrastructure.adapters import PandasLoader
from rde.domain.models.dataset import Dataset, DatasetMetadata
from rde.domain.models.project import Project, ProjectStatus
from rde.domain.models.variable import VariableRole
from rde.application.pipeline import PipelinePhase, PhaseResult, REQUIRED_ARTIFACTS
from rde.infrastructure.persistence.artifact_store import ArtifactStore


def main():
    session = get_session()

    # ── Phase 0: Project Setup ──
    print("=== Phase 0: init_project ===")
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
    store.save(PipelinePhase.PROJECT_SETUP, "project.yaml", {"id": pid, "name": "iris_test"})

    pipeline = session.get_pipeline(pid)
    pipeline.mark_started(PipelinePhase.PROJECT_SETUP)
    pipeline.mark_completed(PhaseResult(
        phase=PipelinePhase.PROJECT_SETUP,
        completed_at=datetime.now(), success=True,
        artifacts={"project.yaml": ""},
    ))
    project.advance_to(ProjectStatus.PROJECT_SETUP)
    print(f"  Project ID: {pid}")
    print("  Phase 0: OK\n")

    # ── Phase 1: Data Intake ──
    print("=== Phase 1: data_intake ===")
    store.save(PipelinePhase.DATA_INTAKE, "intake_report.json",
               {"status": "ok", "files": ["iris.csv"]})
    pipeline.mark_started(PipelinePhase.DATA_INTAKE)
    pipeline.mark_completed(PhaseResult(
        phase=PipelinePhase.DATA_INTAKE,
        completed_at=datetime.now(), success=True,
        artifacts={"intake_report.json": ""},
    ))
    project.advance_to(ProjectStatus.DATA_INTAKE)
    print("  Phase 1: OK\n")

    # ── Phase 2: Schema Registry ──
    print("=== Phase 2: schema_registry ===")
    loader = PandasLoader()
    iris_path = Path("vendor/automl-stat-mcp/sample_data/iris.csv")
    metadata = DatasetMetadata(
        file_path=iris_path, file_format="csv",
        file_size_bytes=iris_path.stat().st_size,
    )
    dataset = Dataset(metadata=metadata)
    df, variables, row_count = loader.load(metadata)
    dataset.mark_loaded(variables, row_count)
    session.register_dataset(dataset, df)

    store.save(PipelinePhase.SCHEMA_REGISTRY, "schema.json",
               {"variables": [v.name for v in variables], "row_count": row_count})
    pipeline.mark_started(PipelinePhase.SCHEMA_REGISTRY)
    pipeline.mark_completed(PhaseResult(
        phase=PipelinePhase.SCHEMA_REGISTRY,
        completed_at=datetime.now(), success=True,
        artifacts={"schema.json": ""},
    ))
    project.advance_to(ProjectStatus.SCHEMA_REGISTRY)
    print(f"  Rows={row_count}, Vars={len(variables)}")
    print(f"  Names: {[v.name for v in variables]}")
    print(f"  Dataset ID: {dataset.id}")
    print("  Phase 2: OK\n")

    # ── Phase 3: Concept Alignment ──
    print("=== Phase 3: concept_alignment ===")
    available_vars = {v.name: v for v in dataset.variables}
    available_vars["species"].role = VariableRole.GROUP
    for vn in ["sepal_length", "sepal_width", "petal_length", "petal_width"]:
        if vn in available_vars:
            available_vars[vn].role = VariableRole.OUTCOME

    alignment = {
        "research_question": project.research_question,
        "roles": {v.name: v.role.value for v in dataset.variables},
    }
    store.save(PipelinePhase.CONCEPT_ALIGNMENT, "concept_alignment.md",
               "# Concept Alignment\n\nIris species comparison")
    store.save(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json", alignment)
    pipeline.mark_started(PipelinePhase.CONCEPT_ALIGNMENT)
    pipeline.mark_completed(PhaseResult(
        phase=PipelinePhase.CONCEPT_ALIGNMENT,
        completed_at=datetime.now(), success=True,
        artifacts={"concept_alignment.md": "", "variable_roles.json": ""},
    ))
    project.advance_to(ProjectStatus.CONCEPT_ALIGNMENT)
    print(f"  Roles: {alignment['roles']}")
    print("  Phase 3: OK\n")

    # ── Phase 4: Plan Registration ──
    print("=== Phase 4: register_plan ===")
    plan = {
        "alpha": 0.05,
        "missing_strategy": "listwise",
        "analyses": [
            {"type": "table_one", "variables": ["sepal_length", "sepal_width", "petal_length", "petal_width"], "group": "species"},
            {"type": "compare_groups", "outcome": ["petal_length", "petal_width"], "group": "species"},
            {"type": "correlation", "variables": ["sepal_length", "sepal_width", "petal_length", "petal_width"]},
        ],
        "locked": True,
    }
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    pipeline.mark_started(PipelinePhase.PLAN_REGISTRATION)
    pipeline.mark_completed(PhaseResult(
        phase=PipelinePhase.PLAN_REGISTRATION,
        completed_at=datetime.now(), success=True,
        artifacts={"analysis_plan.yaml": ""},
    ))
    pipeline.plan_locked = True
    project.advance_to(ProjectStatus.PLAN_REGISTRATION)
    print(f"  Plan locked: {pipeline.plan_locked}")
    print(f"  Analyses planned: {len(plan['analyses'])}")
    print("  Phase 4: OK\n")

    # ── Phase 5: Pre-Explore Check ──
    print("=== Phase 5: pre_explore_check ===")
    checks = []
    checks.append({"id": "H-003", "passed": dataset.meets_min_sample_size(), "detail": f"n={row_count}"})
    checks.append({"id": "H-004", "passed": not any(v.is_pii_suspect for v in variables), "detail": "No PII"})
    checks.append({"id": "H-007", "passed": pipeline.plan_locked, "detail": "Plan locked"})
    for phase in [PipelinePhase.PROJECT_SETUP, PipelinePhase.DATA_INTAKE,
                  PipelinePhase.SCHEMA_REGISTRY, PipelinePhase.CONCEPT_ALIGNMENT,
                  PipelinePhase.PLAN_REGISTRATION]:
        required = REQUIRED_ARTIFACTS.get(phase, [])
        missing = [f for f in required if not store.exists(phase, f)]
        checks.append({"id": "H-008", "phase": phase.value, "passed": len(missing) == 0, "missing": missing})

    all_passed = all(c["passed"] for c in checks)
    store.save(PipelinePhase.PRE_EXPLORE_CHECK, "readiness_checklist.json",
               {"all_passed": all_passed, "checks": checks})
    pipeline.mark_started(PipelinePhase.PRE_EXPLORE_CHECK)
    pipeline.mark_completed(PhaseResult(
        phase=PipelinePhase.PRE_EXPLORE_CHECK,
        completed_at=datetime.now(), success=all_passed,
        artifacts={"readiness_checklist.json": ""},
    ))
    project.advance_to(ProjectStatus.PRE_EXPLORE_CHECK)
    for c in checks:
        status = "PASS" if c["passed"] else "FAIL"
        detail = c.get("detail", c.get("phase", ""))
        print(f"  [{status}] {c['id']}: {detail}")
    print(f"  All passed: {all_passed}")
    print("  Phase 5: OK\n")

    print("=" * 50)
    print(f"PHASE 0-5 SMOKE TEST: {'PASSED' if all_passed else 'FAILED'}")
    print("=" * 50)

    # Export session info for Phase 6 test
    return pid, dataset.id


if __name__ == "__main__":
    main()
