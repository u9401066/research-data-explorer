"""Source-aware replay for TTE inspection and exact protocol locking only."""

import hashlib

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.clinical.target_trial_source import validate_target_trial_source
from rde.infrastructure.clinical.target_trial_study import TargetTrialSpec, verify_source_artifact
from .project_context import ensure_dataset


def validate_replay(project, tool, arguments, saved):
    options = arguments.get("clinical_options", {})
    if tool == "register_analysis_plan":
        analyses = arguments.get("analyses", [])
        candidates = [
            item.get("execution_arguments", {}).get("clinical_options", {})
            for item in analyses
            if isinstance(item, dict)
        ]
        options = next((item for item in candidates if item.get("family") == "target_trial"), {})
    if options.get("family") != "target_trial":
        return
    spec = TargetTrialSpec.parse(options)
    ok, message, entry = ensure_dataset(arguments.get("dataset_id"), project=project)
    if not ok or project is None:
        raise ValueError("TTE_REPLAY_SOURCE: " + message)
    check = validate_target_trial_source(
        project, entry.dataset.metadata, entry.dataframe, spec.weighting, spec.protocol
    )
    if tool == "inspect_clinical_study":
        pin = saved.data.get("source_check", {})
    else:
        store = ArtifactStore(project.artifacts_dir)
        plan_path = store.get_path(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
        plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") or {}
        snapshots = [
            ref for ref in saved.artifacts if ref.relative_path.endswith("/analysis_plan.yaml")
        ]
        if (
            plan.get("locked") is not True
            or len(snapshots) != 1
            or not plan_path.is_file()
            or hashlib.sha256(plan_path.read_bytes()).hexdigest() != snapshots[0].sha256
        ):
            raise ValueError("TTE_REPLAY_PLAN: exact original locked plan is missing or changed")
        pin = plan.get("target_trial_source_check", {})
    if pin.get("receipt_sha256") != check["receipt_sha256"] or not verify_source_artifact(
        pin.get("artifact", {}), project.output_dir, check
    ):
        raise ValueError(
            "TTE_REPLAY_SOURCE: retained source validation no longer matches current source and implementation"
        )
