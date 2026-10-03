"""Publication sources bound to executed branches and their immutable primary study."""

import json
import re

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.prediction.splits import digest
from rde.interface.mcp.tools.clinical_tools import verify_clinical_artifacts


def branch_publication_source(project, branch_id, experiment_id, expected_record_sha256):
    from rde.interface.mcp.tools.publication_tools import file_hash

    if not re.fullmatch(r"br_[a-f0-9]{10}", branch_id) or not re.fullmatch(
        r"exp_[a-f0-9]{10}", experiment_id
    ):
        raise ValueError("Use exact native branch and experiment IDs.")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_record_sha256):
        raise ValueError("Expected branch record SHA256 is required.")
    root = project.output_dir.resolve()
    store = ArtifactStore(project.artifacts_dir)

    def confined(value):
        path = (root / value).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Branch publication evidence must be a file in this project.")
        return path

    folder = store.get_path(
        PipelinePhase.EXECUTE_EXPLORATION, f"branch_results/{branch_id}/experiments"
    )
    wrapper_path = confined(folder / f"{experiment_id}.json")
    wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
    requested = wrapper.get("task", {}).get("analysis_contract", {})
    from rde.infrastructure.visualization.advanced_publication import METHODS, publication_result

    generic = (
        requested.get("tool") == "run_advanced_analysis"
        and requested.get("analysis_type") in METHODS
    )
    method = requested["analysis_type"] if generic else "survival_sensitivity"
    source = confined(folder / f"{experiment_id}_{method}.json")
    if file_hash(source) != expected_record_sha256:
        raise ValueError("Saved branch record differs from the requested SHA256.")
    record = json.loads(source.read_text(encoding="utf-8"))
    events = store.load(PipelinePhase.EXECUTE_EXPLORATION, "branch_experiment_results.jsonl") or []
    matches = [
        e
        for e in events
        if e.get("branch_id") == branch_id and e.get("experiment_id") == experiment_id
    ]
    if len(matches) != 1:
        raise ValueError("A unique executed branch ledger entry is required.")
    event = matches[0]
    execution = wrapper.get("contract_execution", {})
    experiment = wrapper.get("experiment", {})
    experiments = store.load(PipelinePhase.EXECUTE_EXPLORATION, "experiment_ledger.jsonl") or []
    matching_experiments = [
        e
        for e in experiments
        if e.get("branch_id") == branch_id and e.get("experiment_id") == experiment_id
    ]
    contract = record.get("analysis_contract", {})
    if (
        event.get("project_id") != project.id
        or event.get("status") != "completed"
        or confined(event["artifact"]) != wrapper_path
        or wrapper.get("scope") != "branch"
        or wrapper.get("exploratory") is not True
        or wrapper.get("branch_id") != branch_id
        or wrapper.get("experiment_id") != experiment_id
        or not wrapper.get("run_id")
        or event.get("run_id") != wrapper["run_id"]
        or event.get("experiment") != experiment
        or matching_experiments != [experiment]
        or experiment.get("project_id") != project.id
        or experiment.get("branch_id") != branch_id
        or experiment.get("experiment_id") != experiment_id
        or experiment.get("status") != "completed"
        or execution.get("executed") is not True
        or execution.get("status") != "completed"
        or execution.get("artifact_sha256") != expected_record_sha256
        or confined(execution["artifact_path"]) != source
        or record.get("status") != "completed"
        or (not generic and record.get("source") != "local-clinical-survival")
        or record.get("branch_id") != branch_id
        or record.get("experiment_id") != experiment_id
        or record.get("dataset_id") not in project.dataset_ids
        or contract != wrapper.get("task", {}).get("analysis_contract")
        or (
            not generic
            and (
                contract.get("tool") != "run_clinical_study"
                or contract.get("analysis_type") != "survival_sensitivity"
            )
        )
    ):
        raise ValueError("The completed native branch, execution and source identities differ.")
    if generic:
        from rde.infrastructure.adapters.dataframe_lineage import verify_source_binding

        result = record.get("publication_result")
        binding = record["input_evidence"]["source_binding"]
        if (
            record.get("schema") != "advanced-branch-evidence-v1"
            or binding.get("dataset_id") != record["dataset_id"]
            or result != publication_result(record)
            or not verify_clinical_artifacts({**record, "result": result}, root)
        ):
            raise ValueError(
                "Generic branch publication does not match its complete numerical evidence."
            )
        verify_source_binding(binding, root)
        _verify_figures(record, result, confined)
        return source, {
            **record,
            "result": result,
            "run_id": wrapper["run_id"],
            "source": binding["source"],
            "publication_scope": "exploratory_branch",
        }
    result = record.get("analysis_result", {})
    binding = record.get("primary_binding", {})
    primary_path = confined(binding["primary_artifact"])
    if (
        primary_path.parent
        != (project.artifacts_dir / PipelinePhase.EXECUTE_EXPLORATION.value).resolve()
        or not re.fullmatch(r"clinical_study_[a-f0-9]{16}\.json", primary_path.name)
        or file_hash(primary_path) != binding.get("primary_record_sha256")
    ):
        raise ValueError("The primary study record no longer matches the branch binding.")
    primary = json.loads(primary_path.read_text(encoding="utf-8"))
    primary_result = primary.get("result", {})
    spec = result.get("spec", {})
    primary_spec = primary_result.get("spec", {})
    if (
        result.get("status") != "completed"
        or result.get("schema") != "clinical-survival-v1"
        or spec.get("family") != "survival"
        or result.get("spec_sha256") != digest(spec)
        or result.get("primary_binding") != binding
        or any(
            binding.get(key) != contract.get(key)
            for key in (
                "primary_record_sha256",
                "primary_receipt_sha256",
                "case_set_sha256",
                "focus_variable",
                "required_covariates",
            )
        )
        or primary.get("dataset_id") != record["dataset_id"]
        or primary.get("source") != record.get("source_file")
        or primary_result.get("status") != "completed"
        or primary_result.get("receipt_sha256") != binding.get("primary_receipt_sha256")
        or result.get("population_spec") != primary_spec
        or result.get("population_spec_sha256") != digest(primary_spec)
        or result.get("case_ledger") != primary_result.get("case_ledger")
        or result.get("case_set_sha256") != binding.get("case_set_sha256")
        or digest(result.get("case_ledger", {}).get("complete_data_rows"))
        != binding.get("case_set_sha256")
        or any(
            result.get(key) != primary_result.get(key)
            for key in (
                "n",
                "events",
                "censored",
                "competing",
                "event_codes",
                "strata",
                "dataframe_sha256",
            )
        )
        or spec.get("covariates") != contract.get("covariates")
        or not verify_clinical_artifacts(primary, root)
        or not verify_clinical_artifacts({**record, "result": result}, root)
    ):
        raise ValueError(
            "Branch numerical evidence or its fixed primary population failed verification."
        )
    _verify_figures(record, result, confined)
    return source, {
        **record,
        "result": result,
        "run_id": wrapper["run_id"],
        "source": record["source_file"],
        "publication_scope": "exploratory_branch",
    }


def _verify_figures(record, result, confined):
    figures = record.get("figures", [])
    if not figures:
        raise ValueError("This branch has no complete publication figure bundle.")
    artifact_paths = {confined(a["path"]) for a in record["artifacts"]}
    for figure in figures:
        publication = figure.get("publication", {})
        files = publication.get("files", {})
        if (
            publication.get("source_receipt_sha256") != result["receipt_sha256"]
            or set(files) != {"png", "pdf", "svg", "tiff", "data", "caption"}
            or any(confined(path) not in artifact_paths for path in files.values())
            or confined(figure["path"]) != confined(files["png"])
        ):
            raise ValueError("Branch figures do not belong to its complete numerical evidence.")


def create_branch_edition(project, *, branch_id, experiment_id, expected_record_sha256, **options):
    from rde.interface.mcp.tools.publication_tools import _create_verified_edition

    source, record = branch_publication_source(
        project, branch_id, experiment_id, expected_record_sha256
    )
    return _create_verified_edition(
        project,
        source=source,
        study_artifact=str(
            source.relative_to(project.artifacts_dir / PipelinePhase.EXECUTE_EXPLORATION.value)
        ),
        expected_record_sha256=expected_record_sha256,
        record=record,
        result=record["result"],
        **options,
    )
