# Research Data Explorer (RDE) — Project Specification

> Version: 0.2.0 | Status: Architecture Phase | Last Updated: 2026-03-01

## 1. Vision

**Research Data Explorer** 是一個 MCP + Custom Agent + Instructions + Skill 的完整工作流程系統，讓非 IT 專業研究者（臨床醫師、公衛學者等）能用自然語言完成資料探索與分析，產出**完整、透明、可再現**的結構化 EDA 報告。

### 核心目標：透明誠實的科學探索

> **Agent 不是黑箱做探索，而是用工具詳細記錄每一步，經得起審視。**

傳統 EDA 的問題：
- 探索過程不透明 → reviewer 無法驗證
- 分析決策沒記錄 → 無法再現
- 方法選擇憑經驗 → 容易 cherry-pick

RDE 的解法：
- **Pre-registration**：先制定探索計畫，鎖定後才執行
- **Decision Log**：每個決策（選檢定、設 α、處理 missing）寫入日誌
- **Artifact Trail**：每步產出結構化檔案 → 構成完整審計鏈
- **Deviation Tracking**：偏離計畫必須記錄理由

### 工具鏈定位

```
rawdata/ → [Research Data Explorer] → 完整 EDA 報告 → [Med-Paper-Assistant] → 論文
           ▲ 本 repo                   (含 audit trail)    ▲ 下游 repo
```

- **報告 ⊃ 論文**：報告是完整探索紀錄，比論文更詳盡
- **論文 ⊂ 報告**：作者從報告中提取有意義的部分用於 Methods + Results
- **med-paper-assistant** 接續報告中標記的可發表內容 → 撰寫正式論文

## 2. Target Users

| 角色 | 技術能力 | 期望體驗 |
|------|---------|---------|
| 臨床醫師 | 不熟 Python/R | 「把 CSV 丟進來，告訴我有什麼」 |
| 公衛研究者 | 會基本統計 | 「幫我做 Table 1 和 group comparison」 |
| 碩博士生 | 學過統計，但不確定方法 | 「資料長這樣，我應該用什麼檢定？」 |
| Reviewer/PI | 需要驗證流程 | 「讓我看看你的分析計畫和決策紀錄」 |

## 3. Architecture

### 3.1 DDD Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  VS Code Agent Layer                                        │
│  ┌──────────┐ ┌───────────┐ ┌──────────────┐ ┌──────────┐  │
│  │Chatmodes │ │ AGENTS.md │ │   Skills     │ │Instructions│ │
│  │ explore  │ │ RDE Agent │ │ eda-workflow │ │CONSTITUTION│ │
│  │ analyze  │ │           │ │ audit-trail  │ │  Bylaws    │ │
│  │ report   │ │           │ │ report-gen   │ │            │ │
│  └──────────┘ └───────────┘ └──────────────┘ └──────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Interface Layer (src/rde/interface/)                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ MCP Server (FastMCP)                                │    │
│  │ Tools: project / schema / plan / explore / report   │    │
│  │ Prompts: guided workflow templates                  │    │
│  └─────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│  Application Layer (src/rde/application/)                    │
│  ┌──────────┐ ┌────────────┐ ┌──────────┐ ┌────────────┐   │
│  │Use Cases │ │  Pipeline  │ │   DTOs   │ │ Decision   │   │
│  │ 11 phases│ │State Machine│ │          │ │   Logger   │   │
│  └──────────┘ └────────────┘ └──────────┘ └────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  Domain Layer (src/rde/domain/) — Pure Business Logic       │
│  ┌────────┐ ┌──────────┐ ┌────────┐ ┌───────┐ ┌───────┐   │
│  │ Models │ │ Services │ │Policies│ │Events │ │ Ports │   │
│  │  ARs   │ │ Advisor  │ │Hard/Sft│ │Domain │ │  ABCs │   │
│  │  VOs   │ │Classifier│ │        │ │Events │ │       │   │
│  │Entities│ │Assessor  │ │        │ │       │ │       │   │
│  └────────┘ └──────────┘ └────────┘ └───────┘ └───────┘   │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Layer (src/rde/infrastructure/)              │
│  ┌─────────────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐  │
│  │automl-stat-mcp  │ │ ydata-   │ │  pandas  │ │Artifact│  │
│  │Gateway (ACL)    │ │profiling │ │  loader  │ │  Store │  │
│  │localhost:8002   │ │ adapter  │ │          │ │        │  │
│  └─────────────────┘ └──────────┘ └──────────┘ └────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Integration with automl-stat-mcp

- **Git submodule**: `vendor/automl-stat-mcp/` — 版本追蹤
- **Runtime**: automl-stat-mcp 作為獨立 Docker 服務運行
- **Anti-Corruption Layer**: `AutomlGateway` adapter 防止 automl API 概念洩漏到 RDE domain
- **職責分離**:
  - RDE 負責: agent 流程、hooks、軟硬約束、EDA 步驟拆解、**審計紀錄**
  - automl-stat-mcp 負責: 重量級統計分析、ML 訓練、自動化建模

### 3.3 VS Code MCP Configuration

```jsonc
// .vscode/mcp.json
{
  "servers": {
    "research-data-explorer": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "rde"]
    },
    "automl-stat-mcp": {
      "type": "sse",
      "url": "http://localhost:8002/sse"
    }
  }
}
```

## 4. Auditable EDA Pipeline (11 Phases)

> 設計哲學：每一步都產出 **artifact**，構成從原始資料到最終報告的完整審計鏈。
> 任何偏離預定計畫的操作都必須記錄理由。報告比論文更完整 — 作者從報告中提取有意義的部分發表。

### 4.0 Pipeline Overview

```
Phase 0   Phase 1    Phase 2     Phase 3      Phase 4
Project → Data    → Schema   → Concept   → Plan
Setup    Intake    Registry   Alignment   Registration
  │        │         │          │            │
  ▼        ▼         ▼          ▼            ▼
 📁       📋        📊         🔍           📝
project  intake   schema.json concept    analysis
.yaml    report              _mapping    _plan.yaml
                              .md        (LOCKED)
                                            │
Phase 5       Phase 6      Phase 7          ▼
Pre-Explore → Execute   → Collect    Phase 8
Check         Exploration  Results    Report
  │             │            │        Assembly
  ▼             ▼            ▼           │
 ✅           📊🔬         📦           ▼
readiness    decision     results/    📄 EDA
checklist    _log.jsonl   + figures   Report
                                        │
                              Phase 9    ▼    Phase 10
                              Audit  → Auto
                              Review   Improve
                                │         │
                                ▼         ▼
                              🔍        🔄
                             audit     improved
                             _report   _report
```

### 4.1 Phase Details

#### Phase 0: Project Setup — 專案建立

**目的**：建立專案骨架與基礎設定檔

| 子步驟 | 動作 | 產出 Artifact |
|--------|------|---------------|
| 0.1 建立專案目錄 | 建立 `data/projects/{slug}/` 結構 | 目錄結構 |
| 0.2 初始化設定 | 研究問題、作者資訊、日期 | `project.yaml` |
| 0.3 建立 rawdata 連結 | 指向原始資料目錄（不複製不移動） | `rawdata_path` in config |
| 0.4 初始化 artifact store | 建立 `artifacts/` 目錄結構 | `artifacts/` 目錄樹 |

```yaml
# project.yaml
project_id: "proj_20260301_sepsis"
title: "Sepsis Patient Outcome Analysis"
research_question: "What factors predict 30-day mortality in sepsis patients?"
authors: ["Dr. Wang"]
created_at: "2026-03-01T10:00:00"
rawdata_path: "data/rawdata/"
status: "initialized"
pipeline_version: "0.2.0"
```

**專案目錄結構**:
```
data/projects/{slug}/
├── project.yaml              # 專案設定
├── artifacts/                # 所有產出物（按 phase 分目錄）
│   ├── phase_01_intake/
│   ├── phase_02_schema/
│   ├── phase_03_concept/
│   ├── phase_04_plan/
│   ├── phase_05_precheck/
│   ├── phase_06_execution/
│   ├── phase_07_results/
│   ├── phase_08_report/
│   ├── phase_09_audit/
│   └── phase_10_improve/
├── decision_log.jsonl        # 決策日誌（append-only）
├── deviation_log.jsonl       # 偏離紀錄（append-only）
└── figures/                  # 圖表產出
```

---

#### Phase 1: Data Intake — 資料收件與安全檢查

**目的**：確認資料「可以被處理」（格式、大小、安全性），不看內容

| 子步驟 | 動作 | Hook | 產出 Artifact |
|--------|------|------|---------------|
| 1.1 掃描目錄 | 列出所有檔案 | — | `file_inventory.json` |
| 1.2 格式驗證 | 檢查副檔名白名單 | H-002 | pass/reject per file |
| 1.3 大小驗證 | 檢查 ≤ 500MB | H-001 | pass/reject per file |
| 1.4 編碼偵測 | 自動偵測字元編碼 | — | `encoding` per file |
| 1.5 試載入 | 嘗試讀取前 100 rows | — | success/error per file |
| 1.6 PII 初篩 | 檢查欄位名稱是否疑似 PII | H-004 | `pii_suspects[]` |
| 1.7 產出收件報告 | 彙整所有檢查結果 | — | `intake_report.json` |

**Decision Log 記錄**: 每個被拒絕的檔案 → 記錄原因

---

#### Phase 2: Schema Registry — 建立完整資料結構

**目的**：建立資料的完整結構描述（schema），作為後續所有分析的基礎

| 子步驟 | 動作 | Hook | 產出 Artifact |
|--------|------|------|---------------|
| 2.1 載入資料 | 完整載入通過 Phase 1 的檔案 | — | in-memory DataFrame |
| 2.2 型別推論 | 每個欄位的 dtype + 語義型別 | — | `variable_types.json` |
| 2.3 變數分類 | CONTINUOUS/CATEGORICAL/ORDINAL/BINARY/… | — | `variable_classification.json` |
| 2.4 基礎統計 | 每欄: n, missing, unique, min/max/mean | — | `basic_stats.json` |
| 2.5 關聯偵測 | 哪些欄位可能是 ID / date / group key | — | `role_detection.json` |
| 2.6 完整 profiling | ydata-profiling 完整報告 | — | `full_profile.html` + `profile_data.json` |
| 2.7 組裝 schema | 彙整成統一 schema registry | — | `schema.json` |

```json
// schema.json (simplified example)
{
  "dataset": "sepsis_data.csv",
  "n_rows": 1847,
  "n_columns": 42,
  "variables": [
    {
      "name": "age",
      "dtype": "float64",
      "semantic_type": "CONTINUOUS",
      "role": "FEATURE",
      "n_missing": 12,
      "missing_rate": 0.0065,
      "stats": { "mean": 64.3, "std": 15.2, "min": 18, "max": 99 }
    }
  ],
  "pii_flags": ["patient_name", "id_number"],
  "created_at": "2026-03-01T10:15:00"
}
```

---

#### Phase 3: Concept–Schema Alignment — 研究概念對齊

**目的**：將使用者的研究問題（概念）對應到 schema 中的具體變數，確保後續分析有的放矢

| 子步驟 | 動作 | 產出 Artifact |
|--------|------|---------------|
| 3.1 概念提取 | 從研究問題拆出關鍵概念 | `concepts[]` |
| 3.2 概念→變數映射 | 每個概念對應到 schema 中哪些欄位 | `concept_mapping.json` |
| 3.3 角色指派 | 指定 outcome / exposure / covariate / confounder | `variable_roles.json` |
| 3.4 缺口識別 | 概念有缺少對應欄位嗎？ | `gaps[]` |
| 3.5 互動確認 | 與用戶確認映射是否正確 | `user_confirmed: true` |
| 3.6 產出對齊摘要 | 概念-變數對照表 | `concept_alignment.md` |

```markdown
# Concept–Schema Alignment

## Research Question
"What factors predict 30-day mortality in sepsis patients?"

## Mapping
| Concept | Role | Variable(s) | Note |
|---------|------|-------------|------|
| 30-day mortality | PRIMARY OUTCOME | `mortality_30d` (BINARY) | — |
| Sepsis severity | EXPOSURE | `sofa_score` (CONTINUOUS) | SOFA score |
| Age | COVARIATE | `age` (CONTINUOUS) | — |
| Comorbidities | CONFOUNDER | `cci_score` (CONTINUOUS) | Charlson Comorbidity Index |

## Gaps
- "ICU length of stay" mentioned but no matching column found
- User decision: use `hospital_days` as proxy → logged
```

---

#### Phase 4: Analysis Plan Registration — 分析計畫鎖定

**目的**：制定詳細的分析計畫，包含預計使用的統計方法與 automl-stat-mcp 操作指令。**計畫鎖定後，偏離必須記錄理由。**

> 📌 **Pre-registration 精神**：不是先看結果再選方法，而是先決定方法再看結果。

| 子步驟 | 動作 | 產出 Artifact |
|--------|------|---------------|
| 4.1 分析目標列表 | 列出所有要回答的子問題 | `objectives[]` |
| 4.2 統計方法選擇 | 根據變數型別+研究設計選方法 | `methods_per_objective` |
| 4.3 假設前提聲明 | 每個方法的假設前提 | `assumptions[]` |
| 4.4 α 與檢定力設定 | 顯著水準、多重比較校正策略 | `alpha`, `correction_method` |
| 4.5 automl 指令預排 | 規劃要送給 automl-stat-mcp 的操作序列 | `automl_commands[]` |
| 4.6 缺失值策略 | 預定的缺失值處理方式 | `missing_strategy` |
| 4.7 敏感度分析 | 規劃哪些分析要做 sensitivity analysis | `sensitivity_analyses[]` |
| 4.8 用戶簽核 | 用戶確認計畫 | `user_approved: true` |
| 4.9 鎖定計畫 | **計畫凍結，後續偏離須記錄** | `plan_locked_at` timestamp |

```yaml
# analysis_plan.yaml
plan_id: "plan_20260301_v1"
locked_at: "2026-03-01T10:30:00"
locked_by: "user_confirmation"

objectives:
  - id: "OBJ-001"
    question: "SOFA score 與 30-day mortality 的關聯"
    outcome: "mortality_30d"
    exposure: "sofa_score"
    method: "logistic_regression"
    covariates: ["age", "cci_score", "sex"]
    assumptions:
      - "Binary outcome → logistic regression appropriate"
      - "Check multicollinearity among covariates"
    alpha: 0.05
    correction: "bonferroni"  # if multiple primary outcomes

  - id: "OBJ-002"
    question: "存活組 vs 死亡組的基線特徵比較"
    type: "group_comparison"
    group_variable: "mortality_30d"
    method: "auto_select"  # RDE 根據分佈自動選
    note: "Will produce Table 1"

automl_commands:
  - step: "create_project"
    args: { name: "sepsis_eda" }
  - step: "upload_data"
    args: { file: "sepsis_data_clean.csv" }
  - step: "run_analysis"
    args: { type: "logistic_regression", target: "mortality_30d" }

missing_strategy:
  default: "complete_case"
  per_variable:
    sofa_score: "multiple_imputation"  # < 5% missing, important predictor
  justification: "Complete case for variables with < 1% missing; MI for key predictors"

sensitivity_analyses:
  - "Repeat primary analysis excluding outliers (> 3 SD)"
  - "Repeat with different missing data strategy (listwise deletion)"
```

---

#### Phase 5: Pre-Exploration Check — 探索前檢查

**目的**：在真正執行分析前，驗證所有前提條件是否滿足

| 子步驟 | 動作 | Hook | 產出 Artifact |
|--------|------|------|---------------|
| 5.1 樣本量檢查 | 每個分析目標的 n 是否足夠 | H-003 | pass/fail per objective |
| 5.2 常態性檢查 | 連續變數的分佈評估 | S-001 | `normality_results.json` |
| 5.3 變異數齊性 | Levene's test (需要時) | S-001 | `homogeneity_results.json` |
| 5.4 共線性檢查 | VIF 計算 | S-007 | `vif_results.json` |
| 5.5 類別平衡 | 組間樣本比例 | S-008 | `balance_check.json` |
| 5.6 缺失值模式 | MCAR/MAR/MNAR 判斷 | S-005 | `missing_pattern.json` |
| 5.7 計畫可行性 | 根據檢查結果判斷計畫是否需要調整 | — | `feasibility_verdict` |
| 5.8 計畫修正 | 如需調整 → 記錄偏離理由 → **用戶確認** | — | `deviation_log` entry |
| 5.9 產出 readiness 報告 | 彙整所有前提檢查 | — | `readiness_checklist.json` |

```json
// readiness_checklist.json
{
  "overall": "READY_WITH_WARNINGS",
  "checks": [
    { "check": "sample_size", "OBJ-001": "PASS (n=1847)", "OBJ-002": "PASS" },
    { "check": "normality", "sofa_score": "FAIL (Shapiro p<0.001) → plan adjusted to Mann-Whitney" },
    { "check": "vif", "result": "PASS (max VIF=2.3)" },
    { "check": "missing", "pattern": "MAR for sofa_score → MI confirmed" }
  ],
  "plan_deviations": [
    {
      "objective": "OBJ-001",
      "original_method": "independent_t_test",
      "revised_method": "mann_whitney_u",
      "reason": "sofa_score is non-normal (Shapiro-Wilk p < 0.001, skewness = 1.8)",
      "approved_by": "auto (soft constraint S-001)",
      "logged_at": "2026-03-01T10:45:00"
    }
  ]
}
```

---

#### Phase 6: Execute Exploration — 執行探索

**目的**：按照（可能已修正的）計畫，逐步執行分析，**每一步都寫入 decision log**

| 子步驟 | 動作 | Hook | 產出 Artifact |
|--------|------|------|---------------|
| 6.1 資料清理執行 | 按 missing_strategy 執行 | — | `cleaned_dataset` + `cleaning_log.json` |
| 6.2 描述統計 | 全變數描述統計 | — | `descriptive_stats.json` |
| 6.3 Table 1 生成 | 基線特徵表 | S-009 | `table_one.csv` + `table_one.html` |
| 6.4 單變數分析 | 分佈、頻率、趨勢 | S-004 | `univariate_results/` |
| 6.5 雙變數分析 | 相關、組間比較 | S-002, S-009, S-010 | `bivariate_results/` |
| 6.6 automl 委派分析 | 送出預排的 automl 指令 | — | `automl_results/` |
| 6.7 敏感度分析 | 執行預定的 sensitivity analyses | — | `sensitivity_results/` |
| 6.8 視覺化 | 按分析結果生成圖表 | S-003 | `figures/` |

**Decision Log 格式**（每一步 append）：
```jsonl
{"timestamp":"2026-03-01T11:00:00","phase":6,"step":"6.3","action":"generate_table_one","method":"tableone","params":{"groupby":"mortality_30d","variables":["age","sex","sofa_score","cci_score"]},"result_ref":"artifacts/phase_06_execution/table_one.csv","decision":"Include all baseline variables per plan OBJ-002"}
{"timestamp":"2026-03-01T11:05:00","phase":6,"step":"6.5","action":"compare_groups","method":"mann_whitney_u","params":{"var":"sofa_score","groups":"mortality_30d"},"result_ref":"artifacts/phase_06_execution/bivariate_results/sofa_score_vs_mortality.json","decision":"Mann-Whitney chosen because normality check failed (Phase 5 deviation)","effect_size":"r=0.42","p_value":0.00012}
```

---

#### Phase 7: Collect Results — 收集與組織結果

**目的**：從分散的分析結果中，結構化收集、標記可發表內容

| 子步驟 | 動作 | 產出 Artifact |
|--------|------|---------------|
| 7.1 結果彙整 | 收集所有分析結果到統一結構 | `results_summary.json` |
| 7.2 顯著性標記 | 標記統計顯著的發現 | `significant_findings[]` |
| 7.3 效果量整理 | 所有 effect sizes + CI | `effect_sizes.json` |
| 7.4 圖表索引 | 所有圖表的路徑與描述 | `figure_index.json` |
| 7.5 表格索引 | 所有表格的路徑與描述 | `table_index.json` |
| 7.6 可發表性標記 | **標記哪些結果值得放入論文** | `publishable_flags` |
| 7.7 計畫符合度 | 檢查每個 objective 是否都有對應結果 | `plan_coverage.json` |

```json
// results_summary.json (excerpt)
{
  "objectives_coverage": {
    "OBJ-001": { "status": "completed", "key_finding": "SOFA score significantly associated with 30-day mortality (OR=1.35, 95% CI 1.21-1.51, p<0.001)" },
    "OBJ-002": { "status": "completed", "key_finding": "Table 1 generated, 12 of 15 variables significantly different between groups" }
  },
  "publishable_items": [
    { "type": "table", "ref": "table_one.csv", "suggested_label": "Table 1", "for_section": "Results" },
    { "type": "figure", "ref": "figures/sofa_mortality_boxplot.png", "suggested_label": "Figure 1", "for_section": "Results" },
    { "type": "finding", "text": "Higher SOFA scores were independently associated with 30-day mortality (adjusted OR 1.35, 95% CI 1.21–1.51, p < 0.001) after controlling for age, sex, and CCI.", "for_section": "Results" }
  ],
  "methods_summary": "Statistical analyses were performed using Mann-Whitney U test for continuous variables and Chi-squared test for categorical variables. Logistic regression was used for the primary outcome. Multiple testing was corrected using Bonferroni method (α = 0.05/3 = 0.017). Missing data for SOFA score (0.65%) were handled by multiple imputation (m=5)."
}
```

---

#### Phase 8: Report Assembly — 報告組裝

**目的**：組裝完整 EDA 報告。報告是比論文更完整的探索紀錄。

| 子步驟 | 動作 | Hook | 產出 Artifact |
|--------|------|------|---------------|
| 8.1 報告骨架 | 按 template 建立報告結構 | H-005 | report skeleton |
| 8.2 填入資料概述 | 資料集描述、schema 摘要 | — | §1-2 |
| 8.3 填入方法學 | 從 analysis_plan + deviations 生成 | — | §3 Methods |
| 8.4 填入結果 | 從 results_summary 生成 | — | §4 Results |
| 8.5 嵌入圖表 | 按 figure_index 嵌入 | — | inline figures |
| 8.6 嵌入表格 | 按 table_index 嵌入 | — | inline tables |
| 8.7 可發表段落標記 | 用 `<!-- PUBLISHABLE -->` 標記 | — | markers |
| 8.8 附錄：決策日誌 | decision_log 全文附上 | — | Appendix A |
| 8.9 附錄：偏離紀錄 | deviation_log 全文附上 | — | Appendix B |
| 8.10 附錄：完整統計輸出 | 所有原始統計結果 | — | Appendix C |
| 8.11 消毒 | 移除路徑、PII | H-006 | sanitized report |
| 8.12 完整性檢查 | 驗證所有必須章節存在 | H-005 | validation result |
| 8.13 產出最終報告 | Markdown + metadata | — | `eda_report.md` + `report_metadata.json` |

**報告結構**:
```markdown
# EDA Report: {title}
> Generated by Research Data Explorer v0.2.0
> Project: {project_id} | Date: {date} | Pipeline version: {version}

## 1. 研究背景與目的
## 2. 資料概述
### 2.1 資料來源
### 2.2 Schema 摘要
### 2.3 資料品質評估
## 3. 分析方法
### 3.1 分析計畫（原始）
### 3.2 計畫偏離與理由
### 3.3 統計方法
### 3.4 缺失值處理
### 3.5 多重比較校正
## 4. 結果
### 4.1 描述統計
### 4.2 基線特徵 (Table 1)             <!-- PUBLISHABLE:TABLE_1 -->
### 4.3 主要分析結果                    <!-- PUBLISHABLE:PRIMARY -->
### 4.4 次要分析結果
### 4.5 敏感度分析                      <!-- PUBLISHABLE:SENSITIVITY -->
## 5. 圖表
## 6. 建議與限制
## 7. Handoff → med-paper-assistant
### 7.1 可發表內容索引
### 7.2 建議的 Methods 段落
### 7.3 建議的 Results 段落
---
## Appendix A: Decision Log (完整決策紀錄)
## Appendix B: Deviation Log (計畫偏離紀錄)
## Appendix C: Raw Statistical Outputs
## Appendix D: Reproducibility Information
### D.1 Software Versions
### D.2 Random Seeds
### D.3 Execution Timeline
```

---

#### Phase 9: Audit Review — 審計檢查

**目的**：系統性地審查整個探索過程的品質與完整性

| 子步驟 | 動作 | 產出 Artifact |
|--------|------|---------------|
| 9.1 計畫符合度審計 | 每個 objective 是否有結果？ | `coverage_audit` |
| 9.2 方法適當性審計 | 使用的方法是否符合資料特性？ | `method_audit` |
| 9.3 偏離合理性審計 | 每個偏離是否有充分理由？ | `deviation_audit` |
| 9.4 效果量完整性 | 所有比較是否都有 effect size + CI？ | `effect_size_audit` |
| 9.5 多重比較處理 | 多重比較校正是否正確執行？ | `correction_audit` |
| 9.6 視覺化品質 | 圖表是否清晰、標籤完整？ | `visualization_audit` |
| 9.7 PII 最終檢查 | 報告中是否還有殘留的敏感資訊？ | `pii_final_check` |
| 9.8 再現性檢查 | 隨機種子、軟體版本是否記錄？ | `reproducibility_check` |
| 9.9 產出審計報告 | 彙整所有審計結果 | `audit_report.json` |

```json
// audit_report.json
{
  "overall_grade": "A",  // A/B/C/D/F
  "summary": "17/18 checks passed. 1 warning: sensitivity analysis for OBJ-003 not completed.",
  "checks": {
    "plan_coverage": { "pass": 5, "total": 5, "grade": "A" },
    "method_appropriateness": { "pass": 5, "total": 5, "grade": "A" },
    "deviation_justified": { "pass": 2, "total": 2, "grade": "A" },
    "effect_sizes_present": { "pass": 14, "total": 15, "grade": "A", "note": "OBJ-003 sub-analysis missing CI" },
    "multiple_comparison": { "pass": 1, "total": 1, "grade": "A" },
    "pii_clean": { "pass": 1, "total": 1, "grade": "A" },
    "reproducibility": { "pass": 1, "total": 1, "grade": "A" }
  },
  "warnings": [
    "OBJ-003 sensitivity analysis not completed — consider adding or documenting reason"
  ],
  "actionable_items": [
    { "severity": "LOW", "item": "Add confidence interval for OBJ-003 sub-group effect size" }
  ]
}
```

---

#### Phase 10: Auto-Improve — 自動改善

**目的**：根據審計結果自動修正可改善的項目，再次產出報告

| 子步驟 | 動作 | 產出 Artifact |
|--------|------|---------------|
| 10.1 讀取 audit 結果 | 解析 actionable items | — |
| 10.2 自動修正 | 補缺的 CI、修正圖表標籤等 | `auto_fixes.json` |
| 10.3 手動項目標記 | 無法自動修正的 → 標記給用戶 | `manual_items[]` |
| 10.4 重新生成報告 | 用修正後的結果重新組裝 | `eda_report_v2.md` |
| 10.5 二次審計 | 再跑一次 Phase 9（簡化版） | `re_audit_report.json` |
| 10.6 最終報告鎖定 | 標記 final 版本 | `final_report.md` + hash |
| 10.7 Handoff 產出 | 為 med-paper-assistant 準備接續檔案 | `handoff_package/` |

**Handoff Package 結構**:
```
handoff_package/
├── handoff_metadata.json    # 專案摘要、可發表內容索引
├── methods_draft.md         # 建議的 Methods 段落（作者可直接引用）
├── results_draft.md         # 建議的 Results 段落（作者可直接引用）
├── tables/                  # 發表等級的表格
│   ├── table_1.csv
│   └── table_1.html
├── figures/                 # 發表等級的圖表
│   ├── figure_1.png
│   └── figure_1.svg
└── supplementary/           # 補充資料
    ├── full_eda_report.md   # 完整 EDA 報告（含 appendices）
    ├── decision_log.jsonl
    └── analysis_plan.yaml
```

### 4.2 Pipeline Constraints

| 規則 | 說明 |
|------|------|
| **Phase Gate** | 每個 phase 必須完成才能進入下一個 |
| **Artifact Mandatory** | 每個 phase 必須產出指定的 artifacts |
| **Plan Lock** | Phase 4 鎖定後，偏離必須寫入 `deviation_log.jsonl` |
| **Decision Log** | Phase 6 的每個分析操作都寫入 `decision_log.jsonl` |
| **Append-Only** | decision_log 和 deviation_log 只能 append，不能修改 |
| **User Confirmation** | Phase 3 (對齊) 和 Phase 4 (計畫) 必須用戶確認 |
| **Idempotent** | 任何 phase 都可以重新執行（覆蓋 artifacts） |
| **Version Control** | 報告版本化（v1, v2, ...），保留所有版本 |

### 4.3 Audit Trail Completeness

```
完整審計鏈:
  project.yaml
    → intake_report.json
    → schema.json
    → concept_alignment.md
    → analysis_plan.yaml (LOCKED)
    → readiness_checklist.json
    → deviation_log.jsonl (偏離紀錄)
    → decision_log.jsonl (每步決策)
    → results_summary.json
    → eda_report.md (完整報告)
    → audit_report.json (品質評分)
    → final_report.md (最終版)
    → handoff_package/ (→ med-paper-assistant)

任何人（PI、reviewer、co-author）都可以:
1. 從 analysis_plan.yaml 看到「原本打算怎麼做」
2. 從 deviation_log.jsonl 看到「實際改了什麼、為什麼」
3. 從 decision_log.jsonl 看到「每一步怎麼做的」
4. 從 audit_report.json 看到「品質評分與改善紀錄」
5. 從 final_report.md 提取「可以放進論文的段落」
```

## 5. MCP Tools

### 5.1 RDE Core Tools

| Tool | Description | Phase |
|------|-------------|-------|
| `init_project` | 建立專案+目錄結構+初始設定 | 0 |
| `scan_data_folder` | 掃描目錄，列出檔案與安全檢查 | 1 |
| `run_intake` | 執行完整收件流程（格式+大小+PII） | 1 |
| `load_dataset` | 載入資料集 | 2 |
| `build_schema` | 建立完整 schema registry | 2 |
| `profile_dataset` | ydata-profiling 完整報告 | 2 |
| `align_concepts` | 研究概念→schema 變數映射 | 3 |
| `register_plan` | 建立+鎖定 analysis plan | 4 |
| `log_deviation` | 記錄計畫偏離 | 4+ |
| `run_precheck` | 執行所有前提檢查 | 5 |
| `execute_cleaning` | 執行資料清理 | 6 |
| `generate_table_one` | 生成 Table 1 | 6 |
| `analyze_variable` | 單變數分析 | 6 |
| `compare_groups` | 組間比較（自動選擇檢定） | 6 |
| `correlation_matrix` | 相關性分析 | 6 |
| `create_visualization` | 生成圖表 | 6 |
| `collect_results` | 彙整結果+標記可發表內容 | 7 |
| `assemble_report` | 組裝完整 EDA 報告 | 8 |
| `run_audit` | 執行審計檢查 | 9 |
| `auto_improve` | 根據審計自動改善 | 10 |
| `export_handoff` | 產出 handoff package | 10 |
| `get_pipeline_status` | 查看目前 pipeline 進度 | all |
| `get_decision_log` | 查看決策日誌 | all |
| `get_deviation_log` | 查看偏離紀錄 | all |

### 5.2 Delegated to automl-stat-mcp

| Tool | Description |
|------|-------------|
| `create_project` | 建立 automl 分析專案 |
| `upload_data` | 上傳資料到 automl 引擎 |
| `run_quality_check` | 資料品質檢查（automl 版） |
| `run_analysis` | 執行統計分析 |
| `generate_report` | 生成 automl 分析報告 |

## 6. Hook Architecture

### 6.1 Code-Enforced Hooks (Hard Constraints)

| ID | Hook | Trigger | Action |
|----|------|---------|--------|
| H-001 | File Size Guard | run_intake | 檔案超過 500MB 拒絕載入 |
| H-002 | Format Whitelist | run_intake | 僅允許 CSV/Excel/Parquet/SAS/SPSS/Stata/TSV |
| H-003 | Min Sample Size | run_precheck, compare_groups | n < 10 拒絕統計分析 |
| H-004 | PII Detection | run_intake, build_schema | 偵測到 PII 欄位時警告 |
| H-005 | Report Integrity | assemble_report | 報告必須包含所有必要章節 |
| H-006 | Output Sanitization | assemble_report | 清除暫存路徑與敏感資訊 |
| H-007 | Plan Lock | execute_* | Phase 6+ 操作必須有已鎖定的 plan |
| H-008 | Artifact Gate | phase transition | 前一 phase 的 artifacts 必須存在 |
| H-009 | Decision Logging | execute_* | Phase 6 每個分析操作必須寫入 log |
| H-010 | Append-Only Logs | log_deviation, decision_log | Log 檔案只能 append，不能修改或刪除 |

### 6.2 Agent-Driven Hooks (Soft Constraints)

| ID | Hook | Trigger | Guidance |
|----|------|---------|----------|
| S-001 | Normality Check | run_precheck, compare_groups | 非常態分佈 → 建議無母數檢定 |
| S-002 | Multiple Comparisons | compare_groups | 多組比較 → 建議 Bonferroni/FDR 校正 |
| S-003 | Visualization Advisor | create_visualization | 根據變數類型建議適當圖表 |
| S-004 | Transform Suggestion | analyze_variable | 偏態分佈 → 建議 log/sqrt 轉換 |
| S-005 | Missing Pattern | run_precheck | MCAR/MAR/MNAR 判斷與處理建議 |
| S-006 | Outlier Strategy | run_precheck | 極端值 → 建議處理策略 |
| S-007 | Collinearity Warning | run_precheck, correlation_matrix | VIF > 10 → 多重共線性警告 |
| S-008 | Sample Balance | run_precheck, compare_groups | 組間樣本量差距大 → 建議修正 |
| S-009 | Effect Size Reminder | compare_groups | 統計顯著不等於臨床意義 |
| S-010 | Power Analysis Hint | compare_groups | 非顯著結果 → 建議檢定力分析 |
| S-011 | Plan Deviation Alert | execute_* | 操作偏離計畫 → 提醒記錄理由 |
| S-012 | Sensitivity Reminder | collect_results | 主要結果 → 建議做敏感度分析 |

## 7. Report vs. Paper — 產出定位

```
┌──────────────────────────────────────────────────────┐
│                    EDA 完整報告                       │
│  (Full EDA Report — 透明、詳盡、經得起審視)           │
│                                                      │
│  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐        │
│                                              │       │
│  │  可發表內容 (PUBLISHABLE markers)         │       │
│     - Methods 段落                                   │
│  │  - Results 段落                           │       │
│     - Table 1                                        │
│  │  - Key Figures                            │       │
│     - Effect sizes + CI                              │
│  │                                           │       │
│  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘        │
│                        │                             │
│  + Decision Log (完整決策紀錄)                        │
│  + Deviation Log (計畫偏離紀錄)                       │
│  + Raw Statistical Output (原始統計輸出)              │
│  + Reproducibility Info (可再現性資訊)                │
│  + Audit Report (品質評分)                            │
└──────────────────────────────────────────────────────┘
          │
          │  作者提取有意義的部分
          ▼
┌───────────────────────┐
│     論文 (Paper)       │
│  Methods + Results     │
│  (由 med-paper-asst    │
│   接續編寫)            │
└───────────────────────┘
```

**原則**: 報告 ⊃ 論文。報告是完整記錄，論文是精華提取。

## 8. Technology Stack

| Component | Technology |
|-----------|-----------|
| MCP Server | Python (FastMCP / mcp-sdk) |
| Data Processing | pandas, polars |
| Profiling Engine | ydata-profiling |
| Statistical Engine | automl-stat-mcp (submodule) |
| Table 1 Generator | tableone |
| Comparison Reports | sweetviz |
| Visualization | matplotlib, seaborn, plotly |
| Report Format | Markdown (with PUBLISHABLE markers) |
| Artifact Store | File-based (JSON/JSONL/YAML/Markdown) |
| Decision Log | JSONL (append-only) |

## 9. Market Position

### 「5 個零」—— 完全空白的市場

| 維度 | 現況 |
|------|------|
| MCP + Agent + Instructions + Skill 組合 | 0 repos |
| 針對醫學研究者的 MCP 資料分析 | 0 repos |
| MCP → 結構化研究報告（含審計鏈） | 0 repos |
| ydata-profiling/sweetviz MCP 封裝 | 0 repos |
| MCP 工具鏈 (explorer → paper) | 0 repos |

### 與現有工具差異

| 工具 | EDA 能力 | 透明性 | 可再現性 | 審計 | 論文銜接 |
|------|---------|--------|---------|------|---------|
| Jupyter Notebook | ✅ | ❌ 黑箱 | ⚠️ 看人 | ❌ | ❌ |
| ydata-profiling | ✅ 自動化 | ⚠️ 報告 | ✅ | ❌ | ❌ |
| JASP/jamovi | ✅ GUI | ⚠️ | ✅ | ❌ | ❌ |
| **RDE** | ✅ 自然語言 | ✅ 完整 | ✅ 內建 | ✅ | ✅ |

### 可整合的成熟引擎

| 引擎 | Stars | 用途 |
|------|-------|------|
| ydata-profiling | 13,400★ | EDA 報告引擎（首選） |
| automl-stat-mcp | 自有 | 統計分析引擎 |
| tableone | 189★ | 臨床 Table 1 |
| sweetviz | ~3,000★ | 兩組比較報告 |
