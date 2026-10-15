---
name: eda-workflow
description: "13-Phase Auditable EDA Pipeline orchestration. Use when user wants to explore data, run analysis, or asks about the pipeline. Triggers: EDA, 資料探索, 分析資料, pipeline, 13-phase, analyze, 探索."
---

# EDA Workflow Orchestrator

## 描述
協調 RDE 13-Phase Auditable EDA Pipeline 的完整流程，確保每個 Phase Gate 正確通過。

## 觸發條件
- 「我有資料想分析」「分析這個 CSV」「資料探索」「EDA」
- 「pipeline 目前進度」「下一步是什麼」

## 法規依據
- 憲法：CONSTITUTION.md Article II, III
- 子法：.github/bylaws/pipeline-workflow.md
- Hook 清單：SPEC.md §6

## 執行範圍與完成證據

- 先讀 live `get_workflow_contract`、工具 schema 與目前計畫；以下流程是導覽，不是固定要全部執行的方法清單。網站內的 agent 指引由 Workbench 編譯，不會自動載入本檔。
- 核准綁定精確計畫與來源／分析資料集版本。研究計畫已鎖定後，只執行登錄的方法；樣本數規劃屬研究設計階段，不能在已看結果的分析分支補做事前規劃。autoresearch 候選保留獨立探索標記，不自動升格成主要研究。
- 下列人工確認適用互動式編輯器流程。宿主有已保存的全自動授權及審閱機制時，依該宿主契約核對，不重問已授權的操作；模型不能自行聲稱得到授權或以 `confirm=true` 取代審閱。
- 未知臨床定義維持未知。可先鎖定可行的描述性階段，保留事件／病人分母和缺失；不可將指定推論悄悄改成描述，或把重複事件當成獨立病人。
- 執行後完整讀取本次工作的專用方法報告與 `audit_report.json`、`report_readiness.json`。按工具提供的分頁接續；不能只讀尾頁、舊工作報告或用 `completed` 宣稱已完成解讀。
- 核對 readiness 的 `scope`、`target_tier`、缺口及適用性。`descriptive_only` 不要求通用投稿圖表配額，不代表可投稿；稽核等級也不是科學品質證書。`auto_improve` 不授權新增未核准分析。

## 原始多表：先完成 Data Aggregation

- 使用同一個 `data_preparation` MCP：先讀 `op="contract"` 的原生 `aggregation` registry／schemas，再用 `inspect` 取得每張表的 source schema、候選鍵與 observed constraints。候選鍵不等於已確認的病人／就醫識別，原始表也不是已完成準備的分析資料。
- 以 `aggregation_compose` 的 unit／已知 definitions 建立候選，或從保存的 `from_specification` 建立分支；後續以 `aggregation_patch` 修改精確 `candidate_ref` 下的 relation ID／feature output／window／cohort。保留未提及規則；使用 native typed operations，不生成 Python／SQL、不為每次修正重寫整份規格。缺少研究事實保持未知，不能靠省略來源或補造定義取得通過。
- 依 registry 選方法：`unique` 是全選定範圍的一個唯一非缺失值，不是 distinct count；`count` 是事件列數；`first/last` 是有值的最早／最新事件時間，同時點異值會阻擋、同值保留所有來源，不需另造衝突欄位。不要為修正 event feature 而改壞另一個 lookup。
- `aggregation_preview` 後，依 diagnostic 的 relation／feature／stage 定位修正。用同一 reference＋`preview_sha256` 透過 `aggregation_read` 分頁核對 issues、units/output 和 cell trace；`aggregation_diff` 比較規則與已有預覽。分開報告事件配對、來源列、分析單位與病人數；未知涵蓋和缺失不是零值。
- 候選及 preview 都不是核准。已知定義與規則通過審閱後，仍須 draft → 完整核對 → approve → release → bundle → prepared intake；宿主若有自動授權，使用原生 `automated_review` 的 sealed receipt，保留 `clinical_validation="not_performed"`，不得宣稱人工／臨床驗證或完整研究完成。後續分析／autoresearch固定發布資料版本，規則改變走新準備版本。
- 保留完整 request／revision UUID以供失聯後 exact replay；stale reference先讀取比對，不把同一意圖偷偷套到新head。RDE repo內的完整說明為 `docs/DATA_AGGREGATION.md`／`docs/DATA_PREPARATION.md`；安裝環境以 live contract為準。網站的模型指引仍由Workbench宿主載入，不能假設它會讀本skill。

## Typed clinical 研究：探索契約、鎖定與報告

本節只引導選用原生工具，不授予執行權限；既有確認／宿主授權仍適用。網站的研究 plugin 由 Workbench 載入，不能假設網站會讀取編輯器 SKILL。

1. 先查 live `get_analysis_catalog(family=目標家族, detail=true)`，完整讀取工具 schema、來源角色與不支援變體；方法名稱相近不能代換。用 `inspect_clinical_study(dataset_id, clinical_options)` 核對完整規格、來源 hash、人口 ledger、阻擋與限制。Preflight 不等於核准或方法有效性的認證。
2. 以同一份完整 `clinical_options` 呼叫 `propose_analysis_plan(..., clinical_options=..., confirm=false)`，核對 proposal 的唯一 `run_clinical_study` bundle。依既有授權審閱後，用相同規格確認 proposal，再 `register_analysis_plan(..., confirm=true)`；不要讓通用 greedy 候選替換或擴增這份指定分析。頂層 missing／alpha／multiplicity 必須符合 live family 契約，不能靠舊分析／清理工具繞過。
3. 通過 readiness 後，`run_clinical_study` 必須使用已鎖定的完整規格及來源版本。修改 margin、caliper、插補設定、時間窗或角色須修訂並核准新計畫。這些新家族的 branch／autoresearch 尚未提供可執行契約；不可用舊分支改變研究方法。

| 家族 | 本版可選範圍與不可代換的界線 |
| --- | --- |
| `imputation` | 獨立個案、連續／二元 PMM；conditional OLS／Binomial GLM 都從觀察 donor 抽值，Gaussian／binomial 分析模型及 Rubin covariance、漸近 Wald。不是 Bernoulli logreg draws、Barnard–Rubin 小樣本推論、MNAR／多層／存活 MI；完整個案比較不能證明 MAR。 |
| `stratified` | 二元 treatment／outcome 的預指定 2×2 分層 CMH、共同 MH OR 與同質性診斷。不是精確／廣義 CMH、多層模型、配對或分層非劣性；不依結果刪層。 |
| `noninferiority` | 獨立兩組連續終點的 `welch_mean`，預指定原單位 margin、方向、族群與單側 alpha。不能替代二元、存活、配對非劣性或等效性；完整個案不自動代表 ITT／PP。 |
| `matching` | `optimal_1to1_logit_caliper`，1:1 無放回；`matched_treated` 族群，pair-cluster CR1 t 近似推論。丟失 treated 後不宣稱原全體 ATT，不能冒稱 estimated-PS 的完整不確定性已校正。 |
| `target_trial` | 基線單次 treatment、每人單一 time-zero、固定且完整追蹤，沿用既有 weighting 估計。先呼叫 `get_target_trial_contract` 取得已核准 preparation 的精確 binding，再以可追溯來源完成 protocol 並 inspect；不得自行填造 binding、用 boolean 取代來源證據，或以普通 weighting 冒稱 TTE。時變／動態策略、CCW、失訪／不完整追蹤與多 index 均不在本版範圍。 |

執行或以相同 `execution_key` 重取，都要讀取來源與全部 artifact hash 的驗證結果。缺 JSON／CSV／圖或來源改變必須保留失敗證據，不能把重新估計當成修復快取。`collect_results`／`assemble_report`／出版圖使用本次凍結收據；重繪只改呈現，不重新插補、配對或估計。

報告須保留原始、排除及實際分析分母：MI 的 m 份資料不是 n×m 人；matching 的配對前完整人口不等於最終配對人口；TTE 的來源核對不證明無未測量混雜。Gaussian 模型的 binary predictor 係數仍是 outcome 原單位均差，只有 binomial 模型係數是 log-odds，不能因 predictor 是二元就轉成 OR。NI 的完成狀態不等於通過非劣性，須讀其 margin、單側下限與 decision。平衡／收斂圖、readiness、匯出成功均不能替代研究定義與科學審閱。

## 完整流程

### Phase 0: Project Setup
```
init_project(name)
→ project.yaml + artifacts/ 目錄樹
```

### Phase 1: Data Intake
```
scan_data_folder(path)
run_intake()
　├ [H-001] 檔案大小 < 500MB
　├ [H-002] 格式白名單 (CSV/Excel/Parquet/SAS/SPSS/Stata/TSV)
　└ [H-004] PII 初篩
→ intake_report.json
```

### Phase 2: Schema Registry
```
load_dataset(file)
build_schema()
profile_dataset()           # ydata-profiling (fallback: basic engine)
→ schema.json + profile report
```

### Phase 3: Concept–Schema Alignment ⚠️ 用戶必須確認
```
align_concept(research_question, variable_roles, confirm=true)
→ concept_alignment.md + variable_roles.json
```
**Agent 必須：** 向用戶展示對齊結果，等待確認。

### Phase 3.5: Greedy Plan Ideation（自主 EDA 時建議）
```
propose_analysis_plan()
→ greedy_analysis_candidates.json + greedy_analysis_candidates.md
→ greedy_analysis_review.json + greedy_analysis_review.md
→ greedy_execution_schedule.json + greedy_execution_schedule.md
```
**Agent 必須：** 當使用者要 agent 自主規劃，或尚未提供明確分析清單時，先產生候選 blueprint。此步現在包含內部 methodology review + repair，會補足缺失的分析家族，而且必要時可擴張 soft budget 保留額外 EDA 路線，再進 Phase 4。execution schedule artifact 可直接作為 Phase 6 排程骨架。

### Phase 4: Analysis Plan Registration ⚠️ 用戶必須確認 → 🔒 鎖定
```
register_analysis_plan(confirm=true)
→ analysis_plan.yaml (LOCKED after confirmation)
```
**Agent 必須：** 展示完整計畫（方法、α 值、missing 策略），等待確認後鎖定。若 plan 明顯低於方法學最低覆蓋要求，Phase 4 會先自動補入 exploratory extension；若補完後仍不足才在鎖定前擋下，除非明確使用 override flag。鎖定時同步保存 analysis execution schedule，供 Phase 6 依序執行。

### Phase 5: Pre-Exploration Check
```
check_readiness()
　├ [H-003] 樣本量 ≥ 10
　├ [S-001] 常態性檢定
　├ [S-005] 缺失模式 (MCAR/MAR/MNAR)
　└ [S-007] VIF 共線性
→ readiness_checklist.json
```
**如需調整方法：** `log_deviation()` → 告知用戶。

### Phase 6: Execute Exploration 🔒 計畫鎖定中
```
# 僅執行已鎖定的資料準備與方法；下列為可選工具例，不是必跑清單
apply_cleaning()
generate_table_one() / compare_groups() / analyze_variable() / correlation_matrix()
→ H-009: 每步自動寫入 decision_log.jsonl
→ S-002 多重比較, S-009 Effect size, S-010 Power
```
**偏離計畫時：** 必須 `log_deviation()` 並說明理由。

### Phase 7: Collect Results
```
collect_results()
→ results_summary.json (含 PUBLISHABLE markers)
```

### Phase 8: Report Assembly
```
assemble_report()
→ eda_report.md (含 decision_log + deviation_log appendix)
```

### Phase 9: Audit Review
```
run_audit()
→ audit_report.json (A/B/C/D/F 評分)
```

### Phase 10: Auto-Improve
```
auto_improve()     # 根據 audit 自動修正
export_handoff()   # 產出 handoff package → med-paper-assistant
```

## 防呆清單

| 檢查點 | 規則 | 後果 |
|--------|------|------|
| Phase 3 | 用戶確認 | 未確認不能進 Phase 4 |
| Phase 4 | 用戶確認 + 鎖定 | 未鎖定不能進 Phase 6 |
| Phase 6 偏離 | 必須 log_deviation | 審計時扣分 |
| Phase 8 報告 | H-005 完整性 + H-006 路徑清除 | 不完整或有敏感路徑則失敗 |
| Any Phase | H-008 artifact gate | 前一 Phase 未完成不能跳過 |

## 快速路徑

| 用戶意圖 | 走哪條路 |
|----------|----------|
| 「只想看概況」 | Phase 0→1→2 → profile → Quick Report |
| 「比較兩組」 | 完整 Phase 0-7 → compare_groups → Phase 9-12 |
| 「做 Table 1」 | 完整 Phase 0-7 → generate_table_one → Phase 9-12 |
| 「讓 agent 自主規劃」 | Phase 0→1→2→3 → propose_analysis_plan → 4→10 |
| 「完整分析」 | 完整 13-Phase |
