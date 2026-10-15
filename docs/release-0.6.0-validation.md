# RDE 0.6.0：原生契約與發布驗證

本文件記錄發布前工程驗證，不代表已上傳 GitHub／Marketplace、部署 Workbench，
或證明 Qwen 正確解讀每篇論文。發布狀態以 [GitHub Releases](https://github.com/u9401066/research-data-explorer/releases) 為準。

## 本版範圍

25 個能力家族、78 個 MCP 工具，包含以下五個新增原生家族：

| 家族 | 可執行界線 | 不能外推的變體 |
| --- | --- | --- |
| [MI](imputation-study.md) | 獨立個案、連續／二元 PMM，Gaussian／binomial 分析，Rubin covariance、漸近 Wald | 多層、存活、MNAR、Barnard–Rubin 小樣本推論 |
| [分層比較](stratified-study.md) | 二元 treatment/outcome 的固定 2×2 分層 CMH、共同 MH OR | 廣義／精確 CMH、配對、群集試驗推論 |
| [非劣性](noninferiority-study.md) | 兩組獨立連續終點，Welch、預指定 margin／方向／單側 alpha | 二元、存活、群集、配對非劣性或等效性 |
| [配對](matching-study.md) | 固定 1:1 無放回 logit-caliper，保留 matched-treated 族群，pair-cluster CR1 t 近似推論 | 任意配對比／放回、全 treated ATT、完整 estimated-PS 不確定性校正 |
| [基線 TTE](target-trial-source-validation.md) | 核准 preparation 與完整來源／trace、單一 time-zero、基線單次處置、完整固定追蹤；沿用 weighting | 時變／動態策略、CCW、失訪／不完整追蹤、多 index |

Agent 依 live catalog 取得完整 schema，再 inspect、提出相同 clinical_options、審閱、
核准並鎖定計畫。TTE 先以 `get_target_trial_contract` 取得來源綁定，不能自行造 binding。
舊推論、清理與未支援的 autoresearch 不能繞過正式計畫；同 execution key 重取亦核對
來源、凍結數值與全部產物。以上都不取代研究定義、交換性、臨床適用性或解讀審查。

## 數值核心與報告修正

合併驗證來源為 `51246acb740be09c246bb4b77626e91b9a987b62`。
本輪升版只改套件 metadata、文件及文件守門測試；MCP server version 直接讀取已安裝
套件 metadata，沒有另造版本常數或變動估計方法。

保留數值核心的 catalog SHA：
`d8295563cbcff5f4b058c34efa107fa7677f38b63fa5b32ab2c02e76af94bb6f`。

合入的報告修正包含：Gaussian MI 的 binary predictor 係數仍是 outcome 原單位均差；
binomial 模型才有 log-odds 係數。Matching／TTE 使用凍結契約內的 canonical treatment／
outcome 角色，不能把 grouping、unbound metadata 或 raw outcome 的經驗差異替代正式效果。

## 驗證紀錄

基線 `b53f1de` 的完整非 vendor 測試為 **1669 passed、1 failed、76 skipped、5 deselected**。
唯一失敗是說明頁工具清單漏列 TTE source discovery；修正後網站／文件 **25 tests passed**，
原始失敗收據保留。76 個 Arial 條件測試另以既有授權字型精確重跑，**76 passed、0 skipped**，
四份字型檔案前後 SHA 不變。這是完整基線與有界補測，不改寫成一次完整全綠執行。

0.6.0 合併後 focused regression **244 passed、0 skipped**，涵蓋五個家族的共用報告、
matching／TTE、catalog、封裝與文件契約。手機檢查發現長程式路徑溢位，修正換行與舊家族數字後，
文件／網站／版本守門另 **30 passed**。擴充套件 **41 tests passed**，資產同步、ESLint、
Linux install-shape／package validation、所有適用 pre-commit hooks 均通過，沒有 hook 自動改檔。

wheel、sdist 與 VSIX 已封裝並核對版本和全部 runtime Python／JSON bytes；從 wheel 安裝到
隔離目錄後，真 stdio MCP 初始化回報 **0.6.0**、列出 **78 tools**，五個新家族的完整 schema
均可讀，catalog SHA 與上列完全相同。既有依賴圖未升級；忽略追蹤的本機 `uv.lock` 只更新本套件
版本，offline lock check 通過。沒有修改正式 Python 環境。

Chromium 實際檢查 **1440×1000** 與 **390×844**：首頁、版本連結、中文／英文切換、統計頁
導覽與手機選單均可操作；沒有 console／page error 或水平溢位。六張實際截圖已檢視。
Browser plugin 不可用，因此使用既有 Playwright；中文字型取自既有唯讀 Noto CJK，僅建立隔離快取。
封裝測試初次以符號連結共用 `node_modules` 時被 VSIX 的 dependency inventory 拒絕；改以同一鎖檔
在隔離目錄 `npm ci` 後重跑通過，原始失敗記錄保留，沒有改動依賴版本。

## 實際限制

- 本機驗證使用 Python 3.12.12／Node 24.21.0；不冒稱重跑 CI 的 Python 3.11／Node 22，
  或 Windows／macOS 矩陣。
- 5 個 optional vendor Docker 測試未啟動，無新模型呼叫。Qwen／Workbench 的研究驗收另行保存。
- 原生 DOCX 與圖 PDF 不等於整份報告 PDF；本機未安裝 optional `xhtml2pdf`。
- 既有 npm 開發／建置依賴有 29 個 audit 告警（7 moderate、20 high、2 critical，
  critical 為 Vitest／tinypool）；`--omit=dev` 為 0。本輪不以大幅更新依賴冒充已有驗證。
- 統計／工程測試不能證明所有 309 項期刊方法都可執行，也不代表論文重現或研究發現有效。
