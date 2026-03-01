"""Report Tools — MCP tool definitions for Phase 8 (Report Assembly).

Report is the primary output — more complete than a paper.
Authors extract PUBLISHABLE-marked sections for publication.
"""

from __future__ import annotations

from typing import Any


def register_report_tools(server: Any) -> None:
    """Register report generation MCP tools."""

    @server.tool()
    def generate_report(
        dataset_id: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        """生成結構化 EDA 報告。

        彙整所有分析步驟的結果，產出完整報告。
        自動檢查報告完整性（Hook H-005）與敏感資訊（Hook H-006）。

        Args:
            dataset_id: 資料集 ID
            title: 報告標題（可選，預設使用資料集名稱）

        Returns:
            報告內容與匯出路徑
        """
        return {"status": "not_implemented"}

    @server.tool()
    def export_for_paper(
        report_id: str,
        output_dir: str = "data/reports",
    ) -> dict[str, Any]:
        """將報告匯出為 med-paper-assistant 可接續使用的格式。

        包含 handoff metadata，讓下游工具鏈能直接讀取。

        Args:
            report_id: 報告 ID
            output_dir: 輸出目錄

        Returns:
            匯出檔案路徑與 handoff metadata
        """
        return {"status": "not_implemented"}

    @server.tool()
    def create_visualization(
        dataset_id: str,
        plot_type: str,
        variables: list[str],
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """生成視覺化圖表。

        根據變數類型自動建議適當圖表（Hook S-003）。

        Args:
            dataset_id: 資料集 ID
            plot_type: 圖表類型 (histogram, boxplot, scatter, bar, violin, heatmap)
            variables: 要繪製的變數
            output_path: 輸出路徑（可選）

        Returns:
            圖表檔案路徑
        """
        return {"status": "not_implemented"}
