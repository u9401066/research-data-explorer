"""MCP Server — FastMCP entry point.

Registers all MCP tools and configures the server.
Thin layer: receives tool calls, delegates to use cases.
Tool groups organized around the 11-Phase Auditable EDA Pipeline.
"""

from __future__ import annotations

from pathlib import Path

from rde.interface.mcp.tools.discovery_tools import register_discovery_tools
from rde.interface.mcp.tools.profiling_tools import register_profiling_tools
from rde.interface.mcp.tools.analysis_tools import register_analysis_tools
from rde.interface.mcp.tools.report_tools import register_report_tools
from rde.interface.mcp.tools.project_tools import register_project_tools
from rde.interface.mcp.tools.plan_tools import register_plan_tools
from rde.interface.mcp.tools.audit_tools import register_audit_tools


def create_server():
    """Create and configure the MCP server with all tools."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise ImportError("mcp SDK required. Install with: pip install mcp")

    server = FastMCP(
        "research-data-explorer",
    )

    # Register tool groups (organized by pipeline phases)
    register_project_tools(server)       # Phase 0: Project Setup
    register_discovery_tools(server)     # Phase 1-2: Data Intake & Schema
    register_profiling_tools(server)     # Phase 2: Schema Registry (profiling)
    register_plan_tools(server)          # Phase 3-5: Concept, Plan, Pre-check
    register_analysis_tools(server)      # Phase 6-7: Execute & Collect
    register_report_tools(server)        # Phase 8: Report Assembly
    register_audit_tools(server)         # Phase 9-10: Audit & Improve

    return server
