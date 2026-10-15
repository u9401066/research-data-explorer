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

## 來源、範圍與最終解讀

先讀 live `get_workflow_contract` 與目前鎖定計畫；本檔為編輯器指引，網站指引由宿主平台另外載入。依同一次執行、相同來源與分析資料集版本讀取專用方法報告、`audit_report.json` 及 `report_readiness.json`，分頁必須完整覆蓋。舊研究成果不能替代本次缺少的報告。

核對 `scope`、`target_tier`、未通過項目與適用性；`descriptive_only` 等範圍完成不等於一般 production／投稿就緒。描述性研究不為補齊通用 Table 1 或圖數配額新增分析，缺少真實報告仍屬失敗。字母評級、DOCX／PDF 匯出成功及 `completed` 都不能替代科學解讀或實際版面檢查。保留計畫、資料版本與執行來源，說明真實納排、估計、不確定性與限制；沒有圖像像素不能聲稱看圖。

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
| `<windows-user-path>/...` | `<project>/...` |
| `<linux-home>/...` | `<project>/...` |
| API keys, tokens | `<REDACTED>` |

## PUBLISHABLE 標記

報告中待作者核對的候選段落可用以下標記；標記不代表可直接投稿：
```markdown
<!-- PUBLISHABLE:START -->
待核對來源、統計解讀與投稿要求的 Methods/Results 草稿
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
