# Pipeline Workflow Bylaw

> Version: 1.0.0 | 依據：CONSTITUTION.md Article II, III

## §1 Phase 轉換規則

### 1.1 Artifact Gate (H-008)

進入 Phase N 之前，Phase 0 ~ N-1 的所有必要 artifact 必須存在。

| Phase | 必要 Artifact |
|-------|---------------|
| 0 | `project.yaml` |
| 1 | `artifacts/phase_01_intake/intake_report.json` |
| 2 | `artifacts/phase_02_schema/schema.json` |
| 3 | `artifacts/phase_03_concept/concept_alignment.md` |
| 4 | `artifacts/phase_04_plan/analysis_plan.yaml` |
| 5 | `artifacts/phase_05_precheck/readiness_checklist.json` |
| 6 | `decision_log.jsonl` (Phase 6+ 需持續寫入) |
| 7 | `artifacts/phase_07_results/results_summary.json` |
| 8 | `artifacts/phase_08_report/eda_report.md` |
| 9 | `artifacts/phase_09_audit/audit_report.json` |

### 1.2 User Confirmation Gate

以下 Phase 轉換需要**用戶明確確認**：

- Phase 3 → 4: 概念對齊結果確認
- Phase 4 鎖定：分析計畫確認

Agent 不得自動跳過確認步驟。

### 1.3 Plan Lock (H-007)

- Phase 4 計畫鎖定後不可修改
- Phase 6+ 偏離計畫必須 `log_deviation()` 並附理由
- 偏離不需要用戶每次確認，但報告中必須顯示

## §2 Quick Explore 例外

Quick Explore 模式允許跳過 Phase 3-5, 7, 9-10，但：
- 報告必須標記「Quick Explore — Not Audited」
- 不得標記任何內容為 PUBLISHABLE
- Decision log 仍然必須記錄

## §3 automl-stat-mcp 委派

### 3.1 委派條件

以下分析應委派給 automl-stat-mcp（如服務可用）：
- Propensity Score Matching
- Survival Analysis (Kaplan-Meier, Cox)
- ROC/AUC Analysis
- Advanced Power Analysis (非標準設計)
- Multiple Regression / GLM
- Machine Learning (AutoML)

### 3.2 Fallback

automl-stat-mcp 不可用時：
- 基礎統計 → ScipyStatisticalEngine 處理
- 進階分析 → 告知用戶服務未啟動，建議 `docker compose up`

### 3.3 Decision Log

委派 automl 的操作同樣寫入 `decision_log.jsonl`，並標記 `source: automl-stat-mcp`。

## §4 Deviation Handling

### 4.1 何時必須記錄偏離

| 情境 | 必須記錄 |
|------|----------|
| Phase 5 發現前提不符，需改方法 | ✅ |
| 用戶臨時要加分析 | ✅ |
| 樣本量不足改無母數檢定 | ✅ |
| 修正 typo | ❌ |
| 增加圖表 | ❌ (但需 decision_log) |

### 4.2 偏離記錄格式

```json
{
  "timestamp": "ISO-8601",
  "phase": "phase_06",
  "planned_action": "t-test",
  "actual_action": "Mann-Whitney U",
  "reason": "Shapiro-Wilk p < 0.05, 不符常態假設",
  "impact_assessment": "結果解讀不受影響，無母數方法更適當"
}
```
