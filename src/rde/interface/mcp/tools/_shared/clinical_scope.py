"""Fail closed before legacy inference can bypass a registered clinical bundle.

A typed clinical plan is one complete study. Legacy callers cannot authorize a
new estimand, case set or source mutation by supplying their own policy. This
check deliberately does not replace generic EDA's existing deviation workflow.
"""

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore


def has_clinical_bundle(project) -> bool:
    plan = ArtifactStore(project.artifacts_dir).load(
        PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml"
    )
    if plan is None:
        return False
    if not isinstance(plan, dict):
        raise ValueError("Cannot verify registered analysis scope: plan must be an object.")
    analyses = plan.get("analyses", [])
    if not isinstance(analyses, list):
        raise ValueError("Cannot verify registered analysis scope: analyses must be a list.")
    return any(
        isinstance(entry, dict) and entry.get("type") == "run_clinical_study" for entry in analyses
    )


def ensure_legacy_analysis_allowed(project, tool_name: str) -> tuple[bool, str]:
    """Check registration as well as lock flags so a stale flag cannot allow a bypass."""
    try:
        clinical = has_clinical_bundle(project)
    except Exception as error:
        return (
            False,
            f"[CLINICAL_PLAN_SCOPE] Cannot verify the registered plan before {tool_name}: {error}",
        )
    if clinical:
        return False, (
            f"[CLINICAL_PLAN_SCOPE] {tool_name} is outside the registered clinical study bundle. "
            "Use inspect_clinical_study / run_clinical_study with the exact locked clinical_options. "
            "Additional inference or source cleaning requires a separately reviewed dataset/plan revision; "
            "caller-supplied alpha, missingness, multiplicity or cleaning indices cannot authorize it. "
            "未執行檢定、模型或清理；已保存計畫與成果保持不變。"
        )
    return True, "allowed"
