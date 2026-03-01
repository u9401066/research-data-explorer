# Progress

## Done

- [x] Initialize project — DDD 4-layer + 11-Phase pipeline 設計
- [x] Domain layer — models, services, policies, events, ports
- [x] Application layer — use cases, pipeline FSM, DTOs, decision logger
- [x] Infrastructure layer — pandas loader, scipy engine, matplotlib viz, artifact store
- [x] Interface layer — MCP server + 7 tool files (29 tools)
- [x] Governing docs — SPEC v0.2.0, AGENTS.md, CONSTITUTION.md
- [x] P1-P4 Refactor (analyze_variable, CollinearityChecker, profiling, fmt_table)
- [x] Architecture audit — RDE vs automl-stat-mcp 能力盤點
- [x] DocxExporter adapter (python-docx + xhtml2pdf)
- [x] ExportReportUseCase + export_report MCP tool
- [x] DocumentExporterPort (domain port)
- [x] VariableClassifier 深度推論 (sample_values → datetime/numeric_string/ID)
- [x] build_schema Phase 2 重新分類 + 描述統計
- [x] AutomlGateway 重寫 (stats:8003, automl:8001, 取代舊 /api/projects)
- [x] AutomlGatewayPort 擴展 (7 abstract methods)
- [x] xhtml2pdf 安裝至 .venv

## Doing

- [ ] 文件更新 + git commit + push

## Next

- [ ] End-to-end smoke test for export pipeline
- [ ] Multi-file/multi-sheet 支援
- [ ] SessionRegistry 持久化