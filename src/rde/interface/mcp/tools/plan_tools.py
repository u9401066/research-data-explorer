"""Plan Tools — MCP tool definitions for Phase 3-5.

Phase 3: Concept-Schema Alignment
Phase 4: Analysis Plan Registration (LOCKED after completion)
Phase 5: Pre-Exploration Readiness Check
"""

from __future__ import annotations

from typing import Any


def register_plan_tools(server: Any) -> None:
    """Register planning and pre-registration MCP tools."""

    @server.tool()
    def align_concept(
        project_id: str,
        research_question: str,
        variable_roles: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """對齊研究概念與資料 schema（Phase 3）。

        將研究問題的摘要概念對應到實際變數名稱，
        確認 outcome、predictor、confounder 角色分配。

        Args:
            project_id: 專案 ID
            research_question: 研究問題
            variable_roles: 變數角色指定（可選，可互動確認）

        Returns:
            概念對齊報告
        """
        return {"status": "not_implemented"}

    @server.tool()
    def register_analysis_plan(
        project_id: str,
        analyses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """註冊分析計畫（Phase 4 — Pre-registration）。

        定義預計要執行的分析清單。
        完成後計畫會被鎖定（H-007），後續偏離必須記錄。

        ⚠️ 此操作完成後計畫將被鎖定，無法修改。

        Args:
            project_id: 專案 ID
            analyses: 計畫執行的分析列表，每項包含:
                - type: 分析類型
                - variables: 涉及的變數
                - rationale: 分析理由

        Returns:
            已鎖定的分析計畫
        """
        return {"status": "not_implemented"}

    @server.tool()
    def check_readiness(project_id: str) -> dict[str, Any]:
        """執行探索前準備度檢查（Phase 5）。

        驗證：
        - Schema 完整性 ✓
        - 資料品質門檻 ✓
        - 分析計畫已鎖定 ✓ (H-007)
        - 所有前置 artifacts 存在 ✓ (H-008)
        - PII 已處理 ✓ (H-004)

        Args:
            project_id: 專案 ID

        Returns:
            準備度檢查清單（全通過才能進入 Phase 6）
        """
        return {"status": "not_implemented"}
