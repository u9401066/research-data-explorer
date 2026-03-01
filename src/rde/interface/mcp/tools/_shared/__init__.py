"""Shared utilities for MCP tools — logging, project context, formatting."""

from rde.interface.mcp.tools._shared.tool_logging import (
    log_tool_call,
    log_tool_error,
    log_tool_result,
)
from rde.interface.mcp.tools._shared.project_context import (
    ensure_project_context,
    ensure_dataset,
)
from rde.interface.mcp.tools._shared.formatting import (
    fmt_error,
    fmt_success,
    fmt_warning,
    fmt_table,
)

__all__ = [
    "log_tool_call",
    "log_tool_error",
    "log_tool_result",
    "ensure_project_context",
    "ensure_dataset",
    "fmt_error",
    "fmt_success",
    "fmt_warning",
    "fmt_table",
]
