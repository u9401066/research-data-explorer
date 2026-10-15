"""Source-aware replay for every typed clinical inspection and plan lock.

TTE additionally binds its complete preparation/trace/protocol evidence. Ordinary
clinical identities do not claim those causal design guarantees.
"""

import hashlib

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.adapters.dataframe_lineage import frame_record
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.clinical.target_trial_source import validate_target_trial_source
from rde.infrastructure.clinical.target_trial_study import TargetTrialSpec, verify_source_artifact
from .project_context import ensure_dataset


def source_identity(entry):
    metadata = entry.dataset.metadata
    if metadata is None or not metadata.file_path.is_file():
        raise ValueError("CLINICAL_REPLAY_SOURCE: original source file is required")
    return {
        "schema": "clinical-source-identity-v1",
        "dataset_id": entry.dataset.id,
        "path": str(metadata.file_path.resolve()),
        "source_sha256": hashlib.sha256(metadata.file_path.read_bytes()).hexdigest(),
        "sheet": metadata.sheet_name,
        "format": metadata.file_format,
        "frame": frame_record(entry.dataframe),
        "privacy": metadata.privacy,
    }


def validate_replay(project, tool, arguments, saved):
    options = arguments.get("clinical_options", {})
    if tool == "register_analysis_plan":
        candidates = [
            item.get("execution_arguments", {}).get("clinical_options", {})
            for item in arguments.get("analyses", [])
            if isinstance(item, dict) and item.get("type") == "run_clinical_study"
        ]
        if not candidates:
            if (
                arguments.get("confirm") is False
                or arguments.get("expected_review_sha256") is not None
            ):
                from .generic_evidence import preflight, validate_locked

                store = ArtifactStore(project.artifacts_dir)
                ok, message, entry = ensure_dataset(project=project)
                if not ok:
                    raise ValueError("GENERIC_REPLAY_SOURCE: " + message)
                if arguments.get("confirm") is False:
                    current = preflight(
                        project,
                        entry,
                        arguments["analyses"],
                        alpha=arguments.get("alpha", 0.05),
                        missing_strategy=arguments.get("missing_strategy", "listwise"),
                        multiple_comparison_method=arguments.get(
                            "multiple_comparison_method", "bonferroni"
                        ),
                    )
                    if current != saved.data:
                        raise ValueError(
                            "GENERIC_REPLAY_SOURCE: exact readonly review source or contract changed"
                        )
                else:
                    validate_locked(store)
                    plan_path = store.get_path(
                        PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml"
                    )
                    snapshots = [
                        ref
                        for ref in saved.artifacts
                        if ref.relative_path.endswith("/analysis_plan.yaml")
                    ]
                    if (
                        len(snapshots) != 1
                        or hashlib.sha256(plan_path.read_bytes()).hexdigest() != snapshots[0].sha256
                    ):
                        raise ValueError("GENERIC_REPLAY_PLAN: original locked plan changed")
            return
        if len(candidates) != 1:
            raise ValueError("CLINICAL_REPLAY_PLAN: one exact clinical study is required")
        options = candidates[0]
    ok, message, entry = ensure_dataset(arguments.get("dataset_id"), project=project)
    if not ok or project is None:
        raise ValueError("CLINICAL_REPLAY_SOURCE: " + message)
    if tool == "inspect_clinical_study":
        identity = saved.data.get("source_identity")
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
            raise ValueError(
                "CLINICAL_REPLAY_PLAN: exact original locked plan is missing or changed"
            )
        identity = plan.get("clinical_source_identity")
        pin = plan.get("target_trial_source_check", {})
    if identity != source_identity(entry):
        raise ValueError(
            "CLINICAL_REPLAY_SOURCE: original source identity is missing or changed; review a new study"
        )
    if options.get("family") != "target_trial":
        return
    spec = TargetTrialSpec.parse(options)
    check = validate_target_trial_source(
        project, entry.dataset.metadata, entry.dataframe, spec.weighting, spec.protocol
    )
    if pin.get("receipt_sha256") != check["receipt_sha256"] or not verify_source_artifact(
        pin.get("artifact", {}), project.output_dir, check
    ):
        raise ValueError(
            "TTE_REPLAY_SOURCE: retained source validation no longer matches current source and implementation"
        )
