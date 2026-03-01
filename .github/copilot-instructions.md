# Copilot Instructions for Research Data Explorer

> 此檔案指引 Copilot Agent 在 RDE 專案中的行為規範。
> Architecture: DDD | Pipeline: 11-Phase Auditable EDA

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

- **29 MCP tools** across 7 tool files
- **11-Phase Pipeline** with Hard/Soft constraints
- **automl-stat-mcp** delegation via AnalysisDelegator

## 可用 MCP Servers

### 1. Research Data Explorer (RDE)
11-Phase Auditable EDA Pipeline。管理資料探索、統計分析、審計鏈。

### 2. automl-stat-mcp (Execution Engine)
重量級統計分析引擎。透過 Docker 服務運行（localhost:8002）。
RDE 透過 `AnalysisDelegator` 自動委派。

### 3. Zotero + PubMed MCP
文獻搜尋與管理。See Zotero workflow below.

## Pipeline 工作流

### 決策樹

| 用戶說什麼 | 你做什麼 |
|------------|----------|
| 「我有資料想分析」 | 完整 Phase 0-10 |
| 「只想看概況」 | Quick Explore |
| 「比較兩組差異」 | Phase 0-5 → compare_groups → 7-10 |
| 「做 Table 1」 | Phase 0-5 → generate_table_one → 7-10 |
| 「跑進階分析」 | Phase 6: run_advanced_analysis（自動委派 automl） |
| 「目前進度？」 | get_pipeline_status |
| 「產出報告」 | Phase 8 assemble_report |
| 「匯出 Word/PDF」 | Phase 8 export_report |
| 「要給 paper 用」 | Phase 10 export_handoff |

### 防呆規則 (Hard Constraints)

| ID | 規則 | 強制方式 |
|----|------|----------|
| H-001 | 檔案大小 < 500MB | 自動拒絕 |
| H-002 | 格式白名單 | 自動拒絕 |
| H-003 | 樣本量 ≥ 10 | 自動拒絕統計分析 |
| H-004 | PII 偵測 | 警告用戶 |
| H-005 | 報告完整性 | 檢查必備章節 |
| H-006 | 輸出清除敏感路徑 | 自動清除 |
| H-007 | Plan Lock | Phase 6+ 需鎖定計畫 |
| H-008 | Artifact Gate | 前一 Phase 必須完成 |
| H-009 | Decision Logging | Phase 6 自動記錄 |
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

進階分析自動委派給 automl（如服務可用），否則降級為本地引擎：

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

## Quality Layers

| Layer | 狀態 | 機制 |
|-------|------|------|
| L1 Hook | ✅ | H-001~H-010, S-001~S-012 |
| L2 Pipeline | ✅ | Phase Gate + Artifact Gate |
| L3 Audit | ✅ | Decision Log + Audit Report |
| L4 Bylaw | ✅ | .github/bylaws/ |
| L5 Skill | ✅ | .claude/skills/ |

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
