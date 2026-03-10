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
- [x] Governance hardening 第 1 批: confirm gate、Phase 5 成功 gate、PII default-block、decision log 路徑校正
- [x] Governance hardening 第 2 批: 文件與 report contract 對齊現況
- [x] Governance hardening 第 3 批: smoke tests 遷移為 pytest integration/enforcement tests
- [x] Governance hardening 第 4 批: `.github/agent-control.yaml` machine-readable manifest
- [x] Governance hardening 第 5 批: MCP tool schema/docstring 補強、Phase 4 analyses 驗證、Phase 6 plan adherence auto-log、artifact gate hook 修正
- [x] Governance regression tests: 24 passed (`python3 -m pytest -q`)

## Doing

- [ ] 文件 / memory / git / GitHub 交付收尾

## Next

- [ ] 視需要補 pre-commit 實跑驗證
- [ ] Multi-file/multi-sheet 支援
- [ ] SessionRegistry 持久化