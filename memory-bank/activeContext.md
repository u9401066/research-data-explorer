# Active Context

## Current Goals

- 完成 xhtml2pdf 安裝至 venv 並驗證 PDF export
- 分段 git commit + push
- 更新所有文件（memory-bank、AGENTS.md）

## Recently Completed

- P1-P4 refactoring (analyze_variable UseCase, CollinearityChecker, fmt_table)
- DocxExporter adapter (python-docx + xhtml2pdf)
- ExportReportUseCase
- export_report MCP tool (#28)
- DocumentExporterPort domain port
- 28 MCP tools 全數註冊通過

## Known Issues

- xhtml2pdf 未安裝至 .venv（上次誤裝到 conda base）
- AutomlGateway API endpoints 與 automl-stat-mcp 實際 API 不匹配（dead code）
- build_schema 目前只複製 Phase 1 結果，需深度重構
- VariableClassifier 未使用 sample_values 做推論

## Current Blockers

- None critical