"""ExportReportUseCase — Export EDA report to docx / pdf.

Orchestrates the conversion from EDAReport aggregate to document formats.
Follows medpaper's pattern: report → structured document with figures & tables.

Enforces H-006 (Output Sanitization) on all exported content.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rde.domain.models.report import EDAReport, ReportFormat, ReportSection
from rde.domain.ports import DocumentExporterPort

logger = logging.getLogger(__name__)


class ExportReportUseCase:
    """Export an EDAReport to docx and/or pdf."""

    def __init__(self, exporter: DocumentExporterPort) -> None:
        self._exporter = exporter

    def execute(
        self,
        report: EDAReport,
        output_dir: Path,
        *,
        formats: list[str] | None = None,
        figures_dir: Path | None = None,
    ) -> dict[str, Path]:
        """Export report to requested formats.

        Args:
            report: The EDAReport to export.
            output_dir: Directory for output files.
            formats: List of formats ("docx", "pdf"). Default: ["docx"].
            figures_dir: Directory containing figure PNGs.

        Returns:
            Dict mapping format name to output file path.
        """
        if formats is None:
            formats = ["docx"]

        # Validate report is exportable (H-005)
        errors = report.validate_integrity()
        if errors:
            raise ValueError(f"Report not exportable: {'; '.join(errors)}")

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Resolve figures directory
        if figures_dir is None:
            figures_dir = Path("data/reports/figures")
        figures_dir = Path(figures_dir)

        # Attach discovered figures to sections if not already attached
        if figures_dir.exists():
            self._attach_figures(report, figures_dir)

        results: dict[str, Path] = {}

        for fmt in formats:
            fmt_lower = fmt.lower().strip()
            base_name = f"eda_report.{fmt_lower}"
            output_path = output_dir / base_name

            if fmt_lower == "docx":
                path = self._exporter.export_docx(
                    report, output_path, figures_dir=figures_dir,
                )
                results["docx"] = path

            elif fmt_lower == "pdf":
                path = self._exporter.export_pdf(
                    report, output_path, figures_dir=figures_dir,
                )
                results["pdf"] = path

            else:
                raise ValueError(f"Unsupported export format: {fmt}")

        return results

    def _attach_figures(self, report: EDAReport, figures_dir: Path) -> None:
        """Auto-attach figures from figures_dir to relevant report sections.

        Scans the figures directory and maps files to sections by naming
        convention or attaches all figures to 'statistical_analyses' section.
        """
        if not figures_dir.exists():
            return

        all_figs = sorted(figures_dir.glob("*.png"))
        if not all_figs:
            return

        # Already-attached figure paths (avoid duplicates)
        attached = set()
        for section in report.sections:
            for f in section.figures:
                attached.add(Path(f).name)

        unattached = [f for f in all_figs if f.name not in attached]
        if not unattached:
            return

        # Try to match figures to sections by name prefix
        section_map: dict[str, ReportSection] = {
            s.section_id: s for s in report.sections
        }
        remaining: list[Path] = []

        for fig in unattached:
            name = fig.stem.lower()
            matched = False
            # Match by section keywords
            keyword_map = {
                "statistical_analyses": ["compare", "test", "anova", "chi", "mann", "wilcox"],
                "variable_profiles": ["histogram", "boxplot", "distribution", "violin"],
                "key_findings": ["scatter", "trend", "regression"],
                "data_quality": ["missing", "outlier", "quality"],
            }
            for sec_id, keywords in keyword_map.items():
                if sec_id in section_map and any(kw in name for kw in keywords):
                    section_map[sec_id].figures.append(str(fig))
                    matched = True
                    break
            if not matched:
                remaining.append(fig)

        # Attach remaining figures to statistical_analyses or last content section
        if remaining:
            target = section_map.get("statistical_analyses")
            if not target:
                target = report.sections[-1] if report.sections else None
            if target:
                for fig in remaining:
                    target.figures.append(str(fig))
