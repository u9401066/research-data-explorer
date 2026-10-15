# 傾向分數配對：固定設計與配對群聚近似推論

本契約用成熟 Python 套件完成一個明確有界的觀察性研究流程：
`inspect_clinical_study` → 審閱並鎖定 `run_clinical_study` 計畫 → 執行 → 保存數值收據 →
`collect_results` → `assemble_report` → `export_report(formats="docx")`。
圖提供英文 SVG／PDF／300 dpi PNG／TIFF、英文圖說與繁體中文平台解釋。
圖 PDF 並不是整份報告 PDF；整份報告格式依部署能力明確指定。

## 固定方法與目標

- `family="matching"`，catalog key `matching.optimal_1to1_logit_caliper`。
- `method="optimal_1to1_logit_caliper"`：1:1、無放回，先最大化 caliper 內配對數，
  再最小化配對 logit 絕對距離總和。使用 `scipy.optimize.linear_sum_assignment`；
  dummy control 明確表示未配對。沒有先完整配對再刪掉超距離邊。
- `inference="pair_cluster_cr1_t"`：截距＋treatment 的 OLS，依 pair 群聚的 CR1 covariance，
  `use_correction=True, df_correction=True, use_t=True`，自由度讀取 `df_resid_inference=G−1`。
  全程使用 statsmodels，不自製變異估計器。
- `estimand="matched_treated"`：只針對固定配對設計保留的 treated 子族群。
  排除 treated 後不宣稱原全體 ATT／ATE；目標可能受資料與配對設計影響。
- 僅獨立個案、observational_cohort；連續結果為均差，二元結果為事件機率差。
  方向為 treatment 減 control，二元原碼順序為 negative、positive。
  此流程不是隨機試驗效果、Abadie–Imbens matching-imputation 或其 2016 估 PS 變異校正。

## 規格與來源

`MatchingSpec` 沿用明訂的來源角色（欄位參見 runtime catalog generated schema）：
subject、treatment／treatment_levels／定義、outcome／類型／單位／定義／時間窗、
time_origin、study_design、context、independent_rows、pretreatment_covariates、
covariates、可選 interactions／cohort_filter、confidence_level；另必填 caliper_sd。
subject 必須非空且獨立唯一；共變項必須附處置前時間依據，不把 post-treatment 欄位送進 PS。
連續基底、參考值、單位／increment、樣條 knots、類別層級與參考組皆事先固定。

PS 使用含截距的未懲罰 binomial-logit GLM。檢查來源代碼後才剔除必要角色缺失；
完整個案同時涵蓋 treatment、outcome 和全部 PS 共變項。
因此 outcome 是否可觀察會影響族群，不能宣稱完全未受 outcome availability 選擇影響；
但 outcome **數值**不進入 PS 配適或 assignment，也不依結果挑選 caliper。
不收斂、分離、非有限分數、奇異／非正 information 均拒絕，沒有 ridge、截分數或換方法 fallback。

`caliper_sd` 在 `(0,2]`，乘上原完整個案中
`sqrt((sample_variance(control_logit)+sample_variance(treated_logit))/2)`，兩組均 `ddof=1`。
界值包含等號；零 logit SD 僅接受精確 score 配對。按標準化 subject ID 穩定排序，
相同距離的配對取決於保存的 SciPy 版本，並非跨版本保證相同。
assignment matrix 上限 2,000,000 cells；不能在超量時偷偷改 greedy 或抽樣。

## 人口、數值與品質收據

preflight `matching-preflight-v1` 的 `n` 是配對前完整個案數；它只核對來源／design，
不擬合 PS，也不保證能留下足夠配對。
run 採既有外層 clinical record；內層 `clinical-result-v1`／`method_schema="matching-study-v1"`。
run `n=2G` 是實際配對分析人數；`matching_population.complete_cases` 另保存配對前人數。
`case_ledger` 保存來源／cohort／缺失／配對排除列號；`source_case_ledger` 完整涵蓋每列，
區分 outside_cohort、missing_required、unmatched、matched，並保留缺失欄位及未配對原因。
無合法 caliper 邊和控制個案競爭造成的未配對分開記錄；每對保存雙方來源列／ID／PS／距離。

每個原始 covariate／類別及實際模型 basis 都保留前後均值、固定原 treated SD 的 SMD、
分布五數、樣本變異與描述性最大 ECDF 差。indicator SD 用 p(1−p)，連續 SD 用 ddof=1；
原 treated SD=0 時保留 null，不偽造為平衡。連續變數另保留前後 variance ratio；
二元變數不把比例的函數重複當獨立變異診斷。
PS overlap 為固定 20 bins、各組各階段自己的分母，無平滑／clipping／自動trim。
二元結果另保存 control 0/1 × treated 0/1 的四格與 discordant pairs。

固定 `matching-quality-policy-v1`：少於5對不推論；少於30對、二元discordant少於10對、
|SMD|>0.1、連續變異比超出[0.5,2]或無法標準化時提示審閱。
這些是預先固定的軟體運算／品質規則，不是樣本數規劃、臨床充分性或有效涵蓋率的證明。
有警示仍可完成計算並交付透明結果，不把「完成」當成可作因果解讀。
零 pair-difference 變異不加常數、不造 CI。機率差近似區間若超出[-1,1]不截斷。

## 推論適用範圍

Abadie／Spiess 的無放回配對研究支持以 matched-set cluster inference 處理配對內相關，
但原文 §6 明確把 estimated propensity score 的額外 nuisance 複雜性列為未涵蓋範圍。
本工具不以該論文宣稱估 PS 的全部不確定性已精確校正或任意有限樣本有效。
[Abadie & Spiess, Robust Post-Matching Inference](https://economics.mit.edu/sites/default/files/publications/Robust%20Post%20Matching%20Inference.pdf)

MatchIt 的官方方法指南採用配對後 cluster-robust 推論，也明訂 caliper 排除 treated
會改變目標族群。本工具借鏡方法，沒有 R runtime 或 MatchIt 執行依賴。
[Estimating Effects After Matching](https://kosukeimai.github.io/MatchIt/articles/estimating-effects.html)

平衡應核對原 covariates 與分布，不能只看 PS、不能以不顯著的平衡檢定當作成功。
平衡、overlap、caliper 均不證明交換性、未測量混雜消失、完整個案選擇無偏或 causal identification。
[Assessing Balance](https://kosukeimai.github.io/MatchIt/articles/assessing-balance.html)

[statsmodels CR1／df／t 設定](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.RegressionResults.get_robustcov_results.html)
與 [SciPy assignment](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linear_sum_assignment.html)
構成本有界實作。少量配對推論及整條 estimated-PS 流程的涵蓋率需額外情境模擬／科學核對；
單元數值一致不等於全面因果驗證。

## 執行約束與驗證

頂層計畫 `alpha=1-confidence_level`（雙側）、`missing_strategy=listwise`、`multiplicity=none`；
一份計畫只有一個完整 matching bundle。舊 compare_groups、cleaning、advanced 等入口不能
繞過正式族群；matching 的 branch／autoresearch 尚無研究契約，會在執行前拒絕。
修改 caliper、角色、target 或來源必須建立並核准新規格，不覆蓋既有結果。

來源檔／工作表、解析 frame、spec、receipt、全部圖表 hashes 固定；重用與出版僅讀保存數值。
原始數據／已完成研究不改寫。渲染失敗可由保存數值恢復，不重新配對；source／frame／數值／
成果被改動會拒絕重用。

`tests/test_matching_candidate.py` 用部分 injective maps 窮舉獨立核對最大配對數及距離，
以飽和分層比例核對 PS，以 scalar pair differences 獨立核對 OLS 均差及套件 CR1 變異：
`Var(beta)=s_d²/G * (2G−1)/(2G−2)`。這不等於未加該修正的精確 paired t。
另核對來源錯碼、缺失、排除、zero SD、方向、列序、outcome-blind assignment 等。
`tests/test_matching_workflow.py` 經真正 MCP dispatch 驗證鎖定、執行、readiness、報告、
DOCX、出版圖、重用與篡改拒絕；另有共用 legacy／autoresearch 範圍回歸。
