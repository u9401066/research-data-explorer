"""Export the full AKI analysis report to DOCX with all 8 figures embedded."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rde.domain.models.report import EDAReport
from rde.infrastructure.adapters.docx_exporter import DocxExporter

# Paths
report_md = REPO_ROOT / "data" / "reports" / "aki_analysis" / "eda_report_final.md"
figures_dir = REPO_ROOT / "data" / "reports" / "aki_analysis" / "figures"
output_docx = REPO_ROOT / "data" / "reports" / "aki_analysis" / "eda_report_final.docx"
output_pdf_html = REPO_ROOT / "data" / "reports" / "aki_analysis" / "eda_report_final.pdf"


def main() -> None:
    md_content = report_md.read_text(encoding="utf-8")
    print(f"Read report: {len(md_content)} chars")

    report = EDAReport.from_markdown(
        md_content,
        report_id="aki_eda_2026",
        dataset_id="aki_analysis_ready",
        project_id="aki_biomarker_study",
    )
    print(f"Parsed: {len(report.sections)} sections, title={report.title!r}")

    if figures_dir.exists():
        figs = sorted(figures_dir.glob("*.png"))
        print(f"Figures found: {len(figs)}")
        for fig in figs:
            print(f"  - {fig.name} ({fig.stat().st_size:,} bytes)")
    else:
        print("WARNING: No figures directory found!")

    errors = report.validate_integrity()
    if errors:
        print(f"WARNING: Integrity issues: {errors}")
    else:
        print("Integrity: PASS (all required sections present)")

    exporter = DocxExporter()
    result_path = exporter.export_docx(report, output_docx, figures_dir=figures_dir)
    print(f"\nDOCX exported: {result_path} ({result_path.stat().st_size:,} bytes)")

    try:
        result_pdf = exporter.export_pdf(report, output_pdf_html, figures_dir=figures_dir)
        print(f"PDF exported: {result_pdf} ({result_pdf.stat().st_size:,} bytes)")
    except ImportError as exc:
        print(f"PDF export: {exc}")

    print("\nDone!")


if __name__ == "__main__":
    main()
