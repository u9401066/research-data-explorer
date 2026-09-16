"""MCP Server — official SDK v2 entry point.

Registers all MCP tools and configures the server.
Thin layer: receives tool calls, delegates to use cases.
Tool groups organized around the 13-Phase Auditable EDA Pipeline.
"""

from __future__ import annotations


from rde.interface.mcp.tools.discovery_tools import register_discovery_tools
from rde.interface.mcp.tools.profiling_tools import register_profiling_tools
from rde.interface.mcp.tools.analysis_tools import register_analysis_tools
from rde.interface.mcp.tools.report_tools import register_report_tools
from rde.interface.mcp.tools.project_tools import register_project_tools
from rde.interface.mcp.tools.plan_tools import register_plan_tools
from rde.interface.mcp.tools.audit_tools import register_audit_tools
from rde.interface.mcp.tools.branch_tools import register_branch_tools
from rde.interface.mcp.tools.ux_tools import register_ux_tools
from rde.interface.mcp.tools.protocol_tools import register_protocol_tools


def create_server():
    """Create and configure the MCP server with all tools."""
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    try:
        from rde.interface.mcp.runtime import RDEServer
    except ImportError:
        raise ImportError('MCP SDK v2 required. Install with: pip install "mcp>=2.2,<3"')

    from importlib.metadata import version

    server = RDEServer(
        "research-data-explorer",
        title="Research Data Explorer",
        version=version("research-data-explorer"),
        website_url="https://u9401066.github.io/research-data-explorer/",
        instructions=(
            "Research Data Explorer (RDE) — 13-Phase Auditable EDA Pipeline.\n"
            "使用此工具進行結構化、可審計的探索性資料分析。\n"
            "所有分析決策自動記錄 (H-009)，偏離計畫需明確記錄。\n"
            "Pipeline: Phase 0 (Setup) → Phase 12 (Auto-Improve)。"
        ),
    )

    # Register tool groups (organized by pipeline phases)
    register_project_tools(server)  # Phase 0: Project Setup
    register_discovery_tools(server)  # Phase 1-2: Data Intake & Schema
    register_profiling_tools(server)  # Phase 2: Schema Registry (profiling)
    register_plan_tools(server)  # Phase 3-7: Concept, Plan, Pre-check
    register_analysis_tools(server)  # Phase 8-9: Execute & Collect
    register_branch_tools(server)  # Phase 8: YOLO Exploration Branch Loop
    register_ux_tools(server)  # Cross-phase: no-code UX Harness
    register_report_tools(server)  # Phase 10: Report Assembly
    register_audit_tools(server)  # Phase 11-12: Audit & Improve
    register_protocol_tools(server)  # SDK v2: trusted resolver, resources and prompt

    return server
