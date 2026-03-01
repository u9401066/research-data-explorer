# Research Data Explorer — Agents Guide

> 本文件指引 VS Code Copilot Agent 如何使用 RDE 的工具與工作流程。
> Architecture: DDD (Domain-Driven Design) | Pipeline: 11-Phase Auditable EDA

## Core Philosophy

> **Agent 不是黑箱做探索，是用工具詳細記錄並經得起審視。**

- 每個分析決策寫入 `decision_log.jsonl`（append-only）
- 偏離計畫寫入 `deviation_log.jsonl`（append-only）
- 每個 Phase 產出結構化 artifact
- 報告比論文更完整 — 作者從報告中提取有意義的部分發表

## Quick Start

```text
用戶: 「我有一個 CSV 檔案，想看看裡面有什麼」
Agent:
  Phase 0 → init_project("exploratory_analysis")
  Phase 1 → run_intake("rawdata/")        # 格式+大小+PII 檢查
  Phase 2 → build_schema()                 # 完整 schema registry
  Phase 3 → align_concepts()              # 研究問題 → 變數映射
  Phase 4 → register_plan()               # 分析計畫（用戶確認後鎖定）
  Phase 5 → run_precheck()                # 前提檢查
  Phase 6 → execute analysis tools         # 按計畫執行
  Phase 7 → collect_results()             # 結果彙整
  Phase 8 → assemble_report()             # 報告組裝
  Phase 9 → run_audit()                   # 審計
  Phase 10 → auto_improve()              # 自動改善
```

## Available MCP Servers

### 1. research-data-explorer (RDE)

EDA 編排層。管理 11-Phase Pipeline、審計鏈、決策日誌。

**DDD Namespace**: `src/rde/interface/mcp/tools/`

### 2. automl-stat-mcp (Execution Engine)

重量級統計分析引擎。透過 Docker 服務運行（localhost:8002）。
RDE 透過 Anti-Corruption Layer (`AutomlGateway`) 呼叫。

## Tool Inventory

### RDE Core Tools — By Phase

#### Phase 0: Project Setup
| Tool | Purpose |
|------|---------|
| `init_project` | 建立專案+目錄結構+artifact store |

#### Phase 1: Data Intake
| Tool | Purpose |
|------|---------|
| `scan_data_folder` | 掃描目錄，列出可分析的檔案 |
| `run_intake` | 完整收件流程：格式(H-002)+大小(H-001)+PII(H-004) |

#### Phase 2: Schema Registry
| Tool | Purpose |
|------|---------|
| `load_dataset` | 載入資料集（通過 Phase 1 的檔案） |
| `build_schema` | 型別推論+變數分類+基礎統計 → schema.json |
| `profile_dataset` | ydata-profiling 完整報告 |
| `assess_quality` | 資料品質評估（缺失、異常值等） |

#### Phase 3: Concept Alignment
| Tool | Purpose |
|------|---------|
| `align_concept` | 研究問題 → schema 變數映射 → 用戶確認 |

#### Phase 4: Plan Registration
| Tool | Purpose |
|------|---------|
| `register_analysis_plan` | 建立分析計畫+automl 指令預排 → 用戶確認 → 鎖定 |

#### Phase 5: Pre-Exploration Check
| Tool | Purpose |
|------|---------|
| `check_readiness` | 樣本量(H-003)+常態性(S-001)+共線性(S-007)+缺失模式(S-005) |

#### Phase 6: Execute Exploration
| Tool | Purpose |
|------|---------|
| `suggest_cleaning` | 建議清理策略（缺失處理、異常值等） |
| `apply_cleaning` | 執行清理（按 suggest_cleaning 建議或計畫 missing_strategy） |
| `generate_table_one` | 生成 Table 1（基線特徵表） |
| `analyze_variable` | 單變數分析（委派 AnalyzeVariableUseCase） |
| `compare_groups` | 組間比較（自動選擇檢定方法） |
| `correlation_matrix` | 相關性分析矩陣（含 S-007 VIF 檢查） |
| `run_advanced_analysis` | 進階分析（自動委派 automl-stat-mcp） |
| `create_visualization` | 生成圖表 |
| `log_deviation` | 記錄計畫偏離（偏離計畫時必須呼叫！） |

#### Phase 7: Collect Results
| Tool | Purpose |
|------|---------|
| `collect_results` | 彙整結果+標記可發表內容（PUBLISHABLE markers） |

#### Phase 8: Report Assembly
| Tool | Purpose |
|------|---------|
| `assemble_report` | 組裝完整 EDA 報告（含 decision log、deviation log） |
| `export_report` | 匯出報告為 Word (.docx) 和/或 PDF（含嵌入圖表） |

#### Phase 9: Audit Review
| Tool | Purpose |
|------|---------|
| `run_audit` | 計畫符合度+方法適當性+效果量完整性+PII 檢查 |

#### Phase 10: Auto-Improve
| Tool | Purpose |
|------|---------|
| `auto_improve` | 根據審計自動改善 |
| `export_handoff` | 產出 handoff package → med-paper-assistant |
| `verify_audit_trail` | 驗證審計鏈完整性 |

#### Cross-Phase
| Tool | Purpose |
|------|---------|
| `get_pipeline_status` | 查看目前 pipeline 進度與已完成步驟 |
| `get_decision_log` | 查看決策日誌 |
| `get_deviation_log` | 查看偏離紀錄 |

### automl-stat-mcp Tools (Delegated)

> Phase 6 中按照 Phase 4 預排的 automl 指令序列執行。

| Tool | Purpose |
|------|---------|
| `create_project` | 建立分析專案 |
| `upload_data` | 上傳資料至分析引擎 |
| `run_quality_check` | 資料品質檢查 |
| `run_analysis` | 執行統計分析 |
| `generate_report` | 生成分析報告 |

## 11-Phase Pipeline Workflow

### Phase Gate Rules
- ⛔ **Phase 4 (Plan) 鎖定後**：Phase 6+ 的任何操作偏離計畫 → 必須 `log_deviation()`
- ⛔ **Artifact Gate**：前一 Phase 的 artifacts 必須存在才能進入下一 Phase
- ⛔ **Decision Logging**：Phase 6 每個分析操作自動寫入 decision_log.jsonl
- ⛔ **User Confirmation**：Phase 3 (概念對齊) 和 Phase 4 (計畫) 必須用戶確認

### Standard Flow（完整 11-Phase）

```text
Phase 0: Project Setup
  └─ init_project("sepsis_analysis")
  └─ → project.yaml + artifacts/ 目錄樹

Phase 1: Data Intake
  └─ scan_data_folder("rawdata/")
  └─ run_intake()
  └─ [H-001] 大小檢查  [H-002] 格式白名單  [H-004] PII 初篩
  └─ → intake_report.json

Phase 2: Schema Registry
  └─ load_dataset("rawdata/sepsis_data.csv")
  └─ build_schema()
  └─ profile_dataset()           # ydata-profiling
  └─ → schema.json + full_profile.html

Phase 3: Concept–Schema Alignment
  └─ align_concepts()
  └─ 研究問題 → 變數映射 → ⚠️ 用戶確認
  └─ → concept_alignment.md + variable_roles.json

Phase 4: Analysis Plan Registration
  └─ register_plan()
  └─ 統計方法 + automl 指令 + α 值 + missing 策略
  └─ ⚠️ 用戶確認 → 🔒 計畫鎖定
  └─ → analysis_plan.yaml (LOCKED)

Phase 5: Pre-Exploration Check
  └─ run_precheck()
  └─ [H-003] 樣本量  [S-001] 常態性  [S-005] 缺失模式  [S-007] VIF
  └─ 如需調整 → log_deviation() → ⚠️ 用戶確認
  └─ → readiness_checklist.json

Phase 6: Execute Exploration
  └─ execute_cleaning()
  └─ generate_table_one()
  └─ compare_groups() × N
  └─ analyze_variable() × N
  └─ correlation_matrix()
  └─ automl-stat-mcp.run_analysis()    # 按 Phase 4 預排指令
  └─ [S-002] 多重比較  [S-009] Effect size  [S-010] Power
  └─ 每步自動寫入 → decision_log.jsonl
  └─ → execution artifacts + figures/

Phase 7: Collect Results
  └─ collect_results()
  └─ 標記 PUBLISHABLE items
  └─ 檢查 plan coverage
  └─ → results_summary.json

Phase 8: Report Assembly
  └─ assemble_report()
  └─ [H-005] 報告完整性  [H-006] 敏感資訊清除
  └─ → eda_report.md (含 Appendix: decision_log + deviation_log)

Phase 9: Audit Review
  └─ run_audit()
  └─ 計畫符合度 + 方法適當性 + 偏離合理性 + 再現性
  └─ → audit_report.json (A/B/C/D/F 評分)

Phase 10: Auto-Improve
  └─ auto_improve()            # 根據 audit 自動修正
  └─ export_handoff()          # 產出 handoff package
  └─ → final_report.md + handoff_package/
```

### Quick Explore Flow（用戶只想快速看概況）

```text
init_project → run_intake → build_schema → profile_dataset → assemble_report
(跳過 Phase 3-5, 7, 9-10；報告標記為 "Quick Explore — Not Audited")
```

### Guided Comparison Flow（用戶想做組間比較）

```text
完整 Phase 0-5 → generate_table_one + compare_groups → collect → report → audit
```

## Hook Reference

### Hard Constraints（自動執行，不可覆蓋）

| ID | Name | Phase | Check |
|----|------|-------|-------|
| H-001 | File Size Guard | 1 | 檔案 > 500MB → 拒絕 |
| H-002 | Format Whitelist | 1 | 僅 CSV/Excel/Parquet/SAS/SPSS/Stata/TSV |
| H-003 | Min Sample Size | 5, 6 | n < 10 → 拒絕統計分析 |
| H-004 | PII Detection | 1, 2 | 偵測 PII → 警告用戶 |
| H-005 | Report Integrity | 8 | 報告必須含所有必要章節 |
| H-006 | Output Sanitization | 8 | 清除敏感路徑 |
| H-007 | Plan Lock | 6+ | 必須有已鎖定的 plan 才能執行分析 |
| H-008 | Artifact Gate | all | 前一 phase artifacts 必須存在 |
| H-009 | Decision Logging | 6 | 每個分析操作必須寫入 log |
| H-010 | Append-Only Logs | all | decision_log 和 deviation_log 不可修改 |

### Soft Constraints（Agent 提醒，用戶可決定）

| ID | Name | Phase | Guidance |
|----|------|-------|----------|
| S-001 | Normality Check | 5, 6 | 非常態 → 建議無母數檢定 |
| S-002 | Multiple Comparisons | 6 | 多組 → Bonferroni/FDR |
| S-003 | Viz Advisor | 6 | 根據變數型別建議圖表 |
| S-004 | Transform Hint | 6 | 偏態 → log/sqrt |
| S-005 | Missing Pattern | 5 | MCAR/MAR/MNAR 判斷 |
| S-006 | Outlier Strategy | 5 | 極端值處理策略 |
| S-007 | Collinearity | 5, 6 | VIF > 10 → 警告 |
| S-008 | Sample Balance | 5, 6 | 組間 N 差距大 → 修正 |
| S-009 | Effect Size | 6 | 統計顯著 ≠ 臨床意義 |
| S-010 | Power Analysis | 6 | 非顯著 → 檢定力分析 |
| S-011 | Plan Deviation | 6 | 操作偏離計畫 → 提醒記錄 |
| S-012 | Sensitivity Hint | 7 | 主要結果 → 建議敏感度分析 |

## Decision Tree

```text
用戶說什麼 → 你做什麼

「我有資料想分析」         → 完整 Phase 0-10 流程
「只想快速看概況」         → Quick Explore Flow
「比較兩組差異」           → Phase 0-5 → compare_groups → Phase 7-10
「做 Table 1」            → Phase 0-5 → generate_table_one → Phase 7-10
「看相關性」               → Phase 0-5 → correlation_matrix → Phase 7-10
「跑複雜統計模型」         → Phase 6 委派 automl-stat-mcp
「目前進度？」             → get_pipeline_status
「決策紀錄？」             → get_decision_log
「為什麼改了方法？」       → get_deviation_log
「產出報告」               → Phase 8 assemble_report
「報告品質如何？」         → Phase 9 run_audit
「要給 paper 用」          → Phase 10 export_handoff
```

## Artifact Awareness

Agent 應該在回覆時引用具體的 artifact：

```text
✅ 好的回覆:
「根據 Phase 5 的前提檢查 (readiness_checklist.json)，
 sofa_score 非常態分佈 (Shapiro-Wilk p < 0.001)，
 已調整為 Mann-Whitney U 檢定，偏離原因已記錄 (deviation_log entry #2)。」

❌ 差的回覆:
「我用了 Mann-Whitney U 來比較。」
```

## Response Style

- 使用**繁體中文**回應
- 統計結果用白話文解釋，附帶括號內技術數值
- 例: 「兩組有顯著差異 (Mann-Whitney U, p = 0.003, r = 0.45)」
- **引用 artifact 路徑**，讓用戶知道資訊來源
- 偏離計畫時**主動說明理由**，不能默默換方法
- 執行前確認用戶意圖，特別是 Phase 3 概念對齊和 Phase 4 計畫鎖定
