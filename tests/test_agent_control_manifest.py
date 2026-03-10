from pathlib import Path

import yaml


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