# 配對／重複量測研究：固定方向與成對不確定性

本文件記錄新的 `family=repeated` 數值契約。版本維持 RDE 0.5.0。
目前已完成數值核心、MCP 計畫鎖定／報告／稽核、投稿圖與實際重啟取回。
Workbench 的新規格表單、LLM 計畫與瀏覽器操作及正式部署仍待接入。
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
`tests/test_paired_workflow.py` 另驗證真實 MCP、繪圖失敗後不重抽樣的恢復、
成對／共同來源列、結果遭改動的拒絕及來源欄名碰撞（`data_row`／`record`／
`values`）不覆蓋匯出身份。針對性 45 項通過。

## 投稿圖與真實 MCP 驗收（2026-10-02）

圖組包含共同個案納排、所有共同完整受試者軌跡、每對原始量測／個人差值、
固定比較的效果量森林圖及可選 Kendall W。每項比較按計畫保留；每張圖保存
英文圖說、中文解釋、繪圖資料及來源收據 hash。格式含 PNG／TIFF、PDF／SVG、
圖說 Markdown、資料 CSV。中性／Nature 採 300 dpi，PLOS 採 600 dpi；
Nature 使用已授權本機 Arial，未把不同字體代換成 Arial 宣稱符合。
字體與格式參數是技術 preset，不代表期刊接受或研究方法已被認可。

共同軌跡使用分類時點等距，黑點與垂線是保存的中位數及 Q1／Q3，不是 CI；
每位受試者均保留，超過 1,000 人時僅在向量檔內將密集個別標記 rasterize。
配對差值方向與 n 在圖、圖說及資料表一致。退化配對效果仍畫其可定義點估計，
另明示 `CI unavailable`。換圖稿只讀保存數值，不重新估計或重抽樣。

使用外部 stdio MCP，從收件、預檢、概念／計畫審閱與鎖定、執行、彙整、報告、
稽核到 auto-improve，並另起新 MCP 程序取回保存結果。四案都通過：

| 案例 | 共同 n／各對 n | 原始圖數 | 含兩種圖稿的雜湊驗證產物 |
|---|---|---:|---:|
| 合成 paired mean | 21／21、21 | 4 | 82 |
| 合成 signed-rank＋Friedman | 21／22、22 | 5 | 100 |
| 公開 Orthodont paired mean | 27／27、27、27 | 5 | 100 |
| 公開 Orthodont signed-rank＋Friedman | 27／27、27、27 | 6 | 118 |

每案建立 Nature single 與 PLOS full 圖稿：共 60 張圖、360 份圖稿檔。
全部 PDF 都實際轉圖並核對文字邊界；六種輸出皆核對，原始數值與來源未變。
人工目視範圍為合成 Nature 的四張 PNG、公開秩分析 Nature 的全部六張 PDF
轉圖，以及公開 PLOS／合成中性平均差的兩張 PDF 轉圖；未把自動檢查稱為
全部 60 張的人工審閱。8 個「兩方法 × 四種 Nature/PLOS preset」格式案例與
2 個 immutable edition 案例另通過（10 passed）。

最初圖稿嘗試缺少本機字體環境設定而明確拒絕；補上既有授權字體後完成。
PDF 驗證腳本最初錯把全部 preset 當作 300 dpi，改成核對各 preset 原有
300／600 dpi；無產品檔案被修改。來源欄名碰撞修正後，四案再實跑全部流程，
確認 4 份數值收據及 60 張圖的 PNG／PDF／SVG／TIFF／圖說位元組與審閱版本完全相同。

## 公開資料與獨立 R 核對

來源是已固定的 nlme 3.1-168 `Orthodont`，27 位兒童在 8、10、12、14 歲的
108 筆影像量測。`scripts/prepare_paired_public_fixture.py` 使用 CSV 原字串按
Subject／age 轉為寬表，不做平均、刪列、補值或單位換算；108 格各保留來源列。
原始 CSV SHA256：`ca7c0296405bb2bd5959cd5fff7c50a5035606f16ac308c7797f58666fcd7aa1`；
寬表 SHA256：`c21ed3ed349f13e0d8da670121981b874662c0fcf9fe73d1a1c7f924d55a0ceb`。
原資料與轉換紀錄保存在工作機的
`~/.local/share/research-workbench-public-data/paired-20261002/`。

獨立 R 4.5.3 的配對 t／Friedman 與整數多項式卷積的 exact signed-rank，
對照真實 MCP 保存結果全部吻合。腳本與精確結果見
`tests/fixtures/paired-intervals/reference.R`／`reference.json`。
例如 14 歲減 8 歲的平均差 3.907407 mm，95% CI
[2.979614, 4.835201]；對應秩效果為 1，因退化影響值不提供 BCa 區間。
Friedman Q=64.574144、Kendall W=0.797212。這是工程驗證用的
未調整年齡配對比較，沒有重現原論文的多變量模型，也不是治療因果效果。
官方說明的女性 ID 端點有不一致；依原始實際 16 男／11 女，不捏造缺少的人。
資料說明：[nlme Orthodont](https://stat.ethz.ch/R-manual/R-devel/library/nlme/html/Orthodont.html)。

方法來源：[SciPy Wilcoxon](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wilcoxon.html)、
[paired bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)、
[paired t](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_rel.html)、
[Friedman](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.friedmanchisquare.html)。
數值驗證環境為 SciPy 1.16.3；線上文件版本可能較新。
