"""Project Tools — MCP tool definitions for Phase 0 (Project Setup) & pipeline status."""

from __future__ import annotations

from typing import Any


def register_project_tools(server: Any) -> None:
    """Register project management MCP tools."""

    @server.tool()
    def create_project(
        name: str,
        data_dir: str = "data/rawdata",
        research_question: str = "",
    ) -> dict[str, Any]:
        """建立新的 EDA 探索專案（Phase 0）。

        建立專案目錄結構，初始化 project.yaml。
        設定 rawdata 目錄、output 目錄、audit log 路徑。

        Args:
            name: 專案名稱
            data_dir: 原始資料目錄路徑
            research_question: 研究問題描述（可選，Phase 3 再填也行）

        Returns:
            專案 ID 與目錄結構
        """
        return {"status": "not_implemented"}

    @server.tool()
    def get_project_status(project_id: str | None = None) -> dict[str, Any]:
        """查看目前分析專案的進度。

        顯示已完成的 pipeline 階段、下一步建議、
        plan lock 狀態、audit trail 摘要。

        Args:
            project_id: 專案 ID（可選，預設使用目前專案）

        Returns:
            專案進度摘要（11-Phase 狀態）
        """
        return {"status": "not_implemented"}

    @server.tool()
    def get_decision_log(project_id: str | None = None) -> dict[str, Any]:
        """查詢分析決策紀錄（decision_log.jsonl）。

        列出 Phase 6 中所做的每個分析決策，
        包含工具、參數、理由、結果摘要。

        Args:
            project_id: 專案 ID

        Returns:
            決策紀錄清單
        """
        return {"status": "not_implemented"}

    @server.tool()
    def get_deviation_log(project_id: str | None = None) -> dict[str, Any]:
        """查詢偏離紀錄（deviation_log.jsonl）。

        列出與 analysis plan 不同的操作，
        包含原計畫、實際操作、偏離理由。

        Args:
            project_id: 專案 ID

        Returns:
            偏離紀錄清單
        """
        return {"status": "not_implemented"}
