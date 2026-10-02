# 傾向加權：實作與驗證狀態

2026-10-02：來源契約、preflight 與數值核心已實作，尚未接入 MCP、報告或平台。
RDE 維持 0.5.0；這不是已可執行完整加權研究的宣告。

`WeightingSpec` 要求二元處置、連續或二元結果、原始代碼、來源單位、time zero、
結果確認方式與窗口，以及每個共變項的處置前量測依據。限定獨立個案的觀察性世代，
事先指定 ATE、ATT 或 ATO；未確認的時序與因果條件不能由資料檢查代為證明。

`weighting_preflight` 固定共同完整個案，依序檢查納入限制、個案識別欄、來源代碼／數值、
缺值與模型矩陣。ID 缺失／重複及非法代碼，不能被另一欄缺值的排除遮蔽。納排紀錄
保留一開始的來源列號；結果值參與來源指紋，但不進入 propensity 設計矩陣。
類別、參照、樣條結點與交互作用採用既有明示型別契約，不執行來源欄名中的公式。
不提供自動選變項、權重裁切、補值、群集或時變處置的隱含替代。

來源契約的 9 個聚焦邊界案例通過；該階段完整非 vendor 測試為 632 passed、
41 字型條件 skipped、5 vendor deselected。此階段沒有對公開臨床資料估計
propensity 或加權結果。

`run_weighting` 使用未懲罰的 logistic propensity，估計兩組 Hájek 平均數及一個
處置組減參照組的平均差／機率差。ATE、ATT、ATO 的原始權重各自固定，沒有裁切、
截斷、穩定化或失敗時自動換方法。共同估計方程含 propensity 係數、兩組平均數及
權重的導數，完整保存 J、S、參數順序與 sandwich 共變異數；單一對比採漸近常態
Wald 推論，沒有小樣本修正、bootstrap 或多重目標的校正。

逐列紀錄涵蓋全部來源個案與排除原因，不只保存前 500 列。診斷包含所有原始共變項、
全部類別指標及模型基底的平衡、共同刻度分數直方圖、原始權重分位數、sum(w) 與
Kish ESS。SMD 前後固定使用未加權分母：ATT 為處置組標準差，ATE／ATO 為兩組
變異數平均的平方根。連續值使用 ddof=1，類別指標使用 p(1−p)；零分母記為無法定義。

合成資料的 13 個估計邊界案例與上述 9 個契約案例通過。二元共變項飽和模型的
三種目標、兩種結果，以獨立的 cell-frequency 標準化公式及 multinomial delta
method 核對全部參數／共變異數。另驗證單位變更、處置／結果反向、ATO 樣條與
交互作用的平衡、有限差分 Jacobian、完整列保存及分離拒絕。ATT 反向改變目標族群，
不強制視為原結果加負號；單組結果恆定但差異仍可估時保留估計，不要求整個共變異數
滿秩。二元差的 Wald 區間超出 [−1,1] 時保留原值並揭示，對比變異數為零則拒絕推論。
數值核心加入後完整非 vendor 測試為 645 passed、41 字型條件 skipped、5 vendor
deselected；同一環境另啟用授權 Arial，40 項各期刊匯出與 1 項過長圖標題拒絕均通過。
這些檢查涵蓋既有圖表流程；加權圖表仍待實作。

下一步接 MCP、中文完整報告、英文投稿圖與真實資料驗收。
方法範圍參考 [WeightIt 共同估計說明](https://ngreifer.github.io/WeightIt/articles/estimating-effects.html)
與 [Li、Morgan、Zaslavsky 的 balancing weights](https://www2.stat.duke.edu/~fl35/papers/psweight_final.pdf)。
