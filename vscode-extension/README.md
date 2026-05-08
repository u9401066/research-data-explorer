# Research Data Explorer — VS Code Extension

Governed research data exploration assistant with MCP tools, prompts, and skills.

This extension is not a universal statistical autopilot. It is best viewed as a governed workflow layer:

- standard analysis families can run through the built-in MCP workflow
- specialized methods may still require manual analysis or custom integration
- if you only want generic automatic analysis summaries, other general-purpose auto-analysis tools may be a better fit
- the main value here is auditability, plan lock, reproducibility, and handoff packaging

## Core Product Contract

The VSIX path is local-first for non-data-scientists. A user should be able to install the extension, point an agent at a new real dataset, and get a governed report without installing Docker or writing analysis code.

RDE therefore treats automl-stat-mcp as optional. The built-in MCP server can complete the core workflow with local statistics, local-lite adjusted models, ROC/AUC, basic power analysis, Kaplan-Meier summaries, and lightweight propensity scoring. Docker-backed automl-stat-mcp remains useful for heavier vendor workflows such as full matching/weighting, deeper survival methods, and AutoML training.

`report_readiness` and `run_audit` explicitly check the core goal: data understanding, analysis planning, data correctness, reproducible exploration, analysis execution and interpretation, report generation, no-code operation, and agent-friendly harness artifacts.

## Documentation / i18n

- Repository overview: [../README.md](../README.md)
- Traditional Chinese overview: [../README.zh-TW.md](../README.zh-TW.md)
- Agent contract: [../AGENTS.md](../AGENTS.md)
- Extension guide: this file

Keep these documents aligned when changing phase gates, Codex MCP setup, no-Docker behavior, release validation evidence, or supported-platform expectations.

## Features

- 🔍 **13-Phase Auditable EDA Pipeline** — 結構化、可審計的探索性資料分析
- 📊 **49 MCP Tools** — 資料載入、greedy plan ideation、YOLO exploration branches、UX harness、描述統計、分組比較、Table 1、進階分析
- 🧪 **local-lite + optional automl-stat-mcp** — no-Docker adjusted models / ROC / power, with optional heavy delegation
- 📄 **報告匯出** — Word/PDF 匯出
- 🔒 **品質把關** — Hard Constraints (H-001~H-010) + Soft Constraints (S-001~S-012)
- 💬 **Chat Participant** — @rde 自然語言互動

## Installation

### From VSIX

```bash
code --install-extension <downloaded-vsix-file>
```

Or in VS Code: `Ctrl+Shift+P` → `Extensions: Install from VSIX...`

### Marketplace Publishing

- Visual Studio Marketplace publish uses `VSCE_PAT`.
- Open VSX publish uses `OVSX_PAT`.
- Tagging `v*` now triggers the publish workflow in `.github/workflows/publish-extension.yml`.
- You can also run the workflow manually with `workflow_dispatch` to publish one or both targets.

## Requirements

- VS Code 1.100.0 or higher
- GitHub Copilot (for Agent Mode)
- Python 3.11+ with `uv` (recommended)

### Supported Platforms

| 平台 | 狀態 | 備註 |
| ------ | ------ | ------ |
| Windows (x64) | ✅ | PowerShell 5.1+ |
| macOS (Intel/Apple Silicon) | ✅ | Homebrew uv 自動偵測 |
| Linux (x64) | ✅ | snap/apt uv 支援 |

The 0.4.12 release re-verified the Windows VSIX/Codex path locally and keeps the setup code on Node `path`, Python `pathlib`, UTF-8 environment variables, and ASCII-escaped JSON/JSONL artifacts. Full Linux/macOS confidence should come from the CI matrix, but the extension no longer uses Windows-only path assembly for Codex MCP configuration.

## MCP Installation Behavior

- RDE source workspaces run the local project directly via `uv run python -m rde`.
- Packaged VSIX builds ship a bundled Python project and run it via `uv run --project ... python -m rde`.
- No Python package registry publication is required for the MCP server to start.
- If the workspace already has a `.vscode/mcp.json` defining `rde`, the extension skips auto-registration.
- uv 會自動偵測多個可能路徑（`~/.local/bin`, `~/.cargo/bin`, `%LOCALAPPDATA%\uv\bin`, `/opt/homebrew/bin`）。

## Release Validation Snapshot

For 0.4.12, the extension-facing path was checked with:

```bash
npm test -- extensionHelpers.test.ts
npm run compile
python scripts/codex_rde_smoke.py --list-tools-only
python scripts/codex_rde_smoke.py
```

The full governed real-file smoke was also run through the RDE MCP subprocess with `scripts/codex_rde_smoke.py --full-yolo`, producing an audit grade A report with `report_readiness=production_ready` and `core_goal_audit=9/9`.

## automl-stat-mcp (進階分析引擎)

### 什麼是 automl-stat-mcp?

`automl-stat-mcp` 是 RDE 的重量級統計分析後端，透過 Docker 服務提供以下分析能力：

| 分析 | 引擎 | 端口 |
| ------ | ------ | ------ |
| 描述統計、t-test、chi-square、Table 1 | 本地 ScipyEngine | — |
| Propensity Score Matching | stats-service | :8003 |
| Survival Analysis (KM, Cox) | stats-service | :8003 |
| ROC/AUC | stats-service | :8003 |
| Power Analysis (Advanced) | stats-service | :8003 |
| AutoML Training | automl-service | :8001 |

### automl-stat-mcp 是可選的

**不安裝 automl-stat-mcp 也能正常使用 RDE！** 基礎統計由本地 ScipyEngine 處理，調整模型、ROC/AUC、基本 power、Kaplan-Meier 與輕量 propensity scoring 由 local-lite statsmodels/scipy fallback 處理。

也要誠實說明：即使安裝了 `automl-stat-mcp`，也不代表所有特殊分析方法都會自動可用。超出目前委派契約的分析仍可能需要手動處理或額外整合。

### 啟用方式

```bash
# 在專案根目錄
cd vendor/automl-stat-mcp && docker compose up -d

# Optional: VSIX users can complete the core report path without Docker.
# RDE falls back to local-lite advanced analysis when automl is unavailable.
```

### 行為邏輯

1. Extension 啟動時自動檢查 `stats-service:8003/health`
2. 若服務可用 → 進階分析自動委派
3. 若服務不可用 → 靜默降級到本地引擎，不阻擋使用
4. 可透過 `RDE: Check automl-stat-mcp Status` 指令手動檢查

## Usage

### Chat Commands (@rde)

| 指令 | 說明 |
| ------ | ------ |
| `@rde /explore` | 🔍 快速探索資料集概況 |
| `@rde /fullreport` | 📄 從資料到完整分析報告的受治理流程 |
| `@rde /pipeline` | 🔄 查看目前 Pipeline 進度 |
| `@rde /compare` | 📊 比較兩組差異 |
| `@rde /table1` | 📋 產生 Table 1 (基線特徵表) |
| `@rde /advanced` | 🧪 進階統計分析 (PSM, Survival, ROC) |
| `@rde /report` | 📄 組裝與匯出報告 |
| `@rde /audit` | 🔒 審計紀錄與品質檢查 |
| `@rde /help` | 顯示所有指令 |

### Command Palette (Ctrl+Shift+P)

| 指令 | 說明 |
| ------ | ------ |
| `RDE: Run Full Pipeline` | 直接啟動完整報告工作流，不是只看 pipeline 狀態 |
| `RDE: Open UX Harness Dashboard` | 開啟 approval card、dashboard、artifact index、blocker playbook 的無代碼檢視；優先讀取 workspace `artifacts/`，否則讀取 `data/projects/` 最新專案 |
| `RDE: Show Status` | 顯示擴充功能狀態 |
| `RDE: Setup Workspace` | 設定 Copilot/Codex/Cline skills、prompts、rules、instructions |
| `RDE: Configure Codex MCP` | 重新寫入 `~/.codex/config.toml` 的 RDE MCP server 設定；VSIX 啟用時也會自動執行一次 |

### Agent Mode 自然語言

直接在 Agent Mode 輸入：

- 「我有資料想分析」→ 完整 13-Phase
- 「請幫我完成完整分析報告」→ `/fullreport`
- 「只想看概況」→ Quick Explore
- 「比較兩組差異」→ compare_groups
- 「做 Table 1」→ generate_table_one
- 「跑進階分析」→ run_advanced_analysis
- 「產出報告」→ assemble_report

### Recommended Strict Mode

- `.github/agents/eda.agent.md` 提供更硬的受治理 EDA 模式，只保留 memory/context 類工具，要求實際分析必須走 `@rde` MCP workflow。

### 給非工程師的最短路徑

1. 開啟 VS Code 後執行 `RDE: Run Full Pipeline`。
2. 在 chat 視窗貼上你的資料需求，例如「請從這份 Excel 做完整分析報告」。
3. 如果你要 agent 先自主規劃，先讓它跑 `propose_analysis_plan(confirm=true)` 產生經過內部 review / repair 的 greedy blueprint。這一步現在也會在必要時擴張 soft budget、保留更多 EDA 路線，並輸出 Phase 6 execution schedule。再確認 Phase 4 的分析計畫；若 plan 太薄，Phase 4 會先自動補入 exploratory branches，只有補完後仍不足時才擋下來，之後再讓 `@rde` 完成 `collect_results`、`assemble_report`、`run_audit`。

## Architecture

```text
Capability → Skill → MCP Tool
```

### 13-Phase Pipeline

| Phase | Name | Purpose |
| ------- | ------ | ------ |
| 0 | Setup | Project and artifact store |
| 1 | Intake | File, format, size, and PII checks |
| 2 | Schema Registry | Schema, profile, and quality artifacts |
| 3 | Concept Alignment | Research question to variable roles |
| 4 | Creative Ideation | Greedy analysis candidates |
| 5 | Plan Completeness Review | Methodology review before lock |
| 6 | Plan Registration | Locked executable analysis plan |
| 7 | Pre-Explore Check | Readiness, assumptions, and sample checks |
| 8 | Execute Exploration | Planned analyses plus branch-scoped YOLO exploration |
| 9 | Collect Results | Results summary and report readiness |
| 10 | Report Assembly | EDA report and export |
| 11 | Audit Review | Audit score and contract checks |
| 12 | Auto-Improve | Final report and handoff |

### MCP Tools (49)

自動註冊 MCP Server:

- **Research Data Explorer** — 49 tools (project, discovery, profiling, plan, analysis, YOLO branches, UX harness, report, audit)

### Bundled Skills (8)

| 類別 | Skills |
| ------ | -------- |
| 核心 | eda-workflow, data-profiling, report-generator |
| 管理 | session-start, session-end |
| 維護 | memory-updater, memory-checkpoint, git-precommit |

## Configuration

| 設定 | 說明 | 預設 |
| ------ | ------ | ------ |
| `rde.pythonPath` | Python 執行路徑 | Auto-detect (uv > venv > system) |
| `rde.automlEndpoint` | automl-stat-mcp 端點 | `http://localhost:8002` |
| `rde.automlAutoCheck` | 啟動時自動檢查 automl 可用性 | `true` |

## Development

```bash
# Clone
git clone https://github.com/u9401066/research-data-explorer
cd research-data-explorer/vscode-extension

# Install & Build
npm install

# Linux/macOS
./scripts/build.sh

# Windows PowerShell
.\scripts\build.ps1

# Manual steps
npm run compile       # TypeScript only
npm run package       # Generate .vsix

# Optional manual publish
npx @vscode/vsce publish
npx ovsx publish *.vsix

# Validate build output
./scripts/validate-build.sh          # Linux/macOS
.\scripts\validate-build.ps1         # Windows
```

## License

Apache-2.0
