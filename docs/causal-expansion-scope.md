# 因果分析擴充範圍：既有加權、配對界線與基線目標試驗設計

**狀態：design-only，2026-10-15。** 本文件保存唯讀程式／依賴盤點與下一階段設計。
下述 target-trial protocol validator、原生執行守門與對應平台流程尚未實作。
沒有新 matching 效果推論或 TTE runtime 已交付的宣稱；不能以本文件更新方法覆蓋為完成。
本輪遵循 Python 與成熟統計引擎的方向，不新增 R、任意使用者程式碼或自製匹配變異核心。

## 已交付的正式加權界線

現有 `clinical/weighting_contract.py` 與 `clinical/weighting.py` 經正式
`inspect_clinical_study`、鎖定計畫及 `run_clinical_study` 使用：

- 獨立個案、觀察性 cohort、固定二元處置；每個 propensity covariate 需明示基線前依據。
- 事先固定 ATE、ATT 或 ATO，不以顯著性／平衡結果自動換目標人口。
- 未懲罰 binary logistic propensity；保留明訂 basis／interactions，拒絕 separation、
  rank 問題及非有限估計，不作 silent clipping、trimming 或自動換模型。
- 兩個分組正規化 Hájek 均值；binary 結局提供 probability difference，continuous 提供
  mean difference。不是 RR、OR 或 weighted Cox。
- Independent-case joint estimating-equation sandwich 納入 propensity 估計與權重導數；
  單一事先固定 contrast 的漸近常態 Wald 推論，沒有小樣本校正。
- 一個共同完整個案集合、逐列狀態／propensity／weights、原欄及 model basis 平衡、
  score overlap 與 Kish ESS；完整收據、圖表、來源與重用檢查。

`tests/test_weighting_models.py` 的飽和分層案例，以獨立 multinomial cell functional
及其導數核對參數與完整 covariance；亦驗證 ATE／ATT／ATO、單位改變與方向改變。
`tests/test_weighting_workflow.py` 驗證原生 MCP、完整人口帳冊、報告與凍結重繪。
這些驗證不證明真實研究的 exchangeability、positivity、可忽略缺失或臨床因果識別。

不支援：時變處置、重複入組、群集／survey、失訪或 censoring weights、weighted survival、
動態策略、clone–censor–weight、matching 效果推論與 MI 後自動接加權。
既有 `time_origin`／`outcome_window` 是研究文字定義，尚不是逐列時間對齊的 TTE 驗證。
完整個案分析也不自動代表原 eligible target population。

## Legacy propensity／matching 不是完整 ATT

`AnalysisDelegator._run_propensity_score` 提供舊 `propensity_score` 診斷：
greedy ascending treated score、最近 control、1:1 無放回；沒有 caliper 或 common-support
restriction。舊 IPTW 診斷把 propensity 限於 `[1e-6,1-1e-6]`；平衡使用每個階段自己的
pooled SD。配對來源列與平衡有保存，`outcome_effect_estimated=false` 也明確保存。

因此不能把這份 matched rows 接普通獨立 t test／paired t test 就標成完整 ATT：

1. 被配上的 treated 子集可能與完整 treated target 不同；目標人口及 unmatched 人員尚未形成
   完整效果契約，沒有 caliper／positivity 規則也不能由結果反向補定。
2. 配對設計、估計 propensity、donor 使用及 outcome 模型共同決定適用推論。
   一般 t test 不自動處理這些條件，亦不能從結果重新推定獨立性。
3. 舊配對目前沒有固定 estimand、outcome effect、適用 covariance 與獨立 oracle；
   不可藉助圖／函式名稱補造已驗證能力。

固定鄰居 matching 的普通 bootstrap 亦不是通用修補；
[Abadie–Imbens 原始研究](https://economics.mit.edu/sites/default/files/publications/ON%20THE%20FAILURE%20OF%20THE%20BOOTSTRAP%20FOR.pdf)
展示其失效情形與適用推論需求。這不表示所有 matching／bootstrap 變體皆無效；
正式採納前必須逐項匹配估計器、目標與 variance 條件。

## Python 依賴盤點與選擇邊界

本機正式 `.venv` 讀取到 statsmodels 0.15.0、scikit-learn 1.9.1、lifelines 0.30.3。
未安裝 causallib、DoWhy、CausalML、EconML、PSMPy、pymatch、zEpid、DoubleML、pyfixest；
此次未安裝或修改環境。

- [statsmodels Treatment Effects 官方說明](https://www.statsmodels.org/stable/treatment.html)
  有 conditional-independence treatment estimators 與 GMM standard errors；這不等於
  已提供 matching-specific variance，也不能替代目前 weighting 的指定 scope。
- [causallib Matching 官方介面](https://causallib.readthedocs.io/en/stable/api/generated/causallib.estimation.matching.Matching.html)
  提供 matching direction、caliper、replacement 與 matching backend。這份 API 尚不足以
  證明一條可直接採用、含適用 analytic variance 的 RDE matching inference pipeline。
  「能找到最近鄰」與「完成正確效果推論」必須分別驗收。

目前未確認本環境可直接交付的成熟 matching＋variance 路徑；這不是「Python 做不到」的
宣稱。後續若引入套件，需要固定版本、明確方法／推論契約、獨立數值 oracle、來源追溯、
凍結重用及平台驗收。不得先標為完成，再以未驗證套件或自製 SE 補洞。

## 有界基線 TTE v1：設計提案

原始 [Hernán–Robins target-trial framework](https://pmc.ncbi.nlm.nih.gov/articles/PMC4832051/)
要求明確描述假想試驗，對齊 eligibility、treatment assignment 與 follow-up 的 time zero；
多次入組、grace period 與持續策略可能需要不同資料結構與推論。以下是根據現有 RDE
能力提出的有限軟體設計，並非原文宣稱所有情境都能由 weighting 解決。

建議保留 `family="weighting"` 的既有數值核心，加上完整、可選的 typed
`target_trial_protocol`。只有伺服器驗證過 protocol／preparation／release／trace 的
執行才能標記「基線目標試驗模擬」。沒有 protocol 的一般 weighting 仍保留原範圍。
不能僅憑使用者字串、勾選 `tte=true` 或八段自由文字升級方法名稱。

| 必需契約 | 結構化內容與證據 |
| --- | --- |
| Eligibility | 時間零點可判定的納排規則、rule IDs、來源欄與依賴；不得依賴 follow-up/outcome features。 |
| Time zero | index 欄、時區、選擇規則、唯一受試者；納入、分派及追蹤起點的逐列比較。 |
| Treatment strategies | 兩個原碼、點處置／開始治療的明確定義、開始時間；禁止依未來治療紀錄分類。 |
| Assignment | 假想試驗的分派方法與實際觀察資料如何對應分開記錄；固定 confounders 及選擇依據。 |
| Follow-up | 固定 horizon、觀察結束、資料來源 coverage、失訪／競爭事件處理；未知不得當陰性。 |
| Outcome | 事件／非事件原碼或連續值單位、評估窗口與時間、可用時間、來源／rule mapping。 |
| Estimand | ATE／ATT／ATO 的精確目標人口及基線點處置 contrast；不得把開始治療效果冒稱 sustained per-protocol。 |
| Analysis | 完整固定 WeightingSpec、共同人口、估計量與推論；consistency、exchangeability、positivity 與缺失限制。 |

限定一人一個事先固定 time zero、兩種基線點處置／開始治療策略、固定 horizon 的
連續或二元結局。無 grace period、cloning、時變處置、依從性或 censoring 校正。
不支援的策略應在 inspect／plan 阻擋，不能換成另一個 estimand 後繼續。

所有 eligible 個案必須具有可判定的結局。binary positive 需可追溯合法窗口內事件；
binary negative 需有觀察至 horizon 的充分 coverage。連續結局需符合事先固定評估窗。
失訪、未知 coverage、未定義 competing events 或無法判定結局者阻擋這個 TTE v1；
不能先以 outcome missing 做 listwise exclusion，再宣稱分析原 eligible target。
基線缺失的規則也必須事先定義，不能在看到結局後改變納排。

## 核准來源、完整列集合與 trace 守門

重用既有鏈：`aggregation → preparation draft/review/approve → release → bundle → prepared intake`。
`portable.verify_bundle_folder`、`metadata.preparation` 與 `load_prepared` 已能核對
release／檔案／typed values；新 TTE validator 應讀取這些伺服器驗證結果，不接受 caller
自稱核准的 boolean 或只比對檔名。

必須固定 preparation ID、plan／review／approval／release／bundle hashes、全部輸入 source
hashes、analysis dataset/schema/trace hashes、protocol SHA 與 weighting spec SHA。
任何變更需新版本與原生計畫重新審閱，歷史結果保持原引用。

1. 讀完整 prepared population、cohort flow、exceptions 與 trace；不能只讀 20 個診斷例子或
   第一頁 output。以 release 的 exact rows／unit IDs 比對 protocol eligible 集合。
2. Included／excluded 集合不得重複或漏人；同人多 index 必須拒絕此獨立個案版本。
   在 preparation 排除者、基線規則排除者與未知追蹤者分開記帳，事件列不能計成人數。
3. 每個 weighting role 綁定同一 release 的真實欄及 source/rule provenance；完整 model
   population 必須等於經 protocol 固定的人口，禁止額外 outcome-driven exclusion。
4. 所有基線 covariate 的 contributing records 核對 event time 與 availability time。
   基線前採樣但基線後才可得仍不能作基線調整。真正不隨時間改變的 root facts 也需明確
   依據；`at_index_basis` 是已記錄的宣告，不是軟體恢復出的時間證據。
5. `no_record`、`not_exported`、`outside_window`、`link_failed`、`not_available`、
   `unknown_coverage` 分開核對。只有經完整 coverage 證實的未發生事件才能編為陰性。
6. TTE protocol／時間檢查收據與 weighting 數值收據分開保存並互相綁定；重用時核對全部
   artifact inventory、SHA 與人口集合。不得以重新跑數值掩蓋損壞／缺頁的來源證據。

自動檢查可驗證這些可計算條件，不能證明無未測 confounding 或臨床真值。
既有 automated preparation review 的 `clinical_validation="not_performed"` 必須保留。

## 後續實作邊界與驗收矩陣

依本輪已授權的因果研究擴充範圍分三段實作；本文件仍只是設計，需完成下列驗收才可發布：

1. 新 `target_trial_contract.py`／source-evidence validator：純 typed protocol 與現有
   prepared bundle/trace 核對，不做新統計估計或第二套 aggregation。
2. WeightingSpec／clinical inspect-run／readiness／report 接線：數值仍用既有 weighting，
   新增 protocol table、時間軸、人口核對與凍結證據；保持既有來源／計畫守門。
3. Workbench／Agent：研究計畫內編輯與版本審閱、顯示阻擋原因、capability/catalog/smoke
   一致更新。新方法名稱只在 exact protocol evidence 通過後使用。

| 獨立案例／負向案例 | 必須驗收的結果 |
| --- | --- |
| 手寫三表與完整固定追蹤 | 獨立 SQL oracle 逐列比對納排、基線值、時間零點與事件分母。 |
| 基線前採檢、基線後回報 | 不能成為基線 propensity covariate；明列未可用原因。 |
| 依未來開始用藥分類 | 阻擋 future-assignment／immortal-time 設計。 |
| 未匯出、連結失敗、追蹤不足 | 保存不同原因，不編成陰性。 |
| 同人重複 index／多次入組 | 拒絕獨立個案 TTE，不靠刪除任一列修復。 |
| outcome missing／失訪 | 阻擋 TTE，不默默縮小原 target population。 |
| eligibility 引用後續結局 | 阻擋後見納排，即使最終欄位無缺值。 |
| source／protocol／rule／release 任一更動 | 舊核准不可沿用；需要新修訂與完整審閱。 |
| 輸入列序重排、同等來源含義 | 透過 unit identity 比對同一人口與數值；來源 byte hash 仍如實不同。 |
| 符合限制的 prepared dataset | wrapper 與直接既有 weighting 的 estimates／covariance 完全一致。 |
| 缺 trace 頁、漏 inventory、人口集合偷減 | 拒絕完成／重用，不只核對總 n。 |
| frozen receipt 重繪與重啟重用 | 不重估、來源契約與每個 artifact hash 保留。 |
| Qwen 方法選擇與平台操作 | 非符合限定情境時如實說明未支援，不改名為 TTE 後執行近似方法。 |

此設計完成前，catalog／期刊覆蓋表應繼續區分「正式 weighting 可執行」、
「legacy matching 診斷」與「TTE／完整 matching inference 尚未交付」。
