# Progress (Updated: 2026-05-08)

## MEM+ 2026-05-08

- [x] v0.4.12 release package prepared: artifact-backed phase resume, audit diagnostics, local-lite no-Docker fallback hardening, Windows ANSI-safe JSON/JSONL artifacts, full-yolo MCP runner, and README/i18n alignment.
- [x] v0.4.12 real-file governed MCP validation passed with audit grade A, 130/130, `report_readiness=production_ready`, `core_goal_audit=9/9`, publication bundle met, and 23 decision-log entries.
- [x] v0.4.12 cross-platform entrypoint checks passed locally: VSIX helper tests, Codex MCP config/UTF-8/path coverage, MCP tool inventory smoke, and Quick Explore smoke.
- [x] Codex MCP support added: config writer, external stdio smoke runner, Codex skill/AGENTS setup docs, and live config update for `~/.codex/config.toml`.
- [x] Quick Explore backend mode added through `init_project(mode="quick_explore")`, with UX harness artifacts auto-bootstrapped at Phase 0.
- [x] Phase 10 report path fixed: `assemble_report()` no longer fails on stale undefined output variables.
- [x] UX harness readiness hardened: no-code and agent-friendly core goals now require approval card, dashboard, artifact index, and blocker playbook evidence.
- [x] Codex/RDE validation passed: `codex_rde_smoke.py --list-tools-only`, `codex_rde_smoke.py`, and full `python -m pytest -q` = 210 passed, 5 skipped.

## MEM+ 2026-05-07

- [x] v0.4.8 hotfix prepared: no-active-project guidance now points to `init_project()`, and `/pipeline` exposes Phase 0-7 bootstrap tools.
- [x] v0.4.9 hotfix prepared: `align_concept()` recovers auditable Phase 0-2 project context from orphan session datasets.
- [x] v0.4.10 hardening prepared: recovery requires intake/schema provenance, ambiguous multi-dataset recovery is blocked, Phase 3/4 confirmation reload drift is fixed, legacy locked-plan reload is preserved, and VSIX partial MCP tool lists missing `init_project` are blocked.
- [x] Harness Contract Hardening: plan/readiness gates now protect branch/autoresearch execution from drift and quick-explore bypass.
- [x] Autoresearch Durable Runner: queue, budget, resume/status, next-task, drain-runner, failure thresholds, expired lease reclaim, and lifecycle decision logging.
- [x] UX Harness: approval card, dashboard, artifact index, blocker playbook, and VSIX dashboard command.
- [x] Phase 4 docs/tool sync: two-step draft then confirm contract is reflected in manifest, prompts, docs, and regression tests.
- [x] Release verification: Python tests, VSIX tests, bundled asset sync, and whitespace checks passed for v0.4.10 after final subagent review follow-up.
- [x] Release metadata prepared for branch push and `v0.4.10` tag publication.
- [x] v0.4.11 hardening prepared: full MCP tool-surface manifest, VSIX command-filter drift fix, true Phase 4 draft-confirm gate, UX bootstrap approval card, clinical planner inference, local-lite figure fallback, report-safe visualization promotion, Windows UTF-8 hook hardening, and vendor CSV/JSON encoding fallback.
- [x] v0.4.11 verification: `python -m pytest -q` = 205 passed, 5 skipped; VSIX `npm.cmd test` = 33 passed; `git diff --check` passed; release consistency hook passed.

## MEM+ 2026-05-06

- [x] Canonical 13-phase contract aligned across manifest, MCP runtime, tests, prompts, VSIX assets, AGENTS, SPEC, and memory docs.
- [x] Phase 4/5/6 planning now emits separate greedy blueprint, methodology review, and locked plan artifacts.
- [x] VSIX setup now scaffolds Copilot, Codex, and Cline harness assets.
- [x] Runtime hardening added value-level PII detection, project-bound dataset rehydrate, Phase 4/5 readiness gates, Shapiro-Wilk preview, and Phase 5 methodology-review based report readiness.
- [x] Superseded stale 0.4.5 release todo; current release target is v0.4.12.

## Done

- 新增 `propose_analysis_plan()` MCP tool，作為 Phase 4 greedy autonomous EDA layer
- 新增 AutonomousEDAPlanner domain service 與 ProposeAnalysisPlanUseCase
- 將 greedy plan ideation 接入 extension tool allowlist、strict agent prompt、workflow skill、README 與 agent-control manifest
- 新增 autonomous planner tests，並驗證全 repo pytest 通過（57 passed, 4 skipped）
- 在 AutonomousEDAPlanner 內加入 methodology review / repair stage，輸出 review metadata 與 repair actions
- `register_analysis_plan()` 現在會先用 reviewed blueprint 自動補入 optional exploratory branches，補完後仍太薄才需要 `allow_methodology_override=true`
- `propose_analysis_plan()` / `register_analysis_plan()` 現在都會保存 execution schedule artifact，讓 Phase 6 依 reviewed blueprint 排序
- 新增 autonomous EDA benchmark regression 測試，量化 reviewed plan 對 coverage 與分析數的保留
- collect_results / audit 改為只以 required analyses 計算 plan coverage，避免 exploratory extension 造成假性 coverage 下降
- 全 repo pytest 再驗證通過（63 passed, 3 skipped）

## Doing

- Prepare segmented git commits, push branch, and publish `v0.4.12` tag.

- 整理 soft-budget expansion / execution schedule 後的最終文件與 memory bank 狀態

## Next

- After release, add dedicated vendor roundtrip tests for utf-8-sig, cp950/big5, utf-16 with/without BOM, and malformed-byte fallback behavior.
- Consider adding a small hook-state archive regression harness for the PowerShell scripts.

- 評估是否要讓 `propose_analysis_plan()` 進一步讀取 raw profiling 統計，而不只依賴 schema/roles heuristics
- 若要更激進的 autonomous EDA，可考慮把 execution schedule 進一步接成真正的 blueprint → execute orchestrator，而不只是一份 artifact
- 可考慮將 methodology review 的分數與 shadow benchmark 指標存成 artifact，做版本間比較
