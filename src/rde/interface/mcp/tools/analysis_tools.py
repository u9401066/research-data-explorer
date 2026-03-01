"""Analysis Tools — MCP tool definitions for Phase 6 (Execute) & Phase 7 (Collect).

All Phase 6 tools auto-log decisions to decision_log.jsonl (H-009).
Plan deviations trigger S-011 alerts.
"""

from __future__ import annotations

from typing import Any


def register_analysis_tools(server: Any) -> None:
    """Register statistical analysis MCP tools."""

    @server.tool()
    def suggest_cleaning(dataset_id: str) -> dict[str, Any]:
        """根據品質評估建議資料清理策略。

        Args:
            dataset_id: 已評估品質的資料集 ID

        Returns:
            清理建議清單（需用戶確認後才執行）
        """
        return {"status": "not_implemented"}

    @server.tool()
    def apply_cleaning(dataset_id: str, approved_indices: list[int]) -> dict[str, Any]:
        """執行用戶已確認的清理操作。

        Args:
            dataset_id: 資料集 ID
            approved_indices: 用戶核准的清理動作索引

        Returns:
            清理結果
        """
        return {"status": "not_implemented"}

    @server.tool()
    def analyze_variable(dataset_id: str, variable_name: str) -> dict[str, Any]:
        """分析單一變數的分佈與描述統計。

        自動判斷常態性（Hook S-001）並建議轉換（Hook S-004）。

        Args:
            dataset_id: 資料集 ID
            variable_name: 要分析的變數名稱

        Returns:
            單變數分析結果
        """
        return {"status": "not_implemented"}

    @server.tool()
    def compare_groups(
        dataset_id: str,
        outcome_variables: list[str],
        group_variable: str,
        is_paired: bool = False,
    ) -> dict[str, Any]:
        """組間比較，自動選擇適當的統計檢定方法。

        根據變數類型、樣本大小、分佈特徵自動選擇：
        - t-test / Mann-Whitney U (兩組連續)
        - ANOVA / Kruskal-Wallis (多組連續)
        - Chi-squared / Fisher's exact (類別)

        自動應用 Soft Constraints: S-001, S-002, S-008, S-009, S-010

        Args:
            dataset_id: 資料集 ID
            outcome_variables: 要比較的結果變數列表
            group_variable: 分組變數
            is_paired: 是否為配對資料

        Returns:
            比較結果與統計量
        """
        return {"status": "not_implemented"}

    @server.tool()
    def correlation_matrix(
        dataset_id: str,
        variables: list[str] | None = None,
    ) -> dict[str, Any]:
        """計算相關性矩陣。

        自動選擇 Pearson/Spearman 相關係數，
        檢查共線性（Hook S-007）。

        Args:
            dataset_id: 資料集 ID
            variables: 要分析的變數（空則分析所有連續變數）

        Returns:
            相關性矩陣與多重共線性警告
        """
        return {"status": "not_implemented"}

    @server.tool()
    def generate_table_one(
        dataset_id: str,
        group_variable: str,
        variables: list[str] | None = None,
    ) -> dict[str, Any]:
        """生成臨床研究的 Table 1（基線特徵表）。

        使用 tableone 引擎，自動區分連續/類別變數，
        選擇適當的摘要統計量與檢定方法。

        Args:
            dataset_id: 資料集 ID
            group_variable: 分組變數
            variables: 要納入的變數列表（空則全部納入）

        Returns:
            Table 1 內容
        """
        return {"status": "not_implemented"}
