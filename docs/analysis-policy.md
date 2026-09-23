# 可核對的分析政策（0.5.0）

`register_analysis_plan` 驗證 alpha、listwise/pairwise 與 bonferroni/holm/fdr。
`compare_groups` 未提供政策參數時讀取鎖定計畫；顯式參數與執行政策一起保存。
不把計畫中的字串視為已完成補值，沒有隐含 imputation。

- 組間比較：listwise 是**本次所有 outcome 與 group** 的共同完整列；pairwise 是每個 outcome/group 各自完整。每個結果保存 n_input/n_analyzed/n_excluded、缺失欄位、組別人數、零起始來源列位置。配對分析仍以 subject key 的完整對為單位，清楚標示與獨立列策略不同。
- 校正家族：同一次 compare_groups 的所有 outcome tests。statsmodels 實算 Bonferroni、Holm 或 Benjamini–Hochberg（fdr），保存原始／校正 p、方法與 alpha。顯著性及 report candidate 必須使用校正 p 與指定 alpha。其他呼叫、模型係數和探索分支不自動併入家族。
- 相關矩陣與熱圖：listwise 使用所有指定變項的共同完整列，pairwise 每對各自完整；JSON 保存每對樣本數／列位置，圖例顯示實際 cell n 範圍。純描述相關，沒有新增 p 值檢定。
- 進階分析：未指定 confidence_level 時採 1−計畫 alpha。local logistic/linear 模型保存實際編碼後完整個案；pairwise 不會變成 pairwise regression。係數及各估計的信賴區間是 pointwise，未做跨分析多重校正。Vendor 端結果仍以該 executor 的原始證據為準，不推定已核對其列集合。
- Table 1：`include_p_values=false` 預設只描述各變項可用資料，回報分組缺失與觀察數；此明確參數不受舊環境變數改寫。明確開啟的基線 p 值標為未校正。
- 圖表：MCP `create_visualization(include_tests=false)` 預設不加組間／scatter 檢定；分布與樣本數仍可查看。不要從圖表自行選最小 p 值作為主要結果。

來源 bytes 不變。需要看回原始缺失、非有限值與合理性過濾紀錄；來源列位置是該次資料 frame 的零起始位置，不是 patient identifier。可用個案分析不等於 ITT，也不能消除缺失偏差。

校正實作對照 [statsmodels multipletests](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html)。臨床基線只描述、預先指定共變項與分析方法的設計理由，參考 [CONSORT 2025 item 21a](https://www.consort-spirit.org/item21a-primaryandsecondaryoutcomes)。這些軟體政策不代替研究設計審閱。

驗證：`tests/test_analysis_policy.py` 涵蓋已知校正數值、不同缺失位置、非有限值、配對來源、圖表與矩陣一致、原始 bytes 不變、真實 MCP 讀取鎖定政策及錯誤政策不鎖定。完整 pytest 另含既有臨床／模型／探索／恢復回歸。
