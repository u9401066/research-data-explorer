"""Discovery Tools — Phase 1 (Data Intake) & Phase 2 (Schema).

Includes orchestrated `run_intake` and `build_schema` tools.
All tools return markdown strings.
"""

from __future__ import annotations

from typing import Any


def register_discovery_tools(server: Any) -> None:
    """Register data discovery MCP tools."""

    @server.tool()
    def scan_data_folder(directory: str = "data/rawdata") -> str:
        """掃描指定目錄，列出所有可分析的資料檔案。

        支援格式: CSV, Excel, Parquet, SAS, SPSS, Stata, TSV

        Args:
            directory: 要掃描的資料目錄路徑（預設: data/rawdata）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_result, log_tool_error,
            fmt_error, fmt_table,
        )
        from pathlib import Path

        log_tool_call("scan_data_folder", {"directory": directory})

        try:
            from rde.infrastructure.adapters import PandasLoader
            from rde.application.use_cases.discover_data import DiscoverDataUseCase

            if not Path(directory).exists():
                return fmt_error(f"目錄不存在: {directory}")

            loader = PandasLoader()
            use_case = DiscoverDataUseCase(loader)
            files = use_case.execute(Path(directory))

            if not files:
                return fmt_error(f"目錄 `{directory}` 中沒有可分析的檔案。")

            loadable = sum(1 for f in files if f.is_loadable)
            rejected = sum(1 for f in files if not f.is_loadable)

            headers = ["檔案", "格式", "大小 (MB)", "狀態", "原因"]
            rows = []
            for f in files:
                size_mb = round(f.file_size_bytes / (1024 * 1024), 2)
                status = "✅" if f.is_loadable else "❌"
                reason = f.rejection_reason or ""
                rows.append([f.file_name, f.file_format, size_mb, status, reason])

            table = fmt_table(headers, rows)

            log_tool_result("scan_data_folder", f"{loadable} loadable, {rejected} rejected")

            return (
                f"# 📂 資料目錄掃描 — `{directory}`\n\n"
                f"- **可載入:** {loadable} 個\n"
                f"- **被拒絕:** {rejected} 個\n\n"
                f"{table}\n\n"
                f"**下一步:** 使用 `load_dataset(file_path)` 載入資料，"
                f"或 `run_intake()` 執行完整收件流程。"
            )

        except Exception as e:
            log_tool_error("scan_data_folder", e, {"directory": directory})
            return fmt_error(f"掃描失敗: {e}")

    @server.tool()
    def load_dataset(
        file_path: str,
        encoding: str | None = None,
        sheet_name: str | None = None,
    ) -> str:
        """載入資料集到記憶體，執行格式與大小的安全檢查。

        Args:
            file_path: 資料檔案路徑
            encoding: 檔案編碼（可選，自動偵測）
            sheet_name: Excel 工作表名稱（可選）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_result, log_tool_error,
            fmt_error, fmt_table,
        )
        from pathlib import Path

        log_tool_call("load_dataset", {"file_path": file_path})

        try:
            from rde.infrastructure.adapters import PandasLoader
            from rde.domain.models.dataset import Dataset, DatasetMetadata
            from rde.application.session import get_session

            path = Path(file_path)
            if not path.exists():
                return fmt_error(f"檔案不存在: {file_path}")

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
                return fmt_error("資料集無法載入", "; ".join(errors))

            loader = PandasLoader()
            df, variables, row_count = loader.load(metadata)
            dataset.mark_loaded(variables, row_count)

            session = get_session()
            session.register_dataset(dataset, df)

            pii_vars = [v.name for v in variables if v.is_pii_suspect]

            headers = ["變數", "dtype", "類型", "缺失", "唯一值"]
            rows = [
                [v.name, v.dtype, v.variable_type.value, v.n_missing, v.n_unique]
                for v in variables
            ]
            table = fmt_table(headers, rows)

            pii_warning = ""
            if pii_vars:
                pii_warning = (
                    f"\n⚠️ **[H-004] 疑似 PII 變數:** {', '.join(pii_vars)}\n"
                    f"請確認是否需要遮蔽或移除。\n"
                )

            log_tool_result("load_dataset", f"{row_count} rows, {len(variables)} vars")

            return (
                f"✅ 資料集載入成功！\n\n"
                f"- **資料集 ID:** `{dataset.id}`\n"
                f"- **檔案:** {path.name}\n"
                f"- **列數:** {row_count:,}\n"
                f"- **變數數:** {len(variables)}\n"
                f"{pii_warning}\n"
                f"{table}\n\n"
                f"**下一步:** 使用 `build_schema()` 建立完整 schema，"
                f"或 `profile_dataset()` 產生 profiling 報告。"
            )

        except Exception as e:
            log_tool_error("load_dataset", e, {"file_path": file_path})
            return fmt_error(f"載入失敗: {e}")

    @server.tool()
    def run_intake(
        directory: str = "data/rawdata",
        project_id: str | None = None,
    ) -> str:
        """執行完整收件流程（Phase 1 orchestration）。

        自動執行: 掃描目錄 → 格式檢查 (H-002) → 大小檢查 (H-001) → PII 初篩 (H-004)
        → 載入第一個可用的資料集 → 儲存 intake_report.json artifact。

        Args:
            directory: 原始資料目錄路徑
            project_id: 專案 ID（如已建立）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_result, log_tool_error,
            fmt_error, fmt_success, ensure_project_context,
        )
        from pathlib import Path
        from datetime import datetime

        log_tool_call("run_intake", {"directory": directory, "project_id": project_id})

        try:
            from rde.infrastructure.adapters import PandasLoader
            from rde.application.use_cases.discover_data import DiscoverDataUseCase
            from rde.domain.models.dataset import Dataset, DatasetMetadata
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult
            from rde.infrastructure.persistence.artifact_store import ArtifactStore

            if not Path(directory).exists():
                return fmt_error(f"目錄不存在: {directory}")

            # Step 1: Scan
            loader = PandasLoader()
            use_case = DiscoverDataUseCase(loader)
            files = use_case.execute(Path(directory))

            loadable_files = [f for f in files if f.is_loadable]
            rejected_files = [f for f in files if not f.is_loadable]

            if not loadable_files:
                rejection_details = "\n".join(
                    f"- {f.file_name}: {f.rejection_reason}" for f in rejected_files
                )
                return fmt_error(
                    f"目錄 `{directory}` 中沒有可載入的檔案。",
                    rejection_details if rejection_details else "",
                    "請確認檔案格式 (H-002) 與大小限制 (H-001)。",
                )

            # Step 2: Load first available file
            first_file = loadable_files[0]
            path = Path(first_file.file_path)
            metadata = DatasetMetadata(
                file_path=path,
                file_format=path.suffix.lstrip(".").lower(),
                file_size_bytes=path.stat().st_size,
            )
            dataset = Dataset(metadata=metadata)
            df, variables, row_count = loader.load(metadata)
            dataset.mark_loaded(variables, row_count)

            session = get_session()
            session.register_dataset(dataset, df)

            # Step 3: PII check (H-004)
            pii_vars = [v.name for v in variables if v.is_pii_suspect]

            # Step 4: Save intake artifact
            intake_report = {
                "directory": str(directory),
                "total_files": len(files),
                "loadable": len(loadable_files),
                "rejected": len(rejected_files),
                "loaded_file": first_file.file_name,
                "dataset_id": dataset.id,
                "row_count": row_count,
                "column_count": len(variables),
                "pii_suspects": pii_vars,
                "rejections": [
                    {"file": f.file_name, "reason": f.rejection_reason}
                    for f in rejected_files
                ],
                "timestamp": datetime.now().isoformat(),
            }

            # Save artifact if project exists
            ok, _, project = ensure_project_context(project_id)
            if ok:
                store = ArtifactStore(project.artifacts_dir)
                store.save(PipelinePhase.DATA_INTAKE, "intake_report.json", intake_report)

                pipeline = session.get_pipeline(project.id)
                pipeline.mark_started(PipelinePhase.DATA_INTAKE)
                pipeline.mark_completed(PhaseResult(
                    phase=PipelinePhase.DATA_INTAKE,
                    completed_at=datetime.now(),
                    success=True,
                    artifacts={"intake_report.json": ""},
                ))

            pii_warning = ""
            if pii_vars:
                pii_warning = (
                    f"\n⚠️ **[H-004] 疑似 PII:** {', '.join(pii_vars)}\n"
                )

            rejected_info = ""
            if rejected_files:
                rejected_info = "\n**被拒絕的檔案:**\n" + "\n".join(
                    f"- {f.file_name}: {f.rejection_reason}" for f in rejected_files
                )

            log_tool_result("run_intake", f"loaded {first_file.file_name}, {row_count} rows")

            return (
                f"✅ 收件流程完成 (Phase 1)\n\n"
                f"## 掃描結果\n"
                f"- **目錄:** `{directory}`\n"
                f"- **可載入:** {len(loadable_files)} / {len(files)} 個檔案\n\n"
                f"## 已載入\n"
                f"- **檔案:** {first_file.file_name}\n"
                f"- **資料集 ID:** `{dataset.id}`\n"
                f"- **列數:** {row_count:,}\n"
                f"- **變數數:** {len(variables)}\n"
                f"{pii_warning}{rejected_info}\n\n"
                f"**下一步:** 使用 `build_schema()` 建立 schema (Phase 2)。"
            )

        except Exception as e:
            log_tool_error("run_intake", e, {"directory": directory})
            return fmt_error(f"收件流程失敗: {e}")

    @server.tool()
    def build_schema(
        dataset_id: str | None = None,
        project_id: str | None = None,
    ) -> str:
        """建立完整 schema — 型別推論 + 變數分類 + 基礎統計（Phase 2 orchestration）。

        自動執行變數分類並儲存 schema.json artifact。

        Args:
            dataset_id: 資料集 ID（可選，預設使用第一個）
            project_id: 專案 ID（可選）
        """
        from rde.interface.mcp.tools._shared import (
            log_tool_call, log_tool_result, log_tool_error,
            fmt_error, fmt_table, ensure_dataset, ensure_project_context,
        )
        from datetime import datetime

        log_tool_call("build_schema", {"dataset_id": dataset_id})

        try:
            import pandas as pd
            from rde.application.session import get_session
            from rde.application.pipeline import PipelinePhase, PhaseResult
            from rde.infrastructure.persistence.artifact_store import ArtifactStore
            from rde.domain.services.variable_classifier import VariableClassifier

            ok, msg, entry = ensure_dataset(dataset_id)
            if not ok:
                return fmt_error(msg)

            ds = entry.dataset
            df = entry.dataframe

            # ── Phase 2: Re-classify variables with sample_values ───
            # Phase 1 classification was fast (dtype-only).
            # Phase 2 does DEEP inference using actual sample values.
            classifier = VariableClassifier()
            reclassified: list[str] = []

            for i, v in enumerate(ds.variables):
                if v.name not in df.columns:
                    continue
                col = df[v.name]
                samples = col.dropna().head(20).tolist()

                new_var = classifier.classify(
                    name=v.name,
                    dtype=str(col.dtype),
                    n_unique=int(col.nunique()),
                    n_total=len(df),
                    sample_values=samples,
                )
                new_var.n_missing = int(col.isna().sum())
                new_var.role = v.role  # preserve user-set role

                if new_var.variable_type != v.variable_type:
                    reclassified.append(
                        f"{v.name}: {v.variable_type.value} → {new_var.variable_type.value}"
                    )
                ds.variables[i] = new_var

            # ── Build schema with basic descriptive stats ───────────
            schema: dict = {
                "dataset_id": ds.id,
                "row_count": ds.row_count,
                "column_count": len(ds.variables),
                "variables": [],
                "created_at": datetime.now().isoformat(),
            }

            headers = ["變數", "dtype", "類型", "缺失率", "唯一值", "PII"]
            rows = []
            for v in ds.variables:
                missing_rate = round(v.n_missing / ds.row_count, 4) if ds.row_count > 0 else 0
                var_info: dict = {
                    "name": v.name,
                    "dtype": v.dtype,
                    "variable_type": v.variable_type.value,
                    "role": v.role.value,
                    "n_missing": v.n_missing,
                    "missing_rate": missing_rate,
                    "n_unique": v.n_unique,
                    "is_pii_suspect": v.is_pii_suspect,
                }

                # Add descriptive stats for numeric variables
                if v.name in df.columns and pd.api.types.is_numeric_dtype(df[v.name]):
                    desc = df[v.name].describe()
                    var_info["stats"] = {
                        "mean": round(float(desc.get("mean", 0)), 4),
                        "std": round(float(desc.get("std", 0)), 4),
                        "min": float(desc.get("min", 0)),
                        "max": float(desc.get("max", 0)),
                        "median": float(desc.get("50%", 0)),
                    }

                schema["variables"].append(var_info)
                pii_flag = "⚠️" if v.is_pii_suspect else ""
                rows.append([
                    v.name, v.dtype, v.variable_type.value,
                    f"{missing_rate:.1%}", v.n_unique, pii_flag,
                ])

            table = fmt_table(headers, rows)

            # Save artifact if project exists
            ok_p, _, project = ensure_project_context(project_id)
            if ok_p:
                session = get_session()
                store = ArtifactStore(project.artifacts_dir)
                store.save(PipelinePhase.SCHEMA_REGISTRY, "schema.json", schema)

                pipeline = session.get_pipeline(project.id)
                pipeline.mark_started(PipelinePhase.SCHEMA_REGISTRY)
                pipeline.mark_completed(PhaseResult(
                    phase=PipelinePhase.SCHEMA_REGISTRY,
                    completed_at=datetime.now(),
                    success=True,
                    artifacts={"schema.json": ""},
                ))

            log_tool_result("build_schema", f"{len(ds.variables)} variables, {len(reclassified)} reclassified")

            reclass_info = ""
            if reclassified:
                reclass_info = (
                    "\n### 🔄 重新分類的變數\n"
                    + "\n".join(f"- {r}" for r in reclassified)
                    + "\n"
                )

            return (
                f"✅ Schema 建立完成 (Phase 2)\n\n"
                f"- **資料集:** `{ds.id}`\n"
                f"- **列數:** {ds.row_count:,}\n"
                f"- **變數數:** {len(ds.variables)}\n"
                f"- **重新分類:** {len(reclassified)} 個\n"
                f"{reclass_info}\n"
                f"{table}\n\n"
                f"**下一步:** 使用 `profile_dataset()` 產生完整 profiling，"
                f"或 `align_concept()` 進行概念對齊 (Phase 3)。"
            )

        except Exception as e:
            log_tool_error("build_schema", e)
            return fmt_error(f"Schema 建立失敗: {e}")
