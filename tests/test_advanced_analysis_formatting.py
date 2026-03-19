from __future__ import annotations

from pathlib import Path

from rde.domain.models.project import Project
from rde.interface.mcp.tools.analysis_tools import (
    _format_advanced_analysis_output,
    _is_direct_analysis_contract,
    _save_advanced_analysis_artifact,
    _summarize_advanced_analysis_result,
)


def _make_project(tmp_path: Path) -> Project:
    return Project(
        id="proj-advanced",
        name="advanced",
        data_dir=tmp_path / "raw",
        output_dir=tmp_path / "output",
    )


def test_direct_analysis_contract_detection_and_summary() -> None:
    payload = {
        "job_id": "stats-123",
        "job_type": "auto_analyze_direct",
        "status": "pending",
        "message": "Direct analysis job submitted.",
        "data_preview": {"rows": 20, "columns": 4},
    }

    assert _is_direct_analysis_contract(payload) is True
    assert _summarize_advanced_analysis_result(payload) == "job_id=stats-123, status=pending, rows=20, columns=4"


def test_save_advanced_analysis_artifact_persists_phase06_json(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    artifact = _save_advanced_analysis_artifact(
        project,
        dataset_id="dataset-1",
        analysis_type="logistic_regression",
        source="automl-stat-mcp",
        config={"target": "outcome"},
        analysis_result={
            "job_id": "stats-123",
            "job_type": "auto_analyze_direct",
            "status": "pending",
            "message": "submitted",
            "data_preview": {"rows": 20, "columns": 4},
        },
    )

    assert artifact.exists()
    assert artifact.name == "advanced_analysis_logistic_regression_stats-123.json"
    content = artifact.read_text(encoding="utf-8")
    assert '"contract": "direct_analyze"' in content
    assert '"analysis_type": "logistic_regression"' in content


def test_format_advanced_analysis_output_includes_job_summary_and_artifact(tmp_path: Path) -> None:
    artifact_path = tmp_path / "advanced_analysis_logistic_regression_stats-123.json"
    rendered = _format_advanced_analysis_output(
        analysis_type="logistic_regression",
        source="automl-stat-mcp",
        analysis_result={
            "job_id": "stats-123",
            "job_type": "auto_analyze_direct",
            "status": "pending",
            "message": "Direct analysis job submitted.",
            "data_preview": {
                "rows": 20,
                "columns": 4,
                "column_names": ["outcome", "age", "bmi", "sex"],
                "sample_rows": [{"outcome": 1, "age": 60}],
                "dtypes": {"outcome": "int64", "age": "int64"},
            },
        },
        artifact_path=artifact_path,
        automl_available=True,
    )

    assert "## 工作提交摘要" in rendered
    assert "- **job_id:** stats-123" in rendered
    assert "- **列數:** 20" in rendered
    assert "欄位型別" in rendered
    assert str(artifact_path) in rendered