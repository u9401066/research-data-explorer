"""Export the full AKI analysis report to DOCX with all 8 figures embedded."""
import sys
sys.path.insert(0, "src")

from pathlib import Path
from rde.domain.models.report import EDAReport
from rde.infrastructure.adapters.docx_exporter import DocxExporter

# Paths
report_md = Path("data/reports/aki_analysis/eda_report_final.md")
figures_dir = Path("data/reports/aki_analysis/figures")
output_docx = Path("data/reports/aki_analysis/eda_report_final.docx")
output_pdf_html = Path("data/reports/aki_analysis/eda_report_final.pdf")

# Read the markdown report
md_content = report_md.read_text(encoding="utf-8")
print(f"Read report: {len(md_content)} chars")

# Parse into EDAReport
report = EDAReport.from_markdown(
    md_content,
    report_id="aki_eda_2026",
    dataset_id="aki_analysis_ready",
    project_id="aki_biomarker_study",
)
print(f"Parsed: {len(report.sections)} sections, title={report.title!r}")

# List available figures
if figures_dir.exists():
    figs = sorted(figures_dir.glob("*.png"))
    print(f"Figures found: {len(figs)}")
    for f in figs:
        print(f"  - {f.name} ({f.stat().st_size:,} bytes)")
else:
    print("WARNING: No figures directory found!")

# Validate integrity
errors = report.validate_integrity()
if errors:
    print(f"WARNING: Integrity issues: {errors}")
else:
    print("Integrity: PASS (all required sections present)")

# Export DOCX
exporter = DocxExporter()
result_path = exporter.export_docx(report, output_docx, figures_dir=figures_dir)
print(f"\nDOCX exported: {result_path} ({result_path.stat().st_size:,} bytes)")

# Export PDF (via HTML fallback if xhtml2pdf not available)
try:
    result_pdf = exporter.export_pdf(report, output_pdf_html, figures_dir=figures_dir)
    print(f"PDF exported: {result_pdf} ({result_pdf.stat().st_size:,} bytes)")
except ImportError as e:
    print(f"PDF export: {e}")

print("\nDone!")
