"""Project & dataset context helpers — reusable validation across tools."""

from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
import uuid

from rde.application.pipeline import (
    PREREQUISITES,
    OPTIONAL_PHASES,
    PhaseResult,
    PipelinePhase,
    PipelineState,
)
from rde.application.session import get_session, DatasetEntry
from rde.domain.models.dataset import Dataset, DatasetMetadata
from rde.domain.models.project import Project
from rde.domain.models.project import ProjectStatus
from rde.domain.models.variable import VariableRole
from rde.domain.policies.hard_constraints import HardConstraints
from rde.infrastructure.persistence.artifact_store import ArtifactStore


def ensure_project_context(
    project_id: str | None = None,
) -> tuple[bool, str, Project | None]:
    """Validate and return the active project.

    Returns:
        (is_valid, message, project_or_none)
    """
    session = get_session()
    try:
        project = session.get_project(project_id)
        return True, f"專案: {project.name} ({project.id})", project
    except KeyError as e:
        message = e.args[0] if e.args else str(e)
        return False, str(message), None


def persist_project(project: Project) -> None:
    """Persist the latest in-memory project state to the repository."""
    from rde.infrastructure.persistence import (
        FileSystemProjectRepository,
        resolve_projects_base_dir,
    )

    repo = FileSystemProjectRepository(resolve_projects_base_dir())
    repo.save(project)


def _recover_project_dataset_ids(project: Project) -> list[str]:
    """Recover dataset bindings from project artifacts for legacy projects."""
    store = ArtifactStore(project.artifacts_dir)
    recovered: list[str] = []

    intake = store.load(PipelinePhase.DATA_INTAKE, "intake_report.json")
    if isinstance(intake, dict):
        dataset_id = intake.get("dataset_id")
        if isinstance(dataset_id, str) and dataset_id.strip():
            recovered.append(dataset_id.strip())

    alignment = store.load(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json")
    if isinstance(alignment, dict):
        dataset_id = alignment.get("dataset")
        if isinstance(dataset_id, str) and dataset_id.strip():
            recovered.append(dataset_id.strip())

    return list(dict.fromkeys(recovered))


def project_dataset_ids(project: Project | None = None) -> list[str]:
    """Return dataset ids scoped to the current project when available."""
    session = get_session()
    if project is not None:
        if project.dataset_ids:
            return list(dict.fromkeys(project.dataset_ids))
        recovered = _recover_project_dataset_ids(project)
        if recovered:
            return recovered

    if project is None and session.active_project_id:
        try:
            active_project = session.get_project()
        except KeyError:
            active_project = None
        if active_project is not None:
            if active_project.dataset_ids:
                return list(dict.fromkeys(active_project.dataset_ids))
            recovered = _recover_project_dataset_ids(active_project)
            if recovered:
                return recovered

    return session.list_datasets()


def link_dataset_to_project(project: Project, dataset_id: str) -> None:
    """Attach a dataset to the project and persist the association."""
    if dataset_id not in project.dataset_ids:
        project.dataset_ids.append(dataset_id)
        persist_project(project)


def _session_dataset_schema(entry: DatasetEntry) -> dict[str, object]:
    dataset = entry.dataset
    existing_schema = dataset.tags.get("schema_registry")
    if isinstance(existing_schema, dict) and existing_schema.get("dataset_id") == dataset.id:
        schema = dict(existing_schema)
        schema["auto_recovered_from_session"] = True
        return schema

    variables: list[dict[str, object]] = []
    for variable in dataset.variables:
        missing_rate = variable.n_missing / dataset.row_count if dataset.row_count else 0
        variables.append(
            {
                "name": variable.name,
                "dtype": variable.dtype,
                "variable_type": variable.variable_type.value,
                "role": variable.role.value,
                "n_missing": variable.n_missing,
                "missing_rate": round(missing_rate, 4),
                "n_unique": variable.n_unique,
                "is_pii_suspect": variable.is_pii_suspect,
            }
        )
    return {
        "dataset_id": dataset.id,
        "row_count": dataset.row_count,
        "column_count": len(dataset.variables),
        "variables": variables,
        "created_at": datetime.now().isoformat(),
        "auto_recovered_from_session": True,
    }


def recover_project_context_from_session(
    *,
    research_question: str = "",
    dataset_id: str | None = None,
) -> tuple[Project | None, str]:
    """Create a minimal auditable project when intake/schema ran before Phase 0."""

    session = get_session()
    if session.active_project_id:
        try:
            return session.get_project(), ""
        except KeyError:
            pass

    candidate_ids = [dataset_id] if dataset_id else session.list_datasets()
    candidate_ids = [candidate for candidate in candidate_ids if candidate]
    if not candidate_ids:
        return None, ""
    if dataset_id is None and len(candidate_ids) != 1:
        return None, (
            "Multiple datasets are loaded but no project is active; pass dataset_id or call "
            "init_project() so Phase 3 can bind the right dataset."
        )

    resolved_dataset_id = candidate_ids[-1]
    try:
        entry = session.get_dataset_entry(resolved_dataset_id)
    except KeyError:
        return None, f"Dataset '{resolved_dataset_id}' is not available for project recovery."

    dataset = entry.dataset
    intake = dataset.tags.get("intake_report")
    if not isinstance(intake, dict) or intake.get("dataset_id") != dataset.id:
        return None, (
            f"Phase 1 intake provenance is not available for dataset `{dataset.id}`. "
            "Run `run_intake()` before `align_concept()` so recovery can preserve "
            "the original intake audit trail."
        )
    schema = dataset.tags.get("schema_registry")
    if not isinstance(schema, dict) or schema.get("dataset_id") != dataset.id:
        return None, (
            f"Phase 2 schema is not available for dataset `{dataset.id}`. "
            f"Run `build_schema(dataset_id=\"{dataset.id}\")` before `align_concept()`."
        )

    metadata = dataset.metadata
    file_path = metadata.file_path if metadata is not None else Path("data/rawdata") / dataset.id
    created_at = datetime.now()
    project_id = str(uuid.uuid4())[:8]

    from rde.infrastructure.persistence import resolve_projects_base_dir
    from rde.interface.mcp.tools.project_tools import _make_project_folder_slug

    dataset_stem = file_path.stem if file_path.name else dataset.id[:8]
    project_name = f"recovered_{dataset_stem}"
    folder_slug = _make_project_folder_slug(project_name)
    folder_name = f"{created_at.strftime('%Y%m%d_%H%M%S')}_{folder_slug}_{project_id}"
    output_dir = resolve_projects_base_dir() / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "artifacts").mkdir(exist_ok=True)
    (output_dir / "figures").mkdir(exist_ok=True)

    project = Project(
        id=project_id,
        name=project_name,
        data_dir=file_path.parent,
        output_dir=output_dir,
        created_at=created_at,
        research_question=research_question,
        dataset_ids=[dataset.id],
        config={
            "auto_recovered_from_session": True,
            "recovery_reason": "intake/schema completed before active project existed",
            "source_dataset_id": dataset.id,
        },
    )
    session.register_project(project)
    store = ArtifactStore(project.artifacts_dir)

    store.save(
        PipelinePhase.PROJECT_SETUP,
        "project.yaml",
        {
            "id": project_id,
            "folder_slug": folder_slug,
            "folder_name": folder_name,
            "name": project_name,
            "data_dir": str(project.data_dir),
            "output_dir": str(output_dir),
            "research_question": research_question,
            "created_at": created_at.isoformat(),
            "auto_recovered_from_session": True,
            "source_dataset_id": dataset.id,
        },
    )
    recovered_intake = dict(intake)
    recovered_intake["auto_recovered_from_session"] = True
    recovered_intake["recovered_at"] = created_at.isoformat()
    store.save(PipelinePhase.DATA_INTAKE, "intake_report.json", recovered_intake)
    store.save(PipelinePhase.SCHEMA_REGISTRY, "schema.json", _session_dataset_schema(entry))

    pipeline = session.get_pipeline(project.id)
    for phase, artifacts in [
        (PipelinePhase.PROJECT_SETUP, {"project.yaml": ""}),
        (PipelinePhase.DATA_INTAKE, {"intake_report.json": ""}),
        (PipelinePhase.SCHEMA_REGISTRY, {"schema.json": ""}),
    ]:
        pipeline.mark_started(phase)
        pipeline.mark_completed(PhaseResult(phase, datetime.now(), True, artifacts))
        project.advance_to(ProjectStatus(phase.value))
    persist_project(project)

    return project, (
        f"auto-recovered project `{project.id}` from dataset `{dataset.id}` because Phase 0 "
        "was missing from the active tool flow."
    )


def _rehydrate_dataset_from_project(project: Project, dataset_id: str) -> DatasetEntry | None:
    """Reload a project-bound dataset from intake artifacts after MCP session reset."""
    store = ArtifactStore(project.artifacts_dir)
    intake = store.load(PipelinePhase.DATA_INTAKE, "intake_report.json")
    if not isinstance(intake, dict) or intake.get("dataset_id") != dataset_id:
        return None

    loaded_file = intake.get("loaded_file")
    if not isinstance(loaded_file, str) or not loaded_file.strip():
        return None

    candidates: list[Path] = []
    directory = intake.get("directory")
    if isinstance(directory, str) and directory.strip():
        candidates.append(Path(directory).expanduser() / loaded_file)
    candidates.append(project.data_dir / loaded_file)

    data_path = next((path for path in candidates if path.exists()), None)
    if data_path is None:
        return None

    from rde.application.session import DatasetEntry as SessionDatasetEntry
    from rde.infrastructure.adapters import PandasLoader

    metadata = DatasetMetadata(
        file_path=data_path,
        file_format=data_path.suffix.lstrip(".").lower(),
        file_size_bytes=data_path.stat().st_size,
    )
    dataframe, variables, row_count, report = PandasLoader().load(metadata)
    dataset = Dataset(id=dataset_id, metadata=metadata)
    dataset.mark_loaded(variables, row_count)
    dataset.tags["normalization_report"] = report.as_dict()

    alignment = store.load(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json")
    if isinstance(alignment, dict):
        raw_roles = alignment.get("variable_roles")
        if isinstance(raw_roles, dict):
            variable_by_name = {variable.name: variable for variable in dataset.variables}
            for variable_name, role_value in raw_roles.items():
                variable = variable_by_name.get(str(variable_name))
                if variable is None:
                    continue
                try:
                    variable.role = VariableRole(str(role_value))
                except ValueError:
                    continue
            dataset.tags["concept_alignment"] = alignment

    session = get_session()
    session.register_dataset(dataset, dataframe)
    return SessionDatasetEntry(dataset=dataset, dataframe=dataframe)


def ensure_dataset(
    dataset_id: str | None = None,
    *,
    project: Project | None = None,
) -> tuple[bool, str, DatasetEntry | None]:
    """Validate and return a dataset entry.

    If dataset_id is None, prefers the dataset bound to the current project.

    Returns:
        (is_valid, message, entry_or_none)
    """
    session = get_session()
    resolved_dataset_id = dataset_id
    if resolved_dataset_id is None:
        ids = project_dataset_ids(project)
        if not ids:
            return False, "尚未載入任何資料集。請先使用 load_dataset()。", None
        if project is not None and not project.dataset_ids and len(ids) > 1:
            return (
                False,
                "此專案尚未綁定資料集，且目前 session 有多份資料集。"
                "請先用 run_intake()/load_dataset() 綁定資料，或明確指定 dataset_id。",
                None,
            )
        resolved_dataset_id = ids[-1] if project is not None else ids[0]

    try:
        entry = session.get_dataset_entry(resolved_dataset_id)
        return True, f"資料集: {resolved_dataset_id}", entry
    except KeyError:
        if project is not None:
            entry = _rehydrate_dataset_from_project(project, resolved_dataset_id)
            if entry is not None:
                return True, f"鞈??? {resolved_dataset_id} (rehydrated)", entry
        available = project_dataset_ids(project)
        return False, f"資料集 '{resolved_dataset_id}' 不存在。可用: {available}", None


def ensure_phase_ready(
    phase: PipelinePhase,
    *,
    project_id: str | None = None,
    dataset_id: str | None = None,
    require_dataset: bool = False,
) -> tuple[bool, str, Project | None, DatasetEntry | None]:
    """Validate that a pipeline phase is allowed to run in the current context."""
    ok, msg, project = ensure_project_context(project_id)
    if not ok or project is None:
        return False, msg, None, None

    dataset_entry = None
    if require_dataset:
        ok, msg, dataset_entry = ensure_dataset(dataset_id, project=project)
        if not ok:
            return False, msg, project, None

    session = get_session()
    project = session.sync_project_from_artifacts(project.id)
    pipeline = session.get_pipeline(project.id)
    can_execute, reason = pipeline.can_execute(phase)
    if not can_execute:
        return False, reason, project, dataset_entry

    store = ArtifactStore(project.artifacts_dir)
    required_phases = PREREQUISITES.get(phase, set())
    if pipeline.is_quick_explore:
        required_phases = required_phases - OPTIONAL_PHASES

    for prereq in required_phases:
        present, missing = store.check_artifacts(prereq)
        if not present:
            return (
                False,
                f"Missing artifacts for {prereq.value}: {', '.join(missing)}",
                project,
                dataset_entry,
            )

    return True, "ready", project, dataset_entry


def ensure_minimum_sample_size(
    dataset_entry: DatasetEntry,
    *,
    min_n: int = 10,
) -> tuple[bool, str]:
    """Validate H-003 before statistical analysis executes."""
    check = HardConstraints.h003_min_sample_size(dataset_entry.dataset.row_count, min_n=min_n)
    return check.passed, check.message


PHASE6_PROGRESS_FILENAME = "phase_08_progress.json"
PHASE6_REQUIRED_COVERAGE = 0.8
PHASE6_MIN_EXECUTIONS_NO_PLAN = 2


def _extract_planned_analyses(plan: dict | None) -> list:
    """Return required analyses from the locked plan."""
    if not plan or not isinstance(plan, dict):
        return []
    entries = plan.get("analyses", plan.get("steps", [])) or []
    return [
        entry for entry in entries if not isinstance(entry, dict) or entry.get("required", True)
    ]


def compute_phase6_progress(project: Project) -> dict[str, object]:
    """Compute how far Phase 8 execution has progressed relative to the locked plan."""
    session = get_session()
    logger = session.get_logger(project.id)
    decisions = logger.read_decisions()
    decision_count = len(decisions)
    branch_decision_count = 0
    primary_decision_count = 0
    dataset_ids = project_dataset_ids(project)
    analysis_result_count = 0
    for did in dataset_ids:
        ok, _, entry = ensure_dataset(did, project=project)
        if ok and entry is not None:
            analysis_result_count += len(entry.analysis_results)
    for decision in decisions:
        parameters = decision.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}
        if parameters.get("scope") == "branch":
            branch_decision_count += 1
        else:
            primary_decision_count += 1
    executed = max(primary_decision_count, analysis_result_count)

    store = ArtifactStore(project.artifacts_dir)
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    planned_entries = _extract_planned_analyses(plan)
    planned = len(planned_entries)
    matched_decision_count = 0
    off_plan_decision_count = 0

    if planned > 0:
        for decision in decisions:
            tool_name = str(decision.get("tool_used") or decision.get("action") or "")
            parameters = decision.get("parameters")
            if not isinstance(parameters, dict):
                parameters = {}
            if parameters.get("scope") == "branch":
                continue
            in_plan, _ = check_plan_adherence(project, tool_name, parameters)
            if in_plan:
                matched_decision_count += 1
            else:
                off_plan_decision_count += 1
        executed = max(matched_decision_count, analysis_result_count)

    if planned > 0:
        required_executions = max(1, math.ceil(planned * PHASE6_REQUIRED_COVERAGE))
        coverage = executed / planned if planned else 0.0
        ready = executed >= required_executions and coverage >= PHASE6_REQUIRED_COVERAGE
    else:
        required_executions = PHASE6_MIN_EXECUTIONS_NO_PLAN
        coverage = 1.0 if executed else 0.0
        ready = executed >= required_executions

    return {
        "planned_analyses": planned,
        "planned_entries": planned_entries,
        "executed_analyses": executed,
        "decision_count": decision_count,
        "primary_decision_count": primary_decision_count,
        "branch_decision_count": branch_decision_count,
        "matched_decision_count": matched_decision_count if planned > 0 else primary_decision_count,
        "off_plan_decision_count": off_plan_decision_count,
        "analysis_result_count": analysis_result_count,
        "coverage": coverage,
        "required_coverage": PHASE6_REQUIRED_COVERAGE if planned else None,
        "required_executions": required_executions,
        "ready": ready,
    }


def save_phase6_progress(
    project: Project,
    progress: dict[str, object],
    *,
    last_action: dict | None = None,
) -> tuple[dict[str, object], str]:
    """Persist the latest Phase 8 execution progress snapshot."""
    store = ArtifactStore(project.artifacts_dir)
    snapshot = dict(progress)
    snapshot["timestamp"] = datetime.now().isoformat()
    if last_action:
        snapshot["last_action"] = last_action
    path = store.save(PipelinePhase.EXECUTE_EXPLORATION, PHASE6_PROGRESS_FILENAME, snapshot)
    return snapshot, str(path)


def mark_phase6_complete_if_ready(
    project: Project,
    pipeline: PipelineState,
    progress: dict[str, object],
    progress_path: str | None,
    *,
    force: bool = False,
) -> bool:
    """Mark Phase 8 execution as completed when ready or forced."""
    from rde.application.pipeline import PipelinePhase

    if PipelinePhase.EXECUTE_EXPLORATION in pipeline.completed_phases:
        return False

    if not progress.get("ready", False) and not force:
        return False

    artifacts = {"decision_log.jsonl": str(project.decision_log_path)}
    if progress_path:
        artifacts[PHASE6_PROGRESS_FILENAME] = progress_path

    pipeline.mark_completed(
        PhaseResult(
            phase=PipelinePhase.EXECUTE_EXPLORATION,
            completed_at=datetime.now(),
            success=True,
            artifacts=artifacts,
            warnings=[] if not force else ["forced_completion_before_plan_coverage"],
        )
    )
    project.advance_to(ProjectStatus.EXECUTE_EXPLORATION)
    persist_project(project)
    return True


def format_phase6_gate_message(progress: dict[str, object]) -> str:
    """Build a user-facing message for insufficient Phase 8 execution progress."""
    planned = progress.get("planned_analyses", 0) or 0
    executed = progress.get("executed_analyses", 0) or 0
    coverage = progress.get("coverage", 0.0) or 0.0
    required_exec = progress.get("required_executions", 0) or 0
    if planned:
        return (
            f"Phase 8 尚未達到完成門檻：計畫 {planned} 項，已執行 {executed} 項 "
            f"(覆蓋率 {coverage:.0%}，需至少完成 {required_exec} 項或覆蓋率 "
            f"{PHASE6_REQUIRED_COVERAGE:.0%})"
        )
    return (
        f"Phase 8 仍在進行：已執行 {executed} 項分析，需至少 {required_exec} 項後才能收斂 "
        "(無鎖定計畫時預設門檻 = 2)"
    )


def _normalize_plan_value(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _plan_values(payload: dict, keys: tuple[str, ...]) -> set[str]:
    values: set[str] = set()
    for key in keys:
        raw = payload.get(key)
        if raw is None:
            continue
        if isinstance(raw, (list, tuple, set)):
            values.update(str(item) for item in raw if item is not None)
        else:
            values.add(str(raw))
    return {value for value in values if value}


def _normalized_plan_values(payload: dict, keys: tuple[str, ...]) -> set[str]:
    return {_normalize_plan_value(value) for value in _plan_values(payload, keys)}


def _planned_named_fields_match(entry: dict, parameters: dict) -> bool:
    required_pairs = (
        (("group_variable", "group_var", "group"), ("group_variable", "group_var", "group")),
        (("time_variable", "time_var"), ("time_variable", "time_var")),
        (("score_variable", "score_var"), ("score_variable", "score_var")),
        (
            ("target_variable", "outcome_variable", "target"),
            ("target_variable", "outcome_variable", "variable_name", "target"),
        ),
    )
    for planned_keys, parameter_keys in required_pairs:
        planned_values = _normalized_plan_values(entry, planned_keys)
        if not planned_values:
            continue
        actual_values = _normalized_plan_values(parameters, parameter_keys)
        if not actual_values or not planned_values.intersection(actual_values):
            return False
    return True


def _check_plan_adherence_against_analyses(
    analyses: list,
    tool_name: str,
    parameters: dict,
) -> bool:
    tool_type_map = {
        "compare_groups": {
            "compare_groups",
            "group_comparison",
            "t_test",
            "mann_whitney",
            "chi_square",
        },
        "analyze_variable": {"analyze_variable", "univariate", "descriptive"},
        "correlation_matrix": {"correlation_matrix", "correlation", "collinearity"},
        "generate_table_one": {"generate_table_one", "table_one", "table_1", "baseline"},
        "run_advanced_analysis": {"run_advanced_analysis"},
        "run_repeated_measures": {"run_repeated_measures", "repeated_measures", "friedman"},
        "apply_cleaning": {"apply_cleaning", "cleaning", "clean"},
        "suggest_cleaning": {"suggest_cleaning", "cleaning", "clean"},
        "create_visualization": {"create_visualization", "visualization", "plot", "chart"},
    }
    normalized_tool_name = _normalize_plan_value(tool_name)
    synonyms = {
        _normalize_plan_value(value)
        for value in tool_type_map.get(normalized_tool_name, {normalized_tool_name})
    }
    if normalized_tool_name == "run_advanced_analysis" and parameters.get("analysis_type"):
        synonyms.add(_normalize_plan_value(parameters["analysis_type"]))

    param_vars = _plan_values(
        parameters,
        (
            "outcome_variables",
            "outcome_variable",
            "variables",
            "variable_name",
            "target_variable",
            "group_variable",
            "group_var",
            "group",
            "time_variable",
            "time_var",
            "score_variable",
            "score_var",
        ),
    )

    for entry in analyses:
        if not isinstance(entry, dict):
            continue
        planned_type = _normalize_plan_value(entry.get("type", ""))
        planned_analysis_type = _normalize_plan_value(entry.get("analysis_type", ""))
        type_matches = planned_type in synonyms or any(s in planned_type for s in synonyms)
        if not type_matches and planned_analysis_type:
            type_matches = planned_analysis_type in synonyms
        if not type_matches:
            continue
        if not _planned_named_fields_match(entry, parameters):
            continue

        planned_vars = _plan_values(entry, ("variables",))
        if not planned_vars or param_vars.intersection(planned_vars):
            return True

    return False


def check_plan_adherence(
    project: "Project",
    tool_name: str,
    parameters: dict,
) -> tuple[bool, str | None]:
    """Check if the current Phase 8 operation matches the locked analysis plan.

    Returns (is_in_plan, deviation_reason_or_none).
    If the plan has no analyses listed, or Phase 4 was skipped, returns (True, None).
    """
    from rde.infrastructure.persistence.artifact_store import ArtifactStore
    from rde.application.pipeline import PipelinePhase

    store = ArtifactStore(project.artifacts_dir)
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")

    if not plan or not isinstance(plan, dict):
        return True, None  # no plan → nothing to check

    analyses = plan.get("analyses", [])
    if analyses:
        if _check_plan_adherence_against_analyses(analyses, tool_name, parameters):
            return True, None
        return False, (
            f"Tool '{tool_name}' is not covered by the locked analysis plan "
            f"({len(analyses)} planned analyses checked)."
        )
    return True, None  # empty plan → nothing to check
