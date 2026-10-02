# 傾向加權：實作與驗證狀態

2026-10-02：來源契約與 preflight 已實作，尚未接入 MCP、加權估計、報告或平台。
RDE 維持 0.5.0；這不是已可執行完整加權研究的宣告。

`WeightingSpec` 要求二元處置、連續或二元結果、原始代碼、來源單位、time zero、
結果確認方式與窗口，以及每個共變項的處置前量測依據。限定獨立個案的觀察性世代，
事先指定 ATE、ATT 或 ATO；未確認的時序與因果條件不能由資料檢查代為證明。

`weighting_preflight` 固定共同完整個案，依序檢查納入限制、個案識別欄、來源代碼／數值、
缺值與模型矩陣。ID 缺失／重複及非法代碼，不能被另一欄缺值的排除遮蔽。納排紀錄
保留一開始的來源列號；結果值參與來源指紋，但不進入 propensity 設計矩陣。
類別、參照、樣條結點與交互作用採用既有明示型別契約，不執行來源欄名中的公式。
不提供自動選變項、權重裁切、補值、群集或時變處置的隱含替代。

9 個聚焦邊界案例通過；完整非 vendor 測試為 632 passed、41 字型條件 skipped、
5 vendor deselected。此階段沒有對公開臨床資料估計 propensity 或加權結果。

下一步是 Hájek 組別平均數與單一平均差／機率差，並以包含 propensity 係數及兩組
平均數的共同估計方程計算 sandwich 共變異數。須先以獨立數值參照檢查不確定性、
處置／結果反向及單位變更，再接 MCP、完整診斷、投稿圖與真實資料驗收。
方法範圍參考 [WeightIt 共同估計說明](https://ngreifer.github.io/WeightIt/articles/estimating-effects.html)
與 [Li、Morgan、Zaslavsky 的 balancing weights](https://www2.stat.duke.edu/~fl35/papers/psweight_final.pdf)。
