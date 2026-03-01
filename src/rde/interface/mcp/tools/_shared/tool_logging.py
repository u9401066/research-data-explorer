"""Tool call logging — structured logging for every MCP tool invocation."""

from __future__ import annotations

import logging
import traceback
from typing import Any

_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("rde.mcp.tools")
        if not _logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            )
            _logger.addHandler(handler)
            _logger.setLevel(logging.DEBUG)
    return _logger


def _safe_serialize(value: Any, max_length: int = 500) -> str:
    """Truncate long values for safe logging."""
    s = str(value)
    return s[:max_length] + "..." if len(s) > max_length else s


def log_tool_call(tool_name: str, params: dict[str, Any]) -> None:
    """Log a tool invocation with sanitized parameters."""
    logger = _get_logger()
    safe = {k: _safe_serialize(v) for k, v in params.items()}
    logger.debug("🔧 TOOL_CALL: %s | params=%s", tool_name, safe)


def log_tool_result(tool_name: str, summary: str, success: bool = True) -> None:
    """Log tool result."""
    logger = _get_logger()
    icon = "✅" if success else "⚠️"
    logger.debug("%s TOOL_RESULT: %s | %s", icon, tool_name, summary)


def log_tool_error(tool_name: str, error: Exception, params: dict[str, Any] | None = None) -> None:
    """Log tool error with traceback."""
    logger = _get_logger()
    tb = traceback.format_exc()
    logger.error("❌ TOOL_ERROR: %s | %s: %s", tool_name, type(error).__name__, error)
    logger.debug("Traceback:\n%s", tb)
