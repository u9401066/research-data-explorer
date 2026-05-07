# Copilot Instructions for Research Data Explorer

> 此檔案指引 Copilot Agent 在 RDE 專案中的行為規範。
> Architecture: DDD | Pipeline: 13-Phase Auditable EDA

> 若與實際程式行為或測試不一致，請以 [agent-control.yaml](agent-control.yaml) 與 `python3 -m pytest -q` 的測試結果為準。

## 回應風格

- 使用**繁體中文**回應
- 統計結果用白話文解釋，附帶括號內技術數值
- 例: 「兩組有顯著差異 (Mann-Whitney U, p = 0.003, r = 0.45)」
- **引用 artifact 路徑**，讓用戶知道資訊來源
- 偏離計畫時**主動說明理由**

## 核心架構

```
Interface (MCP tools) → Application (Use Cases) → Domain (Pure logic) ← Infrastructure (Adapters)
```

- **49 MCP tools** across 9 tool files
- **13-Phase Pipeline** with Hard/Soft constraints
- **local-first AnalysisDelegator** with local-lite statsmodels/scipy fallback and optional automl-stat-mcp delegation

## Core Product Contract

RDE serves non-data-scientists who bring real datasets but may not know which analyses to run, how to combine methods, or how to code the analysis. Agents must help the user complete:

1. data understanding
2. analysis planning
3. reproducible exploration
4. analysis execution and plain-language interpretation
5. report generation, audit, improvement, export, and handoff

`report_readiness` and `run_audit` enforce this contract with `core_goal:*` gaps. Do not call a report production-ready if data intake/schema, concept alignment, plan review/lock, readiness checks, decision logs, collected results, and report deliverables are missing.

## 可用 MCP Servers

### 1. Research Data Explorer (RDE)
13-Phase Auditable EDA Pipeline。管理資料探索、統計分析、審計鏈。

### 2. automl-stat-mcp (Execution Engine)
重量級統計分析引擎。透過 Docker 服務運行（localhost:8002）。
RDE 透過 `AnalysisDelegator` 自動委派。

automl-stat-mcp is optional. VSIX users can complete the core report flow through local-lite fallback when Docker is unavailable.

### 3. Zotero + PubMed MCP
文獻搜尋與管理。See Zotero workflow below.

## Pipeline 工作流

### 決策樹

| 用戶說什麼 | 你做什麼 |
|------------|----------|
| 「我有資料想分析」 | 完整 Phase 0-12 |
| 「幫我自己先規劃分析」 | Phase 0-3 → propose_analysis_plan → Phase 4-12 |
| 「只想看概況」 | Quick Explore |
| 「比較兩組差異」 | Phase 0-7 → compare_groups → Phase 9-12 |
| 「做 Table 1」 | Phase 0-7 → generate_table_one → Phase 9-12 |
| 「跑進階分析」 | Phase 8: `run_advanced_analysis`（automl 可用時委派，否則 local-lite fallback） |
| 「目前進度？」 | get_pipeline_status |
| 「產出報告」 | Phase 8 assemble_report |
| 「匯出 Word/PDF」 | Phase 8 export_report |
| 「要給 paper 用」 | Phase 10 export_handoff |

### 防呆規則 (Hard Constraints)

| ID | 規則 | 強制方式 |
|----|------|----------|
| H-001 | 檔案大小 < 500MB | 自動拒絕 |
| H-002 | 格式白名單 | 自動拒絕 |
| H-003 | 最低樣本量: n ≥ 10 | 樣本量 n < 10 時自動拒絕統計分析 |
| H-004 | PII 偵測 | 預設拒絕載入；僅可明確 override |
| H-005 | 報告完整性 | 檢查必備章節 |
| H-006 | 輸出清除敏感路徑 | 自動清除 |
| H-007 | Plan Lock | Phase 6+ 需鎖定計畫 |
| H-008 | Artifact Gate | 前一 Phase 必須完成 |
| H-009 | Decision Logging | Phase 8 自動記錄 |
| H-010 | Append-Only Logs | decision/deviation log 不可修改 |

### 統計提醒 (Soft Constraints)

| ID | 提醒 |
|----|------|
| S-001 | 常態性 → 無母數/有母數選擇 |
| S-002 | 多重比較 → Bonferroni/FDR |
| S-003 | 圖表建議 |
| S-004 | 偏態 → 轉換建議 |
| S-005 | 缺失模式 (MCAR/MAR/MNAR) |
| S-006 | 極端值處理 |
| S-007 | 多重共線性 (VIF) |
| S-008 | 組間平衡 |
| S-009 | 效果量 ≠ 臨床意義 |
| S-010 | 檢定力分析 |
| S-011 | 計畫偏離提醒 |
| S-012 | 敏感度分析提醒 |

## automl-stat-mcp 委派邏輯

進階分析會在 automl 可用時委派；不可用時先降級為 local-lite / 本地引擎：

| 分析 | 引擎 | 端點 |
|------|------|------|
| 描述統計、t-test、chi-square、Table 1 | 本地 ScipyEngine | — |
| Propensity Score | stats-service:8003 | /propensity/* |
| Survival Analysis | stats-service:8003 | /survival/* |
| ROC/AUC | stats-service:8003 | /roc/* |
| Power Analysis | stats-service:8003 | /power/* |
| AutoML Training | automl-service:8001 | /train/automl |

使用 `run_advanced_analysis()` 自動選擇引擎。

## Git Hooks

已配置 `.pre-commit-config.yaml`，含 4 個 RDE 自定 hook：
- `rde-decision-log-integrity` (H-010)
- `rde-pii-scan` (H-004/H-006)
- `rde-artifact-gate` (H-008)
- `rde-report-sanitize` (H-006)

安裝: `pip install pre-commit && pre-commit install`

## Agent Control Notes

- Phase 3 uses `align_concept(confirm=true)` only after concept-schema review.
- Phase 4 is two-step: `propose_analysis_plan(confirm=false)` generates the greedy blueprint/review artifacts, then `propose_analysis_plan(confirm=true)` confirms them after user review.
- Phase 5+6 uses `register_analysis_plan(confirm=true)` to perform plan review and lock the Phase 6 plan in one governed call.
- `load_dataset()` / `run_intake()` 偵測疑似 PII 時預設拒絕；只有 `allow_pii=true` 可覆蓋，而且回覆中必須明確警告
- `decision_log.jsonl` 與 `deviation_log.jsonl` 位於 `artifacts/phase_08_execute_exploration/`
- 測試與回歸驗證請使用 `python3 -m pytest -q`

## Quality Layers

| Layer | 狀態 | 機制 |
|-------|------|------|
| L1 Hook | ✅ | H-001~H-010, S-001~S-012 |
| L2 Pipeline | ✅ | Phase Gate + Artifact Gate |
| L3 Audit | ✅ | Decision Log + Audit Report |
| L4 Bylaw | ✅ | .github/bylaws/ |
| L5 Agent Assets | ✅ | .github/agents, .codex/skills, .clinerules |

## Zotero + PubMed MCP

### 搜尋文獻
1. 使用 `parse_pico` 分析研究問題
2. 使用 `unified_search` 搜尋（PubMed、Europe PMC、CORE）
3. 結果快取，用 `get_session_pmids` 取回

### 匯入到 Zotero
1. `list_collections` 取得 Collection
2. 詢問用戶選擇 Collection
3. `quick_import_pmids` 匯入

### 避免重複
- `check_articles_owned` 檢查 PMID
- `search_pubmed_exclude_owned` 搜尋未擁有的
