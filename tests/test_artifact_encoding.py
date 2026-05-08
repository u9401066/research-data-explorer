import json

from rde.application.decision_logger import DecisionLogger
from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore


def test_json_artifacts_are_ascii_escaped_for_windows_ansi_readers(tmp_path):
    store = ArtifactStore(tmp_path)

    path = store.save(
        PipelinePhase.AUDIT_REVIEW,
        "audit_report.json",
        {"details": "schema=✅", "variable": "成功_0不成功_1成功"},
    )

    text = path.read_bytes().decode("cp950")
    assert "✅" not in text
    assert "\\u2705" in text
    assert json.loads(text)["variable"] == "成功_0不成功_1成功"
    assert store.load(PipelinePhase.AUDIT_REVIEW, "audit_report.json")["details"] == "schema=✅"


def test_jsonl_decision_logs_are_ascii_escaped_for_windows_ansi_readers(tmp_path):
    logger = DecisionLogger(tmp_path)
    logger.log_decision(
        phase="phase_08_execute_exploration",
        action="analyze",
        tool_used="compare_groups",
        parameters={"變數": "成功_0不成功_1成功"},
        rationale="可審計",
        result_summary="passed ✅",
    )

    path = tmp_path / PipelinePhase.EXECUTE_EXPLORATION.value / "decision_log.jsonl"
    text = path.read_bytes().decode("cp950")
    assert "✅" not in text
    assert "\\u2705" in text
    assert json.loads(text)["result_summary"] == "passed ✅"
