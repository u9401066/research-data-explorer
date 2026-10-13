---
name: report-generator
description: "Phase 10 report assembly and export workflow. Use when user wants to generate, review, or export the EDA report. Triggers: 報告, report, assemble, export, 產出報告, 匯出."
---

# Report Generator

## 描述
Phase 10 的報告組裝工作流，包括品質檢查、敏感資訊清除、匯出。

## 觸發條件
- 「產出報告」「匯出結果」「report」「看報告」

## 法規依據
- 憲法：CONSTITUTION.md Article II §4
- H-005: 報告完整性
- H-006: 輸出清除敏感資訊

## 前提

報告組裝前必須確認：
1. Phase 9 `collect_results()` 已完成
2. `results_summary.json` 存在
3. `decision_log.jsonl` 存在

## 來源、範圍與最終解讀

先讀 live `get_workflow_contract` 與目前鎖定計畫；本檔為編輯器指引，網站指引由宿主平台另外載入。依同一次執行、相同來源與分析資料集版本讀取專用方法報告、`audit_report.json` 及 `report_readiness.json`，分頁必須完整覆蓋。舊研究成果不能替代本次缺少的報告。

核對 `scope`、`target_tier`、未通過項目與適用性；`descriptive_only` 等範圍完成不等於一般 production／投稿就緒。描述性研究不為補齊通用 Table 1 或圖數配額新增分析，缺少真實報告仍屬失敗。字母評級、DOCX／PDF 匯出成功及 `completed` 都不能替代科學解讀或實際版面檢查。保留計畫、資料版本與執行來源，說明真實納排、估計、不確定性與限制；沒有圖像像素不能聲稱看圖。

## 報告結構 (H-005 必備章節)

```markdown
# EDA Report — {project_name}

## 1. Executive Summary
## 2. Data Description
## 3. Data Quality
## 4. Analysis Plan (+ 偏離紀錄)
## 5. Findings
   - 每個結果附 effect size + CI
   - statistically significant candidates (audit required)
## 6. Visualizations
## 7. Limitations
## 8. Appendix
   - A: Decision Log (完整)
   - B: Deviation Log
   - C: Software Versions
```

## H-006 清除規則

自動清除以下內容：
| 模式 | 替換為 |
|------|--------|
| `<windows-user-path>/...` | `<project>/...` |
| `<linux-home>/...` | `<project>/...` |
| API keys, tokens | `<REDACTED>` |

## Candidate Finding Markers

報告中待作者核對的候選段落可用以下標記；標記不代表可直接投稿：
```markdown
<!-- CANDIDATE_FINDING:START -->
待核對來源、統計解讀與投稿要求的 Methods/Results 草稿
<!-- CANDIDATE_FINDING:END -->
```

## Handoff 到 med-paper-assistant

```
export_handoff()
→ handoff_package/
  ├ methods_draft.md
  ├ results_draft.md
  ├ tables/
  ├ figures/
  └ metadata.json
```
