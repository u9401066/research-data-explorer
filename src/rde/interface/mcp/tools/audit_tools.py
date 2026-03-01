"""Audit Tools — MCP tool definitions for Phase 9 (Audit Review) & Phase 10 (Auto-Improve)."""

from __future__ import annotations

from typing import Any


def register_audit_tools(server: Any) -> None:
    """Register audit and improvement MCP tools."""

    @server.tool()
    def run_audit(project_id: str) -> dict[str, Any]:
        """執行審計審查（Phase 9）。

        檢查項目：
        - Completeness: 所有階段的 artifacts 是否齊全
        - Traceability: decision_log 是否完整記錄每個分析步驟
        - Reproducibility: 是否有足夠資訊重現結果
        - Plan Adherence: 偏離數量與合理性

        產出 audit_report.json，包含 A/B/C/D/F 等級。

        Args:
            project_id: 專案 ID

        Returns:
            審計報告（含等級與改善建議）
        """
        return {"status": "not_implemented"}

    @server.tool()
    def suggest_improvements(project_id: str) -> dict[str, Any]:
        """根據審計結果建議改善項目（Phase 10）。

        分析 audit_report 中的缺陷，
        建議可回頭補充的分析或說明。

        Args:
            project_id: 專案 ID

        Returns:
            改善建議清單
        """
        return {"status": "not_implemented"}

    @server.tool()
    def verify_audit_trail(project_id: str) -> dict[str, Any]:
        """驗證審計軌跡完整性。

        確認：
        - decision_log.jsonl 是 append-only (H-010)
        - deviation_log.jsonl 是 append-only (H-010)
        - 所有 Phase artifacts 存在 (H-008)
        - 報告中引用的所有數據可追溯到 decision_log

        Args:
            project_id: 專案 ID

        Returns:
            完整性驗證結果
        """
        return {"status": "not_implemented"}
