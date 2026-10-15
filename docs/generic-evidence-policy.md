# Generic OLS 的版本化證據契約

`generic-ols-evidence-policy-v1` 是有限範圍的計畫與成果驗證，不是新估計器。
它適用獨立個案、連續終點的既有 OLS，可包含數值或原生核心完整記錄的 dummy predictors。
輔助 `compare_groups` 限二組數值終點的 rank screen。三組以上比較、配對、重複量測、
混合模型及其他未知方法不被這份契約認證；typed clinical 家族維持自己的完整契約。

六張分析圖保留為編輯建議，不作統計必要條件。正式品質判斷依研究問題所需資訊、
估計值與不確定性、診斷、實際分母及已核准圖表，而不是圖數。
這與 [ICMJE 對表圖與統計報告的建議](https://www.icmje.org/recommendations/browse/manuscript-preparation/preparing-for-submission.html)
及 [SAMPL 報告指引](https://www.equator-network.org/reporting-guidelines/sampl/) 的方向一致；
本契約的具體守門規則仍是 RDE 的工程範圍，不冒稱這些指引指定了本套流程。

## 核准前先審查精確草案

1. 完成來源 schema 與 confirmed concept roles。未知欄位角色不由名稱推定。
2. 呼叫 `register_analysis_plan(analyses=..., confirm=false)`，使用實際預定分析、
   `alpha`、`missing_strategy`、`multiple_comparison_method`。這一步只讀，不新增 phase、
   計畫、圖檔或收據，也不自動增補分析。
3. 讀取 `generic-plan-preflight-v1` 的 `applicability`：
   - `applicable`：屬有限政策；只有 `can_lock=true` 才能核准。
   - `requires_revision`：例如 OLS 混入未知模型，必須修訂；不能移除 pin 後當作通過。
   - `outside_policy`：例如純描述或獨立的 logistic 流程，沿其原有契約；不宣稱本政策已核實。
4. 修正所有 errors 後，帶原 `review_sha256` 作為 `expected_review_sha256`，以
   `confirm=true` 註冊同一計畫。核准時重新核對完整來源、角色、設定與方法，保存不可覆寫的
   `generic_ols_evidence_contract.json`。
5. 依原核准內容執行及產生圖表；收集／報告階段重新驗證原始收據，不補算遺失成果。

純 rank screen 沒有原工具提供的 effect confidence interval，因此不能獨自通過本政策。
應改用適合研究設計的 typed comparison，或**另行預指定** OLS mean-model estimand。
OLS CI 不能冒充 rank-effect CI。OLS 係數與不同模型的區間未作跨模型校正；
binary predictor 的 Gaussian 係數是 outcome 原單位均差，不是 log-OR。

## 完成所需證據

- 精確核准的 OLS outcome、covariates、confidence level 和 listwise 策略。
- 完整來源／納入排除帳本、實際 n、滿秩設計、正的殘差自由度。
- 每個係數的有限估計／區間、共變異矩陣及逐列 observed、fitted、residual。
- 原生模型 inclusion、coefficient、fitted、residual 圖的凍結檔案與 hash。
- 所有核准補充圖的精確欄位、分組、圖型與檔案；重複圖不補足缺少的診斷。
- 輔助 rank screen 的獨立分母、case set、效果值和校正 p 值，與 OLS estimand 分開。

補充圖只呈現原始可觀察資料，不新增視覺檢定、趨勢擬合或隱藏 plausibility filtering。
圖檔、binding 與輸出清單封存後不能覆寫；需另存新檔。模型本身仍沿用既有核心，
其清理／排除必須在原始來源與模型帳本中保留，不因圖表政策改變估計流程。
假設獨立性、臨床合理性和模型適合性仍須科學審查，完整檔案不等於假設已證明。

## 跨工作空間與歷史研究

`portable_contract` 綁定實際 intake bytes SHA、sheet、format、完整 frame 值／順序／dtype、
schema、confirmed roles、精確 analyses、設定與 policy SHA。研究代碼檔和原始上傳檔若不同，
其來源 hash 不可互換。原始 project／dataset ID、路徑、privacy 與完整 roles artifact hash
另留 `origin`，本地核准後一併鎖定。

Host 在原資料空間與分析隔離空間移轉時，必須保存原收據、來源 artifact 及 lineage，
比對完整 portable contract 與 hash，再記錄新本地收據的雙向對應。合法目錄或 ID 改變不改
portable hash；來源值、schema、角色或計畫改變則必須重新審查。相同 execution key 重取
preflight／registration 也重新核對來源，不得用成功快取繞過守門。

既有未帶這份 pin 的研究保留舊契約，不回填、改寫或宣稱已通過新政策。研究角色顯示與一般
readiness 改為只引用 confirmed roles 和 locked plan 的明確 target／covariates；圖表或描述
所列 variables 不再被當成 outcomes，未指派欄位不會被自動當成 covariates。
