"""Project & dataset context helpers — reusable validation across tools."""

from __future__ import annotations

from datetime import datetime
import math

from rde.application.pipeline import (
    PREREQUISITES,
    OPTIONAL_PHASES,
    PhaseResult,
    PipelinePhase,
    PipelineState,
)
from rde.application.session import get_session, DatasetEntry
from rde.domain.models.project import Project
from rde.domain.models.project import ProjectStatus
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
        return False, str(e), None


def ensure_dataset(
    dataset_id: str | None = None,
) -> tuple[bool, str, DatasetEntry | None]:
    """Validate and return a dataset entry.

    If dataset_id is None, uses the first loaded dataset.

    Returns:
        (is_valid, message, entry_or_none)
    """
    session = get_session()
    if dataset_id is None:
        ids = session.list_datasets()
        if not ids:
            return False, "尚未載入任何資料集。請先使用 load_dataset()。", None
        dataset_id = ids[0]

    try:
        entry = session.get_dataset_entry(dataset_id)
        return True, f"資料集: {dataset_id}", entry
    except KeyError:
        available = session.list_datasets()
        return False, f"資料集 '{dataset_id}' 不存在。可用: {available}", None


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
        ok, msg, dataset_entry = ensure_dataset(dataset_id)
        if not ok:
            return False, msg, project, None

    session = get_session()
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


PHASE6_PROGRESS_FILENAME = "phase_06_progress.json"
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
    """Compute how far Phase 6 has progressed relative to the locked plan."""
    session = get_session()
    logger = session.get_logger(project.id)
    decision_count = logger.decision_count
    dataset_ids = session.list_datasets()
    analysis_result_count = sum(
        len(session.get_dataset_entry(did).analysis_results) for did in dataset_ids
    )
    executed = max(decision_count, analysis_result_count)

    store = ArtifactStore(project.artifacts_dir)
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    planned_entries = _extract_planned_analyses(plan)
    planned = len(planned_entries)

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
    """Persist the latest Phase 6 progress snapshot."""
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
    """Mark Phase 6 as completed when ready or forced."""
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
    return True


def format_phase6_gate_message(progress: dict[str, object]) -> str:
    """Build a user-facing message for insufficient Phase 6 progress."""
    planned = progress.get("planned_analyses", 0) or 0
    executed = progress.get("executed_analyses", 0) or 0
    coverage = progress.get("coverage", 0.0) or 0.0
    required_exec = progress.get("required_executions", 0) or 0
    if planned:
        return (
            f"Phase 6 尚未達到完成門檻：計畫 {planned} 項，已執行 {executed} 項 "
            f"(覆蓋率 {coverage:.0%}，需至少完成 {required_exec} 項或覆蓋率 "
            f"{PHASE6_REQUIRED_COVERAGE:.0%})"
        )
    return (
        f"Phase 6 仍在進行：已執行 {executed} 項分析，需至少 {required_exec} 項後才能收斂 "
        "(無鎖定計畫時預設門檻 = 2)"
    )


def check_plan_adherence(
    project: "Project",
    tool_name: str,
    parameters: dict,
) -> tuple[bool, str | None]:
    """Check if the current Phase 6 operation matches the locked analysis plan.

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
    if not analyses:
        return True, None  # empty plan → nothing to check

    # Normalise tool_name → analysis type keywords for matching
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
        "run_advanced_analysis": set(),  # matched by analysis_type param
        "run_repeated_measures": {"run_repeated_measures", "repeated_measures", "friedman"},
        "apply_cleaning": {"apply_cleaning", "cleaning", "clean"},
        "suggest_cleaning": {"suggest_cleaning", "cleaning", "clean"},
        "create_visualization": {"create_visualization", "visualization", "plot", "chart"},
    }

    synonyms = tool_type_map.get(tool_name, {tool_name})

    # For run_advanced_analysis, also include the analysis_type parameter
    if tool_name == "run_advanced_analysis" and "analysis_type" in parameters:
        synonyms = {parameters["analysis_type"], tool_name}

    # Extract the target variables from parameters
    param_vars = set()
    for key in ("outcome_variables", "variables", "variable_name"):
        val = parameters.get(key)
        if isinstance(val, list):
            param_vars.update(val)
        elif isinstance(val, str) and key == "variable_name":
            param_vars.add(val)
    if "group_variable" in parameters:
        param_vars.add(parameters["group_variable"])

    # Check each planned analysis for a match
    for entry in analyses:
        if not isinstance(entry, dict):
            continue
        planned_type = str(entry.get("type", "")).lower().replace("-", "_").replace(" ", "_")
        planned_vars = set()
        pv = entry.get("variables")
        if isinstance(pv, list):
            planned_vars = set(pv)
        elif isinstance(pv, str):
            planned_vars = {pv}

        # Type match
        if planned_type in synonyms or any(s in planned_type for s in synonyms):
            # If planned analysis has no specific vars, type match is enough
            if not planned_vars:
                return True, None
            # If there's variable overlap, it matches
            if param_vars & planned_vars:
                return True, None

    # No match found — this is a deviation
    return False, (
        f"工具 '{tool_name}' 不在已鎖定的分析計畫中 "
        f"(計畫含 {len(analyses)} 項分析)。已自動記錄偏離。"
    )
