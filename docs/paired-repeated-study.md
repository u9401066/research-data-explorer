# 配對／重複量測研究：固定方向與成對不確定性

本文件記錄新的 `family=repeated` 數值契約。版本維持 RDE 0.5.0。
目前完成數值核心與邊界驗證；MCP、投稿圖、Workbench 操作及正式部署尚待接入。
既有 `run_repeated_measures` 的歷史結果不會被改寫或宣稱已有新版區間。

## 研究者事先指定

- 同一結果／單位的 2–8 個寬表量測欄、唯一受試者欄及各時點名稱。
- 1–28 組明確方向的比較：第一欄減第二欄；反向重複不算新假設。
- `paired_mean` 配對平均差／Student t，或 `signed_rank` 配對秩二列相關。
- `complete` 全時點共同完整個案，或 3 個以上時點的 `pairwise` 每對完整個案。
- 秩流程可明訂 Friedman 整體檢定；平均差流程不把 Friedman 當作平均值 ANOVA。
- 信賴水準、多重比較 Holm／Bonferroni／BH、秩效果量 BCa 次數及固定 seed。
- 研究情境、結果定義／單位、受試者獨立與同一結果的明確確認。

所有比較都執行並保留，不依整體 p 值決定是否顯示；可選整體檢定與全部固定
比較構成同一家族。無法計算的檢定保留校正位置，輸出 p 仍為缺值。
效果量區間是逐項未校正，不能取代校正 p 判讀；未達門檻不等於等效。

## 數值與個案

配對平均差先計算每位受試者差值，再用 Student t 區間；不使用獨立兩組標準誤。
配對秩效果量是 `(正差秩和 − 負差秩和) / 非零差總秩和`，不是獨立組優勢機率
或中位數差。零差值採 wilcox 規則，從秩與分母排除，但重抽樣仍保留這些受試者。
非零配對最多 50 組時，p 採含同分中秩的完整符號翻轉分布；以上使用同分秩變異數
的常態近似、不作連續性校正。來源差值不隱含四捨五入。

BCa 以受試者為單位，完整保留配對／多時點向量；PCG64 seed、次數、偏差校正、
delete-one acceleration、分布 SHA256 均保存。各對比 seed 為基礎 seed 加零起算
對比索引（模 2^32）；整體檢定 seed 為基礎 seed 加對比數。
Friedman 同分校正統計量及 Kendall W 使用共同完整個案；小樣本或時點少時
明示卡方近似限制。所有零差、退化 jackknife、無定義重抽樣等情形保存
「無法估計」，不丟棄失敗抽樣或換成零寬母群區間。

來源列號從 1 起算（不含標題）。先核對納入範圍內所有身份，再排除結果缺失；
身份重複不能被缺失掩蓋。保存完整納排、量測缺失 bitmask、每對來源列與差值、
共同時點描述、來源角色 hash 及完整數值收據。沒有補值、BMI 等欄名推斷刪值。
共同描述圖的 n 不會當作 pairwise 比較的 n。

來源至少 10 列、共同完整個案至少 5 位只是程式操作下限，不是 power 證明。
此契約不處理共變項調整、受試者間群集、處置與時間交互作用或 crossover
period／carryover；配對變化本身不證明因果療效。

## 已驗證與待驗收

`tests/test_repeated_intervals.py` 以完整符號列舉、獨立逐項配秩、SciPy
delete-one BCa、配對 t 與 Friedman 計算比對；涵蓋 ties／zeros／全退化／
反向比較／來源尺度 1e-150 和 1e150／溢位拒絕。
`tests/test_paired_study_contract.py` 核對 pairwise 分母、完整來源納排、缺失前
身份檢查、固定家族、顯示順序不改對比方向及數值收據。
合計 39 項通過；尚不可据此宣稱平台或投稿圖已完成。

方法來源：[SciPy Wilcoxon](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wilcoxon.html)、
[paired bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)、
[paired t](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_rel.html)、
[Friedman](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.friedmanchisquare.html)。
數值驗證環境為 SciPy 1.16.3；線上文件版本可能較新。
