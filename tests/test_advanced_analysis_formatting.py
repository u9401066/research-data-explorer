from __future__ import annotations

from pathlib import Path

from rde.domain.models.project import Project
from rde.interface.mcp.tools.analysis_tools import (
    _format_advanced_analysis_output,
    _is_async_job_contract,
    _is_direct_analysis_contract,
    _save_advanced_analysis_artifact,
    _save_advanced_analysis_markdown_artifact,
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
    assert (
        _summarize_advanced_analysis_result(payload)
        == "job_id=stats-123, status=pending, rows=20, columns=4"
    )


def test_async_job_contract_detection_and_summary() -> None:
    payload = {
        "job_id": "automl-123",
        "job_type": "automl",
        "status": "pending",
        "progress": 0.0,
        "status_message": "Queued for processing",
        "created_at": "2026-03-28T12:00:00Z",
    }

    assert _is_async_job_contract(payload) is True
    assert (
        _summarize_advanced_analysis_result(payload)
        == "job_id=automl-123, status=pending, progress=0.0, message=Queued for processing"
    )


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


def test_save_advanced_analysis_artifact_marks_generic_job_submission(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    artifact = _save_advanced_analysis_artifact(
        project,
        dataset_id="dataset-1",
        analysis_type="automl",
        source="automl-stat-mcp",
        config={"target": "outcome"},
        analysis_result={
            "job_id": "automl-123",
            "job_type": "automl",
            "status": "pending",
            "progress": 0.0,
            "status_message": "Queued for processing",
            "created_at": "2026-03-28T12:00:00Z",
        },
    )

    assert artifact.exists()
    content = artifact.read_text(encoding="utf-8")
    assert '"contract": "job_submission"' in content
    assert '"analysis_type": "automl"' in content


def test_save_advanced_analysis_markdown_artifact_persists_phase06_markdown(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path)
    artifact = _save_advanced_analysis_markdown_artifact(
        project,
        analysis_type="learning_curve_cusum",
        analysis_result={"analysis_type": "learning_curve_cusum"},
        content="# CUSUM\n\nsummary",
    )

    assert artifact.exists()
    assert artifact.name == "advanced_analysis_learning_curve_cusum.md"
    assert artifact.read_text(encoding="utf-8") == "# CUSUM\n\nsummary"


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


def test_format_advanced_analysis_output_renders_generic_async_job(tmp_path: Path) -> None:
    artifact_path = tmp_path / "advanced_analysis_automl_automl-123.json"
    rendered = _format_advanced_analysis_output(
        analysis_type="automl",
        source="automl-stat-mcp",
        analysis_result={
            "job_id": "automl-123",
            "job_type": "automl",
            "status": "pending",
            "progress": 0.0,
            "status_message": "Queued for processing",
            "created_at": "2026-03-28T12:00:00Z",
        },
        artifact_path=artifact_path,
        automl_available=True,
    )

    assert "## 工作提交摘要" in rendered
    assert "- **job_id:** automl-123" in rendered
    assert "- **job_type:** automl" in rendered
    assert "- **status:** pending" in rendered
    assert "- **progress:** 0.0%" in rendered
    assert "Queued for processing" in rendered
    assert str(artifact_path) in rendered


def test_format_advanced_analysis_output_does_not_prompt_docker_for_local_lite(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "advanced_analysis_logistic_regression.json"
    rendered = _format_advanced_analysis_output(
        analysis_type="logistic_regression",
        source="local-lite (statsmodels)",
        analysis_result={
            "analysis_type": "logistic_regression",
            "engine": "statsmodels.Logit",
            "target": "outcome",
            "covariates": ["age", "severity"],
            "nobs": 20,
            "interpretation": "Adjusted model completed locally.",
        },
        artifact_path=artifact_path,
        automl_available=False,
    )

    assert "local-lite (statsmodels)" in rendered
    assert "docker compose" not in rendered


def test_format_advanced_analysis_output_for_learning_curve_cusum(tmp_path: Path) -> None:
    artifact_path = tmp_path / "advanced_analysis_learning_curve_cusum.json"
    rendered = _format_advanced_analysis_output(
        analysis_type="learning_curve_cusum",
        source="local (ScipyStatisticalEngine)",
        analysis_result={
            "analysis_type": "learning_curve_cusum",
            "success_variable": "成功_0不成功_1成功",
            "operator_variable": "Operator_ID",
            "trial_variable": "Trial",
            "target_success_rate": 0.75,
            "cohort_success_rate": 0.8,
            "total_trials": 24,
            "operators_analyzed": 3,
            "operators": [
                {
                    "operator_id": "A",
                    "n_trials": 10,
                    "success_rate": 0.9,
                    "final_cusum": 1.5,
                    "peak_cusum": 1.8,
                    "peak_trial": 9,
                }
            ],
            "interpretation": "1/3 位施打者高於 cohort target。",
        },
        artifact_path=artifact_path,
        automl_available=False,
    )

    assert "## 分析設定" in rendered
    assert "成功_0不成功_1成功" in rendered
    assert "Operator_ID" in rendered
    assert "Trial" in rendered
    assert "## 施打者 CUSUM 摘要" in rendered
    assert "final CUSUM=1.500" in rendered
    assert "**解讀:** 1/3 位施打者高於 cohort target。" in rendered
    assert str(artifact_path) in rendered
