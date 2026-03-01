# Active Context

## Current Goals

- End-to-end smoke test for export pipeline
- 清理與增強步驟驗證

## Recently Completed

- P1-P4 refactoring (analyze_variable UseCase, CollinearityChecker, fmt_table)
- DocxExporter adapter (python-docx + xhtml2pdf)
- ExportReportUseCase + export_report MCP tool
- DocumentExporterPort domain port
- VariableClassifier 深度推論 (sample_values: datetime/numeric_string/ID by name)
- build_schema Phase 2 重新分類 + 描述統計
- AutomlGateway 重寫對齊實際 API (stats-service:8003 + automl-service:8001)
- AutomlGatewayPort 擴展 (direct_analyze, propensity, survival, roc, power, automl)
- xhtml2pdf 安裝至 .venv
- 29 MCP tools 全數註冊通過

## Known Issues

- SessionRegistry 無持久化（服務重啟丟失狀態）
- Export pipeline 尚未 end-to-end 測試

## Current Blockers

- None critical