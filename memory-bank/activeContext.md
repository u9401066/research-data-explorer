# Active Context

## MEM+ 2026-07-15

- Robotic VATS timed-NRS review exposed three reusable RDE defects: paired tests independently dropped each column and could mis-pair subjects, Phase 12 used CRBD-only heading allowlists that discarded unrelated report sections, and Table 1 export treated Markdown separator rows as observations.
- Paired t/Wilcoxon now use row-aligned complete pairs. `run_repeated_measures` supports two-timepoint Wilcoxon and 3+ timepoint Friedman analyses, persists JSON/Markdown case-set ledgers, and reports complete versus pairwise post-hoc denominators explicitly.
- Missingness screening now says MCAR is not rejected rather than proven, carries the registered missing strategy into readiness/report text, and warns that time-dependent availability and MNAR remain unresolved by the heuristic.
- Missingness screening now also tests availability by locked-plan group variables. Timed-NRS readiness detects PcaGroup-dependent 24 h and paired-change availability, classifies the pattern as MAR-compatible, and still does not exclude MNAR.
- Paired figure annotations now use the same tie-aware SciPy Wilcoxon implementation as the formal analysis. Manifest upserts remove stale rows for the same physical figure path, and report assembly selects only the newest durable repeated-measures artifact per variable set.
- Phase 10 regeneration preserves analyst-authored supplemental sections with a SHA-256 manifest; Phase 12 preserves every generic/project-specific section. Table 1 parser drops Markdown separator rows.
- Real project `d271e173` was rerun through registered RDE tools: rest/movement each had 69 row-aligned 24–48 h pairs and 22 exclusions; tie-aware Wilcoxon p=0.148929 (rest) and p=0.005089 (movement). The final report contains 23 unique figures, audit remained A (165/165), and the append-only audit trail passed with 54 decisions and 11 deviations.
- Asset-Aware validation of regenerated DOCX outputs: ingest integrity PASS, 23/23 media, table 100%, text/structure/style 100%; round-trip scores 99.1% (Phase 10) and 99.8% (Phase 12), with only nonsemantic bold-run differences remaining.

## MEM+ 2026-07-01

- Loop-engineering P0 shipped: raised the local logistic/regression fast-path thresholds (rows 200 -> 50000, columns 8 -> 15) so real-world models use `statsmodels.Logit` with p-values and now odds-ratio 95% CIs instead of the silent numpy ridge fallback.
- Closed the Readiness->Queue autonomous loop: derived-variable provenance branches are prioritized to the front of the common medical EDA suggestions so a budget-truncated autoresearch run cannot starve the branch that satisfies the `derived_variable_provenance` readiness requirement.
- Root-cause insight: `common_medical_eda_pack` already generated the `dominant_vs_other` provenance branch; the open loop was that readiness gaps never influenced autoresearch execution priority, so a late-ordered branch was dropped once the task budget truncated the queue.
- Verification: `.venv\Scripts\python.exe -m pytest -q` = 257 passed, 5 skipped; added unit prioritization and end-to-end tight-budget loop-integrity tests.
- Cleanup candidate: `branch_tools._build_branch_suggestions` early-returns to the pack service, leaving its older in-file `is_multilevel_treatment_var` derived-branch path as dead code.

## MEM+ 2026-05-12

- v0.4.14 release focus: VSIX multi-platform CI/runtime hardening so installs are guarded on Ubuntu, Windows, macOS Intel, and macOS Apple Silicon before publishing.
- Latest v0.4.14 local verification: Node 20 extension tests passed (40 tests), bundled-tool install smoke passed, VSIX package produced successfully, package validation passed, workflow YAML parsed, and `git diff --check` passed.
- v0.4.13 release focus: multi-workbook/multi-sheet analysis coverage, scoped Phase 7 readiness, structured figure interpretation, formal report export reliability, and scheduled Phase 8 plan-adherence checks.
- KMU SPARK AKI governed rerun completed on project `d626d6d9`: two Excel workbooks / 19 worksheets were classified as main analysis, derived merge, QC/context, or excluded context before Phase 6 lock.
- New derived master for the rerun is 50 rows x 118 columns; Phase 8 produced 43 analyses, 27 figures, Table 1, repeated-measures tests, adjusted regressions, and propensity/balance diagnostics.
- Phase 10/12 DOCX/PDF exports were regenerated and verified locally; report package includes embedded media and `figure_interpretation_harness.json` with 27 structured figure interpretation entries.
- PubMed Search MCP context was added as `pubmed_literature_context.md` to keep discussion anchored to perioperative AKI, urinary biomarkers, and hypotension literature.
- Code hardening added raw workbook/sheet coverage readiness, locked-plan/role scoped readiness, and execution-schedule-aware plan adherence.
- Latest verification for v0.4.13: `.venv\Scripts\python.exe -m pytest -q` = 254 passed, 5 skipped; `.venv\Scripts\python.exe -m ruff check .` = all checks passed; RDE audit grade A, 165/165.
- Post-release VSIX multi-platform audit found the practical gap was CI/runtime evidence rather than package metadata: CI now has Ubuntu/Windows/macOS Intel/macOS Apple Silicon VSIX smoke jobs, MCP subprocess env preserves PATH/HOME/TEMP platform variables, validation dispatches to the native platform script, and `docs/vsix_multiplatform_audit_20260512.md` records the MedPaper comparison.

## MEM+ 2026-05-08

- v0.4.12 release focus: artifact-backed MCP phase resume, audit diagnostic path, no-Docker local-lite performance/fallback hardening, Windows ANSI-safe JSON/JSONL artifacts, full-yolo Codex/RDE runner, i18n README alignment, and release verification evidence.
- Full governed real-file Codex/RDE smoke passed through MCP with no Docker dependency: audit grade A, 130/130, `report_readiness=production_ready`, `core_goal_audit=9/9`, publication bundle met, 23 decision-log entries, and 100% plan adherence.
- Cross-platform entrypoint confidence was rechecked locally through VSIX helper tests, Codex MCP config upsert coverage, UTF-8 env assertions, MCP tool inventory smoke, and Quick Explore MCP smoke.
- Codex/RDE support is now explicit: `scripts/configure_codex_mcp.py --apply` writes the `research-data-explorer` MCP server block to `~/.codex/config.toml`, and `scripts/codex_rde_smoke.py` verifies a real stdio subprocess can list tools and run Quick Explore to Phase 10.
- `init_project(mode="quick_explore")` now marks the pipeline as Quick Explore and bootstraps approval card, harness dashboard, artifact index, and blocker playbook artifacts at Phase 0.
- `assemble_report()` Phase 10 NameError was fixed; Quick Explore can assemble `Quick Explore -- Not Audited` reports with `allow_incomplete=true`.
- Report readiness now requires the UX harness bundle for `core_goal:no_code_operation` and `core_goal:agent_friendly_harness`, so friendly-agent support cannot be claimed without artifacts.
- Agent-facing docs now explain Codex MCP setup and enforce the Phase 4 `propose_analysis_plan(confirm=false)` review before `confirm=true` contract.
- Latest focused verification for v0.4.12: full-yolo real Excel MCP smoke passed; `python scripts/codex_rde_smoke.py --list-tools-only` exposed 49 tools; Quick Explore smoke produced a Phase 10 report; focused Python regression suite passed; VSIX helper tests and compile passed.

## MEM+ 2026-05-07

- v0.4.7 release focus: harness contract hardening, autoresearch durable runner, and no-code UX harness.
- v0.4.8 hotfix focus: repair VSIX/RDE project bootstrap drift so Phase 3 cannot strand users without `init_project()`.
- v0.4.9 hotfix focus: recover project context from session-only intake/schema flows when client tool cache omits `init_project`.
- v0.4.10 hardening focus: subagent review follow-up for recovery provenance, confirmation reload drift, multi-dataset ambiguity, and VSIX partial MCP tool lists.
- v0.4.11 release focus: MCP tool-surface drift prevention, true Phase 4 draft confirmation, clinical heuristic planning, local-lite figure fallback, Windows UTF-8 resilience, and report-safe artifact promotion.
- Recovery now requires real `run_intake()` provenance plus `build_schema()` tags before Phase 3 can auto-create an auditable project.
- Explicit `confirm=false` for Phase 3/4 remains blocked after MCP session reload; legacy locked-plan projects remain resumable for backwards compatibility.
- Legacy project JSON with `plan_locked=true` remains authoritative when old `analysis_plan.yaml` lacks a `locked` field; an explicit `locked:false` artifact still overrides it.
- VSIX chat guard now blocks incomplete RDE MCP tool lists missing `init_project` instead of letting the agent enter a half-registered workflow.
- Phase 8 branch/autoresearch is governed-only: a confirmed locked plan plus readiness pass are required before execution.
- Autoresearch can run overnight-style branch queues with budget, resume/status, failure budget, lease reclaim, and lifecycle decision logs; promotion remains behind audit/user gates.
- UX harness now includes approval card, dashboard status, artifact index, and blocker playbook. Webview previews redact local absolute paths.
- Phase 4 confirmation contract is enforced in code: direct `propose_analysis_plan(confirm=true)` is blocked unless an existing unconfirmed draft exists; confirmation preserves the reviewed blueprint instead of regenerating it.
- VSIX missing-bootstrap detection now checks the full live RDE MCP surface before command filtering, so `/explore` does not falsely fail when the server is complete.
- Local-lite analysis now emits fallback figures and report manifests when Docker/AutoML is offline; report assembly ignores stale, escaped, or missing figure paths.
- Windows hooks force UTF-8 input/output and archive transient state instead of deleting it; release guard reads staged paths with `core.quotepath=false` and NUL separation.
- Latest verification before v0.4.11 release metadata: `python -m pytest -q` = 205 passed, 5 skipped; VSIX `npm.cmd test` = 33 passed; `git diff --check` and `python scripts/hooks/check_release_consistency.py` passed.

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
