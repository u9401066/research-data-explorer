# Project Brief

## Purpose

Research Data Explorer (RDE) 是 MCP + VS Code Agent 的完整工作流程系統，讓非 IT 專業研究者（臨床醫師、公衛學者等）能用自然語言完成資料探索與分析，產出**完整、透明、可再現**的結構化 EDA 報告。

## Target Users

| 角色 | 技術能力 | 期望體驗 |
|------|---------|---------|
| 臨床醫師 | 不熟 Python/R | 「把 CSV 丟進來，告訴我有什麼」 |
| 公衛研究者 | 會基本統計 | 「幫我做 Table 1 和 group comparison」 |
| 碩博士生 | 學過統計 | 「資料長這樣，我應該用什麼檢定？」 |
| Reviewer/PI | 驗證流程 | 「讓我看看分析計畫和決策紀錄」 |

## Core Design Principles

1. **透明高於一切** — Agent 不是黑箱，每個決策寫入 decision_log
2. **Pre-registration 精神** — 先制定計畫，鎖定後才執行
3. **報告 ⊃ 論文** — 報告是完整探索記錄，作者從中提取可發表內容
4. **DDD 架構** — Interface → Application → Domain ← Infrastructure
5. **11-Phase Pipeline** — Phase 0-10，每步產出結構化 artifact

## Tool Chain

```
rawdata/ → [RDE] → 完整 EDA 報告 → [Med-Paper-Assistant] → 論文
```

## Repository

- Python >=3.11, FastMCP
- 30 MCP tools across 7 tool files
- automl-stat-mcp as vendor submodule (Docker 獨立服務)
- `.github/agent-control.yaml` 作為 agent workflow / gate / override / audit path 的 authoritative manifest
