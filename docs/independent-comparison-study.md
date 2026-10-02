# 預先指定的獨立組比較（開發版）

`inspect_clinical_study`／`run_clinical_study` 新增 `family="comparison"`，沿用唯一鎖定計畫、來源檔／工作表／資料框雜湊、固定個案集合、完整報告與保存成果的檢查。版本維持 RDE 0.5.0。這是明確指定效果量與比較對象的新研究契約；既有 `compare_groups` 的 `comparison-inference-v2` 收據仍沒有信賴區間，不能用換圖樣式將其變成新研究。

本階段已驗證 RDE MCP 後端；Workbench 表單、LLM 工具設定、研究計畫審閱與正式站部署仍待整合。下面的工程資料驗證不等於已完成實際臨床研究或期刊投稿審閱。

## 固定研究問題

必填 outcome、group、group_levels（2–8 個精確原碼，決定顯示順序）、contrasts（1–12 個有方向的兩組對比）、method、primary_effect、outcome_unit、outcome_definition、outcome_window、context、study_design、independent_rows=true。差值為第一組減第二組；比值為第一組除第二組。反向重複對比被拒絕，不由資料自動挑比較對象或方法。

可指定 subject、cohort_filter、confidence_level（0.8–0.999）、multiplicity（holm／bonferroni／fdr）與 omnibus（至少三組）。結果欄、組別欄及身份欄須不同；身份缺失／重複和非法原碼先於結果缺失排除檢查。來源列數限制為 10–100,000，共同完整個案至少 10、每組至少 2，這些是執行限制而非檢定力條件。

| 方法 | 主要效果量 | 區間 | 檢定 |
|---|---|---|---|
| welch_mean | mean_difference，保留原單位 | Welch–Satterthwaite t | 雙尾 Welch t |
| rank | rank_biserial，P(第一組較大)−P(第一組較小)，平手貢獻零 | 各組獨立重抽樣 BCa | 雙尾 Mann–Whitney，保存實際 exact／asymptotic 政策 |
| binary | proportion_difference／proportion_ratio／odds_ratio | Newcombe–Wilson／Miettinen–Nurminen score／central exact conditional OR | 固定邊際、probability ordering 的雙尾 Fisher |

rank 結果必須是明確的數值有序尺度，且指定 `bootstrap={"resamples":1999,"seed":20261002}`；允許 999–19,999 次、uint32 seed。使用 PCG64、各對比依計畫順序 seed 加一（mod 2³²），保存批次大小、實際抽樣次數、分布雜湊、bias percentile、analytic delete-one acceleration 與調整後 quantiles。批次最多 64，並受每批一百萬個抽樣值的記憶體限制。秩效果不是中位數差；退化影響值、非有限 bias correction 或 BCa pole 不偷偷改用另一種區間。

binary 另指定 `outcome_levels=[非事件原碼,事件原碼]`。病例對照（case_control）或未確定抽樣（unspecified）只提供條件勝算比；不計算母群事件比例及比例差／比。其他設計保存三種效果，主要效果量明列，其他效果是同一對比的補充，不算作新的獨立檢定。勝算比的點估計是 conditional MLE，與舊的 sample OR 不同。比例比採約束二項概似的 score 反演，固定 N/(N−1) 修正、不加虛擬事件；零事件／全事件仍直接處理。

三組以上可明確要求 Welch ANOVA、Kruskal–Wallis 或 Pearson 整體檢定。二元整體檢定若任一預期格數小於 5，審閱前即拒絕；需另行規劃精確／置換方法，或明確保留原計畫的兩組對比，不自動合併類別或換方法。

## 不確定性與共同個案

全部對比從同一結果／組別完整個案集合選取。原始列號從 1 起算、不含標題，每列納入／範圍外／必要欄位缺失狀態保存於 CSV。固定身份欄並不能證明觀察獨立、ITT 或因果識別。

每個區間均為逐項、未多重校正的區間。p 值家族包含所有事先指定對比及可選的整體檢定；計畫 alpha 必須等於 1−confidence_level，missing_strategy=listwise，multiple_comparison_method 必須符合 spec。不能估計的檢定仍保留其家族位置，內部中性校正值不輸出成虛構 p=1。

BCa 與 Mann–Whitney、Newcombe／比例比 score 與 Fisher，以及 central exact OR 區間與 probability-ordered Fisher 雙尾 p 不一定互為反演。區間是否包含無效值不能代替家族校正判定，未達門檻不等於等效。多個研究、結果變項或分支不自動納入同一校正家族。

數值使用嚴格 JSON，各 scalar 明列 finite／positive_infinity／negative_infinity／undefined。區間另有 available／unavailable 與原因。全部無事件的比值點估計可未定義，而合法參數空間仍為 [0,+∞]；這不是有精度的效果估計。Welch 零樣本變異或 BCa 退化不產生假的零寬區間。

## 報告及投稿圖

保存中文完整報告、效果／分組／原始觀察／全部假說／逐列納排 CSV。投稿圖提供英文標籤及英文圖說，平台解釋為繁體中文。圖說保留 G1…G8 原始組碼、U1 單位、事件定義、觀察窗口、方向、實際方法與限制。

- 共同個案流程。
- 連續結果的全部原始點及保存的四分位／中位數／1.5 IQR 鬚線；圖上抖動僅用於顯示。病例對照顯示計數，其他二元設計顯示比例及 Wilson 區間。
- 每種主要／補充效果的對比圖，每頁最多六項。比值使用對數軸；零、未定義與無限大點估計只在數字欄表達，不放到虛假的座標。開放邊界用箭頭，有限界限全部保留；區間無法估計時有明確文字。

每圖包含原生 PDF／SVG、PNG／LZW TIFF、完整圖說及繪圖數據。一般預設 300 dpi；期刊預設沿用各自技術規格。Nature／PLOS 樣式、圖號和圖說版本只能讀取固定數值，不能重新 fit／bootstrap、改參照或刪掉不顯著對比。實際投稿仍須核對期刊、研究情境及統計解讀。

## 驗證依據

- `tests/fixtures/comparison-intervals/reference.R` 在既有 R 4.5.3 容器獨立計算 8 組二元邊界與 Welch 案例。比例比使用數值約束概似最佳化，條件 OR 使用固定邊際組合數列舉，並未共用 Python 的二次方程實作。JSON 保存來源程式及容器 image 雜湊。
- BCa 以 SciPy 實際 delete-one jackknife 和獨立逐對比較統計核對；另測試組別反向、退化、不同尺度、非法代碼、共同個案與完整校正家族。
- 六個外部 stdio MCP 流程：Welch、rank、二元邊界、病例對照、常數資料、足夠預期格數的二元整體檢定。每次走來源收件、schema、概念確認、計畫審閱／鎖定、readiness、分析、報告、audit、期刊版本，重啟後取回原收據；合計核對 522 份成果雜湊。
- 一般、Nature 單欄與 PLOS 文字欄使用同一數值 CSV；最多八組與跨頁對比、無限界限、原始中文標籤、資料破壞後拒絕覆寫都有回歸檢查。本次人工檢視 3 張 PNG 與 8 張實際 PDF 轉繪，涵蓋平均差、秩效果、比例差／比、跨頁勝算比、不可估計區間與病例對照計數；未宣稱每張每種格式均經人工審閱。

方法依據：[SciPy bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)、[SciPy conditional odds ratio](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.contingency.odds_ratio.html)、[statsmodels 兩比例區間](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.confint_proportions_2indep.html)、[score test 實作](https://www.statsmodels.org/stable/_modules/statsmodels/stats/proportion.html)。本次本機核對版本為 SciPy 1.16.3、statsmodels 0.15.0、NumPy 2.3.5；保存在各次數值收據，不以網頁最新版本代替實際執行環境。

2026-10-02 驗證：聚焦比較套件含授權 Arial 字型的期刊測試 33 passed；完整非 vendor 套件 741 passed、49 skipped、5 deselected。Ruff lint／format 通過。正式站仍使用先前已驗證版本，新的比較研究尚未部署。
