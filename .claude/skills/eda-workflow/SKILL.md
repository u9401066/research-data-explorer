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
