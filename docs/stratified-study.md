# 二元分層比較：CMH 與 Mantel–Haenszel OR

`StratifiedSpec(family="stratified")` 將二元治療、二元結果與預先指定的分層固定在同一份規格。
Python 原生計算使用 statsmodels `StratifiedTable`；此模組不提供任意廣義 CMH、精確分層檢定、
modified-ridit、風險比、非劣性、配對或群集試驗推論，也不是一般多層模型。

## 輸入及流程

| 欄位 | 必要內容 |
| --- | --- |
| `subject` | 非空、全來源唯一的個案識別欄；缺失剔除前即核對，不能拿重複人次當人數。 |
| `treatment`, `treatment_levels` | 治療欄與兩個原碼，順序固定為 `[reference, exposed]`。 |
| `outcome`, `outcome_levels` | 二元結果欄與原碼，順序固定為 `[non_event, event]`。 |
| `strata`, `strata_levels` | 一個原始／核准派生分層欄，以及預先列完整的 2–50 層順序；空層也列出。 |
| `treatment_definition`, `outcome_definition`, `outcome_window`, `context` | 治療與事件的研究定義、結果評估時間窗及研究背景，不從欄名推定。 |
| `study_design` | `randomized_parallel`、`observational_cohort`、`cross_sectional`、`case_control` 或 `unspecified`。 |
| `independent_rows` | 必須明示 `true`，代表層內及層間各人獨立；工具不驗證研究者的宣告本身。 |
| `missing_strategy` | 明示 `complete_case`；治療、結果及分層採共用完整個案集合，不插補。 |
| `confidence_level` | 預設 `.95`；允許 `.8`–`.999`，固定於核准規格。 |

`parse` 拒絕未知欄位；`to_dict` 保存完整規格；`variables` 回傳原始角色欄位。
多欄分層應在 RDE 資料準備階段建立可追溯複合欄，不能在本工具依結果選層或合併稀疏層。
本版沒有額外 `cohort_filter`，納排先由核准資料準備完成。

1. `prepare_stratified(df, spec)` 先核對來源與所有已觀察到的代碼，才排除缺失。
   回傳處理後 frame、共同 case ledger、來源欄與值的 SHA256。
2. `stratified_preflight(df, spec)` 顯示每層 2×2、原來源／完整個案數、缺失與退化層，
   不計算效果量、CI 或 P 值。來源及完整個案的 10 人下限是執行界線，不是檢定力證明。
3. 在來源與規格固定、原生流程核准／鎖定／readiness 通過後，
   `run_stratified(df, spec)` 執行一個事前指定的二元 CMH 主假說、共同 OR 與同質性診斷。
   整合層仍須使用既有 MCP 執行／稽核邊界，不能由直接呼叫計算函式繞過計畫授權。

## 計算方向與輸出

每層表格的列為 `[reference, exposed]`，欄為 `[non_event, event]`：

```text
                     non_event   event
reference                 a         b
exposed                   c         d
```

因此共同 OR 為 `sum(a*d/n) / sum(b*c/n)`，意義是 exposed 相對 reference 的事件勝算比。
反轉任一組原碼順序會使 OR 取倒數，CMH 的雙側關聯檢定不變。來源原碼不猜義，
字串不修剪；數值代碼沿用 RDE 的一致原碼正規化方式。

輸出 `schema="clinical-result-v1"`、`method_schema="stratified-binary-v1"`，包含：

- `spec`、`spec_sha256`、`dataframe_sha256`、`receipt_sha256` 與套件版本。
- `case_ledger`、每層 2×2、獨立性虛無下期望格數、逐列 `data_row` 追溯。
- `cmh`：不作連續性修正的 1 df CMH χ² 與漸近 P 值；以 SciPy survival function
  計算尾端機率，避免 `1-cdf` 的相消誤差。
- `common_odds_ratio`：MH OR 與 log 尺度常態區間，採
  Robins–Breslow–Greenland 變異後轉回 OR；不是精確區間。
- `equal_odds`：Breslow–Day／Tarone 同質性診斷，df 為層數減一。
  這是診斷，不用其 P 值決定是否刪層或停止呈現主要結果。

上述統計與獨立性前提依 [statsmodels StratifiedTable 官方文件](https://www.statsmodels.org/stable/generated/statsmodels.stats.contingency_tables.StratifiedTable.html)。
同質性診斷的調整見 [test_equal_odds 官方文件](https://www.statsmodels.org/stable/generated/statsmodels.stats.contingency_tables.StratifiedTable.test_equal_odds.html)。

## 退化、缺失與推論界線

所有宣告層都保留。空層、完整人數不足兩人或治療／結果零邊際會列入 preflight
`blocking_strata`；執行拒絕匯總，不默默丟層。單一零格但各邊際仍正的層可以保留，
**不加 0.5**。每層期望格數小於 5 會顯示警示，漸近結果不因此變成精確檢定。

OR 在零或無界邊界時保留明確 `boundary`；無界值以 `null` 加狀態呈現，
無法取得的 log 常態 CI 不填零。CI 或診斷不可估仍不會捏造 P 值。
目前 statsmodels 的同質性公式在共同 OR 恰為 1 時有除零邊界；本工具保留可估的
CMH／OR／CI，同質性診斷標記 `not_estimable` 與原因，不冒充 P=1。

共同 OR 不等於 RR、風險差或因果效果；case-control 與未知抽樣尤其不能藉事件比例外推母群風險。
缺失完整個案不證明 MCAR/MAR。同質性檢定不顯著或不可估不證明共同 OR 假設成立。
跨多個主要／次要終點的多重性需另外在計畫中管理，本工具只宣告一個 CMH 主假說。

## 測試範圍

原生 `inspect_clinical_study` 回傳完整規格與每層計數；以唯一
`run_clinical_study` bundle 登錄並鎖定計畫後執行。頂層 plan 使用
`missing_strategy="listwise"`、`multiple_comparison_method="none"`、
`alpha=1-confidence_level`；內層 spec 維持 `missing_strategy="complete_case"`。
`none` 僅表示本 family 的一個 CMH 主假說；不授予跨終點任意未校正推論。

原生結果收集／readiness／組裝報告核對共同完整分母、全部宣告層、逐列追溯及產物 hash。
預設英文圖為 population flow、分層 2×2 表與共同 OR／CI；大表分頁，另附中文解釋，
保存 SVG／PDF、300 dpi PNG／TIFF、圖說與逐值 CSV。無界／零 OR 的圖會明示邊界，
不畫有限點或虛構區間。`render_publication_figures` 從凍結收據重繪，不重新估計。

`tests/test_clinical_stratified.py` 用手寫 2×2 計數及獨立有理數運算核對
超幾何條件期望／變異所得到的 CMH χ²、MH OR，另以可手算的重複同表核對 log CI。
測試包括方向反轉、列序／分層順序改變、來源 hash 與逐列追溯、非法碼先於缺失排除、
重複個案、空層、零邊際、零格、OR 邊界、稀疏格與 case-control 風險不得外推。
`tests/test_missing_stratified_workflow.py` 經實際 MCP dispatch 核對計畫政策、執行、
readiness、報告、免重估重用／重繪、輸出 hash／DPI、來源變更拒絕、邊界結果正常報告。
這不代表完成某篇期刊重算、真實個案核對或平台／Agent 全流程驗證。
