"""MarkdownReportRenderer — Adapter implementing ReportRendererPort.

Renders EDAReport to Markdown or HTML format.
"""

from __future__ import annotations

from typing import Any

from rde.domain.models.report import EDAReport
from rde.domain.ports import ReportRendererPort


class MarkdownReportRenderer(ReportRendererPort):
    """Render EDAReport as Markdown or HTML."""

    def render_markdown(self, report: Any) -> str:
        rpt: EDAReport = report
        lines: list[str] = []

        lines.append(f"# {rpt.title}")
        lines.append("")
        lines.append(f"**Dataset:** {rpt.dataset_id}")
        lines.append(f"**Project:** {rpt.project_id}")
        lines.append(f"**Generated:** {rpt.created_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for section in rpt.sections:
            lines.append(f"## {section.title}")
            lines.append("")
            lines.append(section.content)
            lines.append("")

            if section.figures:
                lines.append("### Figures")
                for fig in section.figures:
                    lines.append(f"![{section.title}]({fig})")
                lines.append("")

            if section.tables:
                for tbl in section.tables:
                    lines.append(self._dict_to_md_table(tbl))
                    lines.append("")

            lines.append("---")
            lines.append("")

        # Metadata footer
        lines.append("## Metadata")
        lines.append("")
        for k, v in rpt.metadata.items():
            lines.append(f"- **{k}:** {v}")
        lines.append("")

        return "\n".join(lines)

    def render_html(self, report: Any) -> str:
        rpt: EDAReport = report
        md = self.render_markdown(rpt)
        # Minimal HTML wrapper — proper HTML rendering can be added later
        html_lines = [
            "<!DOCTYPE html>",
            '<html lang="zh-TW">',
            "<head>",
            f"<title>{rpt.title}</title>",
            '<meta charset="utf-8">',
            "<style>",
            "  body { font-family: sans-serif; max-width: 900px; margin: auto; padding: 2em; }",
            "  table { border-collapse: collapse; width: 100%; margin: 1em 0; }",
            "  th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }",
            "  th { background: #f4f4f4; }",
            "  hr { margin: 2em 0; }",
            "  img { max-width: 100%; }",
            "</style>",
            "</head>",
            "<body>",
        ]

        for section in rpt.sections:
            html_lines.append(f"<h2>{section.title}</h2>")
            # Wrap content paragraphs
            for para in section.content.split("\n\n"):
                para = para.strip()
                if para:
                    html_lines.append(f"<p>{para}</p>")

            if section.figures:
                for fig in section.figures:
                    html_lines.append(f'<img src="{fig}" alt="{section.title}">')

            if section.tables:
                for tbl in section.tables:
                    html_lines.append(self._dict_to_html_table(tbl))

        html_lines.extend(["</body>", "</html>"])
        return "\n".join(html_lines)

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _dict_to_md_table(tbl: dict[str, Any]) -> str:
        if not tbl:
            return ""
        headers = list(tbl.keys())
        first_vals = tbl[headers[0]]
        if isinstance(first_vals, dict):
            rows_keys = list(first_vals.keys())
        else:
            return str(tbl)

        lines = []
        lines.append("| " + " | ".join(str(h) for h in headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for rk in rows_keys:
            vals = [str(tbl[h].get(rk, "")) if isinstance(tbl[h], dict) else str(tbl[h]) for h in headers]
            lines.append("| " + " | ".join(vals) + " |")
        return "\n".join(lines)

    @staticmethod
    def _dict_to_html_table(tbl: dict[str, Any]) -> str:
        if not tbl:
            return ""
        headers = list(tbl.keys())
        first_vals = tbl[headers[0]]
        if isinstance(first_vals, dict):
            rows_keys = list(first_vals.keys())
        else:
            return f"<pre>{tbl}</pre>"

        lines = ["<table>", "<tr>"]
        for h in headers:
            lines.append(f"<th>{h}</th>")
        lines.append("</tr>")
        for rk in rows_keys:
            lines.append("<tr>")
            for h in headers:
                val = tbl[h].get(rk, "") if isinstance(tbl[h], dict) else tbl[h]
                lines.append(f"<td>{val}</td>")
            lines.append("</tr>")
        lines.append("</table>")
        return "\n".join(lines)
