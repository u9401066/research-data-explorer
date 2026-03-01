"""Formatting helpers — consistent markdown output for MCP tools."""

from __future__ import annotations

from typing import Any


def fmt_error(message: str, detail: str = "", suggestion: str = "") -> str:
    """Format an error response."""
    parts = [f"❌ {message}"]
    if detail:
        parts.append(f"\n{detail}")
    if suggestion:
        parts.append(f"\n**建議:** {suggestion}")
    return "\n".join(parts)


def fmt_success(message: str, detail: str = "") -> str:
    """Format a success response."""
    parts = [f"✅ {message}"]
    if detail:
        parts.append(f"\n{detail}")
    return "\n".join(parts)


def fmt_warning(message: str, detail: str = "") -> str:
    """Format a warning response."""
    parts = [f"⚠️ {message}"]
    if detail:
        parts.append(f"\n{detail}")
    return "\n".join(parts)


def fmt_table(headers: list[str], rows: list[list[Any]]) -> str:
    """Format a markdown table."""
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def fmt_checks(checks: list[dict[str, Any]]) -> str:
    """Format a list of check results as markdown."""
    lines = []
    for c in checks:
        icon = "✅" if c.get("passed") else "❌"
        cid = c.get("id", "")
        name = c.get("name", "")
        detail = c.get("detail", "")
        lines.append(f"{icon} **[{cid}] {name}**: {detail}")
    return "\n".join(lines)


def fmt_kv(data: dict[str, Any], title: str = "") -> str:
    """Format key-value pairs as markdown."""
    lines = []
    if title:
        lines.append(f"## {title}\n")
    for k, v in data.items():
        lines.append(f"- **{k}**: {v}")
    return "\n".join(lines)
