# Research Data Explorer — VS Code Extension

AI-powered research data exploration assistant with MCP tools, prompts, and skills.

## Features

- 🔍 **11-Phase Auditable EDA Pipeline** — 結構化、可審計的探索性資料分析
- 📊 **30 MCP Tools** — 資料載入、描述統計、分組比較、Table 1、進階分析
- 🧪 **automl-stat-mcp 委派** — PSM, Survival, ROC, Power Analysis 自動委派
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
|------|------|------|
| Windows (x64) | ✅ | PowerShell 5.1+ |
| macOS (Intel/Apple Silicon) | ✅ | Homebrew uv 自動偵測 |
| Linux (x64) | ✅ | snap/apt uv 支援 |

## MCP Installation Behavior

- RDE source workspaces run the local project directly via `uv run python -m rde`.
- Packaged VSIX builds ship a bundled Python project and run it via `uv run --project ... python -m rde`.
- No Python package registry publication is required for the MCP server to start.
- If the workspace already has a `.vscode/mcp.json` defining `rde`, the extension skips auto-registration.
- uv 會自動偵測多個可能路徑（`~/.local/bin`, `~/.cargo/bin`, `%LOCALAPPDATA%\uv\bin`, `/opt/homebrew/bin`）。

## automl-stat-mcp (進階分析引擎)

### 什麼是 automl-stat-mcp?

`automl-stat-mcp` 是 RDE 的重量級統計分析後端，透過 Docker 服務提供以下分析能力：

| 分析 | 引擎 | 端口 |
|------|------|------|
| 描述統計、t-test、chi-square、Table 1 | 本地 ScipyEngine | — |
| Propensity Score Matching | stats-service | :8003 |
| Survival Analysis (KM, Cox) | stats-service | :8003 |
| ROC/AUC | stats-service | :8003 |
| Power Analysis (Advanced) | stats-service | :8003 |
| AutoML Training | automl-service | :8001 |

### automl-stat-mcp 是可選的

**不安裝 automl-stat-mcp 也能正常使用 RDE！** 基礎統計分析由本地 ScipyEngine 處理。

### 啟用方式

```bash
# 在專案根目錄
cd vendor/automl-stat-mcp && docker compose up -d
```

### 行為邏輯

1. Extension 啟動時自動檢查 `stats-service:8003/health`
2. 若服務可用 → 進階分析自動委派
3. 若服務不可用 → 靜默降級到本地引擎，不阻擋使用
4. 可透過 `RDE: Check automl-stat-mcp Status` 指令手動檢查

## Usage

### Chat Commands (@rde)

| 指令 | 說明 |
|------|------|
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
|------|------|
| `RDE: Run Full Pipeline` | 直接啟動完整報告工作流，不是只看 pipeline 狀態 |
| `RDE: Show Status` | 顯示擴充功能狀態 |
| `RDE: Setup Workspace` | 設定 Skills/Prompts/Instructions |

### Agent Mode 自然語言

直接在 Agent Mode 輸入：

- 「我有資料想分析」→ 完整 Phase 0-10
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
3. 依序確認 Phase 3 的變數對齊與 Phase 4 的分析計畫，之後讓 `@rde` 完成 `collect_results`、`assemble_report`、`run_audit`。

## Architecture

```
Capability → Skill → MCP Tool
```

### 11-Phase Pipeline

| Phase | 名稱 | 說明 |
|-------|------|------|
| 0 | Setup | 專案建立 |
| 1 | Intake | 資料載入 |
| 2 | Schema | Schema 登記 |
| 3 | Concept | 概念校準 |
| 4 | Plan | 分析計畫 |
| 5 | Pre-check | 前置檢查 |
| 6 | Execute | 執行分析 |
| 7 | Collect | 收集結果 |
| 8 | Report | 報告組裝 |
| 9 | Audit | 審計 |
| 10 | Improve | 自我改善 |

### MCP Tools (30)

自動註冊 MCP Server:

- **Research Data Explorer** — 30 工具 (project, discovery, profiling, plan, analysis, report, audit)

### Bundled Skills (8)

| 類別 | Skills |
|------|--------|
| 核心 | eda-workflow, data-profiling, report-generator |
| 管理 | session-start, session-end |
| 維護 | memory-updater, memory-checkpoint, git-precommit |

## Configuration

| 設定 | 說明 | 預設 |
|------|------|------|
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
