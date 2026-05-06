# Active Context

## MEM+ 2026-05-06

- Canonical pipeline is 13 phases. Keep the public phase count stable; use phase-local artifacts for finer granularity.
- Phase 4/5/6 are distinct: creative ideation, plan completeness review, and locked plan registration.
- Decision/deviation logs are Phase 8 artifacts under `artifacts/phase_08_execute_exploration/`.
- VSIX setup must cover Copilot (`.github`), Codex (`AGENTS.md` + `.codex/skills`), and Cline (`.clinerules`) without overwriting existing files.
- H-004 PII detection now includes value-level email/phone/SSN-style patterns in addition to column names.
- Project-bound datasets can be rehydrated from `intake_report.json` after MCP session reset.
- Phase 7 readiness must check Phase 4/5 artifacts and provide Shapiro-Wilk normality previews.

## Current Goals

- 將 autonomous EDA 的 greedy plan ideation 正式整合進受治理 workflow
- 維持 agent-control manifest、tool policy、prompt、README 與測試一致
- 讓 agent 能先自主展開候選分析，再進入 Phase 4 plan lock

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
- Phase 8 decision/deviation log 路徑統一到 artifacts/phase_08_execute_exploration/
- Phase 8 自動 plan adherence 檢查與 deviation auto-log (S-011)
- 全 repo pytest 通過，現為 24 tests
- repo 與 VS Code extension 版本同步檢查已接入 pre-commit
- CHANGELOG.md 已建立，0.1.0 與 Unreleased 區段已就位
- 內部測試資料經超音波施打動脈導管收案總表V3xlsx.xlsx 已加入 gitignore 與 release guard 阻擋
- 全 repo pytest 通過，現為 49 passed, 3 skipped
- pre-commit 全綠，包含新的 release consistency hook
- `propose_analysis_plan()` 已落地為正式 MCP tool，對應 Phase 4 creative ideation
- 新增 deterministic greedy AutonomousEDAPlanner domain service + ProposeAnalysisPlanUseCase
- extension allowlist、strict eda prompt、README、skills、agent-control 已同步接受 greedy plan ideation
- 全 repo pytest 通過，現為 57 passed, 4 skipped
- Phase 5 現在包含 deterministic methodology review + repair，不再只是 draft greedy 排序
- Phase 4 現在會輸出 greedy execution schedule，供 Phase 8 排序使用
- Phase 4/5 的 methodology review 改為 soft-budget expansion 優先，不先為了守住舊 budget 砍掉新 EDA 分支
- Phase 5 `register_analysis_plan()` 會先自動補入 optional exploratory branches；補完後仍 under-scoped 才要求 override
- collect_results / audit 的 plan coverage 只計 required analyses，不用 exploratory extension 懲罰 coverage
- 全 repo pytest 通過，現為 63 passed, 3 skipped

## Known Issues

- SessionRegistry 無持久化（服務重啟丟失狀態）
- GitHub label / PR metadata 仍取決於本機 gh 認證與 repo 權限

## Current Blockers

- None critical
- AGENTS.md 仍有既有 markdownlint 噪音，但不影響 pytest / docs sync / MCP workflow
