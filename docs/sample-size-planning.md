# 前瞻樣本數規劃

2026-10-02，開發版新增；尚待 Workbench 表單、LLM 入口及正式 LAN 部署驗收。
RDE 版本維持 0.5.0。此設計流程不需要病人資料集，且不等於完成 EDA 13 階段。

## 共同契約

先 `init_project`。`draft_sample_size_plan` 保存不可變草案，
`get_sample_size_plan` 讀回完整中文審閱。研究者確認族群／主要結果、
假設與來源、方法及獨立性、主情境／分配／失訪後，才能
`approve_sample_size_plan`；核准固定整份草案 SHA256。
`run_sample_size_plan` 同時要求 plan／approval SHA256 與新的 run UUID。
計算實作、套件或 Python 版本在審閱後改變，須另建草案審閱。

這些步驟保存於 `artifacts/prospective_design/{plan_uuid}/`，並追加專屬
`decision_log.jsonl`。不偽造 intake／schema、不推進 EDA 階段，也不修改原研究計畫。
人類可審閱的 Markdown 另有 hash；資料來源是使用者提出的具體引用、定位及適用理由，
不宣稱機器已查證來源真實性。數值參數沒有未經審閱的 effect／alpha／power 預設。

草案與核准不可覆寫。相同成功 run ID 驗證全部產物後取回原版，不重算；
中斷或失敗保留已有證據，須檢視後使用新 run ID。損壞、來源不符或跨專案要求會停止。

## 方法與整數設計

| design | 明示假設與參數 | 分析單位 |
| --- | --- | --- |
| independent_means | 獨立且常態、共同 SD；signed difference／sd；pooled t，不是 Welch | 兩組獨立個案 |
| paired_means | 獨立配對、配對差值常態；signed difference／差值 SD | 完整配對 |
| independent_proportions | 各組 p1／p2，0..1 機率；pooled-null、unpooled-alternative 常態近似 | 兩組獨立個案 |

僅單一主要雙側檢定、零差值虛無假設。非劣性／等效性、群集、期中／適應性分析、
存活事件／收案、預測建模及精確罕見事件需另外驗證的契約，不能套用這些公式。
差值方向一律量測／組別 1 減 2；兩機率差乘 100 才是百分點。

獨立組明訂最簡整數比例 `[a,b]`（各 1..20）；每組至少 2 個觀察。
配對 allocation=null，至少 2 個完整配對，不能用量測列數替代。
以倍增找界及整數二分尋找最小分配倍數 k，並核對 k 及前一個可計算設計的 power。
上限是明訂的可分析總數，最大 1,000,000；任一情境無法達標就停止，不替換主情境。

平均差的非中心 t 同時計入兩個拒絕尾端。獨立組 df=n1+n2−2，
非中心參數為 `(difference/sd)/sqrt(1/n1+1/n2)`；配對 df=n−1，
非中心參數為 `sqrt(n)*difference/sd`。兩機率法不做連續性校正；報告保存
虛無與對立假設的各格期望數，少於 10 提醒審閱近似品質，並非精確性保證。

每個情境明訂共同缺失率 L（0..0.8）；招募分配數為 `ceil(k/(1−L))`，
以十進位運算避免 80% 等邊界多加一個配對。各組保留分配比例；第一版不支援
差異失訪率。期望留存數不是保證，也不處理失訪偏差、不依從或效果稀釋。

主情境及最多四個敏感度情境在核准前固定。報告包含每組／配對整數數量、
目標及回算 power、前一設計、預期留存、完整假設與來源、版本、限制及數值收據。
兩組英文投稿圖是設計 power 曲線與招募／可分析數，均有中文解釋、PDF／SVG／
300 dpi PNG／TIFF、英文圖說及 CSV。曲線不代表信賴區間。
`render_sample_size_publication` 可從固定 run receipt 另建 Nature／PLOS 圖稿，
保存原圖說與人工編修，不再計算樣本數。

## 已辨識的既有問題

S-010 不再因「未顯著且原始列數少於 100」建議觀察效應的事後 power。
現在依校正 p 與明訂 alpha 提醒檢視估計值／區間及臨床重要差異，使用實際分析個案
或完整配對數，不宣稱未顯著就等於沒有效果或檢定力不足。
舊 `power_analysis_advanced` 分析入口已關閉；新的規劃須走上述完整核准流程。

## 方法與驗證來源

假設依據及敏感度規劃參照 [ICH E9 §3.5](https://database.ich.org/sites/default/files/E9_Guideline.pdf)。
數值方法參照 [TTestIndPower](https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestIndPower.html)、
[TTestPower](https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestPower.html) 與
[兩機率 power](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.power_proportions_2indep.html)。
事後 power 問題參照 [Hoenig & Heisey (2001) 原始摘要](https://doi.org/10.1198/000313001300339897)，未聲稱已讀全文。

`tests/fixtures/sample-size/reference.R` 用 R 4.5.3 的 `power.t.test(strict=TRUE)`、
`pt`／`pnorm` 產生獨立對照，不等比例、相反差值及小效應的兩尾案例均納入。
`test_sample_size_planning.py` 核對數值／整數／失訪邊界；
`test_sample_size_workflow.py` 透過實際 MCP 工具檢查無假資料集、核准前阻擋、
跨專案／損壞／中斷、重啟取回及圖稿不重算。實際外部 stdio MCP 與視覺審閱證據
另記於本文件後續驗收紀錄；在完成前不標成正式平台可用。

## 2026-10-02 RDE 開發階段驗收

- 完整 Python 套件：698 passed／52 skipped；最後報告文字、讀回路徑與網頁修正的聚焦
  回歸為 65 passed。另檢查中斷 run 的父目錄不可被 symlink 導向專案外。
  VS Code extension：40 passed、資產同步檢查與 0.5.0 VSIX 打包通過。
- 獨立 subprocess stdio MCP：三種方法各兩情境，以及五個長名稱情境／主情境不在首位，
  共四個規劃。草案、讀回、未核准阻擋、人工核准、執行、Nature／PLOS 圖稿與
  程序重啟逐一測試，172 份產物的 SHA256 全部一致；病人資料集數維持零。
- 人工看過 24 張 PNG，以及 Nature 的 8 張實際 PDF 頁面；英文字、曲線／目標線、
  圖例、配對單位、主情境與招募數未見裁切或遮蔽。24 份 PDF 字型均嵌入，PNG 均達
  300 dpi。前三種設計沿用已逐張審閱的相同圖像位元組；比較收據保留於驗收資料。
- 說明頁在 Chromium 1440×1050、390×844 的中英文導覽及工具清單通過。
  修正四格表頭配三欄資料、長名稱與路徑撐寬手機畫面的問題。Browser plugin 不可用，
  使用既有 Playwright；隔離的 fontconfig 載入本機已固定的 Noto CJK，未更動產品字型。
- 原始請求／回應、失敗嘗試、重啟、字型及圖像收據先保存於
  `/tmp/rde-sample-size-mcp-v3-20261002` 與前兩次驗收目錄；階段封存另留完整 manifest。

數值例均為明示的工程合成假設，不是臨床推薦。來源文字未經自動文獻查證。
系統生成圖說用英文，使用者填寫的族群／結果等文字維持原文；若原文為中文，
作者需在投稿圖稿中審閱英文翻譯。尚未驗收 Workbench 入口、LLM 提案與正式 LAN 部署。
