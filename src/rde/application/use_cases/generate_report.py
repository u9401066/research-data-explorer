"""GenerateReportUseCase — Pipeline Step 8.

Assembles the final EDA report from all previous step artifacts.
Enforces report integrity (H-005) and output sanitization (H-006).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from rde.domain.models.report import EDAReport, ReportSection
from rde.domain.policies.hard_constraints import HardConstraints
from rde.domain.ports import ReportRendererPort


class GenerateReportUseCase:
    """Generate the final EDA report."""

    def __init__(self, renderer: ReportRendererPort) -> None:
        self._renderer = renderer

    def execute(
        self,
        dataset_id: str,
        project_id: str,
        title: str,
        artifacts: dict[str, Any],
    ) -> EDAReport:
        """Assemble and validate the EDA report."""
        report = EDAReport(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            project_id=project_id,
            title=title,
        )

        # Build sections from artifacts
        self._build_sections(report, artifacts)

        # Hard Constraint H-005: report integrity
        integrity_check = HardConstraints.h005_report_integrity(report)
        if not integrity_check.passed:
            raise ValueError(f"Report integrity failed: {integrity_check.message}")

        return report

    def render(self, report: EDAReport, fmt: str = "markdown") -> str:
        """Render report to a string format."""
        if fmt == "markdown":
            content = self._renderer.render_markdown(report)
        elif fmt == "html":
            content = self._renderer.render_html(report)
        else:
            content = self._renderer.render_markdown(report)

        # Hard Constraint H-006: sanitize output
        content = self._sanitize_output(content)
        sanitization_check = HardConstraints.h006_output_sanitization(content)
        if not sanitization_check.passed:
            raise ValueError(f"Output sanitization failed: {sanitization_check.message}")

        return content

    def _build_sections(self, report: EDAReport, artifacts: dict[str, Any]) -> None:
        """Build report sections from pipeline artifacts."""
        section_builders = [
            ("data_overview", "Data Overview", 1),
            ("data_quality", "Data Quality", 2),
            ("variable_profiles", "Variable Profiles", 3),
            ("baseline_table", "Table 1 — Baseline Characteristics", 4),
            ("key_findings", "Key Findings", 5),
            ("statistical_analyses", "Statistical Analyses", 6),
            ("learning_curve_cusum", "Learning Curve CUSUM", 7),
            ("sensitivity_analysis", "Sensitivity Analysis", 8),
            ("recommendations", "Recommendations", 9),
        ]

        for section_id, title, order in section_builders:
            content = artifacts.get(section_id, "")
            if isinstance(content, dict):
                content = str(content)
            report.add_section(
                ReportSection(
                    section_id=section_id,
                    title=title,
                    content=content if content else f"[{title}: No data available]",
                    order=order,
                )
            )

    def _sanitize_output(self, content: str) -> str:
        """H-006: Remove sensitive file paths from output."""
        patterns = [
            r"[A-Z]:\\Users\\[^\\]+\\",  # Windows user paths
            r"/home/[^/]+/",  # Linux home
            r"/Users/[^/]+/",  # macOS home
            r"\\AppData\\[^\\]+\\",  # Windows AppData
        ]
        for pattern in patterns:
            content = re.sub(pattern, "[PATH]/", content)
        return content
