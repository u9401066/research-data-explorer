# RDE Product Doctrine

## 目標使用者

RDE 是給非資料科學家使用的 agent harness。使用者可以提供真實資料集，但可能不知道：

1. 要跑哪些分析
2. 怎樣把描述、比較、關聯、模型、敏感度分析組合起來
3. 怎樣寫可重現的分析程式

因此 RDE 的核心不是「自動猜一份摘要」，而是讓 Copilot、Codex、Cline 這類 agent 在可審計的工具流程內完成完整報告。

## 核心工作

Agent 必須完成五件事：

1. 了解資料：`run_intake`、`build_schema`、`profile_dataset`、`assess_quality`、PII / format / size checks
2. 規劃分析：`align_concept`、`propose_analysis_plan`、`register_analysis_plan`
3. 可重現探索：locked plan、artifact gates、`decision_log.jsonl`、`deviation_log.jsonl`
4. 分析與解釋：Phase 8 tools、local-lite advanced analysis、optional automl-stat-mcp delegation
5. 報告產出：`collect_results`、`assemble_report`、`run_audit`、`auto_improve`、`export_report`、`export_handoff`

## 13 Phase 是否足夠

13 phase 作為 macro workflow 是足夠的，因為它把資料收件、schema、概念對齊、創意發想、計畫審查、計畫鎖定、readiness、執行、彙整、報告、audit、改善、handoff 分開治理。

不足的不是 phase 數量，而是每個 phase 是否產生可檢查 artifact，以及 final readiness 是否回頭確認核心產品目標。因此 RDE 另外加入 cross-phase `core_goal_audit`，讓 13 phase 之外的核心目標也成為硬契約。

## Readiness Contract

`report_readiness.core_goal_audit` 檢查：

- `data_understanding`
- `analysis_planning`
- `data_correctness`
- `reproducible_exploration`
- `analysis_execution_interpretation`
- `analysis_completeness`
- `report_generation`
- `no_code_operation`
- `agent_friendly_harness`

缺少任何核心項目時，`missing_requirements` 會出現 `core_goal:*`，`assemble_report` / `export_report` 預設不能把結果視為 production-ready。

## automl-stat-mcp Positioning

VSIX 的核心路徑必須是 local-first。非工程師不應該被要求安裝 Docker 或啟動額外 MCP 才能完成完整報告。

RDE 在 automl-stat-mcp 不可用時使用 local-lite fallback：

- logistic regression
- multiple regression / GLM
- ROC/AUC
- basic power analysis
- Kaplan-Meier summary
- Cox regression when feasible
- lightweight propensity scoring

automl-stat-mcp 保留為可選重型引擎，用於 full propensity matching/weighting、進階 survival workflow、AutoML training 等 vendor workflow。

## Agent Coverage

- Copilot: `.github/copilot-instructions.md`、`.github/agents`、`.github/prompts`
- Codex: `AGENTS.md`、`.codex/skills`
- Cline: `.clinerules`、`.clinerules/workflows`

所有 agent 都應以 `.github/agent-control.yaml` 為主要控制契約，並在回覆中引用具體 artifacts。

## Subagent / Hook / Workflow Design

Subagents 可以用來平行處理資料理解、方法審查、報告審查、平台/VSIX 檢查等獨立工作，但不能繞過 MCP tool contract。所有最後可採信的決策仍必須落在 project-scoped artifacts、`decision_log.jsonl`、`deviation_log.jsonl`、`report_readiness` 與 `audit_report.json`。

Rules、hooks、workflow、instructions 的分工如下：

- `.github/agent-control.yaml`: machine-readable phase gates、override flags、delegation、core goal contract
- `AGENTS.md` / Copilot / Codex / Cline instructions: agent-facing operating contract
- custom hooks: log integrity、PII scan、artifact gate、report sanitization
- MCP tools: 真正執行與寫入 artifacts 的控制面
- tests: regression contract，確保 readiness、delegation、report formatting 不回退

## Multi-Platform VSIX Principle

Windows、macOS、Linux 都應走同一個 local-first VSIX 原則：

- 先啟動 bundled RDE MCP
- 不要求 Docker 才能完成核心報告
- uv / Python path 自動偵測
- automl-stat-mcp 僅在使用者或工程團隊已配置時作為 optional endpoint
- 所有輸出路徑使用 project-scoped artifacts / figures，避免全域共享狀態
