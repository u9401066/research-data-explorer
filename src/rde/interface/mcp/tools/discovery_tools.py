"""Discovery Tools — MCP tool definitions for Phase 1 (Data Intake) & Phase 2 (Schema).

Thin wrappers that delegate to DiscoverDataUseCase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def register_discovery_tools(server: Any) -> None:
    """Register data discovery MCP tools."""

    @server.tool()
    def scan_data_folder(directory: str = "data/rawdata") -> dict[str, Any]:
        """掃描指定目錄，列出所有可分析的資料檔案。

        自動檢查檔案格式與大小限制。
        支援格式: CSV, Excel, Parquet, SAS, SPSS, Stata, TSV

        Args:
            directory: 要掃描的資料目錄路徑（預設: data/rawdata）

        Returns:
            檔案清單與每個檔案的載入狀態
        """
        from rde.infrastructure.adapters import PandasLoader
        from rde.application.use_cases.discover_data import DiscoverDataUseCase

        loader = PandasLoader()
        use_case = DiscoverDataUseCase(loader)
        files = use_case.execute(Path(directory))

        return {
            "total_files": len(files),
            "loadable": sum(1 for f in files if f.is_loadable),
            "rejected": sum(1 for f in files if not f.is_loadable),
            "files": [
                {
                    "name": f.file_name,
                    "path": f.file_path,
                    "format": f.file_format,
                    "size_mb": round(f.file_size_bytes / (1024 * 1024), 2),
                    "loadable": f.is_loadable,
                    "rejection_reason": f.rejection_reason or None,
                }
                for f in files
            ],
        }

    @server.tool()
    def load_dataset(
        file_path: str,
        encoding: str | None = None,
        sheet_name: str | None = None,
    ) -> dict[str, Any]:
        """載入資料集到記憶體。

        自動偵測檔案格式，執行格式與大小的安全檢查。

        Args:
            file_path: 資料檔案路徑
            encoding: 檔案編碼（可選，自動偵測）
            sheet_name: Excel 工作表名稱（可選）

        Returns:
            資料集摘要（列數、欄位、型別等）
        """
        from rde.infrastructure.adapters import PandasLoader
        from rde.domain.models.dataset import Dataset, DatasetMetadata

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}"}

        metadata = DatasetMetadata(
            file_path=path,
            file_format=path.suffix.lstrip(".").lower(),
            file_size_bytes=path.stat().st_size,
            encoding=encoding,
            sheet_name=sheet_name,
        )

        dataset = Dataset(metadata=metadata)
        errors = dataset.validate_loadable()
        if errors:
            return {"error": "; ".join(errors)}

        loader = PandasLoader()
        df, variables, row_count = loader.load(metadata)
        dataset.mark_loaded(variables, row_count)

        # Store in session (simplified — will use proper repository later)
        # TODO: integrate with ProjectRepository

        pii_vars = [v.name for v in variables if v.is_pii_suspect]

        return {
            "dataset_id": dataset.id,
            "file": path.name,
            "rows": row_count,
            "columns": len(variables),
            "variables": [
                {
                    "name": v.name,
                    "dtype": v.dtype,
                    "missing": v.n_missing,
                    "unique": v.n_unique,
                }
                for v in variables
            ],
            "pii_warnings": pii_vars if pii_vars else None,
            "status": dataset.status.value,
        }
