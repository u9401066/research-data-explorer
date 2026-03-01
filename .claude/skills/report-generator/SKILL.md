---
name: report-generator
description: "Phase 8 report assembly and export workflow. Use when user wants to generate, review, or export the EDA report. Triggers: 報告, report, assemble, export, 產出報告, 匯出."
---

# Report Generator

## 描述
Phase 8 的報告組裝工作流，包括品質檢查、敏感資訊清除、匯出。

## 觸發條件
- 「產出報告」「匯出結果」「report」「看報告」

## 法規依據
- 憲法：CONSTITUTION.md Article II §4
- H-005: 報告完整性
- H-006: 輸出清除敏感資訊

## 前提

報告組裝前必須確認：
1. Phase 7 `collect_results()` 已完成
2. `results_summary.json` 存在
3. `decision_log.jsonl` 存在

## 報告結構 (H-005 必備章節)

```markdown
# EDA Report — {project_name}

## 1. Executive Summary
## 2. Data Description
## 3. Data Quality
## 4. Analysis Plan (+ 偏離紀錄)
## 5. Findings
   - 每個結果附 effect size + CI
   - PUBLISHABLE 標記
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
| `C:\Users\xxx\...` | `<project>/...` |
| `/home/xxx/...` | `<project>/...` |
| API keys, tokens | `<REDACTED>` |

## PUBLISHABLE 標記

報告中可直接用於論文的段落用以下標記：
```markdown
<!-- PUBLISHABLE:START -->
這段內容可直接用於論文 Methods/Results
<!-- PUBLISHABLE:END -->
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
