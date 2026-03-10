"""Project & dataset context helpers — reusable validation across tools."""

from __future__ import annotations

from typing import Any

from rde.application.pipeline import PREREQUISITES, OPTIONAL_PHASES, PipelinePhase
from rde.application.session import SessionRegistry, get_session, DatasetEntry
from rde.domain.models.project import Project
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
        available = session.list_datasets()  # proxy — no list_projects on session
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
    except KeyError as e:
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
            return False, f"Missing artifacts for {prereq.value}: {', '.join(missing)}", project, dataset_entry

    return True, "ready", project, dataset_entry


def ensure_minimum_sample_size(
    dataset_entry: DatasetEntry,
    *,
    min_n: int = 10,
) -> tuple[bool, str]:
    """Validate H-003 before statistical analysis executes."""
    check = HardConstraints.h003_min_sample_size(dataset_entry.dataset.row_count, min_n=min_n)
    return check.passed, check.message


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
        "compare_groups": {"compare_groups", "group_comparison", "t_test", "mann_whitney", "chi_square"},
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
