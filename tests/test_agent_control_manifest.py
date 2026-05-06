from pathlib import Path

import yaml

from rde.application.pipeline import PipelinePhase


MANIFEST = Path(__file__).resolve().parent.parent / ".github" / "agent-control.yaml"


def test_agent_control_manifest_exists_and_has_required_controls() -> None:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))

    assert data["locale"] == "zh-TW"
    assert data["defaults"]["test_command"] == "python3 -m pytest -q"
    assert data["phase_controls"]["concept_alignment"]["confirmation_flag"] == "confirm"
    assert data["phase_controls"]["plan_registration"]["confirmation_flag"] == "confirm"
    assert data["override_controls"]["pii_detection"]["explicit_override_flag"] == "allow_pii"
    assert data["audit_contract"]["decision_log_path"].endswith("decision_log.jsonl")
    assert data["audit_contract"]["deviation_log_path"].endswith("deviation_log.jsonl")


def test_agent_control_manifest_phase_names_match_pipeline_enum() -> None:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    valid_phase_names = {phase.value for phase in PipelinePhase}

    for section in data["phase_controls"].values():
        phase_name = section.get("phase")
        if phase_name:
            assert phase_name in valid_phase_names

    execute_phase = data["phase_controls"]["execute_exploration"]["phase"]
    assert execute_phase == PipelinePhase.EXECUTE_EXPLORATION.value


def test_agent_control_manifest_log_paths_match_execution_phase() -> None:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    execution_dir = PipelinePhase.EXECUTE_EXPLORATION.value

    assert (
        data["audit_contract"]["decision_log_path"]
        == f"artifacts/{execution_dir}/decision_log.jsonl"
    )
    assert (
        data["audit_contract"]["deviation_log_path"]
        == f"artifacts/{execution_dir}/deviation_log.jsonl"
    )
    assert data["audit_contract"]["phase_08_required_artifacts"] == ["decision_log.jsonl"]
