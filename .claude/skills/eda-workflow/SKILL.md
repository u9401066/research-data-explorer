---
name: eda-workflow
description: "11-Phase Auditable EDA Pipeline orchestration. Use when user wants to explore data, run analysis, or asks about the pipeline. Triggers: EDA, 資料探索, 分析資料, pipeline, 11-phase, analyze, 探索."
---

# EDA Workflow Orchestrator

## 描述
協調 RDE 11-Phase Auditable EDA Pipeline 的完整流程，確保每個 Phase Gate 正確通過。

## 觸發條件
- 「我有資料想分析」「分析這個 CSV」「資料探索」「EDA」
- 「pipeline 目前進度」「下一步是什麼」

## 法規依據
- 憲法：CONSTITUTION.md Article II, III
- 子法：.github/bylaws/pipeline-workflow.md
- Hook 清單：SPEC.md §6

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
align_concepts(research_question, variable_roles)
→ concept_alignment.md + variable_roles.json
```
**Agent 必須：** 向用戶展示對齊結果，等待確認。

### Phase 4: Analysis Plan Registration ⚠️ 用戶必須確認 → 🔒 鎖定
```
register_plan()
→ analysis_plan.yaml (LOCKED after confirmation)
```
**Agent 必須：** 展示完整計畫（方法、α 值、missing 策略），等待確認後鎖定。

### Phase 5: Pre-Exploration Check
```
run_precheck()
　├ [H-003] 樣本量 ≥ 10
　├ [S-001] 常態性檢定
　├ [S-005] 缺失模式 (MCAR/MAR/MNAR)
　└ [S-007] VIF 共線性
→ readiness_checklist.json
```
**如需調整方法：** `log_deviation()` → 告知用戶。

### Phase 6: Execute Exploration 🔒 計畫鎖定中
```
generate_table_one()
compare_groups() × N
analyze_variable() × N
correlation_matrix()
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
| 「比較兩組」 | 完整 Phase 0-5 → compare_groups → 7-10 |
| 「做 Table 1」 | 完整 Phase 0-5 → generate_table_one → 7-10 |
| 「完整分析」 | 完整 Phase 0-10 |
