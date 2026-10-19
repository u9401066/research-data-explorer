# RDE 0.6.0：原生契約與發布驗證

本文件記錄發布前驗收，不代表部署、市場可取得或所有研究均已通過。部署與發布實績見 [GitHub Releases](https://github.com/u9401066/research-data-explorer/releases) 的精確提交、資產與收據；各市場須分別記錄 publish step 與公開可見結果。

## 2026-10-19 完整報告：發布前驗收

固定來源 `0832b70fb70161b4cf25e7391f46d43cd543e762`，catalog `3433a3f11e23c94d35c003cf839c9916ee73a2f0f5d208135f56b18088fe46a2`；此處記錄 0.6.0 已驗行為來源，最終純文件提交另保留差異。下文早期提交與測試保留原始範圍，不能代替本次全量結果。

- generic 報告保留實際圖檔子目錄，完整列入主 OLS 及預先指定敏感度的係數、CI、p 與分母；摘要僅使用核准且已執行的研究角色，不將未採用的 `mortality` 欄位當結論。Table 1 是否要求／已產出依本計畫契約，不把「政策非一律必需」顯示成不適用。
- 圖解區分單變數分布、分組、相關與模型診斷；不從 p 值推論效果強度，不由未定義 SD 斷定單人組，也不憑空提出合併類別或人體測量冗餘的建議。未知圖形保留原 caption 並明示解讀範圍。僅改報告投影與顯示格式，未重算估計或更動檢定閾值。
- 真保存成果的先紅後綠回歸及後續 91 項圖解回歸通過（2 項會重新估計的測試明確未執行）。原 215 成果 SHA 保持；重組的獨立 DOCX 為 `ef206bdd65b4f8184a62e4be2ede82009f509becfa76186a87b7b842fd8bdc24`，包含 16 張實圖及 12 表。真正平台預覽的全部 22 段桌面及手機 fit 已實看，fit／100% 幾何有瀏覽器核對。這不是 Word 分頁認證，也沒有把原正式報告 FAIL 改成 PASS。
- 舊 pair 的 generic v4 主／敏感度各 n=160、104 項獨立數值與最終解讀核對通過；原 browser FAIL 保留，未完成的下載／手機流程沒有補稱成功。新版配對 Qwen v5 的獨立終態與完整報告驗收另見下表；工程重組不能替代它。

| 本次發布關卡 | 狀態 |
| --- | --- |
| `0832b70` 完整原生測試 | 1,844 passed、0 failed、0 skipped、5 optional vendor deselected；另 41 項 extension 測試通過，舊 1,816 項仍只屬歷史版本 |
| `0832b70` 封裝與安裝 | 9 項命令 exit 0；wheel／sdist／VSIX 的 208 個 runtime 檔比對，實裝 wheel 真 stdio MCP 0.6.0／78 tools／25 families 通過 |
| 配對模型／平台 | 真 Qwen 在 `40411b6`／`0832b70` 完成 20/20 步驟／分支，631 項獨立終態核對；原 Canvas 狀態 FAIL 保留。WB `f75a9ad` 全量 1,557 passed／111 opt-in skipped，並對同成果只讀核對 19/19 子項名稱、身份與狀態；不稱新模型重跑。 |
| 部署／市場發布 | 本文件保留發布前驗收；實際配對建置、部署／還原收據及各市場 publish step、公開可見狀態見 [v0.6.0 Release](https://github.com/u9401066/research-data-explorer/releases/tag/v0.6.0)。 |

最終收據另核對 666 份追蹤來源、95 份正式 Python 套件 metadata、兩份忽略追蹤的 lock 與原 215 份研究成果保持。原生 full 收據 SHA `dfffd28f26d6f9675d7630cab77bdfa3f6b6c0ab65cf5eefd9aafb0b63f104c8`；原始 log 與逐案結果仍在。

本次封裝沒有安裝或升級正式依賴；重用既有離線環境。package 通過不等於完整原生測試或市場發布。私有收據為 `method-resume-20261015/native-report-final-20261019/package/receipt.json`、`package-byte-receipt.json`、`installed-mcp.json`；報告工程驗收為 `report-interpretation-fix-20261019/docx-preview/root-visual-review.json`。v5 獨立終態審查收據 SHA `4d01d8306972ebe6f54954b993920e28ce617440aea0a8ff0aceb0ae411163b7`、證據索引 `method-resume-20261015/generic-v5-independent-review-20261019/review-final.json`；最終文件提交的 archive README 與 source bytes 另核，不能把 0832 的舊包稱為已含新 README。

### 配對 v5 的實際接受範圍

真 Qwen 以 34 分 33.93 秒完成一份計畫、一次主分析與一個預指定敏感度，沒有人工追加指令或重跑估計。主報告 50,196 與分支報告 1,691 UTF-16 單位共 6 頁均完整讀完，數值／來源／終態核對 631 項通過。12 筆請求皆 HTTP 200，input 518,625／output 37,662／total 556,287 tokens，0 缺失、失敗、取消、重試或壓縮；最大 input 68,203，不能外推為 128K 滿窗壓測。

分析 215 份成果與全研究 289 份實際 HTTP 下載皆核對 SHA。新版原生 DOCX 的 16 圖／12 表、完整兩組係數表、34 段桌面與手機預覽，以及 5 張圖 PDF 的 5 頁已實看；不宣稱 Microsoft Word 分頁或臨床有效性。原 WB `40411b6` 的 19 個 generic 子項因 summary path 遮蔽而顯示 needs_review；`dfb01e2` 對同研究副本的只讀 19/19 驗證保持原成果與用量，0 新模型／0 新分析。`f75a9ad` 已另核對 19 個精確步驟名稱、同 plan／run／step／owner 序號與手機作用範圍；敏感度計算完成後仍待研究審閱，不自動提升為主要結論。這些唯讀修正不改寫原失敗。

實際圖文與 Canvas 收據 SHA `a90432c2582f62f33a7e94fc250d0f03da72c210a55510c2b0746396a506c62c`；模型／數值與圖文驗收來自本次 v5，不借用 v4 重組成果。

根層發布前接受收據 SHA `81661eb1401423849fe0ea9742feabadea5e76fc8f61b946fbb3a4c3ff36cb7f`（`root-final-research-acceptance-20261019.json`）；卡片名稱與 settled 分支審查 SHA `4aa95dc48f64f26f3c97106eb232a701328258d7f9fc59db8a9ee450b8f96193`（`generic-component-labels-20261019/review-final.json`）。這些收據接受所記錄的研究／UI 範圍，不代表正式部署或發布。

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

## 首次候選的數值核心與報告修正

合併驗證來源為 `51246acb740be09c246bb4b77626e91b9a987b62`。
本輪升版只改套件 metadata、文件及文件守門測試；MCP server version 直接讀取已安裝
套件 metadata，沒有另造版本常數或變動估計方法。

保留數值核心的 catalog SHA：
`d8295563cbcff5f4b058c34efa107fa7677f38b63fa5b32ab2c02e76af94bb6f`。

合入的報告修正包含：Gaussian MI 的 binary predictor 係數仍是 outcome 原單位均差；
binomial 模型才有 log-odds 係數。Matching／TTE 使用凍結契約內的 canonical treatment／
outcome 角色，不能把 grouping、unbound metadata 或 raw outcome 的經驗差異替代正式效果。

## 首次候選驗證紀錄

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

## 正式維護合併後的來源與成果守門

後續候選合併正式維護 `9d432559e3f4002bda973fcb90316e9d4f2b12f2`，保留 assisted intake
建立可追溯研究資料的行為。上述 catalog 與封裝紀錄屬首次候選，不能當作新程式的驗收。

所有臨床家族共用 `clinical-source-identity-v1`：inspect 與新註冊計畫保存來源檔案 SHA、
sheet、格式、完整 loaded frame 值／index／dtype 和 privacy provenance。相同 execution key
重取 inspect／register 時重新核對身份及原始 locked plan；來源改變不能沿用成功回覆。
新核准計畫也在首次估計前核對來源。舊手動計畫缺少此 pin 不被回填；已存在的舊成果則適用下列限制。

`clinical-artifact-inventory-v1` 封存獨立完整清單，綁定數值收據、規格、來源及每個檔案 SHA。
主 study record 與 execution snapshot 都保存該清單。報告、CSV、每張圖的 SVG／PDF／PNG／TIFF／
caption／data，MI 完整資料及 TTE source check／protocol 都須與原清單完全相符。
刪除檔案後再縮短清單、重複列入項目、刪去清單本身，均不能通過重取或報告 readiness。
尚未封存且已保存數值的真實繪圖失敗仍可接續；已封存的結果不能降級成待繪圖工作再補算。

舊結果沒有此獨立封存清單時回覆 `LEGACY_CLINICAL_INVENTORY`，保留原始研究與歷史檔案供查閱，
不修改舊收據、不替舊成果補造 hash 或冒稱已驗證。需以新研究執行取得新版驗證結果。
跨程式版本的舊 execution key 仍由原有 implementation pin 拒絕，不改寫歷史執行收據。

本輪沒有修改估計核心、依賴版本或新增模型呼叫。最終來源目錄及有界補測／封裝收據另行列入
本輪私有 release QA；首次候選的完整基線測試不被改稱為新版本完整全綠。

此修正的 catalog SHA 為
`503e5eac1dd8d511c322ec05f32f228097f4521f383590971b2ec58a017e6b22`。
來源／成果清單、TTE 全流程、catalog、版本與封裝／文件守門補測 **152 passed、0 skipped**。
前一輪 **78 passed、7 failed** 的失敗全部來自新清單將 TTE 原有 protocol JSON 誤當不合格 CSV；
修正為精確 TTE protocol 檔名後納入上述 152 項重新通過。非 TTE 五家族、survival／weighting
及 renderer recovery 的成功紀錄保留。另有 **16 個原 execution-key 回歸與 6 個 assisted-intake**
測試通過。第一次新增測試的 9 個 fixture API 拼字錯誤也保存原紀錄，已在上述補測修正通過。

## 有界 OLS 證據政策與隱私視圖重播

[一般 OLS 證據政策](generic-evidence-policy.md)讓計畫審查與報告 readiness 共用同一個
版本化規則。`register_analysis_plan(confirm=false)` 可唯讀審查精確計畫，回傳是否適用、
能否鎖定及缺件；不展開或修改計畫。Portable pin 固定來源內容、schema、確認角色、完整分析
與政策；跨合法執行目錄保留原始及本地 lineage，不能藉新資料集 ID 改掉方法。

此有限政策將六張圖降為建議，仍要求每個核准圖、模型必要診斷、分母、效果與信賴區間。
純 rank 比較缺少對應 effect CI 時必須修訂，不能借用另一個 mean/OLS 的 CI。
OLS 加入未知方法須修訂；純描述、其他舊方法及 typed clinical 家族保留各自契約。
報告角色只取確認角色與鎖定模型的明確 target/covariates，不把描述欄位列表都當 outcome，
也不把剩餘未指派欄位推定為 covariates。

TTE source replay 現在核對完整 typed release 經保存 privacy policy 轉換後的研究視圖。
每個欄位、值、列序與 dtype 均須完全相符，原始 trace／納排集合照原來源重算；不忽略保護欄位。
Source-check 同時保存 raw 與 analysis frame 指紋，treatment／outcome／baseline predictor／index
不能被 privacy 變值。已保存規則的 loader 與重啟若缺少金鑰直接拒絕，不生成新金鑰或父目錄；
放回原金鑰後可驗證既有成果而不重新估計。新真 MCP 測試涵蓋連續／二元結果、重啟、
來源及 privacy 漂移、完整原始 bundle 不變，以及 raw/research-view weighting 結果完全一致。

## 最終原生發布關卡

固定執行來源為 `a3e21088bd32bc44e293898ff01f07a99332bc34`；目前 catalog SHA 為：
`6d15570f26f3ec500b560d8fa4f606639d91cc83c80961a7920d3fa09b28b55d`。
後續只更新本紀錄與 changelog 的文件 commit，不改 runtime、catalog 或已固定的模型驗收來源。

| 來源與範圍 | 實際結果 |
| --- | --- |
| `6ffa1d86` 完整非 vendor 基線 | 1,782 passed、0 failed、0 skipped、5 vendor deselected |
| `08413d2` 完整非 vendor 執行 | 731 passed、0 failed 後因低磁碟保護中止；不是完整通過 |
| privacy 最後修正的六檔回歸 | 151 passed、1 舊錯誤訊息 fixture 失敗；原紀錄保留 |
| 更新該 fixture 後 focused | 75 passed、0 failed；另有獨立 8 項 privacy/restart 與相同重現腳本紅→綠 |
| `a3e21088` 完整非 vendor 發布測試 | **1,816 passed、0 failed、0 skipped、5 vendor deselected；1098.26 秒** |
| 最終 extension／封裝 | 41 tests passed；lint、install-shape、VSIX validate、適用 pre-commit hooks 全通過且無自動改檔 |

上述 fixture 原本把「不存在的 key」預期成「key changed」；新正確行為是「key is missing」
且不建檔，測試同步增加不存在的斷言。完整測試使用既有授權 Arial 字型與固定 Python 環境，
沒有安裝依賴、重建候選環境或變更正式研究；成功案例只清理各自的測試暫存，失敗與歷史 QA 保留。
最終執行未觸發 disk guard 或 ENOSPC。

最終 wheel、sdist、VSIX 的 **207 個 runtime Python／JSON 檔案集合及每檔 bytes** 均與上述
來源一致。由 wheel 安裝到隔離目錄後，真 stdio MCP 回報 **0.6.0、78 tools**，五個新家族的
完整 schema 及 catalog SHA 均核對一致。這些工程驗證不取代正在分開進行的 Workbench／Qwen
實機研究、因果識別假設、研究定義審查或正式發布。

## 實際限制

- 本機驗證使用 Python 3.12.12／Node 24.21.0；不冒稱重跑 CI 的 Python 3.11／Node 22，
  或 Windows／macOS 矩陣。
- 5 個 optional vendor Docker 測試未啟動，無新模型呼叫。Qwen／Workbench 的研究驗收另行保存。
- 原生 DOCX 與圖 PDF 不等於整份報告 PDF；本機未安裝 optional `xhtml2pdf`。
- 既有 npm 開發／建置依賴有 29 個 audit 告警（7 moderate、20 high、2 critical，
  critical 為 Vitest／tinypool）；`--omit=dev` 為 0。本輪不以大幅更新依賴冒充已有驗證。
- 統計／工程測試不能證明所有 309 項期刊方法都可執行，也不代表論文重現或研究發現有效。
