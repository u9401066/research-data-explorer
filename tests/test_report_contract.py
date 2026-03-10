from pathlib import Path

from rde.domain.models.report import EDAReport, ReportSection
from rde.interface.mcp.tools.report_tools import (
    _format_data_overview,
    _format_data_quality,
    _format_variable_profiles,
)
from rde.application.use_cases.export_report import ExportReportUseCase


def test_format_data_overview_uses_current_intake_keys() -> None:
    intake = {
        "loaded_file": "iris.csv",
        "row_count": 150,
        "column_count": 5,
    }
    schema = {"variables": [{"name": "species"}, {"name": "sepal_length"}]}

    text = _format_data_overview(intake, schema)

    assert "iris.csv" in text
    assert "150" in text
    assert "5" in text
    assert "**Schema 變數數:** 2" in text


def test_formatters_use_current_schema_keys() -> None:
    schema = {
        "variables": [
            {"name": "species", "variable_type": "categorical", "missing_rate": 0.0},
            {"name": "sepal_length", "variable_type": "continuous", "missing_rate": 0.1},
        ]
    }
    readiness = {
        "checks": [
            {"id": "H-003", "name": "最小樣本量", "passed": True, "detail": "n = 150"},
            {"id": "S-005", "name": "缺失模式分析", "passed": True, "detail": "模式: MAR"},
        ]
    }

    quality = _format_data_quality(schema, readiness)
    profiles = _format_variable_profiles(schema)

    assert "categorical: 1" in quality
    assert "continuous: 1" in quality
    assert "species" in profiles
    assert "sepal_length" in profiles
    assert "10.0%" in profiles


class _ExporterSpy:
    def __init__(self) -> None:
        self.figures_dir = None

    def export_docx(self, report, output_path, *, figures_dir=None):
        self.figures_dir = figures_dir
        output_path.write_text("docx", encoding="utf-8")
        return output_path

    def export_pdf(self, report, output_path, *, figures_dir=None):
        self.figures_dir = figures_dir
        output_path.write_text("pdf", encoding="utf-8")
        return output_path


def test_export_use_case_accepts_project_scoped_figures_dir(tmp_path: Path) -> None:
    report = EDAReport(
        id="r1",
        dataset_id="d1",
        project_id="p1",
        title="Demo",
    )
    for idx, section_id in enumerate(
        [
            "data_overview",
            "data_quality",
            "variable_profiles",
            "key_findings",
            "statistical_analyses",
            "recommendations",
        ],
        start=1,
    ):
        report.add_section(ReportSection(section_id=section_id, title=section_id, content="ok", order=idx))

    spy = _ExporterSpy()
    use_case = ExportReportUseCase(spy)
    figures_dir = tmp_path / "project" / "figures"
    figures_dir.mkdir(parents=True)

    result = use_case.execute(
        report=report,
        output_dir=tmp_path / "exports",
        formats=["docx"],
        figures_dir=figures_dir,
    )

    assert result["docx"].exists()
    assert spy.figures_dir == figures_dir