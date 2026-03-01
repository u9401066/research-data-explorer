# Progress

## Done

- [x] Initialize project — DDD 4-layer + 11-Phase pipeline 設計
- [x] Domain layer — models, services, policies, events, ports
- [x] Application layer — use cases, pipeline FSM, DTOs, decision logger
- [x] Infrastructure layer — pandas loader, scipy engine, matplotlib viz, artifact store
- [x] Interface layer — MCP server + 7 tool files (28 tools)
- [x] Governing docs — SPEC v0.2.0, AGENTS.md, CONSTITUTION.md
- [x] P1 Refactor: analyze_variable → AnalyzeVariableUseCase
- [x] P2 Refactor: CollinearityChecker domain service (S-007)
- [x] P3 Refactor: profiling fallback 簡化
- [x] P4 Refactor: correlation_matrix 使用 fmt_table
- [x] Architecture audit — RDE vs automl-stat-mcp 能力盤點
- [x] Schema diagnosis — build_schema 問題分析
- [x] DocxExporter adapter (python-docx + xhtml2pdf)
- [x] ExportReportUseCase
- [x] export_report MCP tool
- [x] DocumentExporterPort (domain port)

## Doing

- [ ] xhtml2pdf 安裝至正確 venv
- [ ] 文件更新 + 分段 git commit + push

## Next

- [ ] Schema enhancement (VariableClassifier 深度推論、multi-file/multi-sheet)
- [ ] AutomlGateway API endpoint 修復 (對齊 automl-stat-mcp 實際 API)
- [ ] execute_cleaning 實作
- [ ] 進階統計委派 (ROC、survival、PSM)
- [ ] End-to-end smoke test for export pipeline