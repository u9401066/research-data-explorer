# 基線目標試驗：原生來源驗證契約 v1

狀態：2026-10-15，**隔離工作樹中的有限原生 MCP 研究契約**。
已接上來源探索、inspect、計畫鎖定、run、來源重驗、凍結成果、報告與投稿圖；整合與部署另行驗收。
沒有新增效果估計器；有限基線點處置研究不代表支援所有 TTE，也不是論文重現或臨床外部驗證。

本設計承接 [causal-expansion-scope.md](causal-expansion-scope.md)，保留既有
`WeightingSpec` 的二元基線處置、ATE／ATT／ATO、Hájek mean／risk difference 與
independent-case joint sandwich 數值核心。來源驗證器只呼叫 `weighting_preflight`，不估計 propensity
或效果。來源一致也不證明 exchangeability、positivity、consistency 或臨床適用性。

## 可呼叫介面

平台與 Agent 應使用同一原生 MCP，不呼叫另一 repo 的內部 Python：

1. `get_target_trial_contract(dataset_id, weighting_options?)` 只讀目前專案核准且已匯入的 preparation。
   回傳完整 typed protocol schema、17 欄 `source_binding`、核准 `preparation_specification`、
   各來源 `{id, sha256, bytes, columns}`、population、review kind 與 clinical-validation 狀態。
   不回傳逐列個案、來源路徑或授權 boolean。若提供完整 weighting 規格，回傳正規化規格與
   `weighting_spec_sha256`，平台不得另猜 Python JSON 數字的表示。
2. `inspect_clinical_study` 接收
   `clinical_options={family:"target_trial",weighting:{完整 WeightingSpec},protocol:{完整 TargetTrialProtocol}}`。
   八項研究定義與時間角色仍須有實際來源支持，不由 metadata 自行補造。
3. `register_analysis_plan` 鎖定同一完整 spec 與 source-check；頂層固定
   `missing_strategy="listwise"`、`multiple_comparison_method="none"`、`alpha=1-confidence_level`。
   額外 eligible-set 守門確認本研究沒有因 missing／filter 刪除任何準備後個案。
4. `check_readiness` → `run_clinical_study` → `collect_results` → `assemble_report`。
   `render_publication_figures` 從凍結收據產生新圖版，絕不重估。

以下為上述 MCP 共用的內部原生 validator 介面：

```python
from rde.infrastructure.clinical.target_trial_contract import TargetTrialProtocol
from rde.infrastructure.clinical.target_trial_source import (
    target_trial_binding,
    validate_target_trial_source,
)

# 從伺服器實際匯入的核准 preparation 取得草案用的精確來源綁定。
# 此操作不核准研究 protocol。
binding = target_trial_binding(project, entry.dataset.metadata)

# protocol 可為 strict dict 或已驗證的 TargetTrialProtocol。
receipt = validate_target_trial_source(
    project, entry.dataset.metadata, entry.dataframe, weighting_spec, protocol
)
```

`TargetTrialProtocol.model_json_schema()` 提供完整機器可讀 schema。`parse` 拒絕未知欄位、
型別轉換、非有限值及不支援的策略。`to_dict()` 是後續計畫與審閱應鎖定的完整內容。
不接受 `tte=true`、`approved=true` 或「已核對」文字代替來源證據。

刻意使用獨立 `target_trial` wrapper；普通 `WeightingSpec` 仍拒絕額外 protocol 欄位，
不會接受後靜默忽略，也不能以普通 weighting 冒充完成此 protocol。

## 八項研究定義與資料證據

| 契約 | 有界 v1 的實際驗證 |
| --- | --- |
| Eligibility | 列出全部 preparation cohort rule IDs，順序完全一致；每個依賴欄位恰有一個來源與 event／available 時間映射。不得依賴處置選組、follow-up feature 或 outcome。每一位 root 個案保留納排帳冊。 |
| Time zero | UTC，來源 ISO timestamp 必須含時區；單一 patient root，unit keys＝subject keys，一人一個事先固定 index。拒絕 encounter／event unit、重複入組、缺鍵修補與事後選 index。 |
| Treatment strategies | 兩個原碼及定義，與 WeightingSpec 方向完全一致。僅 root 記錄的 baseline point treatment；每人 treatment event＝time zero，且 event ≤ available ≤ time zero。 |
| Assignment | 分開記錄假想試驗的 time-zero random assignment，以及實際觀察資料的 recorded treatment 對應／選擇與 confounder 依據；不把觀察資料宣稱為隨機試驗。 |
| Follow-up | 固定整數 horizon 1–3650 日；每位 eligible 的 coverage start ≤ index、end ≥ horizon。必須有實際 root export 與 intercurrent status 欄位，未知／失訪／競爭事件均阻擋，不能刪除該人後繼續。 |
| Outcome | 必須是核准 preparation 的真實 follow-up events relation 與精確窗口。Binary 是 (index, horizon] 的 qualifying-event `exists`，編碼固定 0／1。Continuous 是明訂窗內的 unique／first／last／mean observed measurement，含精確輸出單位。 |
| Estimand | ATE／ATT／ATO 與 baseline level 1 − level 0，完整綁定既有 WeightingSpec。不能把開始治療的點處置效果改稱持續依從的 per-protocol effect。 |
| Analysis | 每個 propensity covariate 按相同順序映射來源；全部 contributing records 都需 event ≤ available ≤ index。精確原生 preflight population 必須等於所有準備後 eligible 個案；不得額外 cohort filter、完整個案刪除或漏人。 |

上述文字說明保存研究意圖；程式只證明明示來源／規則／時間之間的一致性，不能由文字恢復未觀測事實。
Eligibility 可有事先明訂的基線缺失處理規則；**通過 eligibility 後**，任一必要分析角色缺失都阻擋。
目前要求至少一個明示 eligibility rule 與 1–12 個基線 covariates。
基線欄位須有實際 observed contributors；僅以「無紀錄」編成的零值 predictor 或未具時間證據的
immutable-fact 宣告，不在此有限 v1 內。

## 核准 bundle 與完整來源集合

只接受目前 project 自己的 `metadata.preparation`，資料夾必須精確位於
`artifacts/data_preparation/imports/<bundle SHA>`。匯入時的 ZIP SHA 已由原生
`portable.import_bundle` 核對；此處再次核對 server-owned intake、完整解封閉包與 release。
不能由 caller 任意指定另一資料夾充當來源；拒絕符號連結。

綁定包括 preparation／來源 project IDs，以及 bundle、plan、approval、review、release、
source set、specification、全部檔案 inventory、analysis CSV、typed rows、schema、trace、
validation、exceptions 的 SHA。核准 review 保留 reviewer、kind、實際 reviewed unit IDs
與原有 clinical-validation 狀態。`automated_checks` 保持 `not_performed`；
`synthetic_oracle` 僅可用於全部 synthetic sources。雜湊是完整性證據，不是電子簽章或臨床確認。

接著讀取**全部**來源快照與 trace，重用既有 `preparation.engine.Evaluation` 重算：

1. 來源 byte／row／column identity 與核准規則；完整 analysis rows、trace、exceptions、issues。
2. 全部 validation 與 cohort-flow 分母。重算值必須與保存值完全相同。
3. 所有 root record 皆在 trace，subject 唯一；included 與 baseline-excluded 個案分開列出。
4. 當前 DataFrame 的所有欄、值、型別與行序必須等於完整 typed release。
5. 每個 included unit 的來源時間、coverage、處置、基線、outcome contributors。
6. 原生 weighting 的 complete-data row IDs 必須是全部 release rows，missing／filter exclusion 均為空；
   同時比較完整 unit-ID 集合，不能只檢查相同 n。

此處重用既有 engine，不是第二個自製 aggregation 或效果估計器；獨立 SQL oracle 另外放在測試中。
目前只接受與現行 preparation implementation 相同的 release，舊實作的證據需新 preparation
版本與核准，不會自動遷移歷史引用。讀取與驗證不改寫任何原始檔或保留證據。

Binary negative 只有在真實 relation coverage 完整、固定追蹤完整，且狀態為 no_record／
outside_window／filtered_out 時才可沿用 preparation 的 0；unknown、not_exported 或失敗連結不等同陰性。
Positive 與 continuous 每個實際 contributing event 都需在明訂窗口，並於記錄的 coverage end 前可得。
Coverage 與「沒有 intercurrent event」仍是來源提供的主張；本檢查不證明醫院匯出完整性。

## 保存收據與已實作的原生執行門檻

成功回傳 `rde-target-trial-source-check-v1`，包括完整 protocol／WeightingSpec snapshots、
兩者 SHA、全部來源 binding、validator／preparation source hashes 與依賴版本、全部個案時間／納排檢查、
flow、精確 weighting preflight，以及 receipt SHA。沒有使用預覽頁或取樣替代完整列核對。
`execution_authorized=false` 明確表示這不是計畫鎖定或數值執行授權。

`target-trial-preflight-v1` 回傳完整 normalized spec／SHA、n、case ledger、dataframe／design SHA，
以及 source-check 摘要與獨立完整 JSON artifact 的相對路徑、SHA、大小。逐人 trace 保存於
artifact，不塞進模型 context。`target-trial-study-v1` 有自己的 SHA，內含原樣
`weighting_result`／`weighting_receipt_sha256` 與完整 `source_check`／`source_check_sha256`。
三份收據各自驗 SHA 並核對 spec、population、design 與 source links。

以下原生接線已完成；平台與正式部署由整合驗收另外確認：

| 接線點 | 必須完成的行為 |
| --- | --- |
| Clinical parsing／計畫 | 獨立 TargetTrialSpec wrapper 鎖定完整 protocol／WeightingSpec，以及全部來源驗證收據；與普通 weighting 明確區分。 |
| Inspect | 呼叫 source validator；保存完整收據檔。MCP 只回傳可分頁取得的摘要、精確 SHA 與 artifact ID，避免把全 trace 塞進模型 context。任何失敗不得仍標為 TTE-ready。 |
| Locked run | 先核對 exact locked protocol/spec，再重新驗來源、完整 population、implementation；任何守門失敗都要保存 attempt/failure receipt，不能退回普通 weighting。 |
| Numerical execution | 通過守門後，只呼叫原有 `run_weighting(df, spec)`；不重新排序、改 covariates、trim、clip、重建 cohort 或重估其他 estimand。以直接 weighting 結果作估計與 covariance 等值回歸。 |
| Reuse／restart | 必須先重新核對完整 source-check receipt、source closure、locked protocol/spec、實作版本及全部 artifact SHA，再允許重用；禁止先 return cached result 而略過新守門。 |
| Durable execution key | 所有 clinical family 的同 key 成功回傳前，再走 replay-only 原生 runner；缺失原成果不得重 fit 或補畫。TTE inspect／register 同 key 另驗來源與原計畫 pin；歷史 invocation snapshot 不等於當前來源有效。 |
| Persistence | TTE source receipt 與既有數值 receipt 分開保存、互相綁定，並納入完整 artifact inventory；歷史 source／結果不得重寫。 |
| Readiness／report | readiness 必須檢查完整 evidence 而非 boolean。報告從 frozen receipt 顯示八項定義、個案 flow、時間核對、缺失／coverage 與識別限制；weighting 數值／平衡圖沿用 frozen numerical receipt。 |
| Branch | 新入口、worker、舊 queue／expired lease／重啟均按實際 locked family 拒絕通用推論；新問題須另建核准研究版本。 |
| Publication | 原 weighting 圖保存 nested numerical SHA；新增英文 clinical_target_trial_flow 保存 parent TTE SHA。預設 SVG／PDF／300 dpi PNG，另有 TIFF、caption、data。 |

`inspect_clinical_study` 因 TTE 保存來源收據，MCP effect annotation 已不再自稱純只讀；
`get_target_trial_contract` 保持只讀。全部 source-check 也綁定 wrapper／weighting 數值核心的實作版本。

一般 weighting 的 complete-case 契約與本 v1 的 all-eligible 無缺失要求不矛盾：後者是額外守門，
證明這次 weighting 沒有刪除任何 eligible 個案；不能只把計畫 missing-policy 字串改成 `none` 代替驗證。

## 已有回歸證據與未覆蓋範圍

測試在真實原生 draft → review／approve → release → bundle → prepared intake 之上建立三表，
61 位 root 個案、60 位符合事先基線 eligibility 者、每人 2 筆基線紀錄，並保留獨立 SQLite
逐值 oracle。真 MCP 回歸涵蓋 intake／profile／quality／schema、inspect／鎖定／run／報告／重用。
概念的預先確認仍由 fixture 明示提供；研究方向使用實際 typed proposal 的 draft／confirm，鎖定時拒絕替換方法或 protocol。這不是 Qwen 自主規劃或臨床外部驗證。

- Binary／continuous 正例，synthetic review／automated review 的區別；禁止來源檢查擅自 fit。
- 第 61 位個案的未來 eligibility／treatment／available time、短追蹤、未知匯出、intercurrent event、
  naive timestamp；缺失分析角色不得改分母。
- 手動來源刪列、outcome-driven eligibility、額外 analysis filter、未映射 covariate、encounter unit、
  sustained／censoring／multiple-index 策略與 boolean approval 皆拒絕。
- 各別 stale binding、另一 project、未準備資料、改 DataFrame／source bytes／trace 皆拒絕。
- 重新計算 SHA 並封裝成內部完整 bundle 的漏列、錯誤來源列與錯誤分母，仍由完整 replay 拒絕。
- 打亂三份來源行序後，逐人答案與 population 相同，但來源 binding 更新，舊 protocol 不可沿用。
- 收據重複讀取完全一致，包含 validator source versions，無私人路徑，digest 可獨立核對。
- 同 execution key、並行重試、重啟、來源變更、刪除原 JSON／表／圖／source receipt、空 inventory；不得重 fit 或補畫。
- 既有 MI／CMH／matching family 亦驗證共用 replay-only 守門；exception 後合法新 run 仍可估計。

未支援／未宣稱：time-varying treatment、grace periods、clone–censor–weight、重複入組、群集／survey、
失訪／競爭風險估計、MI 接加權、weighted survival、dynamic／sustained strategies、matching-specific variance。
不自動證明實際 eligibility 是在看結果前訂定，亦不能由資料證明沒有未測量 confounding。

方法背景：[Hernán–Robins 目標試驗框架](https://pubmed.ncbi.nlm.nih.gov/26994063/)、
[時間零點與可避免偏誤的原始研究](https://pubmed.ncbi.nlm.nih.gov/27237061/)。
以上有限輸入與拒絕規則是本平台的可驗收軟體範圍，不是這些論文宣稱所有 TTE 都必須具有相同形式。
