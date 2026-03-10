# Active Context

## Current Goals

- 將 governance hardening 變更完整落盤到文件、memory bank、git 與 GitHub 交付
- 維持 agent-control manifest、測試、文件三者一致

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
- agent-control.yaml 成為可執行控制契約
- Phase 3/4 明確 confirm gate 與 Phase 5 成功狀態 gate 已由測試覆蓋
- H-004 改為預設阻擋載入，僅 allow_pii=true 可 override
- Phase 6 decision/deviation log 路徑統一到 artifacts/phase_06_execute_exploration/
- Phase 6 自動 plan adherence 檢查與 deviation auto-log (S-011)
- 全 repo pytest 通過，現為 24 tests

## Known Issues

- SessionRegistry 無持久化（服務重啟丟失狀態）
- GitHub label / PR metadata 仍取決於本機 gh 認證與 repo 權限

## Current Blockers

- None critical